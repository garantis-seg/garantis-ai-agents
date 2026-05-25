"""Validador de jurisprudência ref.tese_jurisprudencia via workers IA.

Roda 2 etapas independentes que disparam workers Gemini em paralelo para
validar / sugerir classificação `resultado_majoritario` em ref.tese_jurisprudencia.

Etapa 1: teses COM paradigmas Poletto (ref.tese_decisao_individual.created_by
         = 'poletto-extraction') × 3 personas (Fazendista, Contribuintista,
         Acadêmico). Workers leem paradigmas reais e avaliam se SUPORTAM o
         resultado_majoritario catalogado.

Etapa 2: teses SEM paradigmas × 10 calls (5 personas × 2 calls — Fazendista,
         Contribuintista, Acadêmico, Prático, Cético). Workers classificam do
         zero usando seu conhecimento jurídico + tema STF/STJ.

Output: JSON raw em --out-dir (default: cwd).

Custo histórico: ~$0.15 total para 254 calls (Gemini 2.5 Flash, temp 0.3).
Histórico de execução: 2026-05-25 — ver memory entry
[[validacao-jurisprudencia-workers-ia-2026-05-25]].

Pré-requisitos:
- gcloud auth login (acessa secrets GEMINI_API_KEY no GSM neqsti)
- gcloud auth print-identity-token (chamadas autenticadas em claude-db-tools)
- pip install google-generativeai requests

Uso:
    python validar_jurisprudencia.py etapa1
    python validar_jurisprudencia.py etapa2
    python validar_jurisprudencia.py etapa1 --out-dir ./out
    python validar_jurisprudencia.py etapa2 --max-workers 4

Variáveis de ambiente opcionais (sobrepõem gcloud):
    GEMINI_API_KEY
    DB_TOOLS_URL (default: https://claude-db-tools-34pal47ocq-rj.a.run.app/api/query)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import google.generativeai as genai


# ── Setup secrets ────────────────────────────────────────────────────────


def _gcloud_secret(name: str) -> str:
    # Windows: gcloud é gcloud.cmd; usar shell=True funciona cross-platform
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
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_FLASH = genai.GenerativeModel(GEMINI_MODEL)

DB_URL = os.environ.get(
    "DB_TOOLS_URL",
    "https://claude-db-tools-34pal47ocq-rj.a.run.app/api/query",
)


# ── DB access ────────────────────────────────────────────────────────────


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


# ── Personas ────────────────────────────────────────────────────────────


PERSONAS = {
    "fazendista": {
        "name": "Tributarista Fazendista",
        "description": (
            "Voce e advogado especialista em defesa da Fazenda Publica (Uniao, Estados, "
            "Municipios). Sua experiencia inclui ate 30 anos em procuradorias. Voce tende "
            "a interpretar jurisprudencia com vies CONSERVADOR pro Fisco — quando ha duvida, "
            "considera que prevalece o interesse arrecadatorio. Voce e conhecido por defender "
            "a presuncao de legitimidade dos atos administrativos e da CDA."
        ),
    },
    "contribuintista": {
        "name": "Tributarista Contribuintista",
        "description": (
            "Voce e advogado especialista em defesa do contribuinte. Sua experiencia inclui "
            "ate 30 anos representando grandes empresas em contencioso tributario. Voce tende "
            "a interpretar jurisprudencia com vies DEFENSIVO pro contribuinte — busca brechas "
            "argumentativas, distinguishing de precedentes, e teses de modulacao. Voce e cetico "
            "sobre 'jurisprudencia firmada' — sabe que mesmo temas STF tem questionamentos."
        ),
    },
    "academico": {
        "name": "Acadêmico Neutro",
        "description": (
            "Voce e professor de Direito Tributario em universidade reconhecida. Sua experiencia "
            "inclui doutorado, publicacoes em revistas tecnicas, e participacao em comissoes "
            "academicas. Voce avalia jurisprudencia com criterio NEUTRO e RIGOROSO — foca em "
            "precedentes STF e STJ (especialmente Temas com repercussao geral e repetitivos), "
            "distingue entre obiter dictum e ratio decidendi, e prefere certeza tecnica a "
            "ativismo de qualquer lado."
        ),
    },
    "pratico": {
        "name": "Tributarista Prático",
        "description": (
            "Voce e advogado tributarista com experiencia de PRATICA real em TRFs e TJs. "
            "Voce conhece como a jurisprudencia 'oficial' STF/STJ se traduz no dia a dia das "
            "instancias inferiores — frequentemente diverge. Voce avalia jurisprudencia por "
            "como ela TEM SIDO APLICADA, nao pelo que esta firmado em tese."
        ),
    },
    "cetico": {
        "name": "Cético / Devil's Advocate",
        "description": (
            "Voce e advogado tributarista experiente cuja tarefa explicita e PROCURAR "
            "CONTRA-PRECEDENTES. Quando ve uma tese marcada como 'firmada', voce busca "
            "decisoes opositoras recentes (modulacao, distinguishing, mudanca de entendimento). "
            "Sua presenca evita falsa precisao — voce sinaliza quando uma classificacao "
            "'firmada' pode ja nao ser tao firme."
        ),
    },
}


RESULTADO_VALORES = [
    "pro_contribuinte_firmado", "pro_fazenda_firmado", "oscilante",
    "pendente_julgamento_superior", "tese_nova", "nao_classificada",
]


# ── Prompts ─────────────────────────────────────────────────────────────


def build_etapa1_prompt(persona_key: str, tese: dict, paradigmas: list[dict]) -> str:
    persona = PERSONAS[persona_key]
    paradigmas_block = "\n".join(
        f"  - Paradigma {i+1} (Risco humano Poletto={p.get('risco_humano', 'n/a')}): "
        f"{(p.get('ementa_resumo') or '')[:600]}"
        for i, p in enumerate(paradigmas[:8])
    )
    return f"""{persona['description']}

