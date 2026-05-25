"""Gera golden snapshot YAML pro PromptFoo regression suite L1 mov_factsheet.

Lê cards atuais de leads.dossier_artifacts (kind='mov_factsheet') + reconstroi
inputs (processo + mov + fb_ctx) via SQL direto. Cada test case do YAML carrega
`vars` (input pro agente) + `expected` (card atual = gabarito).

MVP v1: SO movs sem doc anexado (fallback_used=true). Simplifica fetching e
cobre 70%+ do volume (ordinatorios + publicacoes). Movs com doc anexado
e polo-regression suite ficam pra snapshots v2/v3.

Uso:
    $env:DATABASE_URL = "postgresql://USER:PASS@localhost:5432/garantis"
    python scripts/build_golden_snapshot.py --out golden/snapshot_v1.yaml --sample 30
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("ERRO: psycopg2 nao instalado. Run: pip install psycopg2-binary", file=sys.stderr)
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("ERRO: PyYAML nao instalado. Run: pip install PyYAML", file=sys.stderr)
    sys.exit(1)


# Sample inicial: ordinatorios + decisorias simples sem doc anexado.
# Cards com fallback_used=true e descricao_canonical >= 50 chars (texto util).
_QUERY = """
WITH sampled AS (
    SELECT
        da.id as artifact_id,
        da.entity_id as pn_norm,
        da.summary as expected_card,
        da.raw_ref,
        da.generated_by_model,
        pc.classe,
        pc.polo_ativo,
        pc.polo_passivo,
        pec.cluster_id::text as cluster_id,
        pec.descricao_canonical as mov_texto,
        pec.occurred_at::date::text as mov_data,
        p.resumo_ia as processo_resumo_ia
    FROM leads.dossier_artifacts da
    JOIN leads.processos_canonical pc
      ON pc.processo_numero_normalized = da.entity_id
    LEFT JOIN leads.processos p
      ON p.processo_numero = da.entity_id AND p.grau = '1g'
    LEFT JOIN leads.processo_eventos_canonical pec
      ON pec.cluster_id::text = (da.raw_ref->>'mov_id')
    WHERE da.kind = 'mov_factsheet'
      AND da.entity_type = 'processo'
      AND da.raw_ref->>'fallback_used' = 'true'
      AND pec.descricao_canonical IS NOT NULL
      AND LENGTH(pec.descricao_canonical) >= 50
      AND da.summary->>'error' IS NULL
    ORDER BY RANDOM()
    LIMIT %s
)
SELECT * FROM sampled;
"""


def _format_cnj(pn_norm: str) -> str:
    """20 digits → NNNNNNN-DD.YYYY.J.TR.OOOO."""
    if not pn_norm or len(pn_norm) != 20:
        return pn_norm
    return f"{pn_norm[:7]}-{pn_norm[7:9]}.{pn_norm[9:13]}.{pn_norm[13]}.{pn_norm[14:16]}.{pn_norm[16:]}"


def _polo_to_str(polo) -> str | None:
    """Canonical view retorna polos como list[str]. Agent espera str."""
    if polo is None:
        return None
    if isinstance(polo, list):
        return " / ".join(str(p) for p in polo if p) or None
    return str(polo)


def _build_test_case(row: dict) -> dict:
    """Converte 1 row do query em test case YAML do PromptFoo."""
    raw_ref = row.get("raw_ref") or {}
    if isinstance(raw_ref, str):
        raw_ref = json.loads(raw_ref)

    expected = row.get("expected_card") or {}
    if isinstance(expected, str):
        expected = json.loads(expected)

    processo_resumo_ia = row.get("processo_resumo_ia")
    fb_ctx = None
    if processo_resumo_ia:
        fb_ctx = {
            "processo_resumo_ia": processo_resumo_ia[:1000],
            "mov_anterior_resumo": None,
            "mov_anterior_categoria": None,
            "distance_dias_mov_anterior": None,
        }

    # PromptFoo nao aceita `null` em vars top-level — omite quando vazio.
    vars_dict = {
        "processo": {
            "cnj": _format_cnj(row["pn_norm"]),
            "classe": row.get("classe") or "",
            "classe_cnj_code": 0,  # null nao aceito; 0 = sentinel "nao identificado"
            "polo_ativo": _polo_to_str(row.get("polo_ativo")) or "",
            "polo_passivo": _polo_to_str(row.get("polo_passivo")) or "",
        },
        "mov": {
            "mov_id": row["cluster_id"] or raw_ref.get("mov_id"),
            "data": row.get("mov_data") or "",
            "tipo": raw_ref.get("tipo_origem") or "",
            "texto": row["mov_texto"],
        },
        "documentos_anexados": [],
        "expected": expected,
    }
    if fb_ctx:
        vars_dict["fallback_context"] = fb_ctx

    return {
        "description": (
            f"L1 {expected.get('categoria', '?')}/"
            f"{expected.get('relevancia_merito', '?')} — "
            f"{(row['mov_texto'] or '')[:80].replace(chr(10), ' ')}"
        ),
        "vars": vars_dict,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="Path do YAML output")
    parser.add_argument("--sample", type=int, default=30, help="Sample size (default: 30)")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="Postgres connection string (default: $DATABASE_URL)",
    )
    args = parser.parse_args()

    if not args.database_url:
        print("ERRO: --database-url ou $DATABASE_URL obrigatorio.", file=sys.stderr)
        return 1

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[snapshot] Conectando ao DB...", file=sys.stderr)
    with psycopg2.connect(args.database_url) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            print(f"[snapshot] Query (sample={args.sample})...", file=sys.stderr)
            cur.execute(_QUERY, (args.sample,))
            rows = cur.fetchall()

    print(f"[snapshot] {len(rows)} rows retrieved. Building test cases...", file=sys.stderr)

    test_cases = []
    for row in rows:
        try:
            test_cases.append(_build_test_case(dict(row)))
        except Exception as e:
            print(f"[snapshot] skip row pn={row.get('pn_norm')}: {e!r}", file=sys.stderr)

    print(f"[snapshot] Writing {len(test_cases)} test cases to {out_path}...", file=sys.stderr)
    with out_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            test_cases,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        )

    print(f"[snapshot] Done. {out_path} ({out_path.stat().st_size} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
