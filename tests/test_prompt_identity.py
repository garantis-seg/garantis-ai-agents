"""`prompt_version` DERIVADA do conteudo — card RAIZ [869enrt3w].

## O defeito, medido no incidente real

`processo_synthesis.v2.5` era **identico** antes (137 calls), durante (35) e depois (24) do
PR #180 — a mudanca que ABAIXOU banda e foi revertida 13h depois. ⇒ *"quais cards vieram do
prompt ruim?"* era **irrespondivel**; sobrava arqueologia por janela de timestamp, que pega
card inocente e perde retry fora da janela.

⛔ E nao e "falta bumpar a string": o mesmo vale pro card (`summary_prompt_version` em `v7.0`
em TODOS os 251 `processo_synthesis` e 25.109 `mov_factsheet` de 19/08 ate hoje), onde o campo
e a chave de CACHE — move-lo re-roda a cascata inteira. Identidade que custa dinheiro nao se
move; por isso ela tem de ser **derivada**, nao lembrada.

## O que estes testes guardam

O valor de um hash nao pode ser assertado (ele muda a cada edicao — e esse E o ponto). O que
se guarda e o COMPORTAMENTO: que ele muda quando o conteudo muda, que NAO muda quando nada
muda, que o rotulo humano sobrevive, e que ele nunca derruba uma chamada paga.

Run: pytest tests/test_prompt_identity.py -q
"""
from __future__ import annotations

import pathlib

import pytest

from src.agents._utils.prompt_identity import prompt_identity, versao_com_identidade


@pytest.fixture()
def dois_arquivos(tmp_path):
    a = tmp_path / "prompt.py"
    b = tmp_path / "schema.py"
    a.write_text("REGRA = 'bucketize pela classe'\n", encoding="utf-8")
    b.write_text("class Card: pass\n", encoding="utf-8")
    return a, b


def test_conteudo_igual_da_hash_igual(dois_arquivos):
    """Determinismo: sem isto o id mudaria a cada import e nao serviria de chave."""
    a, b = dois_arquivos
    assert prompt_identity(str(a), str(b)) == prompt_identity(str(a), str(b))


def test_MUDAR_O_PROMPT_muda_a_identidade(dois_arquivos):
    """🚨 O caso do #180: uma linha nova no `<regra_polos>` TEM de virar id novo."""
    a, b = dois_arquivos
    antes = prompt_identity(str(a), str(b))
    a.write_text("REGRA = 'bucketize pela classe'\nPASSO_0 = 'de qual acao e?'\n", encoding="utf-8")
    assert prompt_identity(str(a), str(b)) != antes


def test_MUDAR_O_SCHEMA_tambem_muda(dois_arquivos):
    """⭐ O schema molda a saida tanto quanto o prompt — foi mexendo em `schemas_v4.py` que o
    campo `dispositivo` (PR #182) mudou o comportamento do L1. Custo medido de inclui-lo:
    25 versoes em 90d contra 19/22 so do prompt (e contra 1 hoje)."""
    a, b = dois_arquivos
    antes = prompt_identity(str(a), str(b))
    b.write_text("class Card:\n    dispositivo: str | None = None\n", encoding="utf-8")
    assert prompt_identity(str(a), str(b)) != antes


def test_REVERTER_restaura_a_identidade_ANTIGA(dois_arquivos):
    """⭐⭐ Verificado no git contra o incidente: o revert (`9f53855`) restaurou o blob
    pre-#180 BYTE-IDENTICO. Logo "cards do prompt bom" tem de ser UM balde, nao dois — senao
    a pergunta que o campo existe pra responder fica pela metade."""
    a, b = dois_arquivos
    bom = prompt_identity(str(a), str(b))
    original = a.read_text(encoding="utf-8")
    a.write_text(original + "PASSO_0 = 'x'\n", encoding="utf-8")
    assert prompt_identity(str(a), str(b)) != bom
    a.write_text(original, encoding="utf-8")
    assert prompt_identity(str(a), str(b)) == bom, "revert nao restaurou o id — 2 baldes pro mesmo prompt"


