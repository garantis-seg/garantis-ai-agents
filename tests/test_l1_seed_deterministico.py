"""O L1 manda `seed` — e ele CHEGA no `GenerateContentConfig`, nos dois ramos.

Por que isto tem teste próprio (e não virou 1 assert no
`test_gemini_determinism.py`): no L1 o micro-ruído do decode a temp=0 não sai como
"outro fraseado", sai como OUTRO RÓTULO em campo enumerado — e esse rótulo (`tipo`)
é metade da chave de `leads.admin_items` (`UNIQUE (tipo, numero_normalizado)`,
write-once). Duas leituras do MESMO documento que discordam não se corrigem por
UPDATE: FORKAM a entidade em dois nós permanentes.
Medido em prod (2026-08-14): cards 2232509 e 2232514, **3 segundos** de distância,
mesmo `mov_id` (`peticao-01688863120164025101`), mesmo `doc_id` (770644), mesma
`prompt_version` v6.0, mesmo `gemini-3.1-flash-lite` → `paf` e `pa`.

⛔ A suíte tem que ficar VERMELHA se o seed for (a) não passado, (b) instável entre
leituras idênticas, (c) constante entre leituras DIFERENTES, (d) aceito pelo helper
e perdido no caminho até o SDK — que é o modo de falha barato aqui, porque
`call_vision_l1` monta o `GenerateContentConfig` À MÃO, fora do
`_build_config_params` do provider. Nenhum teste aqui lê o fonte: todos EXECUTAM.
"""
from __future__ import annotations

import asyncio

import pytest

from google.genai import types as gtypes  # noqa: E402

from src.agents._utils import vision as V  # noqa: E402
from src.agents._utils.llm_seed import seed_for  # noqa: E402

_FLAG = "ENGINE_LLM_SEED_ENABLED"


# ── fakes que capturam o CONFIG (não só o kwarg) ─────────────────────────────
class _ClientQueCapturaConfig:
    """Guarda o `GenerateContentConfig` REAL que saiu pro SDK.

    É o boundary que importa: `seed` é campo do `GenerateContentConfig`, então se
    alguém aceitar o kwarg e esquecer de montá-lo no config, o `visto[-1].seed`
    vem `None` e o teste reprova. Contar chamadas não pegaria isso.
    """

    def __init__(self) -> None:
        self.configs: list = []
        outer = self

        class _Models:
            async def generate_content(self, *, model, contents, config):
                outer.configs.append(config)

                class _R:
                    text = "{}"
                    usage_metadata = None

                return _R()

        class _Aio:
            models = _Models()

        self.aio = _Aio()


class _ProviderQueCaptura:
    """Provider com `_types` REAL do SDK — o config é validado pelo pydantic do
    google-genai, então um `seed` de tipo errado reprova aqui e não em prod."""

    def __init__(self) -> None:
        self._types = gtypes
        self._client = _ClientQueCapturaConfig()
        self.agenerate_kwargs: list[dict] = []

    def get_model_pricing(self, model):
        return {"input_per_1m": 0.0, "output_per_1m": 0.0}

    async def agenerate(self, **kw):
        self.agenerate_kwargs.append(kw)

        class _R:
            text = "{}"
            metadata = {"model_variant": "text"}
            input_tokens = output_tokens = 1

        return _R()


# ── 1. O boundary do SDK: `call_vision_l1` monta o config À MÃO ──────────────
def test_call_vision_l1_poe_o_seed_NO_CONFIG_do_sdk():
    """⛔ MUTANTE de 1 caractere que este teste existe pra pegar: apagar a linha
    `config_kwargs["seed"] = seed` (ou trocar `is not None` por `is None`).
    Sem este assert o fix nasce INERTE no ramo Vision e a suíte fica verde —
    `call_vision_l1` não passa pelo `_build_config_params`, que é onde o único
    teste de seed do repo (`test_gemini_determinism.py`) olha."""
    prov = _ProviderQueCaptura()

    asyncio.run(V.call_vision_l1(
        prov, model="m", prompt="p", pdf_bytes_list=[b"%PDF-1.4 fake"], seed=4242,
    ))

    assert len(prov._client.configs) == 1
    assert prov._client.configs[0].seed == 4242


def test_call_vision_l1_sem_seed_NAO_fixa_nada():
    """A outra metade do contrato do `seed_for`: flag OFF devolve `None`, e `None`
    tem que ser no-op — não `seed=None` explícito com significado, nem `seed=0`
    (0 é seed VÁLIDO e fixaria a amostragem com a flag desligada)."""
    prov = _ProviderQueCaptura()

    asyncio.run(V.call_vision_l1(
        prov, model="m", prompt="p", pdf_bytes_list=[b"%PDF-1.4 fake"],
    ))

    assert prov._client.configs[0].seed is None


