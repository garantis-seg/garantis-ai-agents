"""Onda 8 — o INVESTIGADOR: tool-use em 2 fases, sem LLM nos testes.

Camada 1 da pesquisa (Layer-Isolated Evaluation): todo o scaffold testado com
provider dublê e Leitor dublê. O que se trava aqui: dispatch por payload,
envelope do Leitor rejeitado sem confianca em campo, circuit breaker por
(ferramenta, doc), ancoragem por CODIGO a partir do sid, e o contrato de
resposta identico ao do montar_grafo legado.
"""

import asyncio
import json
from types import SimpleNamespace

from garantis_shared.calculo_fichas.documento import DocumentoIndexado, Paragrafo, Sentenca

import src.agents.calculo_ficha.investigador as inv_mod
from src.agents.calculo_ficha.investigador import investigar
from src.agents.calculo_ficha.schemas import MontarGrafoRequest


def _doc() -> DocumentoIndexado:
    s1 = Sentenca(
        sid="fl1-s1", texto="principal de irpj de r$ 1.000.000,00",
        texto_bruto="Principal de IRPJ de R$ 1.000.000,00", pagina=1,
        par_id="fl1-p1", offset=0,
    )
    s2 = Sentenca(
        sid="fl1-s2", texto="multa de oficio de 75%",
        texto_bruto="Multa de oficio de 75%", pagina=1, par_id="fl1-p1", offset=40,
    )
    return DocumentoIndexado(
        doc_id="carf:decisao.pdf", doc_hash="hash-abc", extractor_version="pymupdf-1+norm-2",
        metodo="native", n_paginas=1, sentencas=(s1, s2),
        paragrafos=(Paragrafo(
            pid="fl1-p1", sids=("fl1-s1", "fl1-s2"), pagina=1,
            texto="principal de irpj de r$ 1.000.000,00 multa de oficio de 75%",
        ),),
    )


class _ProviderRoteiro:
    """Devolve uma resposta POR CHAMADA e captura os kwargs de todas."""

    def __init__(self, respostas: list[str]):
        self.respostas = list(respostas)
        self.chamadas: list[dict] = []

    async def agenerate(self, **kwargs):
        self.chamadas.append(kwargs)
        i = min(len(self.chamadas), len(self.respostas)) - 1
        return SimpleNamespace(
            text=self.respostas[i], model="modelo-teste",
            metadata={"cost_usd": 0.001},
        )


def _grafo_final() -> str:
    return json.dumps({
        "celulas": [
            {"id": "principal", "tipo": "dado", "valor": 1_000_000.0, "origem": "extraida"},
            {"id": "garantia_total", "tipo": "formula",
             "expressao": "principal * 1.0", "depende_de": ["principal"]},
        ],
        "evidencias": [{
            "celula_id": "principal", "documento": "carf:decisao.pdf", "pagina": 1,
            "trecho_literal": "Principal de IRPJ de R$ 1.000.000,00",
            "ancora_sid": "fl1-s1", "politica": "span",
        }],
        "grau_sugerido": "exato",
    })


async def _leitor_ok(doc_id, documento, **kw):
    return {
        "resposta": "o principal e R$ 1.000.000,00 [fl1-s1]",
        "citacoes": ["fl1-s1"], "confianca": 0.92,
        "objeto_da_confianca": "de que este e o principal mantido, nao o consolidado",
        "encontrou": True, "lacuna": None, "cost_usd": 0.002,
    }


def _request(**extra) -> MontarGrafoRequest:
    return MontarGrafoRequest(
        dossie={"empresa": "ACME"},
        documentos_indexados={"carf:decisao.pdf": _doc().to_dict()},
        **extra,
    )


def _rodar(coro):
    return asyncio.run(coro)