def test_a_ORDEM_dos_arquivos_importa_e_isso_e_deliberado(dois_arquivos):
    """CONTRA-EXEMPLO: e concatenacao, nao soma. Se a ordem nao importasse, dois conteudos
    trocados dariam o mesmo id. O docstring avisa pra sempre passar na mesma ordem."""
    a, b = dois_arquivos
    assert prompt_identity(str(a), str(b)) != prompt_identity(str(b), str(a))


def test_arquivo_ilegivel_NAO_derruba_a_chamada(tmp_path):
    """⛔ Fail-OPEN de proposito. Isto e TELEMETRIA: derrubar uma chamada de LLM paga porque
    um `read_bytes` falhou inverteria a relacao custo/beneficio."""
    assert prompt_identity(str(tmp_path / "nao_existe.py")) == "unknown"


def test_o_ROTULO_humano_sobrevive(dois_arquivos):
    """O rotulo e o que aparece em log e painel; o hash e o que ninguem precisa lembrar."""
    a, b = dois_arquivos
    v = versao_com_identidade("processo_synthesis.v2.5", str(a), str(b))
    assert v.startswith("processo_synthesis.v2.5+")
    assert len(v.split("+", 1)[1]) == 12


# ── o cabeamento real (o que o mutante mais provavel quebra) ─────────────────

def test_o_L2_carimba_identidade_DERIVADA():
    """CONTRA-EXEMPLO do teste do helper: o helper pode estar perfeito e o agent continuar
    com a string a mao. O que importa e o valor que CHEGA na telemetria."""
    from src.agents.processo_synthesis.agent import PROMPT_VERSION

    assert PROMPT_VERSION.startswith("processo_synthesis.v2.5+"), (
        f"o L2 voltou a carimbar identidade a mao: {PROMPT_VERSION!r}"
    )
    assert PROMPT_VERSION.split("+", 1)[1] != "unknown", "o hash nao resolveu — arquivo movido?"


def test_o_L1_carimba_identidade_DERIVADA():
    from src.agents.mov_factsheet.schemas_v4 import PROMPT_VERSION_V4

    assert PROMPT_VERSION_V4.startswith("mov_factsheet.v4.5+")
    assert PROMPT_VERSION_V4.split("+", 1)[1] != "unknown"


def test_a_TRIAGEM_carimba_identidade_DERIVADA():
    """🚨 A camada que MAIS roda e era a que menos se movia: 318.829 de 612.320 chamadas
    reais em 30d (52%) saiam com `mov_triage.v1`, rotulo parado desde 2026-06-04. O
    comentario acima da constante mandava bumpar a mao — e provou que instrucao nao e
    mecanismo."""
    from src.agents.mov_triage.agent import PROMPT_VERSION

    assert PROMPT_VERSION.startswith("mov_triage.v1+"), (
        f"a triagem voltou a carimbar identidade a mao: {PROMPT_VERSION!r}"
    )
    assert PROMPT_VERSION.split("+", 1)[1] != "unknown", "o hash nao resolveu — arquivo movido?"


def test_cada_camada_cobre_PROMPT_E_SCHEMA_dela():
    """⚠️ A lacuna que eu quase deixei passar: os testes acima ficam TODOS verdes se alguem
    tirar o schema da chamada — o helper continua certo e o agent continua derivando algo.
    Aqui o valor e RECOMPUTADO a partir dos 2 arquivos e comparado: se a lista de entradas
    mudar, isto quebra. Comportamental, nao ancora de texto."""
    from src.agents.mov_factsheet import schemas_v4
    from src.agents.mov_triage import agent as triage_agent
    from src.agents.processo_synthesis import agent as l2_agent

    l2_dir = pathlib.Path(l2_agent.__file__).parent
    assert l2_agent.PROMPT_VERSION == versao_com_identidade(
        "processo_synthesis.v2.5", str(l2_dir / "prompts.py"), str(l2_dir / "schemas.py")
    ), "o L2 parou de cobrir prompt+schema (ou mudou a ordem)"

    l1_schema = pathlib.Path(schemas_v4.__file__)
    assert schemas_v4.PROMPT_VERSION_V4 == versao_com_identidade(
        "mov_factsheet.v4.5", str(l1_schema.with_name("prompts_v4.py")), str(l1_schema)
    ), "o L1 parou de cobrir prompt+schema (ou mudou a ordem)"

    triage_dir = pathlib.Path(triage_agent.__file__).parent
    assert triage_agent.PROMPT_VERSION == versao_com_identidade(
        "mov_triage.v1",
        str(triage_dir / "prompts.py"),
        str(triage_dir / "schemas.py"),
        str(triage_dir / "agent.py"),
    ), "a triagem parou de cobrir prompt+schema+agent (ou mudou a ordem)"


