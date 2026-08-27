import logging
import re

import pdfplumber

logger = logging.getLogger(__name__)

NUMERO_RE = re.compile(r'-?\d{1,3}(?:\.\d{3})*,\d{2}')


def _parse(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _extrair_de_anx12(anx12_path: str) -> tuple[float, float]:
    """
    Extrai orcada e arrecadada do ANX_12 para IMPOSTOS, TAXAS E CONTRIBUIÇÕES.
    Linha: prevista_inicial | prevista_atualizada | realizada | saldo
    """
    with pdfplumber.open(anx12_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                upper = line.upper()
                if "IMPOSTOS" in upper and "TAXAS" in upper and "MELHORIA" in upper:
                    nums = NUMERO_RE.findall(line)
                    if len(nums) >= 3:
                        orcada     = _parse(nums[1])  # prevista_atualizada
                        arrecadada = _parse(nums[2])  # realizada
                        return orcada, arrecadada
    return 0.0, 0.0


def extrair(anx12_path: str) -> dict:
    orcada, arrecadada = _extrair_de_anx12(anx12_path)

    if arrecadada > orcada:
        situacao = "Excesso"
    elif arrecadada < orcada:
        situacao = "Insuficiência"
    else:
        situacao = "Equilíbrio"

    logger.info(
        "ANX10-TRIB Q10: orcada=%.2f arrecadada=%.2f situacao=%s",
        orcada, arrecadada, situacao,
    )

    return {
        "receita_tributaria_realizada":  arrecadada,
        "receita_tributaria_atualizada": orcada,
        "situacao":                      situacao,
    }
