import logging
import re

import fitz
import pdfplumber

from backend.extractors._texto import sem_acento

logger = logging.getLogger(__name__)

NUMERO_RE = re.compile(r'-?\d{1,3}(?:\.\d{3})*,\d{2}')


def _parse(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _fmt(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _extrair_cabecalho(pdf_path: str) -> tuple[str, str]:
    doc = fitz.open(pdf_path)
    text = doc[0].get_text("text").upper()
    doc.close()
    m_mun = re.search(r"PREFEITURA MUNICIPAL DE (.+)", text)
    m_ano = re.search(r"EXERC[IÍ]CIO[^\d]*(\d{4})", text)
    municipio = m_mun.group(1).strip() if m_mun else ""
    exercicio = m_ano.group(1) if m_ano else ""
    return municipio, exercicio


def _linhas_metade(pdf_path: str, lado: str) -> list[str]:
    """Extrai linhas da metade esquerda (INGRESSOS) ou direita (DISPÊNDIOS) — todas as páginas."""
    linhas = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            mid = page.width / 2
            region = page.crop((0, 0, mid, page.height) if lado == "esquerda" else (mid, 0, page.width, page.height))
            text = region.extract_text() or ""
            linhas.extend(text.splitlines())
    return linhas


def _parse_itens(linhas: list[str]) -> list[dict]:
    """Extrai todos os itens com valores de uma lista de linhas."""
    itens = []
    for line in linhas:
        nums = NUMERO_RE.findall(line)
        if not nums:
            continue
        desc = NUMERO_RE.sub("", line)
        # Remove apenas marcador de nota F ou P no FINAL da linha (não remove P/O, etc.)
        desc = re.sub(r'\s+[FP]\s*$', '', desc)
        desc = re.sub(r'\s+', ' ', desc).strip()
        if len(desc) < 3:
            continue
        itens.append({
            "descricao": desc,
            "atual":     _parse(nums[0]),
            "anterior":  _parse(nums[1]) if len(nums) > 1 else 0.0,
        })
    return itens


def _row(linhas: list[str], *termos: str, idx_a: int = 0, idx_ant: int = 1) -> dict:
    """Retorna {atual, anterior} da primeira linha COM NÚMEROS que contém todos os termos."""
    termos_up = [sem_acento(t.upper()) for t in termos]
    for line in linhas:
        upper = sem_acento(line.upper())
        if all(t in upper for t in termos_up):
            nums = NUMERO_RE.findall(line)
            if not nums:
                continue
            return {
                "atual":    _parse(nums[idx_a])  if len(nums) > idx_a  else 0.0,
                "anterior": _parse(nums[idx_ant]) if len(nums) > idx_ant else 0.0,
            }
    return {"atual": 0.0, "anterior": 0.0}


def extrair(pdf_path: str) -> dict:
    municipio, exercicio = _extrair_cabecalho(pdf_path)
    ing = _linhas_metade(pdf_path, "esquerda")
    dis = _linhas_metade(pdf_path, "direita")

    dados = {
        "municipio": municipio,
        "exercicio": exercicio,

        # ── INGRESSOS ──
        "ingressos": {
            # Receita Orçamentária
            "receita_orcamentaria":                  _row(ing, "RECEITA OR"),
            "rec_nao_vinculados":                    _row(ing, "RECURSOS N"),
            # "EXCETO AO RPPS" é único para RECURSOS VINCULADOS; "EXCETO RPPS" é para CAIXA
            "rec_vinculados_exceto_rpps":            _row(ing, "EXCETO AO RPPS"),
            "rec_vinculados_educacao":               _row(ing, "EDUCA"),
            # "SAUDE" sem acento não bate Ú; usa fragmento único em português
            "rec_vinculados_saude":                  _row(ing, "VINCUL", "SA"),
            "rec_vinculados_assist_social":          _row(ing, "SOCIAL"),
            "demais_vinculacoes_transferencias":     _row(ing, "DEMAIS VINCUL"),
            "outras_vinculacoes":                    _row(ing, "OUTRAS VINCUL"),

            # Transferências Financeiras Recebidas
            "transferencias_financeiras_recebidas":  _row(ing, "FINANCEIRAS RECEBIDAS"),
            "transf_recebidas_exec_orc":             _row(ing, "RECEBIDAS PARA"),
            "repasse_recebido":                      _row(ing, "REPASSE RECEBIDO"),
            "transf_recebidas_indep":                _row(ing, "RECEBIDAS INDEPENDENTES"),
            # multi-linha no PDF — mesmo valor que transf_recebidas_indep (234,36)

            # Recebimentos Extra-Orçamentários
            "recebimentos_extra_orcamentarios":      _row(ing, "RECEBIMENTOS EXTRA"),
            "inscricao_restos_pagar":                _row(ing, "RESTOS A PAGAR"),
            "rp_nao_processados":                    _row(ing, "RP N"),
            "rp_processados":                        _row(ing, "RP PROCESSADOS"),
            # "RESTITU" bate "RESTITUÍVEIS" sem problema de acento no Ó de DEPÓSITOS
            "depositos_restituiveis_recebimentos":   _row(ing, "RESTITU"),
            "outras_consignacoes":                   _row(ing, "OUTRAS CONSIG"),
            "outros_recebimentos_extra":             _row(ing, "OUTROS RECEBIMENTOS"),
            # VALORES EM TRÂNSITO: "NSITO" está em TRÂNSITO sem precisar do Â
            "valores_transito_recebimentos":         _row(ing, "NSITO"),

            # Saldos do Exercício Anterior
            "saldos_exercicio_anterior":             _row(ing, "SALDOS DO EXERC"),
            # "EXCETO RPPS" (sem "AO") identifica CAIXA E EQUIVALENTE ... (EXCETO RPPS)
            "caixa_equiv_exceto_rpps_anterior":      _row(ing, "EXCETO RPPS"),
            # "CAIXA (RPPS)" identifica CAIXA E EQUIVALENTE DE CAIXA (RPPS)
            "caixa_equiv_rpps_anterior":             _row(ing, "CAIXA (RPPS)"),
            "depositos_restituiveis_saldo_anterior": _row(ing, "DEPOSITOS RESTITU", "0,00"),

            "total":                                 _row(ing, "TOTAL"),
        },

        # ── DISPÊNDIOS ──
        "dispendios": {
            # Despesa Orçamentária
            "despesa_orcamentaria":                  _row(dis, "DESPESA OR"),
            "rec_nao_vinculados":                    _row(dis, "RECURSOS N"),
            "rec_vinculados_exceto_rpps":            _row(dis, "EXCETO AO RPPS"),
            "rec_vinculados_educacao":               _row(dis, "EDUCA"),
            "rec_vinculados_saude":                  _row(dis, "VINCUL", "SA"),
            "rec_vinculados_assist_social":          _row(dis, "SOCIAL"),
            "demais_vinculacoes_transferencias":     _row(dis, "DEMAIS VINCUL"),
            "outras_vinculacoes":                    _row(dis, "OUTRAS VINCUL"),

            # Transferências Financeiras Concedidas
            "transferencias_financeiras_concedidas": _row(dis, "FINANCEIRAS CONCEDIDAS"),
            "transf_concedidas_exec_orc":            _row(dis, "CONCEDIDAS PARA"),
            "repasse_concedido":                     _row(dis, "REPASSE CONCEDIDO"),
            "transf_concedidas_indep":               _row(dis, "CONCEDIDAS - INDEPENDENTES"),
            "movimento_fundos":                      _row(dis, "MOVIMENTO DE FUNDOS"),

            # Pagamentos Extra-Orçamentários
            "pagamentos_extra_orcamentarios":        _row(dis, "PAGAMENTOS EXTRA"),
            "depositos_restituiveis_pagamentos":     _row(dis, "RESTITU"),
            "outras_consignacoes":                   _row(dis, "OUTRAS CONSIG"),
            "outros_pagamentos_extra":               _row(dis, "OUTROS PAGAMENTOS"),
            "valores_transito_pagamentos":           _row(dis, "NSITO"),

            # Saldos p/o Exercício Seguinte
            "saldos_exercicio_seguinte":             _row(dis, "SALDOS P"),
            "caixa_equiv_exceto_rpps_seguinte":      _row(dis, "EXCETO RPPS"),
            "caixa_equiv_rpps_seguinte":             _row(dis, "CAIXA (RPPS)"),

            "total":                                 _row(dis, "TOTAL"),
        },

        # Listas completas de todos os itens (para preview e auditoria detalhada)
        "_itens_ingressos":  _parse_itens(ing),
        "_itens_dispendios": _parse_itens(dis),
    }

    logger.info(
        "ANX13 BF: receita=%.2f despesa=%.2f saldo_ant=%.2f saldo_seg=%.2f total=%.2f",
        dados["ingressos"]["receita_orcamentaria"]["atual"],
        dados["dispendios"]["despesa_orcamentaria"]["atual"],
        dados["ingressos"]["saldos_exercicio_anterior"]["atual"],
        dados["dispendios"]["saldos_exercicio_seguinte"]["atual"],
        dados["ingressos"]["total"]["atual"],
    )
    return dados


def _valor_apos_secao(linhas: list[str], marcador: str, *termos: str) -> float:
    """Primeiro valor NÃO ZERO dos termos encontrado APÓS uma linha que contém o marcador."""
    termos_up = [sem_acento(t.upper()) for t in termos]
    dentro = False
    for line in linhas:
        u = sem_acento(line.upper())
        if sem_acento(marcador.upper()) in u:
            dentro = True
            continue
        if dentro and all(t in u for t in termos_up):
            for n in NUMERO_RE.findall(line):
                v = _parse(n)
                if v != 0.0:
                    return v
    return 0.0


def extrair_q16(pdf_path: str) -> dict:
    """
    Extrai os dados de Depósitos Restituíveis e Valores Vinculados do BF
    necessários para o Quadro 16 (Análise BF vs BP).
    """
    municipio, exercicio = _extrair_cabecalho(pdf_path)
    ing = _linhas_metade(pdf_path, "esquerda")
    dis = _linhas_metade(pdf_path, "direita")

    # A: total recebido de Depósitos Restituíveis (INGRESSOS)
    recebimentos = _row(ing, "RESTITU")["atual"]

    # B: total pago de Depósitos Restituíveis (DISPÊNDIOS, antes da seção SALDOS)
    pagamentos = 0.0
    for line in dis:
        if "SALDOS P" in line.upper() and "EXERC" in line.upper():
            break
        if "RESTITU" in line.upper() and "VALORES VINCULADOS" in line.upper():
            nums = NUMERO_RE.findall(line)
            if nums:
                v = _parse(nums[0])
                if v > 0:
                    pagamentos = v
                    break

    saldo_c_bf = round(recebimentos - pagamentos, 2)

    # D: Depósitos Restituíveis nos Saldos p/ Exercício Seguinte
    depositos_saldo_seguinte = _valor_apos_secao(
        dis, "SALDOS P", "RESTITU", "VALORES VINCULADOS"
    )

    saldo_e_bf = round(saldo_c_bf - depositos_saldo_seguinte, 2)

    logger.info(
        "ANX13 Q16: receb=%.2f pag=%.2f saldo_c=%.2f saldo_seg=%.2f saldo_e=%.2f",
        recebimentos, pagamentos, saldo_c_bf, depositos_saldo_seguinte, saldo_e_bf,
    )
    return {
        "municipio":   municipio,
        "exercicio":   exercicio,
        "recebimentos_depositos_bf":               recebimentos,
        "pagamentos_depositos_bf":                 pagamentos,
        "saldo_c_bf":                              saldo_c_bf,
        "depositos_restituiveis_saldo_seguinte_bf": depositos_saldo_seguinte,
        "saldo_e_bf":                              saldo_e_bf,
    }


def formatar_texto(pdf_path: str) -> str:
    municipio, exercicio = _extrair_cabecalho(pdf_path)
    d = extrair(pdf_path)

    SEP = "-" * 79
    W = 52

    def linha(desc, atual, anterior):
        return f"{desc[:W]:<{W}} {_fmt(atual):>12} {_fmt(anterior):>12}"

    def cabecalho_secao(titulo):
        return ["", titulo, SEP, f"{'ESPECIFICAÇÃO':<{W}} {'ATUAL':>12} {'ANTERIOR':>12}", SEP]

    out = [
        "ANEXO 13 — BALANÇO FINANCEIRO (MCASP)",
        f"MUNICÍPIO: {municipio} | EXERCÍCIO: {exercicio}",
    ]

    out += cabecalho_secao("INGRESSOS")
    for item in d["_itens_ingressos"]:
        out.append(linha(item["descricao"], item["atual"], item["anterior"]))

    out += cabecalho_secao("DISPÊNDIOS")
    for item in d["_itens_dispendios"]:
        out.append(linha(item["descricao"], item["atual"], item["anterior"]))

    out.append(SEP)
    return "\n".join(out)
