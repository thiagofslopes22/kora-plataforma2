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


def _todas_linhas(pdf_path: str) -> list[str]:
    linhas = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            linhas.extend(text.splitlines())
    return linhas


def _buscar(linhas: list[str], *termos: str) -> list[float]:
    termos_up = [sem_acento(t.upper()) for t in termos]
    for line in linhas:
        upper = sem_acento(line.upper())
        if all(t in upper for t in termos_up):
            nums = NUMERO_RE.findall(line)
            if nums:
                return [_parse(n) for n in nums]
    return []


def _row(nums: list[float]) -> dict:
    return {
        "dotacao_inicial_d":    nums[0] if len(nums) > 0 else 0.0,
        "dotacao_atualizada_e": nums[1] if len(nums) > 1 else 0.0,
        "empenhada_f":          nums[2] if len(nums) > 2 else 0.0,
        "liquidada_g":          nums[3] if len(nums) > 3 else 0.0,
        "paga_h":               nums[4] if len(nums) > 4 else 0.0,
        "saldo_dotacao_i":      nums[5] if len(nums) > 5 else 0.0,
    }


def extrair(pdf_path: str) -> dict:
    municipio, exercicio = _extrair_cabecalho(pdf_path)
    ll = _todas_linhas(pdf_path)

    dados = {
        "municipio":  municipio,
        "exercicio":  exercicio,
        "despesas_correntes":                  _row(_buscar(ll, "DESPESAS CORRENTES", "(VIII)")),
        "despesas_capital":                    _row(_buscar(ll, "DESPESAS DE CAPITAL", "(IX)")),
        "reserva_contingencia":                _row(_buscar(ll, "RESERVA DE CONTINGENCIA", "(X)")),
        "subtotal_despesas":                   _row(_buscar(ll, "SUBTOTAL DAS DESPESAS", "(XI)")),
        "amortizacao_divida_refinanciamento":  _row(_buscar(ll, "AMORTIZACAO", "REFINANCIAMENTO", "(XII)")),
        "subtotal_com_refinanciamento":        _row(_buscar(ll, "SUBTOTAL COM REFINANCIAMENTO", "(XIII)")),
        "superavit":                           _row(_buscar(ll, "SUPERAVIT", "(XIV)")),
        "total":                               _row(_buscar(ll, "TOTAL", "(XV)")),
        "reserva_rpps":                        _row(_buscar(ll, "RESERVA DO RPPS")),
    }

    logger.info(
        "ANX09 Q9: despesas_correntes_empenhada=%.2f total_empenhada=%.2f",
        dados["despesas_correntes"]["empenhada_f"],
        dados["total"]["empenhada_f"],
    )
    return dados