# ── 2. O helper fia o seed nos DOIS ramos ────────────────────────────────────
def test_helper_fia_o_seed_no_ramo_TEXTO():
    """Ramo dominante (99,7% do volume). ⛔ MUTANTE: tirar `seed=seed` do
    `provider.agenerate` final."""
    prov = _ProviderQueCaptura()

    asyncio.run(V.call_l1_with_vision_fallback(
        prov, model="m", prompt="p", gcs_urls=[], response_schema=None, seed=777,
    ))

    assert prov.agenerate_kwargs[-1]["seed"] == 777


def test_helper_fia_o_seed_no_ramo_VISION(monkeypatch):
    """⛔ MUTANTE: tirar `seed=seed` da chamada a `call_vision_l1`. Qual ramo roda
    depende do gate, que o caller NÃO controla — fiar só um deixaria o determinismo
    dependendo de uma decisão de rota, e o ramo Vision é justamente o que lê
    documento-imagem/vetor, onde a leitura é mais frágil."""
    recebido: dict = {}

    async def _fake_fetch(urls):
        return [b"%PDF-1.4 fake"]

    async def _fake_vision(provider, *, pdf_bytes_list, **kw):
        recebido.update(kw)

        class _R:
            metadata = {"pdfs_processed": len(pdf_bytes_list)}

        return _R()

    monkeypatch.setattr(V, "fetch_pdfs_from_gcs", _fake_fetch)
    monkeypatch.setattr(V, "call_vision_l1", _fake_vision)
    # A flag vai pelo ENV de verdade: o `flag_enabled` é importado DENTRO da função.
    monkeypatch.setenv("VISION_L1_ENABLED", "true")

    asyncio.run(V.call_l1_with_vision_fallback(
        _ProviderQueCaptura(), model="m", prompt="p", response_schema=None,
        gcs_urls=["gs://b/x.pdf"], seed=777,
    ))

    assert recebido.get("seed") == 777


# ── 3. O agent: o seed existe, é ESTÁVEL e DISCRIMINA ────────────────────────
def _seed_visto(monkeypatch, *, texto_doc: str, mov_id: str, flag: str) -> int | None:
    """Roda `classify_mov_factsheet` DE VERDADE e devolve o seed que ele mandou."""
    from src.agents.mov_factsheet import agent as A

    visto: dict = {}

    async def _fake_fallback(provider, **kw):
        visto.update(kw)

        class _R:
            text = '{"tipo_doc":"peticao_inicial","resumo_ato":"x"}'
            input_tokens = output_tokens = 1
            metadata = {"model_variant": "text"}

        return _R()

    monkeypatch.setattr(A, "call_l1_with_vision_fallback", _fake_fallback)
    monkeypatch.setattr(A, "create_provider", lambda p: object())
    monkeypatch.setenv("L1_NEUTRAL_ENABLED", "true")
    monkeypatch.setenv(_FLAG, flag)

    asyncio.run(A.classify_mov_factsheet(
        processo={"cnj": "01688863120164025101"},
        mov={"mov_id": mov_id, "texto": ""},
        documentos_anexados=[{"doc_key": "jb-770644", "tipo": "1",
                              "text_content": texto_doc}],
        classe="peticao",
    ))
    return visto.get("seed")


_DOC_A = "Processo Administrativo no 10880.913187/2014-11, Receita Federal. " * 20
_DOC_B = "Processo Administrativo no 99999.111111/2020-22, Sefaz. " * 20
_MOV = "peticao-01688863120164025101"


def test_o_MESMO_input_produz_o_MESMO_seed(monkeypatch):
    """A propriedade que corta o fork: os 2 cards a 3s de distância recebem o
    MESMO seed. ⛔ MUTANTE: pôr qualquer coisa volátil nas parts (timestamp,
    `id()`, `uuid4()`, contador) — a suíte fica vermelha aqui."""
    s1 = _seed_visto(monkeypatch, texto_doc=_DOC_A, mov_id=_MOV, flag="true")
    s2 = _seed_visto(monkeypatch, texto_doc=_DOC_A, mov_id=_MOV, flag="true")

    assert isinstance(s1, int), "o agent não mandou seed nenhum (kwarg ausente/None)"
    assert s1 == s2


def test_inputs_DIFERENTES_produzem_seeds_DIFERENTES(monkeypatch):
    """⛔ MUTANTE que só este pega: `seed = 0` (ou qualquer constante). O teste de
    estabilidade acima passaria feliz — constante é o mais estável que existe —
    e todo documento do acervo passaria a ser amostrado com o mesmo seed.

    ⚠️ O que este teste NÃO pega: dropar o `mov_id` das parts do seed. O
    `prompts_v4` embute o literal do mov_id DENTRO do prompt, então trocar o
    mov_id troca o prompt e o segundo assert se satisfaz sozinho — verificado
    executando o mutante: este teste fica VERDE. Quem pega aquele mutante é o
    `test_o_seed_e_o_do_llm_seed_e_cabe_no_int32_do_gemini` (fonte única).
    Por isso os asserts abaixo afirmam só o que OBSERVAM ("mudar X mudou o
    seed"), nunca "X entra no seed" — que é conclusão sobre as parts, e essas
    duas coisas divergem exatamente no caso do mov_id."""
    s_doc = _seed_visto(monkeypatch, texto_doc=_DOC_A, mov_id=_MOV, flag="true")
    s_doc_outro = _seed_visto(monkeypatch, texto_doc=_DOC_B, mov_id=_MOV, flag="true")
    s_mov_outro = _seed_visto(monkeypatch, texto_doc=_DOC_A, mov_id="peticao-outro",
                              flag="true")

    assert s_doc != s_doc_outro, "mudar o CONTEUDO lido nao mudou o seed"
    assert s_doc != s_mov_outro, "mudar o mov_id nao mudou o seed"


