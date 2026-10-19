import logging
import re

import fitz  # PyMuPDF
import pdfplumber

logger = logging.getLogger(__name__)

CODIGO_RE = re.compile(r'^(9?[12]?\d{3}\.\d{2}\.\d\.\d\.\d{2}\.\d{2})')
NUMERO_RE = re.compile(r'\d{1,3}(?:\.\d{3})*,\d{2}')

# (primario, secundarios, somar_secundarios)
CAMPOS = {
    "iptu":                      ("1112.50.0.0.00.00", ("1112.50.0.1.00.00",),                           False),
    "itbi":                      ("1112.53.0.0.00.00", ("1112.53.0.1.00.00",),                           False),
    # IRRF = família 1113.03 (Trabalho + Outros Rendimentos). NUNCA usar 1113.00 (inclui IRPJ - 1113.02).
    "irrf":                      ("1113.03.0.0.00.00", ("1113.03.1.0.00.00", "1113.03.4.0.00.00"),       True),
    "iss":                       ("1114.51.0.0.00.00", ("1114.51.1.0.00.00", "1114.51.1.1.00.00"),       False),
    "taxas_poder_policia":       ("1121.00.0.0.00.00", ("1121.01.0.0.00.00", "1121.01.0.1.00.00"),       False),
    "taxas_prestacao_servicos":  ("1122.00.0.0.00.00", ("1122.01.0.0.00.00", "1122.01.0.1.00.00"),       False),
    # TAXAS (rubrica consolidadora 1120 = 1121 (integralmente 1121.04) + 1122 (integralmente 1122.01))
    "taxas":                     ("1120.00.0.0.00.00", ("1121.04.0.0.00.00", "1122.01.0.0.00.00"),       True),
    "contribuicoes_melhorias":   ("1131.00.0.0.00.00", ("1131.99.0.0.00.00", "1131.99.0.1.00.00"),       False),
    "cosip":                     ("1241.00.0.0.00.00", ("1241.50.0.0.00.00", "1241.50.0.1.00.00"),       False),
    "icms":                      ("1721.50.0.0.00.00", ("1721.50.0.1.00.00",),                           False),
    "ipva":                      ("1721.51.0.0.00.00", ("1721.51.0.1.00.00",),                           False),
    "ipi":                       ("1721.52.0.0.00.00", ("1721.52.0.1.00.00",),                           False),
    "cide":                      ("1721.53.0.0.00.00", ("1721.53.0.1.00.00",),                           False),
    "fpm_cota_mensal":           ("1711.51.1.0.00.00", ("1711.51.1.1.00.00",),                           False),
    "fpm_cotas_extraordinarias": ("1711.51.2.0.00.00", ("1711.51.2.1.00.00",),                           False),
    # FPM total = código-mãe 1711.51 (fallback: soma mensal + extraordinária)
    "fpm_total":                 ("1711.51.0.0.00.00", ("1711.51.1.0.00.00", "1711.51.2.0.00.00"),       True),
    "itr":                       ("1711.52.0.0.00.00", ("1711.52.0.1.00.00",),                           False),
    # Grupo 4 — retenções ao FUNDEB (códigos 9xxxx) sobre as receitas já usadas nos grupos 2/3
    "fundeb_fpm":                ("91711.51.0.0.00.00", (),                                               False),
    "fundeb_itr":                ("91711.52.0.0.00.00", (),                                               False),
    "fundeb_icms":               ("91721.50.0.0.00.00", (),                                               False),
    "fundeb_ipva":               ("91721.51.0.0.00.00", (),                                               False),
    "fundeb_ipi":                ("91721.52.0.0.00.00", (),                                               False),
}


