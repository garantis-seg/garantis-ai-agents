"""Redator v5 (S4): o agente que lê os autos antes de escrever a ficha.

Decisão do Alfredo de 23/10/2026: "núcleo obrigatório + índice navegável; o
redator vira v5 como agente". Mesmo endpoint (`POST /ficha/write-fields`). O v5
liga quando o request traz `nucleo` e `indice_navegavel`. O v4 e o v3 continuam.

Duas fases, no molde do qualificador do conexo (S2c):

- Fase A (navegação): sem schema. O LLM escolhe UMA ferramenta por turno
  (`resumir_com_missao`, `perguntar_ao_documento`, `pedir_pagina`) num documento
  do índice. O núcleo já está inteiro no prompt. Budget: 25 chamadas por ficha e
  5 por documento, com circuit breaker (`ferramentas.py`).
- Fase B (escrita): JSON. O LLM escreve os slots no JSON fechado do v4, mais a
  `trilha_leitura`. O código valida e devolve os erros ao LLM, por até 3 rodadas
  (as mesmas do v4). Depois disso, `success=false` com `erros[]`.

Regras duras (no código, não no prompt):

1. Todas as validações do v4 (`validacao.py`): slots pedidos, `max`, obrigatório,
   cifra, números de processo citáveis, regra 25, status do SERPRO (regra 26),
   corretor, alertas respondidos.
2. Slot de mérito, `ultima_decisao.texto`, `descricao_infracao` e todo bullet com
   texto têm trilha. Sem trilha, o slot reprova com erro estruturado para o retry.
3. O `doc_id` da trilha existe no núcleo ou no índice. Um documento do índice foi
   lido de fato na fase A.
4. Com o texto disponível, o `trecho_apoio` está no documento. Quem decide é
   `ferramentas.trecho_confere` (23/10/2026): literal, prefixo de 80 caracteres ou
   similar (no mínimo 0,90), depois de normalizar hífen de fim de linha, quebra,
   acento, aspas e cabeçalho de página. Fora do literal, o aviso
   `trecho_aproximado` registra o método.

Determinismo máximo (plano 1.2, rodada real de 23/10/2026). O código conserta ou
verifica antes de reprovar:

- `trecho_apoio` acima de 200 caracteres: o código corta o trecho no fim de
  palavra antes de validar (rodada IRB: 3 rodadas perdidas pelo tamanho).
- `paginas` é opcional para documento do núcleo. Para documento do índice, o
  código acha a página do trecho.
- Documento do índice que a fase A não leu: o código abre o documento (budget de
  5 documentos por ficha) e confere o trecho (rodada Claro). O aviso
  `verificado_pelo_codigo` registra o caso. Sem sucesso, o erro dá a lista dos
  documentos citáveis, e o prompt do retry repete a lista.
- Slot obrigatório vazio ou ausente: o erro diz o motivo da rodada anterior.

Fato sem fonte (regras 11 e 12 de `validacao.py`, 23/10/2026). Rodada real do IRB
1481420 (rev 00413): o modelo escreveu "não foi admitido em 01/09/2026, encerrando a
via administrativa" em 4 slots, e a data não existe em fonte nenhuma. Agora:

- Toda data (DD/MM/AAAA, "DD de mês de AAAA", MM/AAAA) e todo número de acórdão,
  processo, CDA e valor em R$ de um slot existe, normalizado, numa fonte: o texto do
  núcleo, os documentos lidos na fase A (e os conferidos pelo código), o esqueleto, o
  índice, os alertas, as `premissas_v3` e os `metadados` do núcleo.
- Termo de esgotamento ("esgotad", "não foi admitido", "trânsito", ...) só com a etapa
  concluída no esqueleto ou com a decisão literal nos documentos.
- Falhou: erro estruturado para o retry, com a lista das datas e dos números
  permitidos. Na última rodada, `success=false`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from garantis_shared.llm_models import model_for
from pydantic import ValidationError

from ...providers import create_provider
from ...utils.llm_json import parse_llm_json
from .._utils.llm_seed import seed_for
from .._utils.prompt_identity import versao_com_identidade
from .agent import _resolve_campos_alvo
from .ferramentas import Autos, BudgetNavegacao, cortar_trecho, custo_da_resposta, navegar
from .livro import SlotResolvido, chave_livro, motivos_nao_aplicaveis, resolver_slots
from .prompts_v4 import _fatos_fixos
from .prompts_v5 import (
    PROMPT_VERSION,
    build_prompt_escrita,
    build_prompt_navegacao,
    exige_trilha,
)
from .schemas import (
    AlertaRespondido,
    ErroDeCampo,
    FichaWriteFieldsRequest,
    MAX_TRECHO_APOIO,
    FichaWriteFieldsResponse,
    Nucleo,
    TrilhaItem,
)
from .validacao import (
    CAMPO_SAIDA,
    FontesDeFato,
    avisos,
    origem_valor,
    processos_citaveis,
    processos_citaveis_brutos,
    renovacao_sem_corretor,
    validar_alertas,
    validar_campos,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = model_for("ficha_redacao")

#: Rodadas da fase B. As mesmas 3 do v4.
MAX_RODADAS = 3

#: Budget da fase A (pedido de 23/10/2026).
BUDGET_POR_FICHA = 25
BUDGET_POR_DOC = 5

#: O campo do erro de uma entrada da trilha sem slot reconhecível.
CAMPO_TRILHA = "trilha_leitura"

#: Os erros genéricos do v4 para slot sem texto. O v5 junta o motivo anterior.
_ERROS_DE_SLOT_VAZIO = ("slot obrigatório vazio", "slot ausente na resposta")

#: O aviso de um documento que o código abriu e conferiu (23/10/2026).
AVISO_VERIFICADO = "verificado_pelo_codigo"

#: O aviso de um trecho que casou por prefixo ou por similaridade (23/10/2026).
AVISO_APROXIMADO = "trecho_aproximado"

_AQUI = Path(__file__).resolve().parent


def prompt_version() -> str:
    """`ficha_writer_v5+<hash>`. O hash muda com o prompt v5, o prompt v4 ou o schema."""
    return versao_com_identidade(
        PROMPT_VERSION, str(_AQUI / "prompts_v5.py"), str(_AQUI / "prompts_v4.py"),
        str(_AQUI / "schemas.py"),
    )


# ── A trilha ────────────────────────────────────────────────────────────────


def _trilha_valida(
    parsed: Any, slots_da_rodada: set[str],
) -> tuple[dict[str, list[TrilhaItem]], dict[str, list[ErroDeCampo]]]:
    """Lê a `trilha_leitura` da saída. Devolve `(itens por slot, erros por slot)`.

    Entrada de slot fora da rodada é descartada (log), como a chave a mais do v4.
    """
    brutas = parsed.get(CAMPO_TRILHA) if isinstance(parsed, dict) else None
    por_slot: dict[str, list[TrilhaItem]] = {}
    erros: dict[str, list[ErroDeCampo]] = {}
    if not isinstance(brutas, list):
        return por_slot, erros
    for i, b in enumerate(brutas):
        slot = str(b.get("slot") or "") if isinstance(b, dict) else ""
        if slot and slot not in slots_da_rodada:
            logger.warning("FICHA_WRITER_V5 trilha de slot fora da rodada descartada: %r", slot)
            continue
        if isinstance(b, dict):
            b = _reparar_entrada(b)
        try:
            item = TrilhaItem.model_validate(b)
        except ValidationError as e:
            msg = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']) or '$'}: {err['msg']}"
                for err in e.errors(include_url=False)
            )
            erros.setdefault(slot or CAMPO_TRILHA, []).append(ErroDeCampo(
                campo=slot or CAMPO_TRILHA,
                erro=f"{slot or CAMPO_TRILHA}: entrada {i} da trilha_leitura inválida ({msg})",
                valor_anterior=b,
            ))
            continue
        por_slot.setdefault(item.slot, []).append(item)
    return por_slot, erros


def _reparar_entrada(b: dict[str, Any]) -> dict[str, Any]:
    """Conserta a forma de uma entrada da trilha antes do schema (23/10/2026).

    - `trecho_apoio` longo: o código corta em 200 caracteres, no fim de palavra.
    - `paginas` nula vira `[]`. Um inteiro solto vira `[n]`.
    """
    b = dict(b)
    if "trecho_apoio" in b:
        b["trecho_apoio"] = cortar_trecho(b["trecho_apoio"], MAX_TRECHO_APOIO)
    pag = b.get("paginas", [])
    if pag is None:
        b["paginas"] = []
    elif isinstance(pag, int) and not isinstance(pag, bool):
        b["paginas"] = [pag]
    return b


def _erros_da_trilha(
    slot: str, texto: str, itens: list[TrilhaItem], autos: Autos,
) -> tuple[list[ErroDeCampo], list[TrilhaItem], list[str]]:
    """As regras 2, 3 e 4 sobre UM slot já aprovado no texto.

    Devolve `(erros, itens com as páginas corrigidas, avisos de verificação)`.
    """
    if not itens:
        return [ErroDeCampo(campo=slot, erro=(
            f"{slot}: slot sem trilha_leitura. Diga o doc_id e o trecho literal que "
            "sustentam o slot (decisão de 23/10/2026). Documentos que você pode citar: "
            f"{autos.citaveis()}"), valor_anterior=texto)], [], []
    erros: list[ErroDeCampo] = []
    reparados: list[TrilhaItem] = []
    avisos_slot: list[str] = []
    for t in itens:
        conf = autos.verificar(t.doc_id, t.paginas, t.trecho_apoio)
        if conf.erro:
            erros.append(ErroDeCampo(
                campo=slot, erro=f"{slot}: trilha_leitura: {conf.erro}",
                valor_anterior=t.model_dump(),
            ))
            continue
        reparados.append(t.model_copy(update={"paginas": conf.paginas}))
        if conf.verificado_pelo_codigo:
            avisos_slot.append(
                f"{AVISO_VERIFICADO}: {slot}: a fase A não leu o documento {t.doc_id}. "
                "O código abriu o documento e achou o trecho")
        if conf.metodo and conf.metodo != "literal":
            avisos_slot.append(
                f"{AVISO_APROXIMADO}: {slot}: o trecho casou por {conf.metodo} no "
                f"documento {t.doc_id}")
    return erros, reparados, avisos_slot


def _com_motivo_anterior(e: ErroDeCampo, rodada: int, motivos: dict[str, str]) -> ErroDeCampo:
    """Slot obrigatório vazio ou ausente: o erro diz o motivo da rodada anterior.

    Na rodada Claro de 23/10/2026, o erro final só dizia "slot obrigatório vazio".
    """
    if not any(g in e.erro for g in _ERROS_DE_SLOT_VAZIO):
        return e
    anterior = motivos.get(e.campo)
    detalhe = (f" Motivo da rodada anterior: {anterior}" if anterior
               else " Não há motivo anterior registrado para este slot.")
    return e.model_copy(update={"erro": f"{e.erro} na rodada {rodada}.{detalhe}"})


def fontes_do_redator(request: FichaWriteFieldsRequest, autos: Autos) -> FontesDeFato:
    """As fontes da regra 11 para o redator (23/10/2026). Ver o docstring do módulo.

    O texto dos documentos entra uma vez (`textos_de_fonte`). Do núcleo estruturado
    sai o texto dos documentos, e ficam os metadados, as CDAs, as premissas e a S2c.
    """
    nucleo = request.nucleo or Nucleo()
    sem_texto = {"__all__": {"texto"}}
    nucleo_dados = nucleo.model_dump(mode="json", exclude={
        "docs": sem_texto, "acordaos": sem_texto,
        "peticao_inicial": {"texto"}, "ultima_decisao": {"texto"},
    })
    indice = [d.model_dump(mode="json", exclude={"documento_indexado"})
              for d in (request.indice_navegavel or [])]
    return FontesDeFato.montar(
        textos_docs=autos.textos_de_fonte(),
        estruturados=[
            _fatos_fixos(request), [a.model_dump() for a in request.alertas],
            nucleo_dados, indice, list(request.processos_citaveis or []),
        ],
        pipeline=request.esqueleto.pipeline if request.esqueleto else [],
    )


def erros_de_fonte(
    ok: dict[str, str], fontes: FontesDeFato, citaveis: Optional[set[str]] = None,
) -> dict[str, list[ErroDeCampo]]:
    """As regras 11 e 12 sobre os slots aprovados. `{slot: erros}` só com quem falhou."""
    out: dict[str, list[ErroDeCampo]] = {}
    for slot, texto in ok.items():
        erros = fontes.erros_do_slot(slot, texto, citaveis)
        if erros:
            out[slot] = erros
    return out


# ── Ponto de entrada ────────────────────────────────────────────────────────


async def write_v5(
    request: FichaWriteFieldsRequest,
    provider: str,
    model: Optional[str] = None,
    leitor_perguntar: Optional[Callable] = None,
    leitor_resumir: Optional[Callable] = None,
) -> FichaWriteFieldsResponse:
    """Roda as fases A e B. Nunca levanta por erro do LLM: devolve `success=false`.

    `leitor_*` são injetáveis para o teste. O default é o `doc_reader`.
    """
    model = model or DEFAULT_MODEL
    pv = prompt_version()
    chave = chave_livro(request)
    campos_alvo, err = _resolve_campos_alvo(request)
    if err is not None:
        return FichaWriteFieldsResponse(
            success=False, model=model, error=err, prompt_version=pv, tipo_livro=chave,
        )
    slots, nao_aplicaveis = resolver_slots(request, campos_alvo)
    motivos = motivos_nao_aplicaveis(chave, nao_aplicaveis)
    avisos_req = avisos(request, chave, slots)
    origem = origem_valor(request)
    sem_corretor = renovacao_sem_corretor(request, chave)
    citaveis = processos_citaveis(request)
    citaveis_txt = processos_citaveis_brutos(request)
    base = {
        "prompt_version": pv, "tipo_livro": chave,
        "campos_nao_aplicaveis": nao_aplicaveis, "motivos_nao_aplicaveis": motivos,
        "avisos": avisos_req,
    }

    if not slots and not request.alertas:
        return FichaWriteFieldsResponse(success=True, model=model, **base)

    autos = Autos(request.nucleo or Nucleo(), request.indice_navegavel or [])
    nucleo_llm = autos.nucleo_para_llm()
    indice_llm = autos.indice_para_llm()
    chave_seed = request.esqueleto.processo_id if request.esqueleto else ""
    llm = create_provider(provider)

    # ── Fase A — navegação ──────────────────────────────────────────────────
    budget = BudgetNavegacao(max_por_ficha=BUDGET_POR_FICHA, max_por_doc=BUDGET_POR_DOC)
    nav = await navegar(
        llm=llm, model=model, autos=autos, budget=budget,
        prompt_de_decisao=lambda achados, menu, restante, por_doc: build_prompt_navegacao(
            request, chave=chave, slots=slots, citaveis=citaveis_txt, nucleo=nucleo_llm,
            indice=indice_llm, achados=achados, menu=menu, budget_restante=restante,
            budget_por_doc=por_doc,
        ),
        seed=lambda turno: seed_for("ficha_writer_v5", chave_seed, "A", turno),
        leitor_perguntar=leitor_perguntar, leitor_resumir=leitor_resumir,
        rotulo="FICHA_WRITER_V5",
    )
    cost_total = nav.custo_usd
    nav_info = {
        "documentos_lidos": sorted(autos.lidos), "chamadas_ferramenta": budget.chamadas,
        "budget_esgotado": nav.budget_esgotado,
    }

    # ── Fase B — escrita com validação ──────────────────────────────────────
    erros_retry: list[ErroDeCampo] = [
        ErroDeCampo(campo=c.nome, erro=c.erro, valor_anterior=c.valor_anterior)
        for c in (request.campos_com_erro or [])
    ]
    pendentes_slots: list[SlotResolvido] = list(slots)
    pendentes_alertas = list(request.alertas)
    # slot -> o último motivo de reprovação que não é "vazio" (23/10/2026).
    motivos: dict[str, str] = {e.campo: e.erro for e in erros_retry}
    avisos_codigo: list[str] = []
    aprovados: dict[str, str] = {}
    trilha: dict[str, list[TrilhaItem]] = {}
    respondidos: dict[str, AlertaRespondido] = {}
    erros: list[ErroDeCampo] = []
    used_model = model
    rodada = 0

    for rodada in range(1, MAX_RODADAS + 1):
        prompt = build_prompt_escrita(
            request, chave=chave, slots=pendentes_slots, alertas=pendentes_alertas,
            citaveis=citaveis_txt, nucleo=nucleo_llm, indice=indice_llm,
            achados=nav.achados, erros_retry=erros_retry, aprovados=aprovados,
            docs_citaveis=autos.citaveis(),
        )
        resp = await llm.agenerate(
            prompt=prompt, model=model, temperature=0.0,
            response_mime_type="application/json", thinking_budget=0, max_tokens=16384,
            seed=seed_for("ficha_writer_v5", chave_seed, "B", rodada),
        )
        used_model = resp.model or used_model
        cost_total += custo_da_resposta(resp)
        raw = resp.text or ""
        try:
            parsed = parse_llm_json(raw)
        except (ValueError, Exception) as e:  # noqa: BLE001
            logger.warning("FICHA_WRITER_V5_PARSE_FAIL rodada=%s: %r | head=%r",
                           rodada, e, raw[:200])
            erros = [ErroDeCampo(campo=CAMPO_SAIDA, erro=f"parse do JSON do LLM falhou: {e}")]
            erros_retry = erros
            continue

        ok, erros_campos = validar_campos(parsed, pendentes_slots, citaveis,
                                          origem_valor=origem, sem_corretor=sem_corretor)
        nomes_rodada = {s.nome for s in pendentes_slots}
        por_slot, erros_trilha = _trilha_valida(parsed, nomes_rodada)
        for slot in list(ok):
            if not exige_trilha(slot) or not ok[slot]:
                continue
            e_slot = erros_trilha.pop(slot, [])
            if not e_slot:
                e_slot, reparados, av = _erros_da_trilha(
                    slot, ok[slot], por_slot.get(slot, []), autos)
            if e_slot:
                del ok[slot]
                erros_campos += e_slot
            else:
                trilha[slot] = reparados
                avisos_codigo += [a for a in av if a not in avisos_codigo]
        # Regras 11 e 12 (23/10/2026): data, número ou esgotamento sem fonte reprova.
        fontes = fontes_do_redator(request, autos)
        for slot, e_slot in erros_de_fonte(ok, fontes, citaveis).items():
            del ok[slot]
            trilha.pop(slot, None)
            erros_campos += e_slot
        # Erro de trilha de slot que já reprovou no texto: o erro do texto basta.
        # Erro de trilha sem slot: vai ao LLM como erro da saída.
        erros_campos += erros_trilha.pop(CAMPO_TRILHA, [])
        erros_campos = [_com_motivo_anterior(e, rodada, motivos) for e in erros_campos]
        for e in erros_campos:
            if not any(g in e.erro for g in _ERROS_DE_SLOT_VAZIO):
                motivos[e.campo] = e.erro
        ok_alertas, erros_alertas = validar_alertas(parsed, pendentes_alertas)
        aprovados.update(ok)
        respondidos.update({a.codigo: a for a in ok_alertas})
        erros = erros_campos + erros_alertas
        if not erros:
            break
        logger.info("FICHA_WRITER_V5 rodada=%s erros=%s", rodada, [e.campo for e in erros])
        com_erro = {e.campo for e in erros_campos}
        if CAMPO_SAIDA in com_erro or CAMPO_TRILHA in com_erro:
            pendentes_slots = [s for s in pendentes_slots if s.nome not in aprovados]
        else:
            pendentes_slots = [s for s in pendentes_slots if s.nome in com_erro]
        pendentes_alertas = [a for a in pendentes_alertas if a.codigo not in respondidos]
        erros_retry = erros

    if avisos_codigo:
        base["avisos"] = [*base["avisos"], *avisos_codigo]
    alertas_ordenados = [respondidos[a.codigo] for a in request.alertas if a.codigo in respondidos]
    trilha_ordenada = [t for s in slots for t in trilha.get(s.nome, [])]
    if erros:
        resumo = "; ".join(f"{e.campo}: {e.erro}" for e in erros)
        return FichaWriteFieldsResponse(
            success=False, campos=aprovados, model=used_model, cost_usd=round(cost_total, 6),
            error=f"validação falhou após {rodada} rodada(s): {resumo}",
            alertas_respondidos=alertas_ordenados, erros=erros, rodadas=rodada,
            trilha_leitura=trilha_ordenada, **base, **nav_info,
        )
    campos = {s.nome: aprovados[s.nome] for s in slots if s.nome in aprovados}
    return FichaWriteFieldsResponse(
        success=True, campos=campos, model=used_model, cost_usd=round(cost_total, 6),
        alertas_respondidos=alertas_ordenados, rodadas=rodada,
        trilha_leitura=trilha_ordenada, **base, **nav_info,
    )


__all__ = [
    "AVISO_APROXIMADO",
    "AVISO_VERIFICADO",
    "BUDGET_POR_DOC",
    "BUDGET_POR_FICHA",
    "CAMPO_TRILHA",
    "DEFAULT_MODEL",
    "MAX_RODADAS",
    "prompt_version",
    "write_v5",
]