TAREFA: validar a classificacao de uma tese juridica em nossa base.

=== TESE ANALISADA ===
ID: {tese['tese_id']}
Nome: {tese['nome']}
Categoria: {tese.get('categoria', 'n/a')}
Tema STF: {tese.get('tema_stf', 'n/a')}
Tema STJ: {tese.get('tema_stj', 'n/a')}
Descricao: {(tese.get('descricao') or '')[:600]}

CLASSIFICACAO ATUAL: resultado_majoritario={tese.get('resultado_majoritario', 'NULL')}

Significados dos valores:
  - pro_contribuinte_firmado: tese STF/STJ vinculante, favoravel ao contribuinte
  - pro_fazenda_firmado: tese STF/STJ vinculante, favoravel a Fazenda
  - oscilante: decisoes divididas, sem majoritario claro
  - pendente_julgamento_superior: tema afetado, aguarda STF/STJ
  - tese_nova: sem historico significativo
  - nao_classificada: catch-all generico

=== PARADIGMAS REAIS (curados pela corretora Poletto que monitora apolices) ===
Esses sao casos REAIS onde apolice de seguro garantia foi acionada/monitorada
nessa tese. As ementas descrevem o cenario juridico e o desfecho:

{paradigmas_block}

=== SUA ANALISE ===
Considerando sua PERSONA ({persona['name']}) e os paradigmas acima:

1. Os paradigmas SUPORTAM a classificacao atual ({tese.get('resultado_majoritario', 'NULL')})?
   - "sim" se 70%+ dos paradigmas sao consistentes com a classificacao
   - "parcialmente" se 40-70%
   - "nao" se < 40%

2. Sua sugestao final: manter ou mudar pra qual valor?
   - Escolher: pro_contribuinte_firmado | pro_fazenda_firmado | oscilante |
     pendente_julgamento_superior | tese_nova | nao_classificada | manter

3. Justificativa: 1-2 frases citando paradigma especifico OU jurisprudencia
   conhecida que sustenta sua opiniao.

4. Confidence (0.0-1.0): quanto voce confia na sua avaliacao.

Retorne APENAS JSON valido neste formato:
{{
  "suporta_classificacao": "sim|parcialmente|nao",
  "sugestao": "pro_contribuinte_firmado|pro_fazenda_firmado|oscilante|pendente_julgamento_superior|tese_nova|nao_classificada|manter",
  "justificativa": "1-2 frases citando paradigma ou jurisprudencia",
  "confidence": 0.0-1.0
}}"""


def build_etapa2_prompt(persona_key: str, tese: dict) -> str:
    persona = PERSONAS[persona_key]
    return f"""{persona['description']}

