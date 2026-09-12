"""Nenhum cloudbuild deste repo pode passar `--allow-unauthenticated`. Card 869f12nv9.

⭐⭐ O DEFEITO QUE ESTE TESTE EXISTE PRA MATAR, e ele NAO e hipotetico.

`--allow-unauthenticated` no `gcloud run deploy` **GRAVA** `allUsers -> roles/run.invoker`
na IAM policy do servico a cada deploy — nao e "permitir se alguem ja tiver permitido".
Prova de audit log, do merge do 3347f02 em 2026-09-09:

    gcloud logging read 'protoPayload.serviceName="run.googleapis.com" AND
      protoPayload.methodName:"SetIamPolicy" AND protoPayload.resourceName=
      "projects/neqsti/locations/southamerica-east1/services/garantis-ai-agents"' \\
      --project=neqsti --freshness=180d
    => SetIamPolicy as 13:13 e 13:26 UTC pela SA de build (394302633873-compute@),
       request.policy.bindings = [{members:["allUsers"], role:"roles/run.invoker"}]

🚨 Como isso morde: o trigger `deploy-garantis-ai-agents` observa `^master$` e **nao tem
`includedFiles`**, logo QUALQUER push em master deploya — inclusive o PR de pin que o bot
do `bump_consumers.py` do garantis-shared abre sozinho minutos depois de um merge la.
Fechar `allUsers` por `remove-iam-policy-binding` dura ate o proximo merge, e **nada
detecta**: o reconcile diario STRICT compara `services.yaml` x Cloud Run vivo em
env_vars/secrets/sizing, e o bloco deste servico nao declara campo de auth nenhum.

⇒ o fecho mora no caminho de DEPLOY, e este teste e o gate: o step `unit-tests` do
`cloudbuild-deploy.yaml` roda `tests/` e o `kaniko-build` tem `waitFor: ['unit-tests']`,
entao vermelho aqui significa **imagem nao queimada, deploy nao acontece**.

⛔ E o predicado NAO e `"--allow-unauthenticated" in texto`: o comentario que explica
tudo isto **cita o flag literalmente** em 3 arquivos (inclusive este). Ancora textual
crua reprovaria a propria lapide — a armadilha que esta casa ja pagou 3x.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parent.parent

#: A grafia proibida, como TOKEN. `\b` nas duas pontas pra `--no-allow-unauthenticated`
#: (a forma CERTA) nunca casar: o `-no-` antes quebra a fronteira a esquerda.
_PROIBIDO = re.compile(r"(?<![\w-])--allow-unauthenticated\b")


def _cloudbuilds() -> list[Path]:
    achados = sorted(_RAIZ.glob("cloudbuild*.yaml"))
    assert achados, (
        "nenhum cloudbuild*.yaml encontrado — o glob esta apontando pra raiz errada e "
        "este teste seria vacuo"
    )
    return achados


def _linhas_executaveis(texto: str):
    """`(numero, linha)` de toda linha que NAO e comentario YAML.

    ⛔ O filtro e o que separa *"o deploy passa o flag"* de *"alguem escreveu o nome do
    flag numa explicacao"*. Sem ele, o comentario de 20 linhas que documenta este mesmo
    risco reprova o build.
    ⚠️ Comentario `#` dentro do corpo de um script bash (bloco `|`) tambem cai aqui, e
    isso e o certo: la ele tambem nao executa.
    """
    for i, raw in enumerate(texto.splitlines(), start=1):
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        yield i, s


@pytest.mark.parametrize("arq", _cloudbuilds(), ids=lambda p: p.name)
def test_nenhum_cloudbuild_passa_allow_unauthenticated(arq: Path):
    texto = arq.read_text(encoding="utf-8")
    hits = [
        f"{arq.name}:{n}: {linha[:90]}"
        for n, linha in _linhas_executaveis(texto)
        if _PROIBIDO.search(linha)
    ]
    assert not hits, (
        "cloudbuild passando `--allow-unauthenticated`: o deploy vai GRAVAR "
        "`allUsers -> run.invoker` na IAM policy e reabrir o servico pra internet "
        "inteira (20 rotas POST que gastam Vertex + os prompts crus do engine).\n"
        "Quem chama manda OIDC via `garantis_shared.s2s_auth.auth_header_for`; a forma "
        "certa aqui e `--no-allow-unauthenticated`.\n" + "\n".join(hits)
    )


def test_o_deploy_de_prod_declara_o_flag_NEGATIVO_explicitamente():
    """⛔ Ausencia do flag NAO basta, e e por isso que este teste existe separado.

    `gcloud run deploy` sem flag de auth **preserva** a policy existente. Isso deixaria
    o fecho dependendo de uma escrita de IAM fora do git — exatamente o que o comentario
    do modulo diz que nao dura. O flag negativo explicito e o que torna o deploy
    IDEMPOTENTEMENTE fechado: cada build re-afirma o fecho.
    """
    arq = _RAIZ / "cloudbuild-deploy.yaml"
    linhas = [l for _n, l in _linhas_executaveis(arq.read_text(encoding="utf-8"))]
    assert any(re.search(r"--no-allow-unauthenticated\b", l) for l in linhas), (
        "cloudbuild-deploy.yaml nao declara `--no-allow-unauthenticated`. Sem ele o "
        "deploy so PRESERVA a policy, e o fecho volta a depender de escrita manual de "
        "IAM — que o proximo deploy de qualquer branch pode desfazer."
    )


def test_controle_positivo_o_detector_ENXERGA_a_grafia_proibida():
    """⭐ Sem isto, um detector cego passaria os dois testes de cima para sempre.

    E o controle exercita as 2 FORMAS vivas: item de lista de `args` e flag solta dentro
    de um bloco de script bash.
    """
    forma_args = "      - '--allow-unauthenticated'"
    forma_bash = "        gcloud run deploy x --region=y --allow-unauthenticated --quiet"
    for forma in (forma_args, forma_bash):
        achou = [l for _n, l in _linhas_executaveis(forma) if _PROIBIDO.search(l)]
        assert achou, f"detector CEGO a forma: {forma!r}"


def test_controle_negativo_a_grafia_CERTA_nao_e_confundida():
    """⛔ `--no-allow-unauthenticated` contem a substring proibida. Se o predicado for
    substring crua, o conserto reprova a si mesmo e alguem "resolve" removendo o flag —
    que e justamente o estado que `test_o_deploy_de_prod_declara_o_flag_NEGATIVO` proibe.
    """
    certa = "      - '--no-allow-unauthenticated'"
    assert not [l for _n, l in _linhas_executaveis(certa) if _PROIBIDO.search(l)], (
        "o detector casou `--no-allow-unauthenticated` — a fronteira de token esta "
        "errada e o conserto reprova a si mesmo"
    )


def test_comentario_que_CITA_o_flag_nao_reprova():
    """⭐ A lapide tem de sobreviver. O comentario de 20 linhas que documenta este risco
    cita o flag de proposito, e ha 3 arquivos com essa citacao."""
    lapide = "      # ⛔⛔ NAO volte pra `--allow-unauthenticated`. Card 869f12nv9."
    assert not [l for _n, l in _linhas_executaveis(lapide) if _PROIBIDO.search(l)], (
        "o detector reprovou um COMENTARIO — guarda de nome proibido escrita com grep "
        "no fonte reprova a propria documentacao dela"
    )
