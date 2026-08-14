"""O que não cabe no payload inline é DROPADO e CONTADO — nunca vai pro ramo morto.

`client.aio.files.upload` só existe no backend Gemini Developer. Prod roda
`GEMINI_BACKEND=vertex` desde 2026-07-18, então a chamada levantava
`ValueError('This method is only supported in the Gemini Developer client.')`
ANTES do `generate_content`, o `except` de `call_l1_with_vision_fallback`
engolia e o payload INTEIRO virava text-only sem deixar rastro no card:
355 eventos em 30d (192 em 7d: 85 petição + 107 mov), último 2026-08-14T08:14:58Z.

Estes testes exercitam `_build_pdf_parts`/`call_vision_l1` DE VERDADE, com o
`google.genai.types` real (dependência dura do repo) e um client fake que
CONTA as chamadas — a asserção que mais importa é a de que, quando nada cabe,
o Gemini não é chamado nenhuma vez.
"""
from __future__ import annotations

import asyncio

import pytest

from google.genai import types as gtypes  # noqa: E402

from src.agents._utils import vision as V  # noqa: E402

_MB = 1024 * 1024


def _pdf(n_bytes: int, marca: bytes = b"0") -> bytes:
    """PDF do tamanho pedido. O roteador só olha `len()`; o header fica pra manter
    o dado parecido com o que sai do GCS.

    `marca` distingue PDFs do MESMO tamanho sem mudar o tamanho — é o que permite
    afirmar QUAIS sobreviveram ao corte, não só quantos."""
    cabeca = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    return cabeca + marca * (n_bytes - len(cabeca))


class _FakeClient:
    """Conta as chamadas ao Gemini. NÃO tem `files` — se alguém reintroduzir o
    upload, o teste quebra com AttributeError em vez de passar mudo."""

    def __init__(self) -> None:
        self.chamadas: list[list] = []
        outer = self

        class _Models:
            async def generate_content(self, *, model, contents, config):
                outer.chamadas.append(contents)

                class _R:
                    text = "{}"
                    usage_metadata = None

                return _R()

        class _Aio:
            models = _Models()

        self.aio = _Aio()


class _FakeProvider:
    def __init__(self) -> None:
        self._types = gtypes
        self._client = _FakeClient()
        self.texto_chamado = False

    def get_model_pricing(self, model):
        return {"input_per_1m": 0.0, "output_per_1m": 0.0}

    async def agenerate(self, **kw):
        self.texto_chamado = True
        return "RESPOSTA_TEXTO"


# ── 1. A seleção ─────────────────────────────────────────────────────────────
def test_o_que_cabe_SOBE_e_o_excedente_vira_CONTADOR():
    """⛔ MUTANTE: voltar a rotear pra Files API reprova aqui — `_build_pdf_parts`
    não recebe mais `client`, então não tem como chamar o SDK."""
    peq1, grande, peq2 = _pdf(2 * _MB), _pdf(6 * _MB), _pdf(_MB)
    gate: dict = {}

    parts, transport = V._build_pdf_parts(gtypes, [peq1, grande, peq2], gate)

    assert [p.inline_data.data for p in parts] == [peq1, peq2], (
        "sobe o que cabe, na ordem recebida (ordem == prioridade na petição)")
    assert gate["n_nao_enviados_cap"] == 1
    assert transport == "inline_capped"


def test_payload_dentro_dos_caps_nao_muda_de_comportamento():
    """A outra metade: o caso comum (99,7% do volume) tem que continuar idêntico."""
    a, b = _pdf(2 * _MB), _pdf(_MB)
    gate: dict = {}

    parts, transport = V._build_pdf_parts(gtypes, [a, b], gate)

    assert len(parts) == 2 and transport == "inline"
    assert gate["n_nao_enviados_cap"] == 0


def test_o_teto_TOTAL_corta_o_FIM_da_fila_e_conta():
    """4 x 5MB = 20MB > 15MB. Sem o teto somado, o cap por PDF deixaria passar.

    ⛔ MUTANTE que este teste existe pra pegar: percorrer `reversed(pdf_bytes_list)`
    (e reverter no fim) mantém `len(parts)==3` e `n_nao_enviados_cap==1` — passava
    a suíte INTEIRA — mas inverte QUEM paga o corte. No ramo de petição o
    materializer põe a peça na frente, então o mutante droparia a PETIÇÃO e subiria
    3 anexos periféricos, com o card gravado como "lido". Por isso os 4 PDFs são
    do mesmo tamanho e DISTINGUÍVEIS: com blobs idênticos só dá pra contar, e é
    contando que o mutante escapa."""
    quatro = [_pdf(5 * _MB, marca=m) for m in (b"A", b"B", b"C", b"D")]
    gate: dict = {}

    parts, _t = V._build_pdf_parts(gtypes, quatro, gate)

    assert [p.inline_data.data for p in parts] == quatro[:3], (
        "sobrevivem os TRÊS PRIMEIROS, nessa ordem — quem paga o corte é o fim "
        "da fila (o anexo periférico), nunca a peça que vem na frente")
    assert gate["n_nao_enviados_cap"] == 1