TAREFA: classificar o estado da jurisprudencia sobre uma tese tributaria
SEM acesso a paradigmas reais — apenas seu conhecimento juridico.

=== TESE ANALISADA ===
ID: {tese['tese_id']}
Nome: {tese['nome']}
Categoria: {tese.get('categoria', 'n/a')}
Tema STF: {tese.get('tema_stf', 'n/a')}
Tema STJ: {tese.get('tema_stj', 'n/a')}
Descricao: {(tese.get('descricao') or '')[:600]}

CLASSIFICACAO ATUAL EM NOSSO SISTEMA:
  resultado_majoritario={tese.get('resultado_majoritario', 'NULL')}
  observacao={(tese.get('observacao') or '')[:300]}

Significados dos valores:
  - pro_contribuinte_firmado: tese STF/STJ vinculante, favoravel ao contribuinte
  - pro_fazenda_firmado: tese STF/STJ vinculante, favoravel a Fazenda
  - oscilante: decisoes divididas, sem majoritario claro
  - pendente_julgamento_superior: tema afetado, aguarda STF/STJ
  - tese_nova: sem historico significativo
  - nao_classificada: catch-all generico

=== SUA ANALISE ===
Use seu conhecimento juridico (treinamento) sobre o estado da jurisprudencia
desta tese no Brasil. Considere sua PERSONA ({persona['name']}).

1. Sua classificacao final: qual valor?
2. Justificativa: 1-2 frases citando acordaos VERIFICAVEIS (numero + ano)
   quando conhecidos. Se nao conhece bem a tese, diga.
3. Acordaos chave (2-3): liste com formato "TRIBUNAL CASO/ANO".
4. Confidence (0.0-1.0).

