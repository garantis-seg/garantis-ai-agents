"""Onda 8 — o grafo de emissão é ACHATADO (§6.2): refs por id, sem recursão.

Mutation-kill do §9.1: *"introduzir `$ref` recursivo → falha"*. Ferramentas
FSM-based rejeitam ou achatam recursão em profundidade fixa; o schema da FASE B
tem que ser plano POR CONSTRUÇÃO, e este teste percorre o JSON Schema gerado.
"""

from src.agents.calculo_ficha.schemas import GrafoAchatado


def _refs_de(no, acc):
    if isinstance(no, dict):
        if "$ref" in no:
            acc.add(no["$ref"].split("/")[-1])
        for v in no.values():
            _refs_de(v, acc)
    elif isinstance(no, list):
        for v in no:
            _refs_de(v, acc)


def test_sem_ref_recursivo():
    schema = GrafoAchatado.model_json_schema()
    defs = schema.get("$defs", {})
    # grafo de dependencia entre $defs — ciclo = recursao = FSM degrada
    arestas = {}
    for nome, corpo in defs.items():
        alvo: set = set()
        _refs_de(corpo, alvo)
        arestas[nome] = alvo - {nome} if nome not in alvo else alvo

    def _tem_ciclo(nome, caminho):
        if nome in caminho:
            return True
        return any(_tem_ciclo(v, caminho | {nome}) for v in arestas.get(nome, ()))

    for nome in defs:
        assert not _tem_ciclo(nome, set()), f"$ref recursivo via {nome!r}"


def test_celulas_e_evidencias_sao_listas_planas():
    schema = GrafoAchatado.model_json_schema()
    defs = schema.get("$defs", {})
    # cada $def referenciado pelas listas so pode conter escalares/arrays de
    # escalares — nenhum objeto aninhado de segundo nivel
    for nome, corpo in defs.items():
        for prop, spec in (corpo.get("properties") or {}).items():
            filhos: set = set()
            _refs_de(spec, filhos)
            assert not filhos, (
                f"{nome}.{prop} referencia {filhos} — profundidade > 2; o grafo "
                "achatado usa refs por ID (depende_de: [str]), nunca objeto"
            )


def test_depende_de_e_lista_de_strings():
    campo = GrafoAchatado.model_json_schema()["$defs"]["CelulaFormula"][
        "properties"]["depende_de"]
    assert campo["type"] == "array" and campo["items"]["type"] == "string"
