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


def _buscar_primeiro(linhas: list[str], *termos: str) -> float:
    termos_up = [t.upper() for t in termos]
    for line in linhas:
        upper = line.upper()
        if all(t in upper for t in termos_up):
            nums = NUMERO_RE.findall(line)
            if nums:
                return _parse(nums[0])
    return 0.0


def _extrair_loa(pdf_path: str) -> tuple[float, float]:
    """Extrai TOTAL GERAL de receita e despesa da LOA."""
    linhas = _todas_linhas(pdf_path)

    receita_loa = 0.0
    despesa_loa = 0.0
    secao = ""

    for line in linhas:
        upper = line.upper().strip()

        if re.search(r'1\s*[\.\-]\s*RECEITA', upper):
            secao = "receita"
        elif re.search(r'3\s*[\.\-]\s*DESPESA', upper):
            secao = "despesa"

        if "TOTAL GERAL" in upper:
            nums = NUMERO_RE.findall(line)
            if nums:
                val = _parse(nums[-1])
                if secao == "receita" and receita_loa == 0.0:
                    receita_loa = val
                elif secao == "despesa" and despesa_loa == 0.0:
                    despesa_loa = val

    # Fallback: sem seção detectada, pega os dois primeiros TOTAL GERAL
    if receita_loa == 0.0 or despesa_loa == 0.0:
        totais = []
        for line in linhas:
            if "TOTAL GERAL" in line.upper():
                nums = NUMERO_RE.findall(line)
                if nums:
                    totais.append(_parse(nums[-1]))
        if len(totais) >= 2:
            if receita_loa == 0.0:
                receita_loa = totais[0]
            if despesa_loa == 0.0:
                despesa_loa = totais[1]
        elif len(totais) == 1:
            if receita_loa == 0.0:
                receita_loa = totais[0]
            if despesa_loa == 0.0:
                despesa_loa = totais[0]

    return receita_loa, despesa_loa


def _situacao(loa: float | None, bo: float | None) -> str:
    if loa is None or bo is None:
        return "N/D"
    return "Conformidade" if abs(loa - bo) < 1.0 else "Divergência"


def extrair_q11(loa_path: str | None, anx12_path: str) -> dict:
    """Q11 — Comparativo LOA x Balanço Orçamentário.

    loa_path é opcional: quando a LOA não é enviada, os valores da LOA
    ficam None (preenchidos manualmente depois) e apenas os valores do
    Balanço Orçamentário (ANX_12) são extraídos automaticamente.
    """
    municipio, exercicio = _extrair_cabecalho(anx12_path)

    # LOA (opcional)
    if loa_path:
        receita_loa, despesa_loa = _extrair_loa(loa_path)
    else:
        receita_loa, despesa_loa = None, None

    # ANX_12 — PREVISÃO INICIAL (1ª coluna) das linhas de subtotal
    ll = _todas_linhas(anx12_path)
    receita_bo = _buscar_primeiro(ll, "SUBTOTAL DAS RECEITAS", "(III)")
    despesa_bo = _buscar_primeiro(ll, "SUBTOTAL DAS DESPESAS", "(XI)")

    logger.info(
        "Q11: receita loa=%s bo=%.2f | despesa loa=%s bo=%.2f",
        receita_loa, receita_bo, despesa_loa, despesa_bo,
    )

    return {
        "municipio": municipio,
        "exercicio": exercicio,
        "receita_prevista_loa":      receita_loa,
        "receita_prevista_bo":       receita_bo,
        "receita_prevista_situacao": _situacao(receita_loa, receita_bo),
        "dotacao_inicial_loa":       despesa_loa,
        "dotacao_inicial_bo":        despesa_bo,
        "dotacao_inicial_situacao":  _situacao(despesa_loa, despesa_bo),
    }