def _parse(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _extrair_cabecalho(pdf_path: str) -> tuple[str, str]:
    doc = fitz.open(pdf_path)
    text = doc[0].get_text("text").upper()
    doc.close()
    m_mun = re.search(r"PREFEITURA MUNICIPAL DE (.+)", text)
    m_ano = re.search(r"EXERC[IÍ]CIO[:\s]*(\d{4})", text)
    municipio = m_mun.group(1).strip() if m_mun else ""
    exercicio = m_ano.group(1) if m_ano else ""
    return municipio, exercicio


_NUM_TOKEN_RE = re.compile(r'^-?\d{1,3}(?:\.\d{3})*,\d{2}$')
_COD_TOKEN_RE = re.compile(r'^9?\d{4}\.\d{2}\.\d\.\d\.\d{2}\.\d{2}$')
_HDR_ARRECADADA_RE = re.compile(r'^(ARRECADAD|REALIZAD)', re.IGNORECASE)


def _indexar_por_posicao(pdf_path: str) -> dict[str, float] | None:
    """Indexa a coluna ARRECADADA pela POSICAO dos numeros na pagina.

    O Anexo 10 deixa em branco as colunas zeradas (Orcada / Arrecadada / Para Mais /
    Para Menos), entao a ORDEM dos numeros na linha nao diz a coluna: "Orcada + Para
    Menos" (arrecadada 0) e "Arrecadada + Para Mais" (receita nao prevista) tem os
    dois 2 numeros. Os valores sao alinhados a direita: agrupamos o x1 de todos os
    numeros da pagina em colunas e escolhemos a coluna mais proxima do cabecalho
    "ARRECADADA". Retorna None se nenhum cabecalho for encontrado (layout diferente).
    """
    index: dict[str, float] = {}
    alvo = None  # x1 do cabecalho; vale para as paginas seguintes se faltar
    achou_cabecalho = False
    doc = fitz.open(pdf_path)
    try:
        for page in doc:
            words = page.get_text("words")
            hdr = [w for w in words if _HDR_ARRECADADA_RE.match(w[4])]
            if hdr:
                alvo = hdr[0][2]
                achou_cabecalho = True
            if alvo is None:
                continue
            nums = [w for w in words if _NUM_TOKEN_RE.match(w[4])]
            if not nums:
                continue
            colunas: list[list[float]] = []
            for x1 in sorted(w[2] for w in nums):
                if colunas and x1 - colunas[-1][-1] <= 12:
                    colunas[-1].append(x1)
                else:
                    colunas.append([x1])
            centros = [sum(c) / len(c) for c in colunas]
            col_arrec = min(range(len(centros)), key=lambda i: abs(centros[i] - alvo))
            if abs(centros[col_arrec] - alvo) > 40:
                col_arrec = None  # nenhum numero desta pagina caiu sob o cabecalho
            for w in words:
                codigo = w[4]
                if not _COD_TOKEN_RE.match(codigo) or codigo in index:
                    continue
                valor = 0.0
                if col_arrec is not None:
                    for n in nums:
                        if abs(n[1] - w[1]) < 4:
                            ci = min(range(len(centros)), key=lambda i: abs(centros[i] - n[2]))
                            if ci == col_arrec:
                                valor = abs(_parse(n[4].lstrip("-")))
                                break
                index[codigo] = valor
    finally:
        doc.close()
    return index if achou_cabecalho and index else None


def _indexar(pdf_path: str) -> dict[str, float]:
    por_posicao = _indexar_por_posicao(pdf_path)
    if por_posicao is not None:
        logger.info("ANX10: %d códigos indexados por posição em %s", len(por_posicao), pdf_path)
        return por_posicao
    logger.warning("ANX10: cabeçalho 'ARRECADADA' não encontrado em %s — usando leitura por ordem", pdf_path)
    index: dict[str, float] = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            for line in text.splitlines():
                stripped = line.strip()
                m = CODIGO_RE.match(stripped)
                if not m:
                    continue
                codigo = m.group(1)
                if codigo in index:
                    continue
                numeros = NUMERO_RE.findall(stripped)
                if len(numeros) >= 3:
                    # Colunas completas: PREVISTO, ARRECADADO, SALDO.
                    index[codigo] = _parse(numeros[1])
                elif len(numeros) == 2:
                    if codigo.startswith("9"):
                        # Linhas "(R) DEDUÇÕES ..." (retenções FUNDEB): quando só 2
                        # números aparecem, são [PREVISÃO ATUALIZADA, ARRECADADA]
                        # (a coluna INICIAL e o SALDO=0 é que ficam em branco).
                        index[codigo] = _parse(numeros[1])
                    else:
                        # Linhas de receita: ARRECADADO=0 é impresso como "-" (não
                        # capturado pelo regex), sobrando só PREVISTO e SALDO — que
                        # ficam iguais entre si. A arrecadada real aqui é 0, não o
                        # valor de numeros[1] (que na verdade é o SALDO).
                        index[codigo] = 0.0
    logger.info("ANX10: %d códigos indexados em %s", len(index), pdf_path)
    return index


def _resolver(
    index: dict,
    primario: str,
    secundarios: tuple = (),
    somar_secundarios: bool = False,
) -> float:
    if primario in index:
        return index[primario]
    if somar_secundarios:
        return round(sum(index.get(c, 0.0) for c in secundarios), 2)
    for c in secundarios:
        if c in index:
            return index[c]
    return 0.0


def _irrf_codigos(index: dict) -> tuple[str, str]:
    """(sintetico, principal) do IR que pertence ao municipio (CF art. 158, I).

    O correto e a familia 1113.03 (IR Retido na Fonte). Ha prefeituras que lancam a
    mesma retencao em 1113.01 (IRPF) — nesse caso usamos 1113.01. Nunca 1113.00,
    que soma o IRPJ (1113.02).
    """
    if "1113.03.0.0.00.00" in index:
        return "1113.03.0.0.00.00", "1113.03.1.1.00.00"
    if "1113.01.0.0.00.00" in index:
        logger.warning("ANX10: sem 1113.03 (IRRF); usando 1113.01 (IRPF) como IR retido na fonte")
        return "1113.01.0.0.00.00", "1113.01.0.1.00.00"
    return "1113.03.0.0.00.00", "1113.03.1.1.00.00"


def extrair(pdf_path: str) -> dict:
    """Extrai os dados do Anexo 10 e retorna o JSON estruturado do Q1."""
    municipio, exercicio = _extrair_cabecalho(pdf_path)
    index = _indexar(pdf_path)

    def r(campo: str) -> float:
        primario, secundarios, somar = CAMPOS[campo]
        return _resolver(index, primario, secundarios, somar)

    iptu                     = r("iptu")
    itbi                     = r("itbi")
    irrf                     = r("irrf") or index.get(_irrf_codigos(index)[0], 0.0)
    iss                      = r("iss")
    taxas_poder_policia      = r("taxas_poder_policia")
    taxas_prestacao_servicos = r("taxas_prestacao_servicos")
    taxas                    = r("taxas")
    contribuicoes_melhorias  = r("contribuicoes_melhorias")
    cosip                    = r("cosip")

    # Contribuições de melhoria não integram a base do art. 29-A CF
    subtotal_tributaria = round(
        iptu + itbi + irrf + iss + taxas + cosip,
        2,
    )

    icms             = r("icms")
    ipva             = r("ipva")
    ipi              = r("ipi")
    cide             = r("cide")
    icms_desoneracao = 0.0
    subtotal_estado  = round(icms + ipva + ipi + cide, 2)
    # subtotal_repasse: agrupamento exibido no Quadro 1 (CIDE e IPI aparecem
    # na seção "Transferidos pela União", não na de Estado)
    subtotal_repasse_estado = round(icms + ipva + icms_desoneracao, 2)

    fpm_cota_mensal           = r("fpm_cota_mensal")
    fpm_cotas_extraordinarias = r("fpm_cotas_extraordinarias")
    fpm_total                 = r("fpm_total")
    itr                       = r("itr")
    subtotal_uniao            = round(fpm_total + itr, 2)
    subtotal_repasse_uniao    = round(cide + itr + fpm_total + ipi, 2)

    # Grupo 4 — Contribuição do Município para Formação do FUNDEB (retenções 9xxxx
    # sobre FPM, ITR, ICMS, IPVA e IPI). Exibida no quadro, mas NÃO integra o total
    # (Base Cálculo Repasse = apenas grupos 1 + 2 + 3).
    contribuicao_fundeb = round(
        r("fundeb_fpm") + r("fundeb_itr") + r("fundeb_icms") + r("fundeb_ipva") + r("fundeb_ipi"),
        2,
    )

    base_calculo  = round(subtotal_tributaria + subtotal_estado + subtotal_uniao, 2)
    limite_anual  = round(base_calculo * 0.07, 2)
    limite_mensal = round(limite_anual / 12, 2)

    return {
        "municipio": municipio,
        "exercicio": exercicio,
        "receita_tributaria": {
            "iptu":                   iptu,
            "itbi":                   itbi,
            "irrf":                   irrf,
            "iss":                    iss,
            "taxas_poder_policia":    taxas_poder_policia,
            "taxas_prestacao_servicos": taxas_prestacao_servicos,
            "taxas":                  taxas,
            "contribuicoes_melhorias": contribuicoes_melhorias,
            "divida_ativa_tributaria": 0.0,
            "multas_juros_tributos":  0.0,
            "cosip":                  cosip,
            "subtotal":               subtotal_tributaria,
        },
        "transferencias_estado": {
            "icms":             icms,
            "ipva":             ipva,
            "ipi":              ipi,
            "cide":             cide,
            "icms_desoneracao": icms_desoneracao,
            "subtotal":         subtotal_estado,
            "subtotal_repasse": subtotal_repasse_estado,
        },
        "transferencias_uniao": {
            "fpm_cota_mensal":           fpm_cota_mensal,
            "fpm_cotas_extraordinarias": fpm_cotas_extraordinarias,
            "fpm_total":                 fpm_total,
            "itr":                       itr,
            "subtotal":                  subtotal_uniao,
            "subtotal_repasse":          subtotal_repasse_uniao,
        },
        "contribuicao_fundeb": contribuicao_fundeb,
        "totais": {
            "base_calculo":        base_calculo,
            "limite_anual":        limite_anual,
            "limite_mensal":       limite_mensal,
            "percentual_aplicado": 7.0,
        },
    }


def extrair_q22(pdf_path: str, bo_fundeb_path: str = None) -> dict:
    """Q22 — Receitas do FUNDEB (Apuração).

    E = total receitas recebidas (B + complementações + aplic. financeira)
    F = transferências FUNDEB (1751.50)
    G/H/I = complementações VAAF/VAAT/VAAR
    J = receita de aplicação financeira dos recursos do FUNDEB — vem do Balanço
        isolado do FUNDEB (RECEITA PATRIMONIAL realizada), quando enviado; sem ele,
        fica 0 (o ANX_10 não traz código padronizado para essa receita).
    C = receitas destinadas ao FUNDEB (soma dos 9xxxx, 20%)
    K = resultado líquido = F − C  (apenas transferências, não total E)
    """
    municipio, exercicio = _extrair_cabecalho(pdf_path)
    index = _indexar(pdf_path)

    def r(codigo: str) -> float:
        return index.get(codigo, 0.0)

    # ── Receitas recebidas do FUNDEB ─────────────────────────────────────────
    transferencias_fundeb = r('1751.50.0.0.00.00')
    vaaf = r('1715.51.0.0.00.00')
    vaat = r('1715.50.0.0.00.00')
    eti  = r('1715.53.0.0.00.00')
    # (J) Receita de aplicação financeira: mesma fonte do Q20 (Balanço isolado do
    # FUNDEB → RECEITA PATRIMONIAL realizada). Sem o documento, permanece 0.
    aplic_financeira = 0.0
    if bo_fundeb_path:
        from backend.extractors.bo_fundeb import extrair as extrair_bo_fundeb
        aplic_financeira = extrair_bo_fundeb(bo_fundeb_path)['receita_patrimonial_realizada']

    # VAAR: quando arrecadada=0, o PDF imprime "-" (invisível ao regex) e o saldo
    # (= previsão) vira numeros[1], inflando o valor. Calcula por subtração do total
    # de complementações (1715.00), que tem arrecadada>0 e é lido corretamente.
    total_complementacoes = r('1715.00.0.0.00.00')
    vaar_extraido = r('1715.52.0.0.00.00')
    vaar_calculado = round(max(0.0, total_complementacoes - vaaf - vaat - eti), 2)
    # Usa o menor valor entre o extraído e o calculado para evitar o artefato do saldo
    vaar = min(vaar_extraido, vaar_calculado) if total_complementacoes > 0 else vaar_extraido

    receitas_recebidas_fundeb = round(
        transferencias_fundeb + vaaf + vaat + vaar + eti + aplic_financeira, 2
    )

    # ── Receitas destinadas ao FUNDEB (20%) — códigos 9xxxx sintéticos ──────
    fpm_20  = r('91711.51.1.0.00.00')
    itr_20  = r('91711.52.0.0.00.00')
    icms_20 = r('91721.50.0.0.00.00')
    ipva_20 = r('91721.51.0.0.00.00')
    ipi_20  = r('91721.52.0.0.00.00')
    receitas_destinadas_ao_fundeb = round(fpm_20 + itr_20 + icms_20 + ipva_20 + ipi_20, 2)

    # ── Resultado líquido: B (transferências) − A (destinadas) ──────────────
    resultado_liquido = round(transferencias_fundeb - receitas_destinadas_ao_fundeb, 2)

    logger.info(
        "ANX10 Q22: recebidas=%.2f transf=%.2f destinadas=%.2f resultado=%.2f",
        receitas_recebidas_fundeb, transferencias_fundeb,
        receitas_destinadas_ao_fundeb, resultado_liquido,
    )
    return {
        'municipio':                           municipio,
        'exercicio':                           exercicio,
        # Chaves do template
        'receitas_recebidas_fundeb_e':         receitas_recebidas_fundeb,
        'transferencias_recursos_fundeb_f':    transferencias_fundeb,
        'complementacao_uniao_vaaf_g':         vaaf,
        'complementacao_uniao_vaat_h':         vaat,
        'complementacao_uniao_vaar_i':         vaar,
        'receita_aplicacao_financeira_fundeb_j': aplic_financeira,
        'total_destinado_fundeb_apurado_c':    receitas_destinadas_ao_fundeb,
        'resultado_liquido_transferencias_fundeb_k': resultado_liquido,
        # Campos diagnóstico
        'eti':     eti,
        'fpm_20':  fpm_20,
        'itr_20':  itr_20,
        'icms_20': icms_20,
        'ipva_20': ipva_20,
        'ipi_20':  ipi_20,
    }


def extrair_q21(pdf_path: str) -> dict:
    """Q21 — Alocação dos Recursos Destinados à Formação do FUNDEB.

    Conforme template TCE-MA (foto de referência):
      A = RECEITAS DESTINADAS AO FUNDEB = soma das receitas base 100%
          (FPM + ICMS + IPI + ITR + IPVA + Compensações Financeiras)
      B = TOTAL EXIGIDO = 20% de A (calculado individualmente por receita)
      C = TOTAL DESTINADO APURADO = deduções efetivas (códigos 9xxxx do ANX_10)
          Fallback para B se os códigos 9xxxx não forem encontrados.
      D = (C / A) × 100  →  deve resultar em ~20,00%
    """
    municipio, exercicio = _extrair_cabecalho(pdf_path)
    index = _indexar(pdf_path)

    def r(codigo: str) -> float:
        return index.get(codigo, 0.0)

    # ── Receitas base individuais (100%) ─────────────────────────────────────
    # FPM: mesma estratégia do Quadro 1 (código-pai com fallback pro analítico).
    fpm_cota_mensal  = _resolver(index, *CAMPOS["fpm_cota_mensal"])
    icms             = r('1721.50.0.1.00.00')
    ipi_exportacao   = r('1721.52.0.1.00.00')
    itr_desoneracao  = 0.0
    ipva             = r('1721.51.0.1.00.00')
    itr              = r('1711.52.0.1.00.00')

    # A = soma das receitas 100% (linhas individuais do template)
    receitas_destinadas_ao_fundeb_a = round(
        fpm_cota_mensal + icms + ipi_exportacao + itr_desoneracao + ipva + itr, 2
    )
    total_base = receitas_destinadas_ao_fundeb_a

    # ── B: 20% exigido de cada receita ───────────────────────────────────────
    fpm_20  = round(fpm_cota_mensal * 0.20, 2)
    icms_20 = round(icms            * 0.20, 2)
    ipi_20  = round(ipi_exportacao  * 0.20, 2)
    itd_20  = round(itr_desoneracao * 0.20, 2)
    ipva_20 = round(ipva            * 0.20, 2)
    itr_20  = round(itr             * 0.20, 2)

    total_excedido_fundeb_b = round(fpm_20 + icms_20 + ipi_20 + itd_20 + ipva_20 + itr_20, 2)

    # ── C: deduções efetivas (códigos 9xxxx = retenções FUNDEB) ──────────────
    c_fpm  = r('91711.51.1.1.00.00') or r('91711.51.1.0.00.00')
    c_itr  = r('91711.52.0.1.00.00') or r('91711.52.0.0.00.00')
    c_icms = r('91721.50.0.1.00.00') or r('91721.50.0.0.00.00')
    c_ipva = r('91721.51.0.1.00.00') or r('91721.51.0.0.00.00')
    c_ipi  = r('91721.52.0.1.00.00') or r('91721.52.0.0.00.00')
    total_apurado_9x = round(c_fpm + c_itr + c_icms + c_ipva + c_ipi, 2)

    # Fallback: se 9xxxx ausentes no PDF, usa B
    total_destinado_fundeb_apurado_c = total_apurado_9x if total_apurado_9x > 0 else total_excedido_fundeb_b

    # ── D: (C / A) × 100 — deve resultar em ~20,00% ──────────────────────────
    percentual_destinado_fundeb_d = (
        round((total_destinado_fundeb_apurado_c / receitas_destinadas_ao_fundeb_a) * 100, 2)
        if receitas_destinadas_ao_fundeb_a else 0.0
    )

    logger.info(
        "ANX10 Q21: A=%.2f B=%.2f C=%.2f D=%.2f%%",
        receitas_destinadas_ao_fundeb_a, total_excedido_fundeb_b,
        total_destinado_fundeb_apurado_c, percentual_destinado_fundeb_d,
    )
    return {
        'municipio':                        municipio,
        'exercicio':                        exercicio,
        # Linhas do template
        'fpm_cota_mensal':                  fpm_cota_mensal,
        'icms':                             icms,
        'ipi_exportacao':                   ipi_exportacao,
        'itr_desoneracao':                  itr_desoneracao,
        'ipva':                             ipva,
        'itr':                              itr,
        'receitas_destinadas_ao_fundeb_a':  receitas_destinadas_ao_fundeb_a,
        'total_excedido_fundeb_b':          total_excedido_fundeb_b,
        'total_destinado_fundeb_apurado_c': total_destinado_fundeb_apurado_c,
        'percentual_destinado_fundeb_d':    percentual_destinado_fundeb_d,
        # Diagnóstico
        'total_base':  total_base,
        'fpm_20':      fpm_20,
        'icms_20':     icms_20,
        'ipi_20':      ipi_20,
        'ipva_20':     ipva_20,
        'itr_20':      itr_20,
    }


def extrair_q19(pdf_path: str) -> dict:
    """Extrai dados para Q19 — Apuração Receita Impostos/Transferências (Educação/MDE).

    Diferenças-chave vs Q17 (saúde):
    - Usa códigos analíticos (0.1 / 1.1) → separa principal de multas/encargos
    - FPM extraordinário INCLUSO na base
    - Deduz FUNDEB (20% via códigos 9xxxx) → base líquida para calcular 25%
    """
    municipio, exercicio = _extrair_cabecalho(pdf_path)
    index = _indexar(pdf_path)

    def r(codigo: str) -> float:
        return index.get(codigo, 0.0)

    # ── IMPOSTOS (analítico = principal; sintético - analítico = multas/encargos) ──
    iptu          = r("1112.50.0.1.00.00")
    iptu_multas   = max(0.0, round(r("1112.50.0.0.00.00") - iptu, 2))

    itbi          = r("1112.53.0.1.00.00")
    itbi_multas   = max(0.0, round(r("1112.53.0.0.00.00") - itbi, 2))

    iss           = r("1114.51.1.1.00.00")
    iss_multas    = max(0.0, round(r("1114.51.0.0.00.00") - iss, 2))

    irrf_sint, irrf_princ = _irrf_codigos(index)
    irrf          = r(irrf_princ) or r(irrf_sint)
    # Encargos do IRRF não têm linha separada → vai em multas_impostos
    multas_impostos = max(0.0, round(r(irrf_sint) - irrf, 2))

    total_receita_impostos = round(
        iptu + iptu_multas +
        itbi + itbi_multas +
        iss  + iss_multas  +
        irrf + multas_impostos,
        2,
    )

    # ── TRANSFERÊNCIAS (FPM = mensal + extraordinário, ambos integram a base MDE) ──
    # Mesma estratégia do Quadro 1: prioriza o código-pai (valor completo);
    # cai para o código analítico apenas se o pai não existir no PDF.
    fpm_mensal         = _resolver(index, *CAMPOS["fpm_cota_mensal"])
    fpm_extraordinario = _resolver(index, *CAMPOS["fpm_cotas_extraordinarias"])
    fpm_total          = _resolver(index, *CAMPOS["fpm_total"])
    cota_parte_itr     = r("1711.52.0.1.00.00")
    ipva               = r("1721.51.0.1.00.00")
    icms               = r("1721.50.0.1.00.00")
    icms_desoneracao   = 0.0
    ipi_exportacao     = r("1721.52.0.1.00.00")
    iof_ouro           = 0.0
    outras_transferencias = 0.0

    total_receita_transferencias = round(
        fpm_total + cota_parte_itr + ipva + icms +
        icms_desoneracao + ipi_exportacao + iof_ouro + outras_transferencias,
        2,
    )

    # ── FUNDEB (códigos 9xxxx analíticos = deduções 20%) ──
    fundeb_fpm  = r("91711.51.1.1.00.00")
    fundeb_itr  = r("91711.52.0.1.00.00")
    fundeb_icms = r("91721.50.0.1.00.00")
    fundeb_ipva = r("91721.51.0.1.00.00")
    fundeb_ipi  = r("91721.52.0.1.00.00")
    deducao_fundeb = round(fundeb_fpm + fundeb_itr + fundeb_icms + fundeb_ipva + fundeb_ipi, 2)

    # ── BASE EDUCAÇÃO ──
    # base_bruta = impostos + transferências (FPM total já incluso); dedução do FUNDEB fica em Q20
    base_bruta   = round(total_receita_impostos + total_receita_transferencias, 2)
    base_liquida = round(base_bruta - deducao_fundeb, 2)
    aplicacao_minima = round(base_liquida * 0.25, 2)

    logger.info(
        "ANX10 Q19: impostos=%.2f transf=%.2f (fpm_mensal=%.2f fpm_extra=%.2f) fundeb=%.2f base_bruta=%.2f base_liq=%.2f",
        total_receita_impostos, total_receita_transferencias,
        fpm_mensal, fpm_extraordinario, deducao_fundeb, base_bruta, base_liquida,
    )
    return {
        "municipio":                     municipio,
        "exercicio":                     exercicio,
        # Impostos (campos do template)
        "iptu":                          iptu,
        "iptu_multas":                   iptu_multas,
        "itbi":                          itbi,
        "itbi_multas":                   itbi_multas,
        "iss":                           iss,
        "iss_multas":                    iss_multas,
        "irrf":                          irrf,
        "itr_impostos":                  0.0,
        "itr_multas":                    0.0,
        "multas_impostos":               multas_impostos,
        "divida_ativa_impostos":         0.0,
        "multas_divida_ativa":           0.0,
        "total_receita_impostos":        total_receita_impostos,
        # Transferências (campos do template)
        # fpm_regular = FPM total (mensal + extraordinário) — template exibe linha única de FPM
        "fpm_regular":                   fpm_total,
        "cota_parte_itr":                cota_parte_itr,
        "ipva":                          ipva,
        "icms":                          icms,
        "icms_desoneracao":              icms_desoneracao,
        "ipi_exportacao":                ipi_exportacao,
        "iof_ouro":                      iof_ouro,
        "outras_transferencias":         outras_transferencias,
        "total_receita_transferencias":  total_receita_transferencias,
        # Base MDE — template linha 27: base BRUTA (dedução do FUNDEB fica em Q20)
        "total_base_calculo":            base_bruta,
        # Campos adicionais (informativos, fora do template)
        "fpm_mensal":                    fpm_mensal,
        "fpm_extraordinario":            fpm_extraordinario,
        "deducao_fundeb":                deducao_fundeb,
        "fundeb_fpm":                    fundeb_fpm,
        "fundeb_itr":                    fundeb_itr,
        "fundeb_icms":                   fundeb_icms,
        "fundeb_ipva":                   fundeb_ipva,
        "fundeb_ipi":                    fundeb_ipi,
        "base_bruta":                    base_bruta,
        "base_liquida":                  base_liquida,
        "aplicacao_minima":              aplicacao_minima,
    }


def extrair_q17(pdf_path: str) -> dict:
    """Extrai dados para Q17 — Apuração Receita de Impostos e Transferências (Saúde)."""
    municipio, exercicio = _extrair_cabecalho(pdf_path)
    index = _indexar(pdf_path)

    def r(codigo: str) -> float:
        return index.get(codigo, 0.0)

    iptu = r("1112.50.0.0.00.00")
    itbi = r("1112.53.0.0.00.00")
    iss  = r("1114.51.0.0.00.00")
    # IRRF: 1113.03 (agrega trabalho + outros rendimentos conforme LC 141/2012),
    # ou 1113.01 quando a prefeitura lancou a retencao como IRPF
    irrf = r(_irrf_codigos(index)[0])

    total_impostos = round(iptu + itbi + iss + irrf, 2)

    # FPM: mesma estratégia do Quadro 1 (código-pai com fallback pro analítico).
    fpm_mensal         = _resolver(index, *CAMPOS["fpm_cota_mensal"])
    fpm_extraordinario = _resolver(index, *CAMPOS["fpm_cotas_extraordinarias"])
    itr                = r("1711.52.0.0.00.00")
    ipva               = r("1721.51.0.0.00.00")
    icms               = r("1721.50.0.0.00.00")
    icms_desoneracao   = 0.0  # LC 87/96 — incluir se código disponível
    ipi                = r("1721.52.0.0.00.00")
    iof_ouro           = 0.0

    total_transferencias = round(
        fpm_mensal + itr + ipva + icms + icms_desoneracao + ipi + iof_ouro, 2
    )
    base_calculo      = round(total_impostos + total_transferencias, 2)
    aplicacao_minima  = round(base_calculo * 0.15, 2)
    impacto_fpm_extra = round(fpm_extraordinario * 0.15, 2)

    logger.info(
        "ANX10 Q17: impostos=%.2f transferencias=%.2f base=%.2f aplic_min=%.2f",
        total_impostos, total_transferencias, base_calculo, aplicacao_minima,
    )
    return {
        "municipio":           municipio,
        "exercicio":           exercicio,
        "iptu":                iptu,
        "itbi":                itbi,
        "iss":                 iss,
        "irrf":                irrf,
        "total_impostos":      total_impostos,
        "fpm_mensal":          fpm_mensal,
        "fpm_extraordinario":  fpm_extraordinario,
        "itr":                 itr,
        "ipva":                ipva,
        "icms":                icms,
        "icms_desoneracao":    icms_desoneracao,
        "ipi":                 ipi,
        "iof_ouro":            iof_ouro,
        "total_transferencias": total_transferencias,
        "base_calculo":        base_calculo,
        "aplicacao_minima":    aplicacao_minima,
        "impacto_fpm_extra":   impacto_fpm_extra,
    }


def formatar_texto(pdf_path: str) -> str:
    """
    Extrai o Anexo 10 e retorna texto tabelado limpo para consumo pela IA.
    Cada linha: CÓDIGO | DESCRIÇÃO | ARRECADADA
    Cabeçalho via PyMuPDF (sem duplicação de fonte).
    """
    municipio, exercicio = _extrair_cabecalho(pdf_path)

    # Indexa código → (descrição, arrecadada) via pdfplumber
    linhas: list[tuple[str, str, float]] = []
    seen: set[str] = set()

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            prev_desc = ""
            for line in text.splitlines():
                stripped = line.strip()
                m = CODIGO_RE.match(stripped)
                if not m:
                    continue
                codigo = m.group(1)
                if codigo in seen:
                    continue
                seen.add(codigo)

                numeros = NUMERO_RE.findall(stripped)
                if len(numeros) < 2:
                    continue

                arrecadada = _parse(numeros[1])

                # Descrição: texto entre o código e o primeiro número
                pos_fim_codigo = stripped.index(codigo) + len(codigo)
                pos_primeiro_num = stripped.index(numeros[0])
                descricao = stripped[pos_fim_codigo:pos_primeiro_num].strip()
                if not descricao:
                    descricao = prev_desc
                prev_desc = descricao

                linhas.append((codigo, descricao, arrecadada))

    # Monta saída formatada
    out = []
    out.append("ANEXO 10 — COMPARATIVO DA RECEITA ORÇADA COM A ARRECADADA")
    out.append(f"MUNICÍPIO: {municipio} | EXERCÍCIO: {exercicio}")
    out.append("")
    out.append(f"{'CÓDIGO':<22} {'DESCRIÇÃO':<55} {'ARRECADADA':>18}")
    out.append("-" * 97)

    for codigo, descricao, arrecadada in linhas:
        valor_fmt = f"{arrecadada:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        out.append(f"{codigo:<22} {descricao[:54]:<55} {valor_fmt:>18}")

    out.append("-" * 97)
    out.append(f"Total de registros: {len(linhas)}")
    return "\n".join(out)


def extrair_q04(pdf_path: str) -> dict:
    """Q04 — Receita Corrente Líquida (RCL).

    Extrai da coluna ARRECADADA (2º valor numérico) do Anexo 10.
    Códigos conforme mapeamento TCE-MA.
    """
    municipio, exercicio = _extrair_cabecalho(pdf_path)
    index = _indexar(pdf_path)

    def r(codigo: str) -> float:
        return index.get(codigo, 0.0)

    # ── RECEITA TRIBUTÁRIA ────────────────────────────────────────────────────
    impostos               = r("1110.00.0.0.00.00")
    taxas                  = r("1120.00.0.0.00.00")
    contribuicoes_melhorias = r("1130.00.0.0.00.00")
    # Código pai 1100 é fonte primária; a soma é apenas fallback
    subtotal_tributaria = r("1100.00.0.0.00.00") or round(impostos + taxas + contribuicoes_melhorias, 2)

    # ── CONTRIBUIÇÕES (extrair direto do código pai) ──────────────────────────
    subtotal_contribuicoes = r("1200.00.0.0.00.00")
    cosip                  = r("1240.00.0.0.00.00")

    # ── RECEITA PATRIMONIAL ───────────────────────────────────────────────────
    valores_mobiliarios          = r("1320.00.0.0.00.00")
    exploracao_recursos_naturais = r("1340.00.0.0.00.00")
    demais_receitas_patrimoniais = r("1390.00.0.0.00.00")
    subtotal_patrimonial         = r("1300.00.0.0.00.00")  # direto, NÃO calcular (v2)

    # ── RECEITA AGROPECUÁRIA ──────────────────────────────────────────────────
    receita_agropecuaria = r("1400.00.0.0.00.00")

    # ── RECEITA INDUSTRIAL ────────────────────────────────────────────────────
    receita_industrial = r("1500.00.0.0.00.00")

    # ── RECEITA DE SERVIÇOS ───────────────────────────────────────────────────
    receita_servicos = r("1600.00.0.0.00.00")

    # ── TRANSFERÊNCIAS CORRENTES ──────────────────────────────────────────────
    transf_uniao        = r("1710.00.0.0.00.00")
    transf_estados      = r("1720.00.0.0.00.00")
    transf_municipios   = r("1730.00.0.0.00.00")
    transf_inst_priv    = r("1740.00.0.0.00.00")
    transf_outras_pub   = r("1750.00.0.0.00.00")
    # Código pai 1700 é fonte primária; a soma é apenas fallback
    subtotal_transf = r("1700.00.0.0.00.00") or round(
        transf_uniao + transf_estados + transf_municipios +
        transf_inst_priv + transf_outras_pub, 2
    )

    # ── OUTRAS RECEITAS CORRENTES (extrair direto do código pai) ─────────────
    subtotal_outras = r("1900.00.0.0.00.00")

    # ── TOTAL RECEITA CORRENTE (código 1000 — fonte primária) ────────────────
    total_receita_corrente = r("1000.00.0.0.00.00")

    # ── VALIDAÇÃO: soma dos subtotais vs total declarado (v2) ─────────────────
    soma_subtotais_categorias = round(
        subtotal_tributaria + subtotal_contribuicoes + subtotal_patrimonial +
        receita_agropecuaria + receita_industrial + receita_servicos +
        subtotal_transf + subtotal_outras, 2
    )
    diferenca_validacao = round(soma_subtotais_categorias - total_receita_corrente, 2)
    divergencia_existe = abs(diferenca_validacao) > 0.01
    divergencia_obs = (
        "Soma dos subtotais de categoria diverge do total declarado em 1000.00. "
        "Investigar causa (reclassificação, erro de sistema, omissão contábil)."
        if divergencia_existe else ""
    )

    # ── DEDUÇÕES DA RCL ───────────────────────────────────────────────────────
    contrib_servidor_prev      = 0.0   # código não padronizado nos layouts TCE-MA
    compensacao_regimes        = 0.0   # código não padronizado nos layouts TCE-MA
    deducao_fundeb             = r("91000.00.0.0.00.00")   # valor absoluto
    transf_obrig_166a_art51    = 0.0   # emendas individuais — sem código fixo
    transf_obrig_166_art166    = 0.0   # emendas bancada — sem código fixo
    rendimentos_prev           = r("1321.04.0.0.00.00")
    transf_agentes_saude       = 0.0   # CF art.198 — sem código fixo

    subtotal_deducoes = round(
        contrib_servidor_prev + compensacao_regimes + deducao_fundeb +
        transf_obrig_166a_art51 + transf_obrig_166_art166 +
        rendimentos_prev + transf_agentes_saude, 2
    )

    rcl = round(total_receita_corrente - subtotal_deducoes, 2)

    logger.info(
        "ANX10 Q04: total_rc=%.2f soma_subtotais=%.2f divergencia=%.2f deducoes=%.2f rcl=%.2f",
        total_receita_corrente, soma_subtotais_categorias, diferenca_validacao, subtotal_deducoes, rcl,
    )

    return {
        "municipio": municipio,
        "exercicio": exercicio,
        "receita_corrente_liquida": {
            "receita_tributaria": {
                "impostos":               impostos,
                "taxas":                  taxas,
                "contribuicoes_melhorias": contribuicoes_melhorias,
                "subtotal":               subtotal_tributaria,
            },
            "receita_contribuicoes": {
                "cosip":    cosip,
                "subtotal": subtotal_contribuicoes,
            },
            "receita_patrimonial": {
                "valores_mobiliarios":          valores_mobiliarios,
                "exploracao_recursos_naturais": exploracao_recursos_naturais,
                "demais_receitas_patrimoniais": demais_receitas_patrimoniais,
                "subtotal":                     subtotal_patrimonial,
            },
            "receita_agropecuaria": {
                "valor":    receita_agropecuaria,
                "subtotal": receita_agropecuaria,
            },
            "receita_industrial": {
                "valor":    receita_industrial,
                "subtotal": receita_industrial,
            },
            "receita_servicos": {
                "valor":    receita_servicos,
                "subtotal": receita_servicos,
            },
            "transferencias_correntes": {
                "transferencias_uniao":                       transf_uniao,
                "transferencias_estados":                     transf_estados,
                "transferencias_municipios":                  transf_municipios,
                "transferencias_instituicoes_privadas":       transf_inst_priv,
                "transferencias_outras_instituicoes_publicas": transf_outras_pub,
                "subtotal":                                   subtotal_transf,
            },
            "outras_receitas_correntes": {
                "subtotal": subtotal_outras,
            },
            "total_receita_corrente":     total_receita_corrente,
            "soma_subtotais_categorias":  soma_subtotais_categorias,
            "divergencia_total_receita_corrente": {
                "existe":     divergencia_existe,
                "valor":      diferenca_validacao,
                "observacao": divergencia_obs,
            },
            "deducoes": {
                "contrib_servidor_previdencia":                      contrib_servidor_prev,
                "compensacao_financ_regimes_previdencia":            compensacao_regimes,
                "deducao_formacao_fundeb":                           deducao_fundeb,
                "transferencias_obrigatorias_uniao_166a_artigo51":   transf_obrig_166a_art51,
                "transferencias_obrigatorias_uniao_166_artigo166":   transf_obrig_166_art166,
                "rendimentos_aplicacoes_recursos_previdenciarios":   rendimentos_prev,
                "transferencias_uniao_remuneracao_agentes_saude_endemias": transf_agentes_saude,
                "subtotal_deducoes":                                 subtotal_deducoes,
            },
            "receita_corrente_liquida_declarada": rcl,
        },
    }
