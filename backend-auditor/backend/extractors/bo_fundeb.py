"""Balanço Orçamentário ISOLADO do FUNDEB (Anexo 12 — recorte só do isolado FUNDEB).

Fonte das deduções do Quadro 20 que não saem do Anexo 6/10:
  - "(-) Receita de Aplicação Financeira do FUNDEB" = RECEITA PATRIMONIAL realizada.
  - "(-) Despesas Custeadas com Superávit Financeiro, do Exercício Anterior, do FUNDEB":
    só existe quando a despesa (empenhada) do FUNDEB supera a receita (realizada) no
    exercício — o excedente foi bancado pelo superávit financeiro do ano anterior.
"""
import logging
import re

import pdfplumber

logger = logging.getLogger(__name__)

NUMERO_RE = re.compile(r'\d{1,3}(?:\.\d{3})*,\d{2}')


def _parse_br(s: str) -> float:
    return float(s.replace('.', '').replace(',', '.'))


def _linhas(pdf_path: str) -> list[str]:
    linhas: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            linhas.extend((page.extract_text() or "").splitlines())
    return linhas


def _valor_coluna(linha: str, indice: int) -> float:
    """Retorna o n-ésimo número (0-based) da linha, ou 0,00 se não existir."""
    nums = NUMERO_RE.findall(linha)
    return _parse_br(nums[indice]) if len(nums) > indice else 0.0


def extrair(pdf_path: str) -> dict:
    """Extrai receita patrimonial realizada e os totais de receita/despesa do FUNDEB.

    Layout das colunas (Balanço Orçamentário):
      Receitas: INICIAL(a) ATUALIZADA(b) REALIZADAS(c) SALDO(d)  → realizada = índice 2
      Despesas: INICIAL(e) ATUALIZADA(f) EMPENHADAS(g) LIQUIDADAS(h) PAGAS(i) SALDO(j)
                → empenhada = índice 2
    """
    linhas = _linhas(pdf_path)

    receita_patrimonial_realizada = 0.0
    receita_realizada_total = 0.0
    despesa_empenhada_total = 0.0

    for linha in linhas:
        u = linha.strip().upper()

        # "RECEITA PATRIMONIAL 92.833,78 92.833,78 733.547,70 640.713,92" → realizada (c)
        if u.startswith('RECEITA PATRIMONIAL'):
            receita_patrimonial_realizada = _valor_coluna(linha, 2)

        # Total das receitas realizadas — SUBTOTAL DAS RECEITAS (III) coluna (c)
        elif u.startswith('SUBTOTAL DAS RECEITAS'):
            receita_realizada_total = _valor_coluna(linha, 2)

        # Total das despesas empenhadas — SUBTOTAL DAS DESPESAS (XI) coluna (g)
        elif u.startswith('SUBTOTAL DAS DESPESAS'):
            despesa_empenhada_total = _valor_coluna(linha, 2)

    # Superávit financeiro do exercício anterior custeando despesa: só quando a despesa
    # empenhada do FUNDEB supera a receita realizada do próprio exercício.
    superavit_exercicio_anterior = round(
        max(0.0, despesa_empenhada_total - receita_realizada_total), 2
    )

    logger.info(
        "BO_FUNDEB: receita_patrimonial=%.2f receita_total=%.2f despesa_total=%.2f superavit_ant=%.2f",
        receita_patrimonial_realizada, receita_realizada_total,
        despesa_empenhada_total, superavit_exercicio_anterior,
    )
    return {
        'receita_patrimonial_realizada': receita_patrimonial_realizada,
        'receita_realizada_total':       receita_realizada_total,
        'despesa_empenhada_total':       despesa_empenhada_total,
        'superavit_exercicio_anterior':  superavit_exercicio_anterior,
    }
