import logging
import re

import fitz
import pdfplumber

logger = logging.getLogger(__name__)

NUMERO_RE = re.compile(r'-?\d{1,3}(?:\.\d{3})*,\d{2}')


def _parse(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _todas_linhas(pdf_path: str) -> list[str]:
    linhas = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            linhas.extend(text.splitlines())
    return linhas


def _extrair_cabecalho(pdf_path: str) -> tuple[str, str]:
    doc = fitz.open(pdf_path)
    text = doc[0].get_text("text").upper()
    doc.close()
    m_mun = re.search(r'PREFEITURA MUNICIPAL DE (.+?)(?:\s*-\s*MA|\s*\()', text)
    m_ano = re.search(r'EXERC.{1,5}CIO[:\s]*(\d{4})', text)
    municipio = m_mun.group(1).strip().title() if m_mun else ""
    exercicio = m_ano.group(1) if m_ano else ""
    return municipio, exercicio


def _extrair_dtp_rcl(pdf_path: str) -> tuple[float, float]:
    """Extrai (DTP, RCL-ajustada) do RGF Anexo 01 Tabela 1.0.

    RCL = linha "RCL AJUSTADA ... PESSOAL (V)" — base usada pelo template TCE-MA.
    DTP = linha "DTP (VI)" — primeiro número é o valor; segundo é % e deve ser ignorado.
    """
    linhas = _todas_linhas(pdf_path)
    dtp = 0.0
    rcl = 0.0
    for line in linhas:
        upper = line.upper()
        nums = NUMERO_RE.findall(line)
        if not nums:
            continue
        # RCL ajustada para cálculo dos limites da despesa com pessoal (V)
        if "AJUSTADA" in upper and "PESSOAL" in upper and rcl == 0.0:
            rcl = _parse(nums[0])
        # DTP (VI) — nums[0] é o valor monetário, nums[1] seria o %
        if "DTP (VI)" in upper and dtp == 0.0:
            dtp = _parse(nums[0])
    return dtp, rcl


def _calcular_periodo(dtp: float, rcl: float) -> dict:
    limite = round(rcl * 0.54, 2)
    # percentual_apurado retornado como fração (0.5127) porque o template usa
    # formato 0.00"%" e o template_filler multiplica por 100 antes de gravar
    pct_frac = round(dtp / rcl, 6) if rcl != 0 else 0.0
    return {
        "total_despesa": dtp,
        "receita_corrente_liquida": rcl,
        "limite_legal_54_pct": limite,
        "percentual_apurado": pct_frac,
    }


def extrair_q06(
    rgf2_path: str,
    rgf1_path: str | None = None,
    rcl_tce: float | None = None,
) -> dict:
    """Q06 — Comportamento da Despesa com Pessoal no Exercício.

    rgf2_path: RGF 2º semestre → DTP da coluna "Apurado pelo TCE"
    rgf1_path: RGF 1º semestre → coluna "1º Semestre" (opcional; zeros se ausente)
    rcl_tce:   RCL anual vinda do Quadro 5 (base_calculo_rcl) — substitui a RCL
               extraída do RGF 2º semestre para a coluna "Apurado pelo TCE"
    """
    municipio, exercicio = _extrair_cabecalho(rgf2_path)

    dtp2, rcl2_rgf = _extrair_dtp_rcl(rgf2_path)
    # RCL para "Apurado pelo TCE": usa Q5 se disponível, senão cai para o RGF
    rcl2 = rcl_tce if rcl_tce and rcl_tce > 0 else rcl2_rgf
    apurado = _calcular_periodo(dtp2, rcl2)

    if rgf1_path:
        dtp1, rcl1 = _extrair_dtp_rcl(rgf1_path)
        primeiro = _calcular_periodo(dtp1, rcl1)
    else:
        primeiro = {
            "total_despesa": 0.0,
            "receita_corrente_liquida": 0.0,
            "limite_legal_54_pct": 0.0,
            "percentual_apurado": 0.0,
        }

    logger.info(
        "Q6: 1sem dtp=%.2f rcl=%.2f | 2sem dtp=%.2f rcl=%.2f (Q5) pct=%.2f%%",
        primeiro["total_despesa"], primeiro["receita_corrente_liquida"],
        apurado["total_despesa"], apurado["receita_corrente_liquida"],
        apurado["percentual_apurado"],
    )

    return {
        "municipio": municipio,
        "exercicio": exercicio,
        "quadro_6_despesa_pessoal": {
            "primeiro_semestre": primeiro,
            "apurado_pelo_tce": apurado,
        },
    }
