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


def _linhas_tabela_dcl(pdf_path: str) -> tuple[list[str], bool]:
    """Retorna as linhas da tabela da Divida Consolidada Liquida e se o RGF e quadrimestral.

    Semestral:     "RGF-Anexo 02 | Tabela 2.3" — colunas Anterior / 1º Sem / 2º Sem.
    Quadrimestral: "RGF-Anexo 02 | Tabela 2.0" — colunas Anterior / 1º / 2º / 3º Quad.
    """
    todas = _todas_linhas(pdf_path)
    quadrimestral = any("QUADRIMESTRE" in l.upper() and "PER" in l.upper() for l in todas[:15])
    start = None
    end = len(todas)
    for i, line in enumerate(todas):
        up = line.upper()
        if start is None:
            if ("TABELA 2.0" in up and "CONSOLIDADA" in up) or ("2.3" in line and "CONSOLIDADA" in up):
                start = i
        elif "TABELA 2.4" in up or "TABELA 2.1" in up or "TABELA 3" in up:
            end = i
            break
    return todas[start or 0:end], quadrimestral


def _buscar_vals(linhas: list[str], n: int, *termos: str) -> tuple[float, ...]:
    """Localiza a primeira linha com todos os termos e retorna os `n` primeiros numeros.
    Se a linha nao tem numeros suficientes (linha quebrada pelo PDF), verifica a seguinte.
    """
    termos_up = [t.upper() for t in termos]
    for i, line in enumerate(linhas):
        upper = line.upper()
        if all(t in upper for t in termos_up):
            for candidata in (line, linhas[i + 1] if i + 1 < len(linhas) else ""):
                nums = NUMERO_RE.findall(candidata)
                if len(nums) >= n:
                    return tuple(_parse(x) for x in nums[:n])
    return (0.0,) * n


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


def extrair_q07(rgf_path: str) -> dict:
    """Q07 — Dívida Consolidada e Mobiliária.

    Fonte: RGF-Anexo 02 do ULTIMO periodo do exercicio — a tabela ja traz o saldo
    do exercicio anterior e todos os periodos ate o de referencia.

      Quadrimestral (Tabela 2.0, 3º quadrimestre): Anterior / 1º / 2º / 3º Quad.
      Semestral     (Tabela 2.3, 2º semestre):     Anterior / 1º / 2º Sem. O template
        agora e quadrimestral: o 2º semestre (fim do ano) vai na coluna do 3º quad,
        o 1º semestre na do 2º quad, e a do 1º quad fica zerada.

    Percentuais retornados como valor bruto (ex: 15.76) — o template usa formato
    0.00% (Excel nativo) e o template_filler divide por 100 antes de gravar.
    """
    municipio, exercicio = _extrair_cabecalho(rgf_path)
    ll, quadrimestral = _linhas_tabela_dcl(rgf_path)

    ncols = 4 if quadrimestral else 3
    ant: dict = {}
    q1: dict = {}
    q2: dict = {}
    q3: dict = {}

    for campo, termos in _CAMPOS:
        vals = _buscar_vals(ll, ncols, *termos)
        if quadrimestral:
            ant[campo], q1[campo], q2[campo], q3[campo] = vals
        else:
            ant[campo], q2[campo], q3[campo] = vals
            q1[campo] = 0.0

    logger.info(
        "Q7 (%s): DCL ant=%.2f 1q=%.2f 2q=%.2f 3q=%.2f | %%DCL/RCL final=%.2f%%",
        "quadrimestral" if quadrimestral else "semestral",
        ant["divida_consolidada_liquida_dcl"],
        q1["divida_consolidada_liquida_dcl"],
        q2["divida_consolidada_liquida_dcl"],
        q3["divida_consolidada_liquida_dcl"],
        q3["percentual_dcl_sobre_rcl"],
    )

    return {
        "municipio": municipio,
        "exercicio": exercicio,
        "periodicidade": "quadrimestral" if quadrimestral else "semestral",
        # Cabeçalho das 3 colunas do exercício no template/RIT
        "rotulos": ({"col_1": "Até o 1º Quadrimestre", "col_2": "Até o 2º Quadrimestre", "col_3": "Até o 3º Quadrimestre"}
                    if quadrimestral else
                    {"col_1": "—", "col_2": "Até o 1º Semestre", "col_3": "Até o 2º Semestre"}),
        "saldo_exercicio_anterior": ant,
        "ate_1_quadrimestre":       q1,
        "ate_2_quadrimestre":       q2,
        "ate_3_quadrimestre":       q3,
    }
