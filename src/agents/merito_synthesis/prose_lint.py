"""Deterministic List-B leakage linter for the justificativa prose — operationalizes
the auto-check of <filtro_redacao_advogado> (prompts._build_filtro_redacao, v2.6).
Co-located with the filter it mirrors: change the filter's List-B, change this.

0 violations = prose passes the objective gate (the "faz sentido" coherence is a
separate, LLM/human judgment). Cheap, no LLM. Used as:
  1. runtime guard — redacao.redact_merito_synthesis retries then falls back to a
     deterministic template when lint() != [];
  2. telemetria — leak categories logged per cascade (L3_PROSE_LEAK);
  3. CI gate — tests/test_prose_lint.py runs the demo() corpus.

    from .prose_lint import lint
    viols = lint(justificativa)   # list[(categoria, trecho)]
"""
import re

# (d) literais de bastidor — case-insensitive
_BANNED = [
    r"daycoval", r"poletto", r"architecture\s*d", r"sem\s+nuance",
    r"determin[ií]stic", r"piso\s+m[ií]nimo", r"protocolo\s+de\s+risco\s+base",
    r"regra\s+[gh]\b", r"\bsnapshot", r"\bengine\b", r"\bmov_id\b", r"\bcard(s)?\b",
    r"\bscore\b", r"\bcamada\b", r"\bL[23]\b", r"processo_synthesis", r"factual\s*=",
    r"juris\s*=", r"matriz\s*=", r"template\b", r"\bpv\b", r"-fiscal\b",
]
# class-labels do modelo (esquerda da tabela de traducao) — devem virar prosa
_CLASS_LABELS = [r"poucas_chances", r"pro_fazenda_firmado", r"'remota'", r"'provavel'",
                 r"'possivel'", r"'pacifica'", r"'agregada'"]

_PATTERNS = [
    ("decimal_score", re.compile(r"\b(0\.\d+|1\.0+)\b")),          # (a) 0.20, 1.0
    ("percentual",    re.compile(r"\d+\s*%")),                     # (a) %
    ("snake_case",    re.compile(r"\b[a-zà-ÿ]+_[a-zà-ÿ_]+\b", re.I)),  # (b) merito_id, mov_id...
    ("T_codigo",      re.compile(r"\bT-[A-Z]?\d+\b")),             # (e) T-B1, T-XX
    ("merito_id_num", re.compile(r"m[ée]rito[s]?[\s_]*\d", re.I)), # 'merito' + numero
    ("hash",          re.compile(r"#[0-9a-f]{6,}", re.I)),
    ("versao",        re.compile(r"\bv\d+\.\d+\b", re.I)),
    ("literal_bastidor", re.compile("|".join(_BANNED), re.I)),
    ("class_label",   re.compile("|".join(_CLASS_LABELS), re.I)),
]


def lint(text):
    """Return list of (categoria, trecho) for every List-B leak found. Empty = clean."""
    if not text:
        return []
    viols = []
    for cat, pat in _PATTERNS:
        for mt in pat.finditer(text):
            viols.append((cat, mt.group(0)))
    return viols


def is_clean(text):
    return not lint(text)


def lint_fields(*texts):
    """Lint several prose fields at once. Returns the merged violation list."""
    out = []
    for t in texts:
        out.extend(lint(t))
    return out


def demo():
    errado = ("Esta versao reflete a matriz deterministica, sem nuance de LLM. "
              "Factual=Baixo juris=Medio -> matriz=Medio. score agregado 0.20, "
              "piso minimo de risco Medio (Template T-B1). merito 680128.")
    certo = ("A baixa perspectiva de exito das teses, somada a fase recursal sem "
             "decisao definitiva, sustenta um risco no minimo Medio de acionamento. "
             "A apolice foi aceita em Execucao Fiscal suspensa aguardando os Embargos.")
    ve, vc = lint(errado), lint(certo)
    print("ERRADO viola:", sorted({c for c, _ in ve}))
    print("CERTO viola: ", vc)
    assert len(ve) >= 5, ve
    assert vc == [], vc
    print("prose_lint OK")


if __name__ == "__main__":
    demo()
