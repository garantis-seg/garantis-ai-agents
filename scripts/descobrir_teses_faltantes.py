"""Descobre teses faltantes em ref.teses_tributarias via workers IA.

Cross-check inverso do validar_jurisprudencia.py: em vez de validar a
classificacao existente, ataca o lado oposto — pega meritos Poletto SEM
tese_canonica_id (monitoramento.merito_poletto.tese_canonica_id IS NULL),
mostra ao worker a lista completa das 38 teses existentes e o
justificativa_poletto do orfao, e pergunta:

  (a) mapear: existe tese atual que serve? Qual tese_id?
  (b) generico: padrao processual sem tese juridica especifica
  (c) nova_tese: propor nome + categoria + descricao curta

Output: JSON em --out-dir com proposed_teses agregado.

Usa o mesmo wrapper Gemini + claude-db-tools REST do validar_jurisprudencia.

Custo esperado: ~$0.05 (18 orfaos x 3 personas = 54 calls).

Uso:
    python descobrir_teses_faltantes.py
    python descobrir_teses_faltantes.py --out-dir ./out --max-workers 4
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import google.generativeai as genai


def _gcloud_secret(name: str) -> str:
    return subprocess.check_output(
        f"gcloud secrets versions access latest --secret {name} --project neqsti",
        text=True, shell=True,
    ).strip()


def _gcloud_token() -> str:
    return subprocess.check_output(
        "gcloud auth print-identity-token", text=True, shell=True,
    ).strip()


GEMINI_KEY = os.environ.get("GEMINI_API_KEY") or _gcloud_secret("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_KEY)
GEMINI_FLASH = genai.GenerativeModel("gemini-2.5-flash")

DB_URL = os.environ.get(
    "DB_TOOLS_URL",
    "https://claude-db-tools-34pal47ocq-rj.a.run.app/api/query",
)


def query_db(sql: str) -> list[dict]:
    import requests
    token = _gcloud_token()
    r = requests.post(
        DB_URL,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"sql": sql},
        timeout=60,
    )
    r.raise_for_status()
    payload = r.json()
    if not payload.get("success"):
        raise RuntimeError(f"DB error: {payload.get('error')}")
    return payload.get("data", [])


PERSONAS = {
    "academico": (
        "Voce e professor de Direito Tributario e Civil em universidade reconhecida. "
        "Voce avalia padroes processuais com criterio NEUTRO e RIGOROSO. "
        "Voce prefere mapear casos a teses existentes quando ha encaixe razoavel, "
        "e so propoe NOVA tese quando ha lacuna clara com volume estatistico."
    ),
    "pratico": (
        "Voce e advogado tributarista/trabalhista/civelista com 20+ anos de pratica "
        "real em TRFs, TJs e TST. Voce conhece os padroes recorrentes em monitoramento "
        "de apolices de seguro garantia e identifica clusters de casos juridicamente "
        "semelhantes que ainda nao foram catalogados como tese."
    ),
    "cetico": (
        "Voce e Devil's Advocate. Sua tarefa explicita e DESCONFIAR de criar tese nova: "
        "se o padrao for puramente PROCESSUAL (ex: Cumprimento de Sentenca, Embargos a "
        "Execucao) sem tese juridica de merito por tras, voce DEVE classificar como "
        "generico. So aceita NOVA tese se ha questao juridica substantiva."
    ),
}


def build_prompt(persona_key: str, orphan: dict, teses_existentes: list[dict]) -> str:
    persona_desc = PERSONAS[persona_key]
    teses_block = "\n".join(
        f"  - tese_id={t['id']} | {t['nome']} | categoria={t.get('categoria', 'n/a')}"
        for t in teses_existentes
    )
    return f"""{persona_desc}

TAREFA: avaliar um merito orfao (sem tese_canonica_id) e decidir entre:
  (a) mapear pra uma tese EXISTENTE (citar tese_id)
  (b) confirmar como GENERICO (padrao processual sem tese de merito)
  (c) propor NOVA tese (com nome + categoria + descricao curta)

=== MERITO ORFAO ===
ID: {orphan['merito_id']}
Titulo: {orphan['titulo']}
Tipo principal: {orphan['tipo_principal']}
Materia: {orphan['materia']}
Risco humano Poletto: {orphan['risco_poletto']}
Justificativa Poletto: {orphan['justif']}

=== TESES EXISTENTES (catalogo ref.teses_tributarias, 38 ativas) ===
{teses_block}

=== SUA DECISAO ===
Considere:
- Se a justificativa descreve um padrao puramente processual (Cumprimento de
  Sentenca, Embargos a Execucao, Acao Anulatoria/MS sem sentenca), provavelmente
  e GENERICO — nao tese de merito.
- Se ha tese existente com nome semelhante OU categoria compativel e fato juridico
  encaixavel, MAPEAR.
- Propor NOVA tese SO se ha lacuna clara — questao juridica nao coberta +
  potencial volume (ex: pattern recorrente).