class TestInvestigadorE2E:
    def test_pergunta_fim_e_emite_grafo_ancorado(self, monkeypatch):
        prov = _ProviderRoteiro([
            '{"tool": "perguntar_ao_documento", "args": {"doc_id": "carf:decisao.pdf", "pergunta": "principal?"}}',
            '{"fim": true}',
            _grafo_final(),
        ])
        monkeypatch.setattr(inv_mod, "create_provider", lambda *_a, **_k: prov)
        r = _rodar(investigar(_request(), leitor_perguntar=_leitor_ok, leitor_resumir=_leitor_ok))

        assert r.success, r.error
        assert r.model == "modelo-teste"
        ev = r.evidencias[0]
        # ⚑ a Ancora COMPLETA foi preenchida pelo CODIGO a partir do sid
        assert ev["ancora"]["sid"] == "fl1-s1"
        assert ev["ancora"]["doc_hash"] == "hash-abc"
        assert ev["ancora"]["extractor_version"] == "pymupdf-1+norm-2"
        assert r.cost_usd > 0

    def test_dispatch_por_payload_sem_indexados_vai_pro_legado(self, monkeypatch):
        """Sem documentos_indexados, o caminho antigo roda intacto."""
        import src.agents.calculo_ficha.agent as agent_mod
        prov = _ProviderRoteiro([_grafo_final()])
        monkeypatch.setattr(agent_mod, "create_provider", lambda *_a, **_k: prov)
        r = _rodar(agent_mod.montar_grafo({
            "dossie": {}, "documentos": {"decisao.pdf": "Principal de IRPJ de R$ 1.000.000,00"},
        }))
        assert r.success
        assert len(prov.chamadas) == 1          # one-shot, sem loop de decisao

    def test_envelope_do_leitor_sem_objeto_e_falha_da_ferramenta(self, monkeypatch):
        async def leitor_sem_objeto(doc_id, documento, **kw):
            return {"resposta": "…", "confianca": 0.9, "cost_usd": 0.0}

        prov = _ProviderRoteiro([
            '{"tool": "perguntar_ao_documento", "args": {"doc_id": "carf:decisao.pdf", "pergunta": "?"}}',
            '{"fim": true}',
            _grafo_final(),
        ])
        monkeypatch.setattr(inv_mod, "create_provider", lambda *_a, **_k: prov)
        r = _rodar(investigar(_request(), leitor_perguntar=leitor_sem_objeto,
                              leitor_resumir=leitor_sem_objeto))
        assert r.success                        # o grafo final ainda sai
        # mas o achado registrou a REJEICAO do envelope, nao a resposta
        prompt_fim = prov.chamadas[1]["prompt"]
        assert "sem confianca/objeto_da_confianca" in prompt_fim

    def test_pedir_pagina_e_deterministico_e_tem_teto(self, monkeypatch):
        chamadas_pagina = ['{"tool": "pedir_pagina", "args": {"doc_id": "carf:decisao.pdf", "pagina": 1}}'] * 4
        prov = _ProviderRoteiro(chamadas_pagina + ['{"fim": true}', _grafo_final()])
        monkeypatch.setattr(inv_mod, "create_provider", lambda *_a, **_k: prov)
        r = _rodar(investigar(_request(), leitor_perguntar=_leitor_ok, leitor_resumir=_leitor_ok))
        assert r.success
        # a 4a leitura de pagina levou o teto (3 por doc) na cara
        prompt_final = prov.chamadas[4]["prompt"]
        assert "teto de 3 paginas" in prompt_final

    def test_submeter_celulas_devolve_gates_na_hora(self, monkeypatch):
        submissao = json.loads(_grafo_final())
        prov = _ProviderRoteiro([
            json.dumps({"tool": "submeter_celulas", "args": submissao}),
            '{"fim": true}',
            _grafo_final(),
        ])
        monkeypatch.setattr(inv_mod, "create_provider", lambda *_a, **_k: prov)
        r = _rodar(investigar(_request(), leitor_perguntar=_leitor_ok, leitor_resumir=_leitor_ok))
        assert r.success
        # o turno seguinte viu o resultado dos gates (aceitas) no prompt
        assert '"aceitas"' in prov.chamadas[1]["prompt"]
