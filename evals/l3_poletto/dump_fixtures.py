"""Congela os fixtures do eval L3 vs Poletto a partir do DB de producao (read-only).

Para cada merito rotulado pelo Poletto (monitoramento.apolices_monitoradas):
  - label Poletto (risco_poletto + apolice_aceita)
  - risco de PRODUCAO atual + decomposicao (factual_agg/juris_agg/derived/llm_legacy)
    do ultimo card merito_synthesis  -> baseline `--from-snapshot`
  - PAYLOAD de input do L3 (mesmas queries dos loaders do materializer L3) ->
    `processo_syntheses` (com role injetado) + tomador + cdas + previous
    (v2.8, 2026-07-14: aiims REMOVIDO do payload — teardown autos-wide)

Reproduz FIELMENTE garantis_shared.engine_v6.layer3_merito_synthesis.loaders +
materializer._build_payload_and_context (SQL copiado de la). Read-only: usa o
claude-db-tools HTTP (nao precisa de cred CloudSQL local).

Uso:
  python dump_fixtures.py            # escreve evals/l3_poletto/fixtures/*.json
  python dump_fixtures.py --limit 10 # amostra pra teste rapido
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

DB_URL = "https://claude-db-tools-394302633873.southamerica-east1.run.app/api/query"
FIX_DIR = Path(__file__).resolve().parent / "fixtures"


def _token() -> str:
    import os
    tok = os.environ.get("DB_TOKEN")
    if tok:
        return tok.strip()
    # Windows: gcloud e gcloud.cmd -> shell=True acha no PATH.
    return subprocess.check_output(
        "gcloud auth print-identity-token", text=True, shell=True
    ).strip()


def q(sql: str, token: str) -> list[dict]:
    body = json.dumps({"sql": sql}).encode("utf-8")
    req = urllib.request.Request(
        DB_URL, data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        out = json.loads(resp.read())
    if not out.get("success"):
        raise RuntimeError(f"query failed: {out.get('error')}\nSQL: {sql[:200]}")
    return out.get("data", [])


def _chunks(xs: list, n: int):
    for i in range(0, len(xs), n):
        yield xs[i : i + n]


def _pg_array(items: list[str]) -> str:
    """Monta ARRAY['a','b'] ASCII-safe (PNs e cnpjs sao digit-only)."""
    safe = [x for x in items if x and x.replace(".", "").replace("-", "").isalnum()]
    return "ARRAY[" + ",".join(f"'{x}'" for x in safe) + "]::text[]"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="amostra N meritos (0=todos)")
    ap.add_argument("--merito-ids", type=str, default="",
                    help="CSV de merito_ids especificos (ex: '6995,680012'). Vazio=todos rotulados.")
    ap.add_argument("--out-dir", type=str, default="",
                    help="dir de saida (default: ./fixtures). Use um dir separado p/ subset fresco.")
    args = ap.parse_args()
    out_dir = Path(args.out_dir) if args.out_dir else FIX_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    id_filter = ""
    if args.merito_ids.strip():
        ids = [x.strip() for x in args.merito_ids.split(",") if x.strip().isdigit()]
        id_filter = f"AND merito_id = ANY(ARRAY[{','.join(ids)}]::bigint[])"
    token = _token()

    # 1) Meritos rotulados + metadata + risco de producao + decomposicao.
    print("[1/6] meritos rotulados + producao...", file=sys.stderr)
    rows = q(
        f"""
        WITH pol AS (
          SELECT DISTINCT ON (merito_id) merito_id, risco_poletto, apolice_aceita
          FROM monitoramento.apolices_monitoradas
          WHERE merito_id IS NOT NULL AND risco_poletto IS NOT NULL
          {id_filter}
          ORDER BY merito_id, id
        ),
        card AS (
          SELECT DISTINCT ON (entity_id::bigint) entity_id::bigint AS merito_id, summary
          FROM leitura_conexos.dossier_artifacts
          WHERE kind='merito_synthesis' AND entity_type='merito' AND superseded_at IS NULL
          ORDER BY entity_id::bigint, generated_at DESC
        )
        SELECT p.merito_id, p.risco_poletto, p.apolice_aceita,
               m.titulo, m.tipo_principal, m.cnpj_principal, m.razao_social,
               c.summary->>'risco' AS prod_risco,
               c.summary->'risk_decomposition'->>'risco_factual_aggregated' AS factual_agg,
               c.summary->'risk_decomposition'->>'risco_jurisprudencial_aggregated' AS juris_agg,
               c.summary->'risk_decomposition'->>'derived_aggregate' AS derived,
               c.summary->'risk_decomposition'->>'risco_legacy_l3' AS llm_legacy
        FROM pol p
        LEFT JOIN leads.meritos m ON m.id = p.merito_id
        LEFT JOIN card c ON c.merito_id = p.merito_id
        ORDER BY p.merito_id
        """,
        token,
    )
    if args.limit:
        rows = rows[: args.limit]
    meritos = {int(r["merito_id"]): r for r in rows}
    print(f"  {len(meritos)} meritos rotulados", file=sys.stderr)

    mids = list(meritos.keys())
    mid_array = "ARRAY[" + ",".join(str(m) for m in mids) + "]::bigint[]"

    # 2) Role lists (merito -> pn digits + role) — copia load_processo_role_list.
    print("[2/6] role lists...", file=sys.stderr)
    role_rows = q(
        f"""
        SELECT merito_id,
               regexp_replace(item_ref,'[^0-9]','','g') AS pn,
               CASE WHEN role='principal' THEN 'principal' ELSE 'conexo' END AS role
        FROM leads.merito_membros_ativos
        WHERE merito_id = ANY({mid_array}) AND item_type='processo_judicial'
        ORDER BY merito_id, (role='principal') DESC
        """,
        token,
    )
    roles_by_merito: dict[int, list[tuple[str, str]]] = {}
    all_pns: set[str] = set()
    for r in role_rows:
        mid = int(r["merito_id"])
        roles_by_merito.setdefault(mid, []).append((r["pn"], r["role"]))
        if r["pn"]:
            all_pns.add(r["pn"])
    all_pns = sorted(all_pns)
    print(f"  {len(all_pns)} processos-membro", file=sys.stderr)

    # 3) ps_cards (processo_synthesis summaries) — copia load_processo_syntheses.
    print("[3/6] processo_synthesis cards (chunked)...", file=sys.stderr)
    ps_by_pn: dict[str, dict] = {}
    for ch in _chunks(all_pns, 60):
        prows = q(
            f"""
            SELECT DISTINCT ON (entity_id) entity_id AS pn, summary
            FROM leitura_conexos.dossier_artifacts
            WHERE entity_type='processo' AND entity_id = ANY({_pg_array(ch)})
              AND kind='processo_synthesis' AND superseded_at IS NULL
            ORDER BY entity_id, generated_at DESC
            """,
            token,
        )
        for r in prows:
            ps_by_pn[r["pn"]] = r["summary"]
    print(f"  {len(ps_by_pn)}/{len(all_pns)} processos com ps_card", file=sys.stderr)

    # 4) cda cards — copia load_cdas (v2.8: kind='aiim' saiu do loader/payload).
    print("[4/6] cda cards...", file=sys.stderr)
    cda_by_pn: dict[str, list] = {}
    for ch in _chunks(all_pns, 60):
        crows = q(
            f"""
            SELECT entity_id AS pn, summary
            FROM leitura_conexos.dossier_artifacts
            WHERE entity_type='processo' AND entity_id = ANY({_pg_array(ch)})
              AND kind = 'cda' AND superseded_at IS NULL
            ORDER BY generated_at DESC
            """,
            token,
        )
        for r in crows:
            cda_by_pn.setdefault(r["pn"], []).append(r["summary"])

    # 5) tomador cards (por cnpj_basico) — copia load_tomador_card.
    print("[5/6] tomador cards...", file=sys.stderr)
    basicos = sorted({
        (meritos[m].get("cnpj_principal") or "").replace(".", "").replace("/", "").replace("-", "")[:8]
        for m in mids
        if meritos[m].get("cnpj_principal")
    })
    basicos = [b for b in basicos if len(b) == 8]
    tom_by_basico: dict[str, dict] = {}
    for ch in _chunks(basicos, 60):
        trows = q(
            f"""
            SELECT DISTINCT ON (entity_id) entity_id AS cnpj_basico, summary
            FROM leitura_conexos.dossier_artifacts
            WHERE entity_type='tomador' AND entity_id = ANY({_pg_array(ch)})
              AND kind='tomador' AND superseded_at IS NULL
            ORDER BY entity_id, generated_at DESC
            """,
            token,
        )
        for r in trows:
            tom_by_basico[r["cnpj_basico"]] = r["summary"]

    # 6) Monta os fixtures (espelha _build_payload_and_context).
    print("[6/6] montando fixtures...", file=sys.stderr)
    written = 0
    for mid in mids:
        meta = meritos[mid]
        roles = roles_by_merito.get(mid, [])
        role_map = dict(roles)
        ps_cards = []
        for pn, role in roles:
            summ = ps_by_pn.get(pn)
            if summ is None:
                continue
            summ = dict(summ)
            # Producao (load_processo_syntheses) forca processo_numero=entity_id (digits).
            summ["processo_numero"] = pn
            summ["role_no_merito"] = role
            ps_cards.append(summ)
        if not ps_cards:
            # sem L2 -> o L3 abortaria com no-cards; pula (fica fora do eval).
            continue
        cnpj = meta.get("cnpj_principal") or ""
        basico = cnpj.replace(".", "").replace("/", "").replace("-", "")[:8]
        cdas = [c for pn, _ in roles for c in cda_by_pn.get(pn, [])]
        payload = {
            "merito_id": mid,
            "merito_context": "global",
            "titulo": meta.get("titulo"),
            "tipo_principal": meta.get("tipo_principal"),
            "cnpj_principal": cnpj or None,
            "razao_social": meta.get("razao_social"),
            "processo_syntheses": ps_cards,
            "tomador": tom_by_basico.get(basico),
            "cdas": cdas,
            "previous_snapshot": None,  # nao usado pro risco; trajetoria desabilitada
        }
        fixture = {
            "merito_id": mid,
            "context": "global",
            "poletto": {
                "risco": meta.get("risco_poletto"),
                "apolice_aceita": meta.get("apolice_aceita"),
            },
            "production": {
                "risco": meta.get("prod_risco"),
                "factual_agg": meta.get("factual_agg"),
                "juris_agg": meta.get("juris_agg"),
                "derived": meta.get("derived"),
                "llm_legacy": meta.get("llm_legacy"),
            },
            "payload": payload,
        }
        (out_dir / f"{mid}.json").write_text(
            json.dumps(fixture, ensure_ascii=False), encoding="utf-8"
        )
        written += 1
    print(f"OK: {written} fixtures em {out_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