Retorne APENAS JSON valido no formato:
{{
  "decisao": "mapear|generico|nova_tese",
  "tese_id_mapeada": <int|null>,
  "nova_tese_nome": "<string|null>",
  "nova_tese_categoria": "Tributario|Trabalhista|Civel|null",
  "nova_tese_descricao": "<1-2 frases|null>",
  "justificativa": "1-2 frases explicando sua decisao",
  "confidence": 0.0-1.0
}}"""


@dataclass
class WorkerResult:
    merito_id: int
    persona: str
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    elapsed_s: float = 0.0


async def call_gemini(prompt: str, temperature: float = 0.3) -> dict[str, Any]:
    loop = asyncio.get_event_loop()

    def _sync():
        resp = GEMINI_FLASH.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": temperature,
            },
        )
        return resp.text

    text = await loop.run_in_executor(None, _sync)
    return json.loads(text)


async def run_worker(orphan: dict, persona: str, teses: list[dict]) -> WorkerResult:
    started = time.time()
    result = WorkerResult(merito_id=orphan["merito_id"], persona=persona)
    try:
        prompt = build_prompt(persona, orphan, teses)
        result.output = await call_gemini(prompt)
    except Exception as e:
        result.error = f"{type(e).__name__}: {e!r}"[:300]
    result.elapsed_s = round(time.time() - started, 2)
    return result


async def main(out_dir: Path, max_workers: int):
    print("[gap] carregando orfaos...")
    orphans = query_db("""
        SELECT mp.id AS merito_id, mp.titulo, mp.tipo_principal,
               am.materia, am.risco_poletto,
               LEFT(am.justificativa_poletto, 500) AS justif
        FROM monitoramento.merito_poletto mp
        JOIN monitoramento.apolices_monitoradas am ON am.id = mp.apolice_monitorada_id
        WHERE mp.tese_canonica_id IS NULL
          AND am.justificativa_poletto IS NOT NULL
        ORDER BY mp.id
    """)
    print(f"[gap] {len(orphans)} orfaos")

    print("[gap] carregando teses existentes...")
    teses = query_db("""
        SELECT id, nome, categoria
        FROM ref.teses_tributarias
        WHERE ativa = TRUE
        ORDER BY categoria NULLS LAST, nome
    """)
    print(f"[gap] {len(teses)} teses ativas")

    print(f"[gap] disparando {len(orphans) * 3} workers (3 personas x {len(orphans)})")
    sem = asyncio.Semaphore(max_workers)

    async def guarded(orphan, persona):
        async with sem:
            return await run_worker(orphan, persona, teses)

    tasks = [
        guarded(o, p)
        for o in orphans
        for p in ("academico", "pratico", "cetico")
    ]
    results = await asyncio.gather(*tasks)
    n_err = sum(1 for r in results if r.error)
    print(f"[gap] {len(results)} resultados, {n_err} erros")

    by_orphan: dict[int, list[WorkerResult]] = defaultdict(list)
    for r in results:
        by_orphan[r.merito_id].append(r)

    consolidated: list[dict] = []
    for orphan in orphans:
        mid = orphan["merito_id"]
        rs = by_orphan[mid]
        decisoes = [r.output.get("decisao") for r in rs if not r.error]
        decisao_counter = Counter(decisoes)
        majority_decisao = decisao_counter.most_common(1)[0][0] if decisoes else None
        majority_strength = decisao_counter[majority_decisao] if majority_decisao else 0

        nova_propostas = [
            r.output.get("nova_tese_nome")
            for r in rs
            if r.output.get("decisao") == "nova_tese" and r.output.get("nova_tese_nome")
        ]

        tese_id_propostas = [
            r.output.get("tese_id_mapeada")
            for r in rs
            if r.output.get("decisao") == "mapear" and r.output.get("tese_id_mapeada")
        ]

        consolidated.append({
            "merito_id": mid,
            "titulo": orphan["titulo"],
            "materia": orphan["materia"],
            "tipo_principal": orphan["tipo_principal"],
            "justif": orphan["justif"],
            "risco_poletto": orphan["risco_poletto"],
            "majority_decisao": majority_decisao,
            "majority_strength": f"{majority_strength}/3",
            "nova_tese_nomes": nova_propostas,
            "tese_id_mapeadas": tese_id_propostas,
            "workers": [
                {"persona": r.persona, "output": r.output, "error": r.error,
                 "elapsed_s": r.elapsed_s}
                for r in rs
            ],
        })

    # Agregado: padrões propostos como nova_tese cross-orphan
    nova_tese_global = Counter()
    for c in consolidated:
        for nome in c["nova_tese_nomes"]:
            if nome:
                nova_tese_global[nome.strip().lower()] += 1

    summary = {
        "n_orfaos": len(orphans),
        "n_teses_existentes": len(teses),
        "n_workers_total": len(results),
        "n_erros": n_err,
        "distribuicao_decisao": dict(Counter(
            c["majority_decisao"] for c in consolidated if c["majority_decisao"]
        )),
        "nova_tese_propostas_agregadas": [
            {"nome_normalizado": k, "votos": v}
            for k, v in nova_tese_global.most_common(20)
        ],
        "orfaos": consolidated,
    }

    out_path = out_dir / "descobrir_teses_faltantes.json"
    out_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[gap] saved {out_path}")

    print("\n[gap] === RESUMO ===")
    print(f"distribuicao_decisao: {summary['distribuicao_decisao']}")
    print(f"\ntop propostas de nova tese (votos cross-orfao):")
    for prop in summary["nova_tese_propostas_agregadas"][:10]:
        print(f"  {prop['votos']}x  {prop['nome_normalizado']}")


def cli():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out-dir", type=Path, default=Path.cwd())
    ap.add_argument("--max-workers", type=int, default=8)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    asyncio.run(main(args.out_dir, args.max_workers))


if __name__ == "__main__":
    cli()
