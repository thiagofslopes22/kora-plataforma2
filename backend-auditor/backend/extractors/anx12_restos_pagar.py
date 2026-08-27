import logging
import re

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


def _total_apos(linhas: list[str], idx: int | None) -> list[float]:
    """Primeira linha começando com TOTAL a partir do índice dado."""
    if idx is None:
        return []
    for line in linhas[idx:]:
        if line.strip().upper().startswith("TOTAL"):
            nums = NUMERO_RE.findall(line)
            if nums:
                return [_parse(n) for n in nums]
    return []


def extrair(pdf_path: str) -> dict:
    """
    Extrai os totais dos quadros de execução de Restos a Pagar
    Processados e Não Processados do Anexo 12.
    """
    ll = _todas_linhas(pdf_path)

    idx_nao_proc = None
    idx_proc = None
    for i, line in enumerate(ll):
        u = line.upper()
        if "RESTOS A PAGAR NÃO PROCESSADOS" in u and idx_nao_proc is None:
            idx_nao_proc = i
        elif "RESTOS A PAGAR PROCESSADOS" in u and "NÃO" not in u and idx_proc is None:
            idx_proc = i

    nao_proc = _total_apos(ll, idx_nao_proc)
    proc     = _total_apos(ll, idx_proc)

    # Não Processados: (a) anteriores, (b) inscritos, liquidados, pagos, cancelados, saldo
    np_ant, np_insc, np_liq, np_pago, np_canc, np_saldo = (nao_proc + [0.0] * 6)[:6]
    # Processados: (a) anteriores, (b) inscritos, pagos, cancelados, saldo
    p_ant, p_insc, p_pago, p_canc, p_saldo = (proc + [0.0] * 5)[:5]

    dados = {
        "rp_nao_processados": {
            "anteriores": np_ant, "inscritos": np_insc, "liquidados": np_liq,
            "pagos": np_pago, "cancelados": np_canc, "saldo": np_saldo,
        },
        "rp_processados": {
            "anteriores": p_ant, "inscritos": p_insc,
            "pagos": p_pago, "cancelados": p_canc, "saldo": p_saldo,
        },
    }

    logger.info(
        "ANX12 RP: nao_proc(insc=%.2f saldo=%.2f) proc(insc=%.2f saldo=%.2f)",
        np_insc, np_saldo, p_insc, p_saldo,
    )
    return dados