def test_a_triagem_cobre_o_AGENT_e_nao_so_prompt_mais_schema():
    """🚨 O conjunto {prompts,schemas} sozinho seria MUDO, nao estavel.

    Medido em 2026-08-24: esses 2 arquivos tem **1 blob em TODA a historia** (nasceram em
    `aa45a02`, 04/06, nunca tocados), enquanto o `agent.py` mudou 6 vezes — e pelo menos 5
    dessas mudam o que o card EMITE: o leak guard de `resumo_ato` (#69-#72, 29/06), que
    SOBRESCREVE pos-LLM um dos 3 campos que o ramo enxuto copia verbatim; e o swap de modelo
    de `b82f156` (21/07). Com os 3 arquivos sao **7 baldes** em toda a historia.

    ⇒ Sem o `agent.py` o hash seria uma CONSTANTE, carregando a mesma informacao que a string
    `"mov_triage.v1"` que ele substitui. Este teste e o que impede alguem de "simplificar" o
    conjunto de volta e reintroduzir o defeito com o carimbo parecendo certo.
    """
    from src.agents.mov_triage import agent as triage_agent

    triage_dir = pathlib.Path(triage_agent.__file__).parent
    sem_o_agent = versao_com_identidade(
        "mov_triage.v1", str(triage_dir / "prompts.py"), str(triage_dir / "schemas.py")
    )
    assert triage_agent.PROMPT_VERSION != sem_o_agent, (
        "o agent.py saiu do conjunto — o hash volta a ser constante em toda a historia"
    )


def test_as_tres_camadas_tem_identidades_DIFERENTES():
    """⭐ Verificado no git: o PR #182 mexeu SO no L1, e o blob do L2 ficou identico ao do
    revert. A identidade e POR CAMADA — se duas colidissem, uma mudanca numa acusaria
    mudanca na outra e o campo mentiria.
    ⚠️ A triagem entra aqui porque o `schemas.py` dela IMPORTA os tipos de input do
    mov_factsheet: e a tentacao de incluir os arquivos do L1 completo no hash dela, e isso
    faria exatamente a colisao que este teste proibe."""
    from src.agents.mov_factsheet.schemas_v4 import PROMPT_VERSION_V4
    from src.agents.mov_triage.agent import PROMPT_VERSION as TRIAGE_VERSION
    from src.agents.processo_synthesis.agent import PROMPT_VERSION

    hashes = [
        PROMPT_VERSION.split("+", 1)[1],
        PROMPT_VERSION_V4.split("+", 1)[1],
        TRIAGE_VERSION.split("+", 1)[1],
    ]
    assert len(set(hashes)) == 3, f"duas camadas colidiram no mesmo id: {hashes}"


def test_o_agent_do_L2_RETORNA_a_versao_no_resultado():
    """⛔ Sem isto o carimbo e letra morta: o `garantis-shared/.../clients/ai_agents.py` so
    enriquece a telemetria *quando o agent retorna* `prompt_version`. Mesma classe de defeito
    que o `dispositivo` pagou hoje (campo emitido e nao persistido)."""
    import inspect

    import src.agents.processo_synthesis.agent as m

    fonte = inspect.getsource(m)
    assert '"prompt_version": PROMPT_VERSION' in fonte, (
        "o agent parou de devolver prompt_version — o carimbo nao chega em engine_llm_calls"
    )


def test_o_agent_da_TRIAGEM_RETORNA_a_versao_no_resultado():
    """Mesmo motivo do L2, e aqui vale 52% do acervo: derivar a constante e nao devolve-la
    deixaria a coluna com o valor VELHO em silencio."""
    import inspect

    import src.agents.mov_triage.agent as m

    fonte = inspect.getsource(m)
    assert '"prompt_version": PROMPT_VERSION' in fonte, (
        "a triagem parou de devolver prompt_version — o carimbo nao chega em engine_llm_calls"
    )
