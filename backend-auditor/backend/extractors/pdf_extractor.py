import logging

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

DOC_CONFIG = {
    "ANX_10_ATUAL":    {"label": "Anexo 10 — Receita (Ano Atual)",    "extrator": "pymupdf"},
    "ANX_10_ANTERIOR": {"label": "Anexo 10 — Receita (Ano Anterior)", "extrator": "pymupdf"},
    "ANX_12":          {"label": "Anexo 12 — Balanço Orçamentário",   "extrator": "camelot"},
    "ANX_06":          {"label": "Anexo 06 — Programa de Trabalho",   "extrator": "pymupdf"},
    "ANX_02":          {"label": "Anexo 02 — Natureza da Despesa",    "extrator": "pymupdf"},
    "ANX_13":          {"label": "Anexo 13 — Balanço Financeiro",     "extrator": "pymupdf"},
    "ANX_14":          {"label": "Anexo 14 — Balanço Patrimonial",    "extrator": "pymupdf"},
    "DFC":             {"label": "DFC — Fluxos de Caixa",             "extrator": "pymupdf"},
    "LOA":             {"label": "LOA — Lei Orçamentária Anual",      "extrator": "pymupdf"},
}


def _extract_municipio(text: str) -> str:
    for line in text.splitlines():
        if "PREFEITURA MUNICIPAL DE" in line.upper():
            return line.strip()
    return ""


def _extract_with_pymupdf(path: str) -> str:
    doc = fitz.open(path)
    pages_text = []
    for i, page in enumerate(doc, start=1):
        pages_text.append(f"[PÁGINA {i}]\n{page.get_text('text')}")
    doc.close()
    return "\n\n".join(pages_text)


def _extract_with_camelot(path: str) -> str:
    import camelot

    doc = fitz.open(path)
    total_pages = len(doc)
    doc.close()

    pages_range = ",".join(str(i) for i in range(1, total_pages + 1))

    try:
        tables = camelot.read_pdf(path, pages=pages_range, flavor="stream")
        if len(tables) == 0:
            logger.warning("camelot não encontrou tabelas em %s — usando fallback PyMuPDF", path)
            return _extract_with_pymupdf(path)

        parts = []
        for i, table in enumerate(tables, start=1):
            parts.append(f"--- TABELA {i} PÁGINA {table.page} ---\n{table.df.to_string()}")
        return "\n\n".join(parts)

    except Exception as exc:
        logger.warning("camelot falhou em %s (%s) — usando fallback PyMuPDF", path, exc)
        return _extract_with_pymupdf(path)


def process_uploads(files: list[dict]) -> dict:
    """
    Recebe lista de {"filename": ..., "path": ..., "doc_type": ...}
    e retorna dict keyed por tipo de documento.
    """
    result = {}

    for file_info in files:
        filename = file_info["filename"]
        path = file_info["path"]
        doc_type = file_info["doc_type"]

        if doc_type not in DOC_CONFIG:
            logger.warning("Tipo de documento desconhecido: %s", doc_type)
            continue

        extrator = DOC_CONFIG[doc_type]["extrator"]

        try:
            if doc_type in ("ANX_10_ATUAL", "ANX_10_ANTERIOR"):
                logger.info("Extraindo %s com extrator estruturado ANX10: %s", doc_type, filename)
                from backend.extractors.anx10_legislativo import formatar_texto
                text = formatar_texto(path)
            elif doc_type == "ANX_02":
                logger.info("Extraindo %s com extrator estruturado ANX02: %s", doc_type, filename)
                from backend.extractors.anx02_despesas import formatar_texto as fmt_anx02
                text = fmt_anx02(path)
            elif doc_type == "ANX_06":
                logger.info("Extraindo %s com extrator estruturado ANX06: %s", doc_type, filename)
                from backend.extractors.anx06_programa_trabalho import formatar_texto as fmt_anx06
                text = fmt_anx06(path)
            elif extrator == "camelot":
                logger.info("Extraindo %s com camelot: %s", doc_type, filename)
                text = _extract_with_camelot(path)
            else:
                logger.info("Extraindo %s com PyMuPDF: %s", doc_type, filename)
                text = _extract_with_pymupdf(path)
        except Exception as exc:
            logger.error("Falha ao extrair %s (%s): %s", doc_type, filename, exc)
            continue

        municipio = _extract_municipio(_extract_with_pymupdf(path) if extrator == "camelot" else text)

        if doc_type in result:
            logger.warning("Documento duplicado (%s): %s sobrescreve anterior", doc_type, filename)

        result[doc_type] = {
            "text": text,
            "municipio": municipio,
            "filename": filename,
        }
        logger.info("Extraído: %s → %s (município: %s)", filename, doc_type, municipio or "não encontrado")

    return result
