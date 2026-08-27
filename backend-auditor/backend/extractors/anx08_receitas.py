import logging
import re

import fitz
import pdfplumber

logger = logging.getLogger(__name__)

NUMERO_RE = re.compile(r'-?\d{1,3}(?:\.\d{3})*,\d{2}')


def _parse(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _extrair_cabecalho(pdf_path: str) -> tuple[str, str]:
    doc = fitz.open(pdf_path)
    text = doc[0].get_text("text").upper()
    doc.close()
    m_mun = re.search(r"PREFEITURA MUNICIPAL DE (.+)", text)
    m_ano = re.search(r"EXERC[IÍ]CIO[^\d]*(\d{4})", text)
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
    termos_up = [t.upper() for t in termos]
    for line in linhas:
        upper = line.upper()
        if all(t in upper for t in termos_up):
            nums = NUMERO_RE.findall(line)
            if nums:
                return [_parse(n) for n in nums]
    return []


def _row(nums: list[float]) -> dict:
    return {
        "prevista_inicial_a":    nums[0] if len(nums) > 0 else 0.0,
        "prevista_atualizada_b": nums[1] if len(nums) > 1 else 0.0,
        "realizada_c":           nums[2] if len(nums) > 2 else 0.0,
        "saldo_d":               nums[3] if len(nums) > 3 else 0.0,
    }


def extrair(pdf_path: str) -> dict:
    municipio, exercicio = _extrair_cabecalho(pdf_path)
    ll = _todas_linhas(pdf_path)

    dados = {
        "municipio": municipio,
        "exercicio": exercicio,
        "receitas_correntes":                       _row(_buscar(ll, "RECEITAS CORRENTES", "(I)")),
        "receitas_capital":                         _row(_buscar(ll, "RECEITAS DE CAPITAL", "(II)")),
        "subtotal_receitas":                        _row(_buscar(ll, "SUBTOTAL DAS RECEITAS", "(III)")),
        "operacoes_credito_refinanciamento":        _row(_buscar(ll, "REFINANCIAMENTO", "(IV)")),
        "subtotal_com_refinanciamento":             _row(_buscar(ll, "SUBTOTAL COM REFINANCIAMENTO", "(V)")),
        "deficit":                                  _row(_buscar(ll, "DEFICIT", "(VI)")),
        "total":                                    _row(_buscar(ll, "TOTAL", "(VII)")),
        "saldos_exercicios_anteriores":             _row(_buscar(ll, "SALDOS DE EXERCICIOS ANTERIORES")),
        "recursos_arrecadados_exercicios_anteriores": _row(_buscar(ll, "RECURSOS ARRECADADOS EM EXERCICIOS ANTERIORES")),
        "superavit_financeiro":                     _row(_buscar(ll, "SUPERAVIT FINANCEIRO")),
        "reabertura_creditos_adicionais":           _row(_buscar(ll, "REABERTURA DE CREDITOS ADICIONAIS")),
    }

    logger.info(
        "ANX08 Q8: receitas_correntes_realizada=%.2f total_realizada=%.2f",
        dados["receitas_correntes"]["realizada_c"],
        dados["total"]["realizada_c"],
    )
    return dados
