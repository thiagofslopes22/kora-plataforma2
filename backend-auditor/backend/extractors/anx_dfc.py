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


_SECAO_RE = {
    # "FLUXO(S) DE CAIXA(S) DAS ATIVIDADES OPERACIONAIS"
    "operacional":    re.compile(r'FLUXOS?\s+DE\s+CAIXAS?\s+DAS\s+ATIVIDADES\s+OPERACIONAIS', re.IGNORECASE),
    # "FLUXO(S) DE CAIXA(S) DAS ATIVIDADES DE INVESTIMENTO"
    "investimento":   re.compile(r'FLUXOS?\s+DE\s+CAIXAS?\s+DAS\s+ATIVIDADES\s+DE\s+INVESTIMENTO', re.IGNORECASE),
    # "FLUXO(S) DE CAIXA(S) DAS ATIVIDADES DE FINANCIAMENTO"
    "financiamento":  re.compile(r'FLUXOS?\s+DE\s+CAIXAS?\s+DAS\s+ATIVIDADES\s+DE\s+FINANCIAMENTO', re.IGNORECASE),
    # "APURA(ÇÃO|CAO) DO FLUXO DE CAIXA DO PERÍODO"
    "apuracao":       re.compile(r'APURA[ÇC][AÃ]O\s+DO\s+FLUXO\s+DE\s+CAIXA\s+DO\s+PER', re.IGNORECASE),
    "transferencias": re.compile(r'QUADRO\s+DE\s+TRANSFER', re.IGNORECASE),
    "pessoal":        re.compile(r'QUADRO\s+DE\s+DESEMBOLSOS', re.IGNORECASE),
    "juros":          re.compile(r'QUADRO\s+DE\s+JUROS', re.IGNORECASE),
}


def _split_secoes(linhas: list[str]) -> dict:
    """Divide as linhas em seções temáticas pelo cabeçalho de cada quadro.
    Aceita variações como 'CAIXA' vs 'CAIXAS', 'APURAÇÃO' vs 'APURACAO', etc.
    """
    secoes = {k: [] for k in [
        "operacional", "investimento", "financiamento",
        "apuracao", "transferencias", "pessoal", "juros", "outros",
    ]}
    atual = "outros"
    for line in linhas:
        matched = False
        for nome_secao, patron in _SECAO_RE.items():
            if patron.search(line):
                atual = nome_secao
                matched = True
                break
        secoes[atual].append(line)
    return secoes


def _row(linhas: list[str], *termos: str, idx_a: int = 0, idx_ant: int = 1) -> dict:
    """Primeira linha COM NÚMEROS que contém todos os termos."""
    termos_up = [t.upper() for t in termos]
    for line in linhas:
        u = line.upper()
        if all(t in u for t in termos_up):
            nums = NUMERO_RE.findall(line)
            if not nums:
                continue
            return {
                "atual":    _parse(nums[idx_a])   if len(nums) > idx_a   else 0.0,
                "anterior": _parse(nums[idx_ant]) if len(nums) > idx_ant else 0.0,
            }
    return {"atual": 0.0, "anterior": 0.0}


def _parse_itens(linhas: list[str]) -> list[dict]:
    """Extrai todos os itens com valores de uma seção."""
    itens = []
    for line in linhas:
        nums = NUMERO_RE.findall(line)
        if not nums:
            continue
        desc = NUMERO_RE.sub("", line)
        # Remove marcadores de nota de quadro (letra isolada B, C, D no final)
        desc = re.sub(r'\s+[A-D]\s*$', '', desc)
        desc = re.sub(r'\s+', ' ', desc).strip()
        if len(desc) < 3:
            continue
        itens.append({
            "descricao": desc,
            "atual":     _parse(nums[0]),
            "anterior":  _parse(nums[1]) if len(nums) > 1 else 0.0,
        })
    return itens


def extrair(pdf_path: str) -> dict:
    municipio, exercicio = _extrair_cabecalho(pdf_path)
    ll = _todas_linhas(pdf_path)
    s = _split_secoes(ll)

    op  = s["operacional"]
    inv = s["investimento"]
    fin = s["financiamento"]
    apur = s["apuracao"]

    # "GERAÇÃO LÍQUIDA" pode aparecer como "I+II+III" ou por extenso
    geracao   = _row(apur, "I+II+III")
    if geracao["atual"] == 0.0 and geracao["anterior"] == 0.0:
        geracao = _row(apur, "GERA", "QUIDA")
    caixa_ini = _row(apur, "INICIAL")
    caixa_fin = _row(apur, "FINAL")

    dados = {
        "municipio": municipio,
        "exercicio": exercicio,

        # ── Campos flat para o template do quadro_14 ──
        "geracao_liquida_atual":    geracao["atual"],
        "geracao_liquida_anterior": geracao["anterior"],
        "caixa_inicial_atual":      caixa_ini["atual"],
        "caixa_inicial_anterior":   caixa_ini["anterior"],
        "caixa_final_atual":        caixa_fin["atual"],
        "caixa_final_anterior":     caixa_fin["anterior"],

        # ── Dados estruturados para uso futuro ──
        "apuracao": {
            "geracao_liquida": geracao,
            "caixa_inicial":   caixa_ini,
            "caixa_final":     caixa_fin,
        },

        "fluxo_operacional": {
            "ingressos":                 _row(op, "INGRESSOS"),
            "receitas_derivadas":        _row(op, "DERIVADAS"),
            "transferencias_recebidas":  _row(op, "TRANSFER", "RECEBIDAS"),
            "outros_ingressos":          _row(op, "OUTROS INGRESSOS"),
            "desembolsos":               _row(op, "DESEMBOLSOS"),
            "pessoal_despesas":          _row(op, "PESSOAL"),
            "juros_encargos":            _row(op, "JUROS"),
            "transferencias_concedidas": _row(op, "TRANSFER", "CONCEDIDAS"),
            "outros_desembolsos":        _row(op, "OUTROS DESEMBOLSOS"),
            "fluxo_liquido":             _row(op, "OPERACIONAIS (I)"),
        },

        "fluxo_investimento": {
            "ingressos":   _row(inv, "INGRESSOS"),
            "desembolsos": _row(inv, "DESEMBOLSOS"),
            "fluxo_liquido": _row(inv, "INVESTIMENTO (II)"),
        },

        "fluxo_financiamento": {
            "ingressos":   _row(fin, "INGRESSOS"),
            "desembolsos": _row(fin, "DESEMBOLSOS"),
            "fluxo_liquido": _row(fin, "FINANCIAMENTO (III)"),
        },

        "_itens_operacional":   _parse_itens(op),
        "_itens_investimento":  _parse_itens(inv),
        "_itens_financiamento": _parse_itens(fin),
    }

    logger.info(
        "DFC: op=%.2f inv=%.2f fin=%.2f geracao=%.2f caixa_ini=%.2f caixa_fin=%.2f",
        dados["fluxo_operacional"]["fluxo_liquido"]["atual"],
        dados["fluxo_investimento"]["fluxo_liquido"]["atual"],
        dados["fluxo_financiamento"]["fluxo_liquido"]["atual"],
        geracao["atual"], caixa_ini["atual"], caixa_fin["atual"],
    )
    return dados
