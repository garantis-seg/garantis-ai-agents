"""Renderers do prompt do mov_factsheet agent (engine v6_meritos camada 1).

O prompt e o `build_mov_factsheet_prompt_v4` (`prompts_v4.py`), que importa daqui o
bloco de 1 documento (`_summarize_doc`).
"""

from .schemas import DocAnexado


# Cap por doc anexado no prompt (Flash Lite 1M context aguenta, mas economiza)
_DOC_TEXT_CAP_CHARS = 8000


def _summarize_doc(
    doc: DocAnexado, idx: int, total: int, text_cap: int = _DOC_TEXT_CAP_CHARS,
    text_override: str | None = None,
) -> str:
    """Bloco de 1 doc no prompt. text_cap: cap de exibição — o v4 passa o próprio
    orçamento (sem-limite).
    text_override: texto já transformado pelo caller (head+tail de evidência no v4)
    — usado no lugar de doc.text_content quando fornecido."""
    text = (text_override if text_override is not None else (doc.text_content or "")).strip()
    truncated_note = ""
    if len(text) > text_cap:
        text = text[:text_cap]
        truncated_note = f"\n  [TRUNCADO a {text_cap} chars do original]"
    parts = [f"--- DOC {idx + 1}/{total} ---"]
    meta = []
    if doc.tipo:
        meta.append(f"tipo: {doc.tipo}")
    if doc.titulo:
        meta.append(f"titulo: {doc.titulo}")
    if doc.data_documento:
        meta.append(f"data_documento: {doc.data_documento}")
    if doc.paginas:
        meta.append(f"paginas: {doc.paginas}")
    if doc.provider:
        meta.append(f"provider: {doc.provider}")
    if meta:
        parts.append("  " + " | ".join(meta))
    parts.append("  texto:")
    parts.append("  " + text.replace("\n", "\n  "))
    if truncated_note:
        parts.append(truncated_note)
    return "\n".join(parts)