# ── 2. O caso DOMINANTE: 1 doc só (56 dos 66 cards cegos, `n_inalcancaveis=1`) ──
def test_pdf_unico_acima_do_cap_nao_paga_chamada_nenhuma():
    """Aqui não há leitura a recuperar — o único documento não cabe. O que muda é
    que a razão fica DITA (contador + mensagem com o tamanho) em vez de virar um
    ValueError do SDK sobre 'Gemini Developer client', que não diz nada sobre o
    card. E a chamada não sai: o Gemini nunca é acionado com zero PDFs."""
    prov = _FakeProvider()
    gate: dict = {}

    with pytest.raises(ValueError) as exc:
        asyncio.run(V.call_vision_l1(
            prov, model="m", prompt="p", pdf_bytes_list=[_pdf(6 * _MB)],
            gate_out=gate,
        ))

    assert "VISION_INLINE_CAP_DROP" in str(exc.value)
    assert gate["n_nao_enviados_cap"] == 1
    assert prov._client.chamadas == [], "não pode chamar o Gemini sem PDF nenhum"


# ── 3. A fiação até o veredito que a sentinela lê ────────────────────────────
def test_o_veredito_conta_o_que_SUBIU_nao_o_que_o_gate_aprovou():
    """`n_enviados` é o que o Gemini recebeu. Com o cap dropando 1 de 2, dizer 2
    faria a sentinela ler leitura que não houve — e o card cego some da conta."""
    prov = _FakeProvider()
    gate: dict = {}

    async def _fake_fetch(urls):
        return [_pdf(2 * _MB), _pdf(6 * _MB)]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(V, "fetch_pdfs_from_gcs", _fake_fetch)
        mp.setenv("VISION_L1_ENABLED", "true")
        out = asyncio.run(V.call_l1_with_vision_fallback(
            prov, model="m", prompt="p", response_schema=None,
            gcs_urls=["gs://b/1.pdf", "gs://b/2.pdf"], gate_out=gate,
        ))

    assert len(prov._client.chamadas) == 1, "o que coube foi lido"
    assert gate["n_enviados"] == 1 and gate["n_nao_enviados_cap"] == 1
    assert out.metadata["pdfs_processed"] == 1


def test_n_enviados_vem_da_RESPOSTA_nao_de_uma_subtracao():
    """Régua copiada: enquanto o cap for o ÚNICO motivo de drop,
    `len(pedidos) - n_nao_enviados_cap` COINCIDE com a verdade por identidade
    aritmética, e nenhum teste acima separa as duas fórmulas. Este separa,
    simulando o segundo motivo de drop — que o docstring do módulo já anuncia
    como o passo seguinte (encolher o PDF por páginas).

    ⛔ MUTANTE: voltar a subtrair reprova aqui, dizendo `n_enviados=2` contra
    `pdfs_processed=1` — dois números divergentes DENTRO da mesma resposta, e a
    sentinela lendo leitura que não houve."""
    prov = _FakeProvider()
    gate: dict = {}
    real_build = V._build_pdf_parts

    def _dropa_por_outro_motivo(types, pdf_bytes_list, gate_out=None):
        # dropa 1 SEM tocar no contador do cap: é exatamente o que um segundo
        # motivo de drop faria, e o que quebra a subtração.
        return real_build(types, pdf_bytes_list[:-1], gate_out)

    async def _fake_fetch(urls):
        return [_pdf(_MB), _pdf(_MB)]   # os dois CABEM: o cap não corta nada aqui

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(V, "_build_pdf_parts", _dropa_por_outro_motivo)
        mp.setattr(V, "fetch_pdfs_from_gcs", _fake_fetch)
        mp.setenv("VISION_L1_ENABLED", "true")
        out = asyncio.run(V.call_l1_with_vision_fallback(
            prov, model="m", prompt="p", response_schema=None,
            gcs_urls=["gs://b/1.pdf", "gs://b/2.pdf"], gate_out=gate,
        ))

    assert gate["n_nao_enviados_cap"] == 0, "premissa: o cap não foi o que cortou"
    assert out.metadata["pdfs_processed"] == 1
    assert gate["n_enviados"] == 1, (
        "n_enviados tem que sair de `pdfs_processed`; por subtração daria 2-0=2")


def test_cap_engoliu_tudo_cai_no_texto_com_a_CAUSA_carimbada():
    """O card fica cego do mesmo jeito — mas agora `n_nao_enviados_cap>0` separa
    'não coube' de 'o modelo recusou' (o 400 é o modo dominante das falhas de
    Vision). Sem esse discriminador, `n_enviados=0` mistura os dois."""
    prov = _FakeProvider()
    gate: dict = {}

    async def _fake_fetch(urls):
        return [_pdf(6 * _MB)]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(V, "fetch_pdfs_from_gcs", _fake_fetch)
        mp.setenv("VISION_L1_ENABLED", "true")
        out = asyncio.run(V.call_l1_with_vision_fallback(
            prov, model="m", prompt="p", response_schema=None,
            gcs_urls=["gs://b/1.pdf"], gate_out=gate,
        ))

    assert out == "RESPOSTA_TEXTO" and prov.texto_chamado
    assert prov._client.chamadas == []
    assert gate["n_enviados"] == 0 and gate["n_nao_enviados_cap"] == 1