Retorne APENAS JSON valido neste formato:
{{
  "sugestao": "pro_contribuinte_firmado|pro_fazenda_firmado|oscilante|pendente_julgamento_superior|tese_nova|nao_classificada",
  "justificativa": "1-2 frases citando jurisprudencia",
  "acordaos_chave": ["TRIBUNAL Caso/Ano", "..."],
  "confidence": 0.0-1.0
}}"""


# ── Workers (async) ─────────────────────────────────────────────────────


@dataclass
class WorkerResult:
    tese_id: int
    persona: str
    model: str
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


async def run_worker(tese: dict, persona: str, model: str, build_prompt) -> WorkerResult:
    started = time.time()
    result = WorkerResult(tese_id=tese["tese_id"], persona=persona, model=model)
    try:
        prompt = (
            build_prompt(persona, tese)
            if build_prompt.__code__.co_argcount == 2
            else build_prompt(persona, tese, tese["paradigmas"])
        )
        result.output = await call_gemini(prompt)
    except Exception as e:
        result.error = f"{type(e).__name__}: {e!r}"[:300]
    result.elapsed_s = round(time.time() - started, 2)
    return result


# ── Main: etapa 1 ──────────────────────────────────────────────────────


async def etapa1(out_dir: Path, max_workers: int):
    print(f"[etapa1] Buscando teses com paradigmas...")
    teses = query_db("""
        SELECT t.id AS tese_id, t.nome, t.categoria, t.tema_stf, t.tema_stj,
               t.descricao, tj.resultado_majoritario, tj.observacao
        FROM ref.teses_tributarias t
        LEFT JOIN ref.tese_jurisprudencia tj ON tj.tese_id = t.id
        WHERE t.ativa = TRUE
          AND EXISTS (SELECT 1 FROM ref.tese_decisao_individual td
                      WHERE td.tese_id = t.id AND td.created_by = 'poletto-extraction')
        ORDER BY t.id
    """)
    print(f"[etapa1] {len(teses)} teses")

    for tese in teses:
        rows = query_db(f"""
            SELECT ementa_resumo, observacao AS risco_humano
            FROM ref.tese_decisao_individual
            WHERE tese_id = {tese['tese_id']}
              AND eh_paradigma = TRUE
              AND created_by = 'poletto-extraction'
            ORDER BY id LIMIT 8
        """)
        tese["paradigmas"] = rows
    print(f"[etapa1] paradigmas carregados")

    workers = []
    for tese in teses:
        workers.append((tese, "fazendista", "gemini"))
        workers.append((tese, "contribuintista", "gemini"))
        workers.append((tese, "academico", "gemini"))
    print(f"[etapa1] disparando {len(workers)} workers ({len(teses)} teses x 3)")

    sem = asyncio.Semaphore(max_workers)

    async def guarded(tese, persona, model):
        async with sem:
            return await run_worker(tese, persona, model, build_etapa1_prompt)

    tasks = [guarded(t, p, m) for t, p, m in workers]
    results = await asyncio.gather(*tasks)
    print(f"[etapa1] {len(results)} resultados, {sum(1 for r in results if r.error)} erros")

    out = {
        "etapa": 1,
        "n_teses": len(teses),
        "n_workers_per_tese": 3,
        "workers": ["gemini:fazendista", "gemini:contribuintista", "gemini:academico"],
        "results": [
            {"tese_id": r.tese_id,
             "tese_nome": next(t["nome"] for t in teses if t["tese_id"] == r.tese_id),
             "resultado_atual": next(t.get("resultado_majoritario") for t in teses if t["tese_id"] == r.tese_id),
             "persona": r.persona, "model": r.model,
             "output": r.output, "error": r.error, "elapsed_s": r.elapsed_s}
            for r in results
        ],
    }
    out_path = out_dir / "valida_etapa1.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[etapa1] saved {out_path}")


# ── Main: etapa 2 ──────────────────────────────────────────────────────


async def etapa2(out_dir: Path, max_workers: int):
    print(f"[etapa2] Buscando teses sem paradigmas...")
    teses = query_db("""
        SELECT t.id AS tese_id, t.nome, t.categoria, t.tema_stf, t.tema_stj,
               t.descricao, tj.resultado_majoritario, tj.observacao
        FROM ref.teses_tributarias t
        LEFT JOIN ref.tese_jurisprudencia tj ON tj.tese_id = t.id
        WHERE t.ativa = TRUE
          AND NOT EXISTS (SELECT 1 FROM ref.tese_decisao_individual td
                          WHERE td.tese_id = t.id AND td.created_by = 'poletto-extraction')
        ORDER BY t.id
    """)
    print(f"[etapa2] {len(teses)} teses")

    workers = []
    for tese in teses:
        for persona in ("fazendista", "contribuintista", "academico", "pratico", "cetico"):
            workers.append((tese, persona, "gemini"))
            workers.append((tese, persona, "gemini"))
    print(f"[etapa2] disparando {len(workers)} workers ({len(teses)} teses x 10)")

    sem = asyncio.Semaphore(max_workers)

    async def guarded(tese, persona, model):
        async with sem:
            return await run_worker(tese, persona, model, build_etapa2_prompt)

    tasks = [guarded(t, p, m) for t, p, m in workers]
    results = await asyncio.gather(*tasks)
    print(f"[etapa2] {len(results)} resultados, {sum(1 for r in results if r.error)} erros")

    out = {
        "etapa": 2,
        "n_teses": len(teses),
        "n_workers_per_tese": 10,
        "results": [
            {"tese_id": r.tese_id,
             "tese_nome": next(t["nome"] for t in teses if t["tese_id"] == r.tese_id),
             "resultado_atual": next(t.get("resultado_majoritario") for t in teses if t["tese_id"] == r.tese_id),
             "persona": r.persona, "model": r.model,
             "output": r.output, "error": r.error, "elapsed_s": r.elapsed_s}
            for r in results
        ],
    }
    out_path = out_dir / "valida_etapa2.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[etapa2] saved {out_path}")


# ── Entrypoint ──────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("etapa", choices=["etapa1", "etapa2"],
                    help="etapa1: teses com paradigmas (3 workers). etapa2: teses sem (10 workers)")
    ap.add_argument("--out-dir", type=Path, default=Path.cwd(),
                    help="diretório para o JSON de saída (default: cwd)")
    ap.add_argument("--max-workers", type=int, default=8,
                    help="paralelismo máximo (default: 8)")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.etapa == "etapa1":
        asyncio.run(etapa1(args.out_dir, args.max_workers))
    else:
        asyncio.run(etapa2(args.out_dir, args.max_workers))


if __name__ == "__main__":
    main()
