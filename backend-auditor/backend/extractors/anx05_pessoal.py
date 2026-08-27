import logging
import re

import fitz
import pdfplumber

from backend.extractors.anx02_despesas import extrair as extrair_anx02

logger = logging.getLogger(__name__)

NUMERO_RE = re.compile(r'\d{1,3}(?:\.\d{3})*,\d{2}')


def _parse(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _element_value(items: list, orgao_cod: str, element_code: str) -> float:
    """
    Retorna o valor do elemento contábil.
    Tenta o código exato primeiro; se não encontrado, soma os sub-desdobramentos.
    """
    for item in items:
        if item["orgao_codigo"] == orgao_cod and item["codigo"] == element_code:
            return item["valor"]
    prefix = element_code + "."
    return round(sum(
        item["valor"] for item in items
        if item["orgao_codigo"] == orgao_cod and item["codigo"].startswith(prefix)
    ), 2)


def _extrair_exercicio(anx10_path: str) -> str:
    """Extrai o exercício (ano) do ANX_10 — mais confiável que o ANX_02."""
    doc = fitz.open(anx10_path)
    text = doc[0].get_text("text").upper()
    doc.close()
    m = re.search(r"EXERC[IÍ]CIO[^\d]*(\d{4})", text)
    return m.group(1) if m else ""


def _extrair_rcl(anx10_path: str) -> float:
    """Extrai RCL do ANX_10_ATUAL: Receitas Correntes Arrecadadas − Deduções FUNDEB."""
    receitas = 0.0
    deducoes = 0.0
    with pdfplumber.open(anx10_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                stripped = line.strip()
                nums = NUMERO_RE.findall(stripped)
                if len(nums) < 2:
                    continue
                if not receitas and stripped.startswith("1000.00.0.0.00.00"):
                    receitas = _parse(nums[1])
                elif not deducoes and stripped.startswith("91000.00.0.0.00.00"):
                    deducoes = _parse(nums[1])
    return round(receitas - deducoes, 2)


def extrair(anx02_path: str, anx10_path: str, ff_saude_path: str = None) -> dict:
    r = extrair_anx02(anx02_path)
    municipio = r["municipio"]
    exercicio = _extrair_exercicio(anx10_path) or r["exercicio"]

    TERMOS_EXEC = ("EXEC", "PREFEIT", "MUNICIP")
    TERMOS_LEG  = ("CAMARA", "CÂMARA", "LEGISLAT", "PODER LEGISL")

    exec_cod = next(
        (cod for cod, o in r["orgaos"].items()
         if any(t in o["nome"].upper() for t in TERMOS_EXEC)),
        None,
    )
    if exec_cod is None:
        # Fallback: primeiro órgão que claramente não é a câmara
        exec_cod = next(
            (cod for cod, o in r["orgaos"].items()
             if not any(t in o["nome"].upper() for t in TERMOS_LEG)),
            None,
        )
    if exec_cod is None and r["orgaos"]:
        # Último recurso: órgão com maior pessoal_encargos (executivo é tipicamente o maior)
        exec_cod = max(r["orgaos"].items(), key=lambda x: x[1]["pessoal_encargos"])[0]
    if exec_cod is None:
        raise ValueError(f"ANX_02 não contém nenhum órgão reconhecível. Órgãos encontrados: {list(r['orgaos'].keys())}")
    logger.info("Q5: órgão executivo identificado como '%s' (%s)", r['orgaos'][exec_cod]['nome'], exec_cod)

    items = r["itens"]

    pessoal_ativo                  = r["orgaos"][exec_cod]["pessoal_encargos"]
    pessoal_inativo_pensionistas   = 0.0
    outras_despesas_terceirizacao  = _element_value(items, exec_cod, "3.3.90.34")

    # DESPESA COM PESSOAL = valor extraído diretamente do elemento 3.1.90
    # (Aplicações Diretas) — não é mais a soma das linhas de detalhamento acima.
    despesa_bruta = _element_value(items, exec_cod, "3.1.90")

    decisao_judicial           = _element_value(items, exec_cod, "3.1.90.91")
    exercicios_anteriores      = _element_value(items, exec_cod, "3.1.90.92")
    indenizacoes_demissao      = 0.0
    inativos_recursos_vinc     = 0.0

    # Deduções vindas da planilha de repasses Fundo a Fundo da Saúde (FNS), quando enviada:
    #  - ACS/Combate às Endemias com recursos vinculados (CF art. 198 §11)
    #  - Parcela dedutível do piso da enfermagem (ADCT art. 38 §2º; 2025 = 91% do repasse)
    agentes_comunitarios       = 0.0
    piso_enfermeiro            = 0.0
    if ff_saude_path:
        from backend.extractors.fundo_a_fundo import extrair as extrair_ff_saude
        ff = extrair_ff_saude(ff_saude_path, municipio, exercicio)
        agentes_comunitarios = ff["agentes_comunitarios_saude_endemias"]
        piso_enfermeiro      = ff["parcela_dedutivel_piso_enfermeiro"]

    subtotal_deducoes = round(
        decisao_judicial
        + exercicios_anteriores
        + indenizacoes_demissao
        + inativos_recursos_vinc
        + agentes_comunitarios
        + piso_enfermeiro,
        2,
    )

    despesa_liquida_restos_pagar = 0.0
    despesa_liquida = round(
        despesa_bruta - subtotal_deducoes - despesa_liquida_restos_pagar, 2
    )

    rcl = _extrair_rcl(anx10_path)
    percentual = round(despesa_liquida / rcl, 4) if rcl > 0 else 0.0

    logger.info(
        "ANX05 Q5: bruta=%.2f deducoes=%.2f liquida=%.2f rcl=%.2f pct=%.4f (%.2f%%)",
        despesa_bruta, subtotal_deducoes, despesa_liquida, rcl, percentual, percentual * 100,
    )

    return {
        "municipio": municipio,
        "exercicio": exercicio,
        "orgao": "Executivo",
        "despesa_com_pessoal": {
            "pessoal_ativo":                        pessoal_ativo,
            "pessoal_inativo_pensionistas":         pessoal_inativo_pensionistas,
            "outras_despesas_pessoal_terceirizacao": outras_despesas_terceirizacao,
            "despesa_com_pessoal_bruta":            despesa_bruta,
            "deducoes": {
                "decorrentes_decisao_judicial_periodo_anterior": decisao_judicial,
                "despesas_exercicios_anteriores":               exercicios_anteriores,
                "indenizacoes_demissao_incentivos":             indenizacoes_demissao,
                "inativos_pensionistas_recursos_vinculados":    inativos_recursos_vinc,
                "agentes_comunitarios_saude_endemias":          agentes_comunitarios,
                "parcela_dedutivel_piso_enfermeiro":            piso_enfermeiro,
                "subtotal_deducoes":                            subtotal_deducoes,
            },
            "despesa_liquida_pessoal_restos_pagar": despesa_liquida_restos_pagar,
            "despesa_liquida_com_pessoal":          despesa_liquida,
            "base_calculo_rcl":                     rcl,
            "percentual_aplicacao_despesa_pessoal": percentual,
        },
    }
