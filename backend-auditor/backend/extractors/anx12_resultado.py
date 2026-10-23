import logging
import re

import fitz
import pdfplumber

from backend.extractors._texto import busca_exercicio, sem_acento

logger = logging.getLogger(__name__)

NUMERO_RE = re.compile(r'-?\d{1,3}(?:\.\d{3})*,\d{2}')


def _parse(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _extrair_cabecalho(pdf_path: str) -> tuple[str, str]:
    doc = fitz.open(pdf_path)
    text = doc[0].get_text("text").upper()
    doc.close()
    m_mun = re.search(r"PREFEITURA MUNICIPAL DE (.+)", text)
    m_ano = busca_exercicio(text)
    municipio = m_mun.group(1).strip() if m_mun else ""
    exercicio = m_ano.group(1) if m_ano else ""
    return municipio, exercicio


def _buscar_linha(pdf_path: str, *termos: str) -> list[float] | None:
    """Retorna os valores numéricos da primeira linha que contenha todos os termos."""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                upper = sem_acento(line.upper())
                if all(sem_acento(t.upper()) in upper for t in termos):
                    nums = NUMERO_RE.findall(line)
                    if nums:
                        return [_parse(n) for n in nums]
    return None


def extrair(pdf_path: str) -> dict:
    municipio, exercicio = _extrair_cabecalho(pdf_path)

    # Receita realizada: SUBTOTAL COM REFINANCIAMENTO (V), coluna (c) = índice 2.
    # NAO usar TOTAL (VII) = (V + VI): ele soma o DÉFICIT (VI) que fecha o balanço,
    # e com déficit a receita "empata" com a despesa e o resultado sai zero.
    nums_receita = _buscar_linha(pdf_path, "SUBTOTAL COM REFINANCIAMENTO (V)")
    if not (nums_receita and len(nums_receita) > 2):
        nums_total = _buscar_linha(pdf_path, "TOTAL (VII)")
        nums_deficit = _buscar_linha(pdf_path, "DEFICIT (VI)")
        if nums_total and len(nums_total) > 2:
            deficit = nums_deficit[2] if nums_deficit and len(nums_deficit) > 2 else 0.0
            nums_receita = [0.0, 0.0, round(nums_total[2] - deficit, 2)]
    receita_realizada = nums_receita[2] if nums_receita and len(nums_receita) > 2 else 0.0

    # Despesa empenhada: SUBTOTAL COM REFINANCIAMENTO (XIII), coluna (g) = índice 2
    nums_despesa = _buscar_linha(pdf_path, "SUBTOTAL COM REFINANCIAMENTO (XIII)")
    despesa_empenhada = nums_despesa[2] if nums_despesa and len(nums_despesa) > 2 else 0.0

    resultado = round(receita_realizada - despesa_empenhada, 2)
    situacao = "superavitário" if resultado > 0 else "deficitário"

    logger.info(
        "ANX12 Q3: receita=%.2f despesa=%.2f resultado=%.2f (%s)",
        receita_realizada, despesa_empenhada, resultado, situacao,
    )

    return {
        "municipio": municipio,
        "exercicio": exercicio,
        "resultado_orcamentario": {
            "receita_realizada": receita_realizada,
            "despesa_empenhada": despesa_empenhada,
            "resultado":         resultado,
            "situacao":          situacao,
        },
    }