def test_flag_OFF_nao_manda_seed(monkeypatch):
    """⛔ MUTANTE: trocar `seed_for` por `deterministic_seed` (ungated). O ship é
    inerte por default e o flip é explícito — e é assim que dá pra medir o antes
    e o depois. Todos os testes acima passariam com o mutante."""
    assert _seed_visto(monkeypatch, texto_doc=_DOC_A, mov_id=_MOV, flag="false") is None


def test_o_seed_e_o_do_llm_seed_e_cabe_no_int32_do_gemini(monkeypatch):
    """Amarra o valor à fonte única (`_utils/llm_seed.py`) em vez de re-derivá-lo
    aqui — teste que reimplementa a regra testa a própria cópia. E confere a faixa:
    o Gemini rejeita seed fora de int32 positivo, e `deterministic_seed` mascara
    justamente por isso.

    ⛔ NÃO É REDUNDANTE com o teste de inputs-diferentes — este é o ÚNICO guard do
    mutante "dropar o `mov_id` das parts". Verificado executando o mutante: o de
    inputs-diferentes fica VERDE (o mov_id já vive dentro do prompt, então trocá-lo
    troca o prompt e o assert de lá se satisfaz sozinho); só este reprova, porque
    compara contra a chave EXATA. Enxugar este teste por parecer redundante remove
    a cobertura daquele mutante inteira."""
    from src.agents.mov_factsheet import agent as A

    visto: dict = {}

    async def _fake_fallback(provider, **kw):
        visto.update(kw)

        class _R:
            text = '{"tipo_doc":"peticao_inicial","resumo_ato":"x"}'
            input_tokens = output_tokens = 1
            metadata = {"model_variant": "text"}

        return _R()

    monkeypatch.setattr(A, "call_l1_with_vision_fallback", _fake_fallback)
    monkeypatch.setattr(A, "create_provider", lambda p: object())
    monkeypatch.setenv("L1_NEUTRAL_ENABLED", "true")
    monkeypatch.setenv(_FLAG, "true")

    asyncio.run(A.classify_mov_factsheet(
        processo={"cnj": "01688863120164025101"},
        mov={"mov_id": _MOV, "texto": ""},
        documentos_anexados=[{"doc_key": "jb-770644", "tipo": "1",
                              "text_content": _DOC_A}],
        classe="peticao",
    ))

    esperado = seed_for("mov_factsheet", _MOV, visto["prompt"])
    assert visto["seed"] == esperado
    assert 0 <= visto["seed"] <= 0x7FFFFFFF


# ── 4. Guarda de escopo: o pacote NÃO toca o prompt (decisão D-c) ────────────
def test_o_seed_nao_alterou_o_prompt(monkeypatch):
    """O seed é parâmetro de AMOSTRAGEM. Se o prompt mudasse junto, o efeito
    medido depois não seria atribuível — e o prompt do mov_factsheet está
    explicitamente fora deste pacote."""
    from src.agents.mov_factsheet import agent as A
    from src.agents.mov_factsheet.prompts_v4 import build_mov_factsheet_prompt_v4
    from src.agents.mov_factsheet.schemas import DocAnexado, MovInput, ProcessoContext

    visto: dict = {}

    async def _fake_fallback(provider, **kw):
        visto.update(kw)

        class _R:
            text = '{"tipo_doc":"peticao_inicial","resumo_ato":"x"}'
            input_tokens = output_tokens = 1
            metadata = {"model_variant": "text"}

        return _R()

    monkeypatch.setattr(A, "call_l1_with_vision_fallback", _fake_fallback)
    monkeypatch.setattr(A, "create_provider", lambda p: object())
    monkeypatch.setenv("L1_NEUTRAL_ENABLED", "true")
    monkeypatch.setenv(_FLAG, "true")

    proc = {"cnj": "01688863120164025101"}
    mov = {"mov_id": _MOV, "texto": ""}
    docs = [{"doc_key": "jb-770644", "tipo": "1", "text_content": _DOC_A}]

    asyncio.run(A.classify_mov_factsheet(
        processo=proc, mov=mov, documentos_anexados=docs, classe="peticao",
    ))

    esperado = build_mov_factsheet_prompt_v4(
        ProcessoContext(**proc), MovInput(**mov),
        documentos_anexados=[DocAnexado(**docs[0])],
        fallback_context=None, classe="peticao",
    )
    assert visto["prompt"] == esperado
