"""Anexo 6 no formato 'Despesa por Funções e Categorias Econômicas' (TCE/MA).

Alguns sistemas contábeis emitem o Anexo 06 agrupado só por FUNÇÃO, com a natureza da
despesa até o desdobramento do elemento — sem subfunção, unidade orçamentária ou ação
(ex.: Passagem Franca, São Bernardo). Este extrator lê o total de cada função e os
valores por natureza; os quadros que dependem de subfunção/ação (rótulo FUNDEB 70%,
VAAT) não podem ser montados a partir dele.
"""
import logging
import re

import fitz
import pdfplumber

from backend.extractors._texto import sem_acento

logger = logging.getLogger(__name__)

_FUNCAO_RE = re.compile(r'^(\d{2})\s+([A-Za-zÀ-ú].*)$')
_TOTAL_FUNCAO_RE = re.compile(r'^Total da Fun[çc][ãa]o:\s*(-?[\d.]+,\d{2})', re.IGNORECASE)
_NATUREZA_RE = re.compile(r'^(\d(?:\.\d(?:\.\d{2}(?:\.\d{2}(?:\.\d{2})?)?)?)?)\s+.*?\s*(-?\d{1,3}(?:\.\d{3})*,\d{2})$')
_TOTAL_GERAL_RE = re.compile(r'^T\s*O\s*T\s*A\s*L\s+(-?[\d.]+,\d{2})$')
_EXERCICIO_RE = re.compile(r'EXERC[IÍ]CIO:?\s*(\d{4})', re.IGNORECASE)


def _parse(s: str) -> float:
    return float(s.replace('.', '').replace(',', '.'))


def eh_formato_funcoes(pdf_path: str) -> bool:
    doc = fitz.open(pdf_path)
    try:
        texto = sem_acento(doc[0].get_text('text').upper())
    finally:
        doc.close()
    return 'FUNCOES E CATEGORIAS ECONOMICAS' in texto and 'UNIDADE ORCAMENTARIA' not in texto


def extrair(pdf_path: str) -> dict:
    """Retorna {'exercicio', 'funcoes': {cod: {'nome', 'total', 'natureza': {codigo: valor}}},
    'total_documento', 'soma_funcoes'}."""
    funcoes: dict[str, dict] = {}
    atual: str | None = None
    exercicio = ''
    total_doc = None
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for linha in (page.extract_text() or '').splitlines():
                linha = linha.strip()
                if not exercicio:
                    m = _EXERCICIO_RE.search(linha)
                    if m:
                        exercicio = m.group(1)
                m = _TOTAL_FUNCAO_RE.match(linha)
                if m:
                    # "Total da Função" pode cair no topo da página seguinte
                    if atual:
                        funcoes[atual]['total'] = _parse(m.group(1))
                    continue
                m = _TOTAL_GERAL_RE.match(linha)
                if m:
                    total_doc = _parse(m.group(1))
                    continue
                m = _FUNCAO_RE.match(linha)
                if m and not _NATUREZA_RE.match(linha):
                    atual = m.group(1)
                    funcoes.setdefault(atual, {'nome': m.group(2).strip(), 'total': 0.0, 'natureza': {}})
                    continue
                m = _NATUREZA_RE.match(linha)
                if m and atual:
                    # Linhas com texto sobreposto no PDF (valor ilegível) simplesmente não casam
                    funcoes[atual]['natureza'].setdefault(m.group(1), _parse(m.group(2)))

    soma = round(sum(f['total'] for f in funcoes.values()), 2)
    if total_doc is not None and abs(soma - total_doc) > 0.01:
        logger.warning("ANX_06 (por funções): soma das funções %.2f ≠ TOTAL do documento %.2f", soma, total_doc)
    logger.info("ANX_06 (por funções): %d funções, total %.2f (documento %s)", len(funcoes), soma, total_doc)
    return {
        'exercicio':       exercicio,
        'funcoes':         funcoes,
        'total_documento': total_doc,
        'soma_funcoes':    soma,
    }


def total_funcao(dados: dict, codigo: str) -> float:
    return round(dados['funcoes'].get(codigo, {}).get('total', 0.0), 2)
