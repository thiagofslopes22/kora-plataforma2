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


def _linhas_tabela23(pdf_path: str) -> list[str]:
    """Retorna somente as linhas da seção Tabela 2.3 do RGF."""
    todas = _todas_linhas(pdf_path)
    start = 0
    end = len(todas)
    for i, line in enumerate(todas):
        up = line.upper()
        if start == 0 and "2.3" in line and "CONSOLIDADA" in up:
            start = i
        elif start > 0 and ("TABELA 2.4" in up or ("TABELA 3" in up)):
            end = i
            break
    return todas[start:end]


def _buscar_3vals(linhas: list[str], *termos: str) -> tuple[float, float, float]:
    """Localiza a primeira linha com todos os termos e retorna os 3 primeiros números.
    Se a linha não tem números (linha quebrada pelo PDF), verifica a linha seguinte.
    """
    termos_up = [t.upper() for t in termos]
    for i, line in enumerate(linhas):
        upper = line.upper()
        if all(t in upper for t in termos_up):
            nums = NUMERO_RE.findall(line)
            if len(nums) >= 3:
                return _parse(nums[0]), _parse(nums[1]), _parse(nums[2])
            # Linha quebrada: valores na próxima linha
            if i + 1 < len(linhas):
                nums_next = NUMERO_RE.findall(linhas[i + 1])
                if len(nums_next) >= 3:
                    return _parse(nums_next[0]), _parse(nums_next[1]), _parse(nums_next[2])
    return 0.0, 0.0, 0.0


# Mapeamento campo → termos de busca (sem acentos para resistir a encoding garbled)
_CAMPOS: list[tuple[str, list[str]]] = [
    ("divida_consolidada_dc",                       ["DC (I)"]),
    ("divida_mobiliaria",                           ["MOBILI"]),
    ("divida_contratual",                           ["CONTRATUAL"]),
    ("precatorios_posteriores_05052000",            ["05/05/2000"]),
    ("outras_dividas",                              ["OUTRAS"]),          # "OUTRAS" ≠ "OUTROS"
    ("deducoes_total",                              ["DEDU", "(II)"]),
    ("disponibilidade_caixa_bruta",                 ["CAIXA BRUTA"]),
    ("restos_pagar_processados_exceto_precatorios", ["RESTOS A PAGAR PROCESSADOS"]),
    ("demais_haveres_financeiros",                  ["HAVERES FINANCEIROS"]),
    ("divida_consolidada_liquida_dcl",              ["DCL", "(III)"]),
    ("receita_corrente_liquida",                    ["RCL (IV)"]),
    ("transferencias_emendas_individuais",          ["EMENDAS INDIVIDUAIS"]),
    ("rcl_ajustada_endividamento",                  ["AJUSTADA", "LIMITES DE"]),
    # Percentuais: "(I/VI)" e "(III/VI)" distinguem DC de DCL sem ambiguidade
    ("percentual_dc_sobre_rcl",                     ["(I/VI)"]),
    ("percentual_dcl_sobre_rcl",                    ["(III/VI)"]),
    ("limite_resolucao_senado",                     ["LIMITE DEFINIDO", "SENADO"]),
    ("limite_alerta",                               ["LIMITE DE ALERTA", "59"]),
]


def extrair_q07(rgf2_path: str) -> dict:
    """Q07 — Dívida Consolidada e Mobiliária.

    Fonte: RGF-Anexo 02 | Tabela 2.3 do relatório do 2º semestre.
    A tabela já traz as 3 colunas: Exercício Anterior / 1º Semestre / 2º Semestre.

    Percentuais retornados como valor bruto (ex: 15.76) — o template usa formato
    0.00% (Excel nativo) e o template_filler divide por 100 antes de gravar.
    """
    municipio, exercicio = _extrair_cabecalho(rgf2_path)
    ll = _linhas_tabela23(rgf2_path)

    ant: dict = {}
    p1: dict = {}
    p2: dict = {}

    for campo, termos in _CAMPOS:
        v0, v1, v2 = _buscar_3vals(ll, *termos)
        ant[campo] = v0
        p1[campo] = v1
        p2[campo] = v2

    logger.info(
        "Q7: DCL ant=%.2f 1sem=%.2f 2sem=%.2f | %%DCL/RCL 2sem=%.2f%%",
        ant["divida_consolidada_liquida_dcl"],
        p1["divida_consolidada_liquida_dcl"],
        p2["divida_consolidada_liquida_dcl"],
        p2["percentual_dcl_sobre_rcl"],
    )

    return {
        "municipio": municipio,
        "exercicio": exercicio,
        "saldo_exercicio_anterior": ant,
        "ate_1_semestre":           p1,
        "ate_2_semestre":           p2,
    }
