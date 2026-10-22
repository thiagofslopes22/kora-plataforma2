"""Constrói o contexto para o template Mustache RIT_TEMPLATE.html (chevron).

Fontes de dados:
  resultado      — dict com quadros extraídos dos PDFs (quadro_01 … quadro_27)
  dados_manuais  — dict com campos preenchidos pelo usuário na aba "Dados Manuais"
  ocorrencias    — dict retornado por gerar_ocorrencias_rit() (seção 6.2)
  municipio      — nome extraído dos PDFs (pode ser sobrescrito pelo manual)
  exercicio      — ano do exercício

Convenções do novo template:
  - Valores monetários SEM prefixo "R$" (o template já inclui "R$ " antes) → _num()
  - Percentuais em formato brasileiro com "%" (ex.: 52,75%) → _pctbr()
  - Ocorrências: listas de dicts por dimensão (seções Mustache {{#...}})
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import chevron

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"

# ── Helpers de formatação ─────────────────────────────────────────────────────

def _g(d: dict | None, *keys, default=None):
    """Navega dict aninhado com segurança. Suporta múltiplos níveis."""
    v = d
    for k in keys:
        if not isinstance(v, dict):
            return default
        v = v.get(k)
    return v if v is not None else default


def _num(v, default="0,00") -> str:
    """Valor monetário SEM prefixo 'R$' (o template já inclui). Formato brasileiro."""
    if v is None:
        return default
    try:
        n = float(v)
        s = f"{abs(n):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{'- ' if n < 0 else ''}{s}"
    except (TypeError, ValueError):
        return str(v)


def _pctbr(v, mult: float = 1.0, casas: int = 2, default="N/D") -> str:
    """Percentual em formato brasileiro com vírgula e '%'. Ex.: 52,75%"""
    if v is None:
        return default
    try:
        return f"{float(v) * mult:.{casas}f}".replace(".", ",") + "%"
    except (TypeError, ValueError):
        return str(v)


def _manual(dados_manuais: dict, chave: str, default: str = "") -> str:
    """Lê campo manual com fallback seguro."""
    v = dados_manuais.get(chave)
    if v is None:
        return default
    return str(v).strip() or default


def _manual_num(dados_manuais: dict, chave: str) -> float | None:
    """Lê campo manual numérico (aceita '50000000.00' ou 'R$ 50.000.000,00')."""
    v = dados_manuais.get(chave)
    if v is None:
        return None
    s = str(v).strip().replace("R$", "").strip()
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


# ── Construção do contexto ────────────────────────────────────────────────────

def build_context(
    resultado: dict,
    dados_manuais: dict,
    ocorrencias: dict,
    municipio: str,
    exercicio: str,
) -> dict:
    """Retorna o dict de variáveis para renderizar o template Mustache RIT."""

    m = lambda k, d="": _manual(dados_manuais, k, d)
    ctx: dict = {}

    # ── Identificação do ente ─────────────────────────────────────────────────
    mun_title = (municipio or m("municipio_nome")).title()
    uf = m("municipio_uf", "MA")
    ctx["municipio"]             = mun_title
    ctx["municipio_uf"]          = f"{mun_title}/{uf}" if mun_title else ""
    ctx["municipio_uf_maiusculo"] = f"{mun_title.upper()}/{uf}" if mun_title else ""
    ctx["exercicio"]             = str(exercicio or m("exercicio_ano"))
    ctx["exercicio_anterior"]    = str(int(ctx["exercicio"]) - 1) if ctx["exercicio"].isdigit() else ""

    # ── Metadados do processo ─────────────────────────────────────────────────
    ctx["processo_numero"]          = m("processo_numero")
    ctx["processo_numero_compacto"] = m("processo_numero")
    ctx["natureza"]                 = m("natureza", "Prestação de Contas Anual de Governo")
    ctx["responsavel"]              = m("responsavel_nome")
    ctx["cpf"]                      = m("responsavel_cpf")
    ctx["relator"]                  = m("relator_nome")
    ctx["relatorio_numero"]         = m("rit_numero")
    ctx["assinatura"]               = m("assinatura")

    # ── Perfil socioeconômico (manuais) ───────────────────────────────────────
    ctx["populacao"]         = m("populacao_estimada")
    ctx["area_territorial"]  = m("area_territorial")
    ctx["pib_per_capita"]    = m("pib_per_capita")
    ctx["idh"]               = m("idh")
    ctx["idh_extenso"]       = m("idh")
    ctx["idh_faixa"]         = m("classificacao_idh")
    ctx["ideb_nota"]         = m("ideb")
    ctx["ideb_nota_extenso"] = m("ideb")
    ctx["ideb_desempenho"]   = m("classificacao_ideb")
    ctx["transparencia_faixa"] = m("transp_faixa")

    # ── Quadro 1 — Base de Cálculo Repasse à Câmara ──────────────────────────
    q1 = resultado.get("quadro_01", {})
    rt = q1.get("receita_tributaria", {})
    te = q1.get("transferencias_estado", {})
    tu = q1.get("transferencias_uniao", {})
    tot1 = q1.get("totais", {})
    ctx["q1_receita_tributaria"]     = _num(_g(rt, "subtotal"))
    ctx["q1_iptu"]                   = _num(_g(rt, "iptu"))
    ctx["q1_iss"]                    = _num(_g(rt, "iss"))
    ctx["q1_itbi"]                   = _num(_g(rt, "itbi"))
    ctx["q1_irrf"]                   = _num(_g(rt, "irrf"))
    ctx["q1_taxas"]                  = _num(_g(rt, "taxas"))
    ctx["q1_contribuicoes_melhorias"] = _num(_g(rt, "contribuicoes_melhorias"))
    ctx["q1_divida_ativa"]           = _num(_g(rt, "divida_ativa_tributaria"))
    ctx["q1_multas_juros"]           = _num(_g(rt, "multas_juros_tributos"))
    ctx["q1_iluminacao_publica"]     = _num(_g(rt, "cosip"))
    ctx["q1_transf_estado"]          = _num(_g(te, "subtotal"))
    ctx["q1_cp_ipva"]                = _num(_g(te, "ipva"))
    ctx["q1_cp_icms"]                = _num(_g(te, "icms"))
    ctx["q1_icms_desoneracao"]       = _num(_g(te, "icms_desoneracao"))
    ctx["q1_transf_uniao"]           = _num(_g(tu, "subtotal"))
    ctx["q1_cide"]                   = _num(_g(te, "cide"))
    ctx["q1_cp_itr"]                 = _num(_g(tu, "itr"))
    ctx["q1_cp_fpm"]                 = _num(_g(tu, "fpm_total"))
    ctx["q1_cp_ipi"]                 = _num(_g(te, "ipi"))
    ctx["q1_total_contrib_fundeb"]   = _num(_g(q1, "contribuicao_fundeb"))
    ctx["q1_contrib_fundeb"]         = _num(_g(q1, "contribuicao_fundeb"))
    ctx["q1_total_base_calculo"]     = _num(_g(tot1, "base_calculo"))
    # Texto da Câmara
    ctx["camara_percentual_maximo"]  = _pctbr(_g(tot1, "percentual_aplicado"))
    ctx["camara_base_calculo"]       = _num(_g(tot1, "base_calculo"))
    ctx["camara_limite_repasse"]     = _num(_g(tot1, "limite_anual"))
    ctx["camara_valor_repassado"]    = m("camara_repassado")
    ctx["camara_percentual_apurado"] = m("camara_pct_apurado")
    ctx["camara_duodecimo_situacao"] = m("camara_prazo", "cumpriu")

    # ── Quadro 3 — Resultado Orçamentário ────────────────────────────────────
    q3 = resultado.get("quadro_03", {})
    ro = q3.get("resultado_orcamentario", {})
    res_val = _g(ro, "resultado", default=0.0)
    ctx["resultado_orcamentario_situacao"] = _g(ro, "situacao", default="N/D")
    ctx["resultado_execucao_texto"] = "superávit" if (res_val or 0) >= 0 else "déficit"

    # ── Quadro 8 — Balanço Orçamentário Receitas ─────────────────────────────
    q8 = resultado.get("quadro_08", {})
    def _q8(grupo, pre):
        g = q8.get(grupo, {}) if isinstance(q8.get(grupo), dict) else {}
        ctx[f"q8_{pre}_a"] = _num(_g(g, "prevista_inicial_a"))
        ctx[f"q8_{pre}_b"] = _num(_g(g, "prevista_atualizada_b"))
        ctx[f"q8_{pre}_c"] = _num(_g(g, "realizada_c"))
        ctx[f"q8_{pre}_d"] = _num(_g(g, "saldo_d"))
    _q8("receitas_correntes", "correntes")
    _q8("receitas_capital", "capital")
    _q8("subtotal_receitas", "subtotal")
    _q8("operacoes_credito_refinanciamento", "operacoes")
    _q8("subtotal_com_refinanciamento", "subtotal_refin")
    _q8("deficit", "deficit")
    _q8("total", "total")
    _q8("saldos_exercicios_anteriores", "saldos_ant")
    _q8("recursos_arrecadados_exercicios_anteriores", "recursos_ant")
    _q8("superavit_financeiro", "superavit")
    _q8("reabertura_creditos_adicionais", "reabertura")
    total_q8 = q8.get("total", {})
    ctx["receita_realizada"]  = _num(_g(total_q8, "realizada_c"))
    ctx["receita_arrecadada"] = _num(_g(total_q8, "realizada_c"))
    ctx["orcamento_atualizado_de"]   = _num(_g(total_q8, "prevista_inicial_a"))
    ctx["orcamento_atualizado_para"] = _num(_g(total_q8, "prevista_atualizada_b"))
    ctx["loa_receita_prevista"]   = _num(_g(total_q8, "prevista_inicial_a"))
    ctx["loa_receita_atualizada"] = _num(_g(total_q8, "prevista_atualizada_b"))

    # ── Quadro 9 — Balanço Orçamentário Despesas ─────────────────────────────
    q9 = resultado.get("quadro_09", {})
    def _q9(grupo, pre):
        g = q9.get(grupo, {}) if isinstance(q9.get(grupo), dict) else {}
        ctx[f"q9_{pre}_d"] = _num(_g(g, "dotacao_inicial_d"))
        ctx[f"q9_{pre}_e"] = _num(_g(g, "dotacao_atualizada_e"))
        ctx[f"q9_{pre}_f"] = _num(_g(g, "empenhada_f"))
        ctx[f"q9_{pre}_g"] = _num(_g(g, "liquidada_g"))
        ctx[f"q9_{pre}_h"] = _num(_g(g, "paga_h"))
        ctx[f"q9_{pre}_i"] = _num(_g(g, "saldo_dotacao_i"))
    _q9("despesas_correntes", "correntes")
    _q9("despesas_capital", "capital")
    _q9("reserva_contingencia", "reserva")
    _q9("subtotal_despesas", "subtotal")
    _q9("amortizacao_divida_refinanciamento", "amortizacao")
    _q9("subtotal_com_refinanciamento", "subtotal_refin")
    _q9("superavit", "superavit")
    _q9("total", "total")
    _q9("reserva_rpps", "rpps")
    total_q9 = q9.get("total", {})
    # A linha TOTAL do Balanço Orçamentário soma o superávit como lançamento de
    # equilíbrio na coluna "empenhada", inflando o total (ex.: Presidente Dutra
    # 2024 → 240.903.283,17 em vez de 229.432.882,36). A despesa real é o
    # "subtotal com refinanciamento" (inclui amortização de refinanciamento,
    # exclui o superávit de equilíbrio); a empenhada autoritativa é a do
    # Resultado Orçamentário (Quadro 3).
    desp_q9 = q9.get("subtotal_com_refinanciamento") or q9.get("subtotal_despesas") or total_q9
    if not isinstance(desp_q9, dict):
        desp_q9 = total_q9
    emp_empenhada = _g(resultado, "quadro_03", "resultado_orcamentario", "despesa_empenhada")
    if emp_empenhada is None:
        emp_empenhada = _g(desp_q9, "empenhada_f")
    ctx["despesa_empenhada"]     = _num(emp_empenhada)
    ctx["despesa_paga"]          = _num(_g(desp_q9, "paga_h"))
    ctx["loa_dotacao_inicial"]   = _num(_g(desp_q9, "dotacao_inicial_d"))
    # A linha TOTAL da tabela detalhada do Q9 herda a mesma inflação do superávit
    # na coluna empenhada — corrige para a despesa empenhada real.
    ctx["q9_total_f"]            = _num(emp_empenhada)

    # ── Quadro 4 — RCL ────────────────────────────────────────────────────────
    q4 = resultado.get("quadro_04", {})
    rcl = q4.get("receita_corrente_liquida", {})
    ded4 = rcl.get("deducoes", {}) if isinstance(rcl.get("deducoes"), dict) else {}
    ctx["rcl_valor"]                = _num(_g(rcl, "receita_corrente_liquida_declarada"))
    ctx["q4_receita_tributaria"]    = _num(_g(rcl, "receita_tributaria", "subtotal"))
    ctx["q4_receita_contribuicoes"] = _num(_g(rcl, "receita_contribuicoes", "subtotal"))
    ctx["q4_receita_patrimonial"]   = _num(_g(rcl, "receita_patrimonial", "subtotal"))
    ctx["q4_receita_agropecuaria"]  = _num(_g(rcl, "receita_agropecuaria", "subtotal"))
    ctx["q4_receita_industrial"]    = _num(_g(rcl, "receita_industrial", "subtotal"))
    ctx["q4_receita_servicos"]      = _num(_g(rcl, "receita_servicos", "subtotal"))
    ctx["q4_transferencias_correntes"] = _num(_g(rcl, "transferencias_correntes", "subtotal"))
    ctx["q4_outras_receitas"]       = _num(_g(rcl, "outras_receitas_correntes", "subtotal"))
    ctx["q4_receita_corrente"]      = _num(_g(rcl, "total_receita_corrente"))
    ctx["q4_ded_contrib_servidor"]  = _num(_g(ded4, "contrib_servidor_previdencia"))
    ctx["q4_ded_compensacao"]       = _num(_g(ded4, "compensacao_financ_regimes_previdencia"))
    ctx["q4_ded_fundeb"]            = _num(_g(ded4, "deducao_formacao_fundeb"))
    ctx["q4_ded_emendas_individuais"] = _num(_g(ded4, "transferencias_obrigatorias_uniao_166a_artigo51"))
    ctx["q4_ded_emendas_bancada"]   = _num(_g(ded4, "transferencias_obrigatorias_uniao_166_artigo166"))
    ctx["q4_ded_rendimentos_prev"]  = _num(_g(ded4, "rendimentos_aplicacoes_recursos_previdenciarios"))
    ctx["q4_ded_agentes_saude"]     = _num(_g(ded4, "transferencias_uniao_remuneracao_agentes_saude_endemias"))

    # ── Quadro 5 — Despesa com Pessoal ───────────────────────────────────────
    q5 = resultado.get("quadro_05", {})
    dp = q5.get("despesa_com_pessoal", {})
    ded5 = dp.get("deducoes", {}) if isinstance(dp.get("deducoes"), dict) else {}
    dp_raw = _g(dp, "percentual_aplicacao_despesa_pessoal", default=None)
    dp_pct = float(dp_raw) * 100 if dp_raw is not None else None
    ctx["despesa_pessoal_liquida"]  = _num(_g(dp, "despesa_liquida_com_pessoal"))
    ctx["pessoal_percentual_rcl"]   = _pctbr(dp_pct) if dp_pct is not None else "N/D"
    ctx["pessoal_situacao_limite"]  = "abaixo" if (dp_pct or 0) <= 54 else "acima"
    ctx["pessoal_situacao_prudencial"] = "abaixo" if (dp_pct or 0) < 51.3 else "acima"
    ctx["q5_pessoal_ativo"]         = _num(_g(dp, "pessoal_ativo"))
    ctx["q5_pessoal_inativo"]       = _num(_g(dp, "pessoal_inativo_pensionistas"))
    ctx["q5_terceirizacao"]         = _num(_g(dp, "outras_despesas_pessoal_terceirizacao"))
    ctx["q5_despesa_pessoal"]       = _num(_g(dp, "despesa_com_pessoal_bruta"))
    ctx["q5_ded_indenizacoes"]      = _num(_g(ded5, "indenizacoes_demissao_incentivos"))
    ctx["q5_ded_decisao_judicial"]  = _num(_g(ded5, "decorrentes_decisao_judicial_periodo_anterior"))
    ctx["q5_ded_exercicios_anteriores"] = _num(_g(ded5, "despesas_exercicios_anteriores"))
    ctx["q5_ded_inativos_vinculados"]   = _num(_g(ded5, "inativos_pensionistas_recursos_vinculados"))
    ctx["q5_ded_agentes_saude"]     = _num(_g(ded5, "agentes_comunitarios_saude_endemias"))
    ctx["q5_ded_piso_enfermagem"]   = _num(_g(ded5, "parcela_dedutivel_piso_enfermeiro"))
    ctx["q5_despesa_liquida_rp"]    = _num(_g(dp, "despesa_liquida_pessoal_restos_pagar"))
    # Restrição de mandato / regime especial (manuais)
    ctx["pessoal_percentual_2quad"] = m("dp_pct_inicio_sem", "N/D")
    ctx["pessoal_percentual_2021"]  = m("pessoal_pct_2021", "N/D")
    ctx["restricao_mandato_situacao"] = m("dp_restricao_mandato", "não realizou")
    ctx["regime_especial_necessidade"] = m("regime_especial_necessidade", "não havendo")
    ctx["regime_especial_constatacao"] = m("regime_especial_constatacao", "Não se constatou")
    ctx["tem_regime_especial_extra"]   = False

    # ── Quadro 6 — Comportamento da Despesa com Pessoal ──────────────────────
    q6 = _g(resultado, "quadro_06", "quadro_6_despesa_pessoal", default={}) or {}
    # RGF semestral: 1ª coluna = 1º semestre. Planilhas antigas guardavam em "primeiro_semestre".
    q6_sem = (_g(resultado, "quadro_06", "periodicidade") == "semestral") or "primeiro_semestre" in q6
    ctx["q6_rotulo_periodo"] = "1º Semestre (R$)" if q6_sem else "2º Quadrimestre (R$)"
    ctx["q6_periodo_texto"]  = "até o 1º semestre" if q6_sem else "até o 2º quadrimestre"
    _q6int = q6.get("segundo_quadrimestre") or q6.get("primeiro_semestre")
    q6q2 = _q6int if isinstance(_q6int, dict) else {}
    q6an = q6.get("apurado_pelo_tce", {}) if isinstance(q6.get("apurado_pelo_tce"), dict) else {}
    ctx["q6_total_despesa_2quad"] = _num(_g(q6q2, "total_despesa"))
    ctx["q6_total_despesa_ano"]   = _num(_g(q6an, "total_despesa"))
    ctx["q6_rcl_2quad"]           = _num(_g(q6q2, "receita_corrente_liquida"))
    ctx["q6_limite_2quad"]        = _num(_g(q6q2, "limite_legal_54_pct"))
    ctx["q6_limite_ano"]          = _num(_g(q6an, "limite_legal_54_pct"))
    _p6q2 = _g(q6q2, "percentual_apurado")
    if ctx["pessoal_percentual_2quad"] in ("", "N/D") and _p6q2 is not None:
        ctx["pessoal_percentual_2quad"] = _pctbr(_p6q2 * 100)

    # ── Quadro 7 — Dívida Consolidada ────────────────────────────────────────
    q7 = dict(resultado.get("quadro_07", {}) or {})
    # Planilhas antigas (RGF semestral) guardavam "ate_1_semestre"/"ate_2_semestre"
    if "ate_1_semestre" in q7 and "ate_2_quadrimestre" not in q7:
        q7["ate_2_quadrimestre"] = q7.get("ate_1_semestre")
        q7["ate_3_quadrimestre"] = q7.get("ate_2_semestre")
        q7.setdefault("periodicidade", "semestral")
    _rot7 = q7.get("rotulos") if isinstance(q7.get("rotulos"), dict) else (
        {"col_1": "—", "col_2": "Até o 1º Semestre", "col_3": "Até o 2º Semestre"}
        if q7.get("periodicidade") == "semestral" else
        {"col_1": "Até o 1º Quadrimestre", "col_2": "Até o 2º Quadrimestre", "col_3": "Até o 3º Quadrimestre"})
    ctx["q7_rotulo_1"], ctx["q7_rotulo_2"], ctx["q7_rotulo_3"] = _rot7["col_1"], _rot7["col_2"], _rot7["col_3"]
    for suf, chave in (("anterior", "saldo_exercicio_anterior"),
                       ("1quad", "ate_1_quadrimestre"),
                       ("2quad", "ate_2_quadrimestre"),
                       ("3quad", "ate_3_quadrimestre")):
        p = q7.get(chave, {}) if isinstance(q7.get(chave), dict) else {}
        ctx[f"q7_dc_{suf}"]          = _num(_g(p, "divida_consolidada_dc"))
        ctx[f"q7_mobiliaria_{suf}"]  = _num(_g(p, "divida_mobiliaria"))
        ctx[f"q7_contratual_{suf}"]  = _num(_g(p, "divida_contratual"))
        ctx[f"q7_precatorios_{suf}"] = _num(_g(p, "precatorios_posteriores_05052000"))
        ctx[f"q7_outras_{suf}"]      = _num(_g(p, "outras_dividas"))
        ctx[f"q7_deducoes_{suf}"]    = _num(_g(p, "deducoes_total"))
        ctx[f"q7_disp_caixa_{suf}"]  = _num(_g(p, "disponibilidade_caixa_bruta"))
        ctx[f"q7_disp_bruta_{suf}"]  = _num(_g(p, "disponibilidade_caixa_bruta"))
        ctx[f"q7_rp_proc_{suf}"]     = _num(_g(p, "restos_pagar_processados_exceto_precatorios"))
        ctx[f"q7_haveres_{suf}"]     = _num(_g(p, "demais_haveres_financeiros"))
        ctx[f"q7_dcl_{suf}"]         = _num(_g(p, "divida_consolidada_liquida_dcl"))
        ctx[f"q7_rcl_{suf}"]         = _num(_g(p, "receita_corrente_liquida"))
        ctx[f"q7_transf_emendas_{suf}"] = _num(_g(p, "transferencias_emendas_individuais"))
        ctx[f"q7_rcl_ajustada_{suf}"]   = _num(_g(p, "rcl_ajustada_endividamento"))
        ctx[f"q7_perc_dc_{suf}"]     = _pctbr(_g(p, "percentual_dc_sobre_rcl"))
        ctx[f"q7_perc_dcl_{suf}"]    = _pctbr(_g(p, "percentual_dcl_sobre_rcl"))
        ctx[f"q7_limite_senado_{suf}"] = _num(_g(p, "limite_resolucao_senado"))
        ctx[f"q7_limite_alerta_{suf}"] = _num(_g(p, "limite_alerta"))

    # ── Quadro 10 — Arrecadação ──────────────────────────────────────────────
    q10 = resultado.get("quadro_10", {})
    ctx["q10_receita_realizada"]  = _num(_g(q10, "receita_tributaria_realizada"))
    ctx["q10_receita_atualizada"] = _num(_g(q10, "receita_tributaria_atualizada"))
    ctx["gestao_receitas_situacao"] = str(_g(q10, "situacao", default="N/D")).lower()

    # ── Quadro 11 — Comparativo LOA × BO ─────────────────────────────────────
    q11 = resultado.get("quadro_11", {})
    bo_rec = _g(q11, "receita_prevista_bo")
    bo_dot = _g(q11, "dotacao_inicial_bo")
    loa_rec = _g(q11, "receita_prevista_loa")
    if loa_rec is None:
        loa_rec = _manual_num(dados_manuais, "q11_loa_receita")
    if loa_rec is None:
        loa_rec = bo_rec
    loa_dot = _g(q11, "dotacao_inicial_loa")
    if loa_dot is None:
        loa_dot = _manual_num(dados_manuais, "q11_loa_despesa")
    if loa_dot is None:
        loa_dot = bo_dot

    def _sit11(loa, bo):
        if loa is None or bo is None:
            return "N/D"
        return "Conformidade" if abs(loa - bo) < 1.0 else "Divergência"

    ctx["q11_receita_loa"]      = _num(loa_rec)
    ctx["q11_receita_bo"]       = _num(bo_rec)
    ctx["q11_receita_situacao"] = _sit11(loa_rec, bo_rec)
    ctx["q11_dotacao_loa"]      = _num(loa_dot)
    ctx["q11_dotacao_bo"]       = _num(bo_dot)
    ctx["q11_dotacao_situacao"] = _sit11(loa_dot, bo_dot)
    ctx["comparativo_loa_bo_texto"] = (
        "concluiu pela conformidade entre os valores previstos na LOA e os "
        "registrados no Balanço Orçamentário."
        if ctx["q11_receita_situacao"] == "Conformidade" and ctx["q11_dotacao_situacao"] == "Conformidade"
        else "constatou divergência entre os valores previstos na LOA e os registrados no Balanço Orçamentário."
    )

    # ── Quadro 12 — Resultado Financeiro ─────────────────────────────────────
    q12 = resultado.get("quadro_12", {})
    ctx["q12_ativo_atual"]        = _num(_g(q12, "ativo_financeiro_atual"))
    ctx["q12_ativo_anterior"]     = _num(_g(q12, "ativo_financeiro_anterior"))
    ctx["q12_passivo_atual"]      = _num(_g(q12, "passivo_financeiro_atual"))
    ctx["q12_passivo_anterior"]   = _num(_g(q12, "passivo_financeiro_anterior"))
    ctx["q12_creditos_atual"]     = _num(_g(q12, "creditos_adicionais_atual"))
    ctx["q12_creditos_anterior"]  = _num(_g(q12, "creditos_adicionais_anterior"))
    ctx["q12_resultado_atual"]    = _num(_g(q12, "superavit_deficit_atual"))
    ctx["q12_resultado_anterior"] = _num(_g(q12, "superavit_deficit_anterior"))
    ctx["superavit_financeiro"]   = _num(_g(q12, "superavit_deficit_atual"))

    # ── Quadro 13 — Patrimônio Líquido ───────────────────────────────────────
    q13 = resultado.get("quadro_13", {})
    ctx["q13_pl_anterior"]          = _num(_g(q13, "patrimonio_liquido_anterior"))
    ctx["patrimonio_liquido"]       = _num(_g(q13, "patrimonio_liquido_atual"))
    ctx["pl_variacao"]              = _num(_g(q13, "variacao_absoluta"))
    ctx["resultado_patrimonial"]    = _num(_g(q13, "variacao_absoluta"))
    ctx["pl_crescimento_percentual"] = _pctbr(_g(q13, "variacao_percentual"))

    # ── Quadro 14 — Fluxo de Caixa ───────────────────────────────────────────
    q14 = resultado.get("quadro_14", {})
    ctx["fluxo_caixa_inicial"]        = _num(_g(q14, "caixa_inicial_atual"))
    ctx["fluxo_caixa_final"]          = _num(_g(q14, "caixa_final_atual"))
    ctx["fluxo_caixa_geracao_liquida"] = _num(_g(q14, "geracao_liquida_atual"))
    ctx["q14_inicial_anterior"]       = _num(_g(q14, "caixa_inicial_anterior"))
    ctx["q14_final_anterior"]         = _num(_g(q14, "caixa_final_anterior"))
    ctx["q14_geracao_anterior"]       = _num(_g(q14, "geracao_liquida_anterior"))
    ctx["saldo_caixa_final"]          = _num(_g(q14, "caixa_final_atual"))
    ctx["saldo_caixa_dfc"]            = _num(_g(q14, "caixa_final_atual"))
    ctx["saldo_caixa_confere_dfc"]    = "confere"
    ctx["variacao_disponibilidades_bp"]  = _num(_g(q14, "geracao_liquida_atual"))
    ctx["variacao_disponibilidades_dfc"] = _num(_g(q14, "geracao_liquida_atual"))
    ctx["variacao_disponibilidades_situacao"] = "confere"

    # ── Quadro 15 — Suficiência de Caixa ─────────────────────────────────────
    q15 = resultado.get("quadro_15", {})
    ctx["q15_disp_bruta"]         = _num(_g(q15, "disponibilidade_caixa_bruta"))
    ctx["q15_depositos"]          = _num(_g(q15, "depositos_consignacoes"))
    ctx["q15_outras_obrigacoes"]  = _num(_g(q15, "outras_obrigacoes"))
    ctx["q15_disp_liquida"]       = _num(_g(q15, "disponibilidade_caixa_liquida"))
    ctx["q15_rp_anteriores"]      = _num(_g(q15, "rp_exercicios_anteriores"))
    ctx["q15_rp_processados"]     = _num(_g(q15, "rp_processados_inscritos"))
    ctx["q15_rp_nao_processados"] = _num(_g(q15, "rp_nao_processados_inscritos"))
    ctx["q15_total_rp_nao_pago"]  = _num(_g(q15, "total_rp_nao_pago"))
    ctx["q15_rp_pago"]            = _num(_g(q15, "rp_pago"))
    ctx["q15_rp_cancelados"]      = _num(_g(q15, "rp_cancelado"))
    ctx["q15_rp_baixados"]        = _num(_g(q15, "rp_baixado"))
    ctx["q15_total_rp"]           = _num(_g(q15, "total_rp"))
    ctx["q15_saldo"]              = _num(_g(q15, "saldo"))
    ctx["restos_a_pagar"]         = _num(_g(q15, "total_rp_nao_pago"))
    ctx["rp_disponibilidade_caixa"] = _num(_g(q15, "saldo"))
    _saldo15 = _g(q15, "saldo", default=0.0)
    ctx["rp_suficiencia"]         = "suficiente" if (_saldo15 or 0) >= 0 else "insuficiente"

    # ── Quadro 16 — Depósitos Restituíveis ───────────────────────────────────
    q16 = resultado.get("quadro_16", {})
    ctx["q16_recebimentos_bf"] = _num(_g(q16, "recebimentos_depositos_bf"))
    ctx["q16_pagamentos_bf"]   = _num(_g(q16, "pagamentos_depositos_bf"))
    ctx["q16_saldo_c"]         = _num(_g(q16, "saldo_c_bf"))
    ctx["q16_recebimentos_bp"] = _num(_g(q16, "saldo_c_bp"))
    ctx["q16_saldo_e"]         = _num(_g(q16, "diferenca"))
    ctx["depositos_saldo_bf"]  = _num(_g(q16, "saldo_c_bf"))
    ctx["depositos_saldo_seguinte"] = _num(_g(q16, "depositos_restituiveis_saldo_seguinte_bf"))
    ctx["depositos_saldo_devido"]   = _num(_g(q16, "saldo_c_bf"))
    ctx["tem_depositos_inconsistencia"] = False
    ctx["tem_depositos_info_complementar"] = False
    ctx["depositos_info_complementar_texto"] = ""

    # ── Quadro 17 — Base de Cálculo Saúde ────────────────────────────────────
    q17 = resultado.get("quadro_17", {})
    ctx["q17_receita_impostos"] = _num(_g(q17, "total_impostos"))
    ctx["q17_iptu"]             = _num(_g(q17, "iptu"))
    ctx["q17_iptu_encargos"]    = _num(0.0)
    ctx["q17_itbi"]             = _num(_g(q17, "itbi"))
    ctx["q17_itbi_encargos"]    = _num(0.0)
    ctx["q17_iss"]              = _num(_g(q17, "iss"))
    ctx["q17_iss_encargos"]     = _num(0.0)
    ctx["q17_irrf"]             = _num(_g(q17, "irrf"))
    ctx["q17_itr"]              = _num(0.0)
    ctx["q17_itr_encargos"]     = _num(0.0)
    ctx["q17_multas_impostos"]  = _num(0.0)
    ctx["q17_divida_ativa"]     = _num(0.0)
    ctx["q17_divida_ativa_encargos"] = _num(0.0)
    ctx["q17_transferencias"]   = _num(_g(q17, "total_transferencias"))
    ctx["q17_cp_fpm"]           = _num(_g(q17, "fpm_mensal"))
    ctx["q17_cp_itr"]           = _num(_g(q17, "itr"))
    ctx["q17_cp_ipva"]          = _num(_g(q17, "ipva"))
    ctx["q17_cp_icms"]          = _num(_g(q17, "icms"))
    ctx["q17_icms_desoneracao"] = _num(_g(q17, "icms_desoneracao"))
    ctx["q17_cp_ipi"]           = _num(_g(q17, "ipi"))
    ctx["q17_cp_iof"]           = _num(_g(q17, "iof_ouro"))
    ctx["q17_outras"]           = _num(0.0)
    ctx["q17_total_base_calculo"] = _num(_g(q17, "base_calculo"))

    # ── Quadro 18 — Despesas com Saúde ───────────────────────────────────────
    q18 = resultado.get("quadro_18", {})
    saude_pct = _g(q18, "percentual_aplicacao_saude", default=None)
    ctx["saude_percentual"]     = _pctbr(saude_pct)
    ctx["q18_atencao_basica"]   = _num(_g(q18, "atencao_basica"))
    ctx["q18_assistencia_hospitalar"] = _num(_g(q18, "assistencia_hospitalar_ambulatorial"))
    ctx["q18_suporte_profilatico"]    = _num(_g(q18, "suporte_profilatico_terapeutico"))
    ctx["q18_vigilancia_sanitaria"]   = _num(_g(q18, "vigilancia_sanitaria"))
    ctx["q18_vigilancia_epidemiologica"] = _num(_g(q18, "vigilancia_epidemiologica"))
    ctx["q18_alimentacao_nutricao"]   = _num(_g(q18, "alimentacao_nutricao"))
    ctx["q18_outras_subfuncoes"]      = _num(_g(q18, "outras_subfuncoes"))
    ctx["q18_total_saude"]            = _num(_g(q18, "total_despesas_saude"))
    ctx["q18_ded_nao_computadas"]     = _num(_g(q18, "despesas_nao_computadas_rpp"))
    ctx["q18_ded_inativos"]           = _num(_g(q18, "despesas_inativos_pensionistas"))
    ctx["q18_ded_acesso_universal"]   = _num(_g(q18, "despesa_nao_acesso_universal"))
    ctx["q18_ded_outros_recursos"]    = _num(_g(q18, "despesas_outros_recursos"))
    ctx["q18_ded_outras_acoes"]       = _num(_g(q18, "outras_acoes_nao_computadas"))
    ctx["q18_ded_rp_indevidos"]       = _num(_g(q18, "rpp_inscritos_indevidamente"))
    ctx["q18_ded_rp_cancelados"]      = _num(_g(q18, "despesas_caixa_rp_cancelados"))
    ctx["q18_ded_recursos_vinculados"] = _num(_g(q18, "despesas_recursos_vinculados_exerc_anteriores"))
    ctx["q18_total_para_percentual"]  = _num(_g(q18, "total_despesas_saude_percentual_minimo"))
    ctx["q18_base_calculo"]           = _num(_g(q18, "base_calculo_informada"))

    # ── Quadro 19 — Base de Cálculo MDE ──────────────────────────────────────
    q19 = resultado.get("quadro_19", {})
    ctx["q19_receita_impostos"] = _num(_g(q19, "total_receita_impostos"))
    ctx["q19_iptu"]             = _num(_g(q19, "iptu"))
    ctx["q19_iptu_encargos"]    = _num(_g(q19, "iptu_multas"))
    ctx["q19_itbi"]             = _num(_g(q19, "itbi"))
    ctx["q19_itbi_encargos"]    = _num(_g(q19, "itbi_multas"))
    ctx["q19_iss"]              = _num(_g(q19, "iss"))
    ctx["q19_iss_encargos"]     = _num(_g(q19, "iss_multas"))
    ctx["q19_irrf"]             = _num(_g(q19, "irrf"))
    ctx["q19_itr"]              = _num(_g(q19, "itr_impostos"))
    ctx["q19_itr_encargos"]     = _num(_g(q19, "itr_multas"))
    ctx["q19_multas_impostos"]  = _num(_g(q19, "multas_impostos"))
    ctx["q19_divida_ativa"]     = _num(_g(q19, "divida_ativa_impostos"))
    ctx["q19_divida_ativa_encargos"] = _num(_g(q19, "multas_divida_ativa"))
    ctx["q19_transferencias"]   = _num(_g(q19, "total_receita_transferencias"))
    ctx["q19_cp_fpm"]           = _num(_g(q19, "fpm_regular"))
    ctx["q19_cp_itr"]           = _num(_g(q19, "cota_parte_itr"))
    ctx["q19_cp_ipva"]          = _num(_g(q19, "ipva"))
    ctx["q19_cp_icms"]          = _num(_g(q19, "icms"))
    ctx["q19_icms_desoneracao"] = _num(_g(q19, "icms_desoneracao"))
    ctx["q19_cp_ipi"]           = _num(_g(q19, "ipi_exportacao"))
    ctx["q19_cp_iof"]           = _num(_g(q19, "iof_ouro"))
    ctx["q19_outras"]           = _num(_g(q19, "outras_transferencias"))
    ctx["q19_total_base_calculo"] = _num(_g(q19, "total_base_calculo"))

    # ── Quadro 20 — MDE ──────────────────────────────────────────────────────
    q20 = resultado.get("quadro_20", {})
    mde_pct = _g(q20, "percentual_aplicacao_ensino", default=None)
    ctx["mde_percentual"]       = _pctbr(mde_pct)
    ctx["q20_fundeb_impostos"]  = _num(_g(q20, "total_fundeb_impostos_transferencias"))
    ctx["q20_fundeb_1quad"]     = _num(_g(q20, "total_fundeb_primeiro_quadrimestre"))
    ctx["q20_educacao_infantil"] = _num(_g(q20, "educacao_infantil"))
    ctx["q20_ensino_fundamental"] = _num(_g(q20, "ensino_fundamental"))
    ctx["q20_total_mde"]        = _num(_g(q20, "total_acoes_tipicas_mde"))
    ctx["q20_resultado_liquido_fundeb"] = _num(_g(q20, "resultado_liquido_fundeb"))
    ctx["q20_ded_complementacao"] = _num(_g(q20, "complementacao_fundeb_exercicio"))
    ctx["q20_ded_aplicacao_financeira"] = _num(_g(q20, "receita_aplicacao_financeira_fundeb"))
    ctx["q20_ded_superavit_anterior"]   = _num(_g(q20, "superavit_exercicio_anterior_fundeb"))
    ctx["q20_ded_outros_recursos"]      = _num(_g(q20, "outros_recursos"))
    ctx["q20_ded_rp_sem_disp"]  = _num(_g(q20, "rp_sem_disponibilidade_financeira"))
    ctx["q20_ded_rp_cancelados"] = _num(_g(q20, "cancelamento_rp_com_disponibilidade"))
    ctx["q20_total_para_limite"] = _num(_g(q20, "total_despesas_para_fins_de_limite"))
    ctx["q20_base_calculo"]     = _num(_g(q20, "base_calculo_informada"))

    # ── Quadro 21 — Recursos Destinados ao FUNDEB ────────────────────────────
    q21 = resultado.get("quadro_21", {})
    ctx["q21_cp_fpm"]  = _num(_g(q21, "fpm_cota_mensal"))
    ctx["q21_cp_icms"] = _num(_g(q21, "icms"))
    ctx["q21_cp_ipi"]  = _num(_g(q21, "ipi_exportacao"))
    ctx["q21_cp_itr"]  = _num(_g(q21, "itr"))
    ctx["q21_cp_ipva"] = _num(_g(q21, "ipva"))
    ctx["q21_compensacoes"]       = _num(_g(q21, "itr_desoneracao"))
    ctx["q21_receitas_destinadas"] = _num(_g(q21, "receitas_destinadas_ao_fundeb_a"))
    ctx["q21_total_exigido"]      = _num(_g(q21, "total_excedido_fundeb_b"))
    ctx["q21_total_destinado"]    = _num(_g(q21, "total_destinado_fundeb_apurado_c"))
    ctx["q21_percentual_destinado"] = _pctbr(_g(q21, "percentual_destinado_fundeb_d"))

    # ── Quadro 22 — Transferências ao FUNDEB ─────────────────────────────────
    q22 = resultado.get("quadro_22", {})
    ctx["q22_receitas_recebidas"] = _num(_g(q22, "receitas_recebidas_fundeb_e"))
    ctx["q22_transferencias"]     = _num(_g(q22, "transferencias_recursos_fundeb_f"))
    ctx["q22_vaaf"]               = _num(_g(q22, "complementacao_uniao_vaaf_g"))
    ctx["q22_vaat"]               = _num(_g(q22, "complementacao_uniao_vaat_h"))
    ctx["q22_vaar"]               = _num(_g(q22, "complementacao_uniao_vaar_i"))
    ctx["q22_aplicacao_financeira"] = _num(_g(q22, "receita_aplicacao_financeira_fundeb_j"))
    ctx["q22_total_destinado"]    = _num(_g(q22, "total_destinado_fundeb_apurado_c"))
    ctx["q22_resultado_liquido"]  = _num(_g(q22, "resultado_liquido_transferencias_fundeb_k"))

    # ── Quadro 23 (novo) — FUNDEB 70% Remuneração (dado em quadro_24) ────────
    q24 = resultado.get("quadro_24", {})
    f70_pct = _g(q24, "percentual_aplicado", default=None)
    ctx["fundeb_remuneracao_percentual"] = _pctbr(f70_pct)
    ctx["q23_minimo_exigido"]  = _num(_g(q24, "minimo_exigido"))
    ctx["q23_valor"]           = _num(_g(q24, "total_fundeb_70"))
    ctx["q23_ded_rp"]          = _num(0.0)
    ctx["q23_ded_superavit"]   = _num(0.0)
    ctx["q23_valor_aplicado"]  = _num(_g(q24, "total_fundeb_70"))
    ctx["q23_base_calculo"]    = _num(_g(q24, "base_calculo"))

    # ── Subfunções — Educação Função 12 (dado em quadro_23) ──────────────────
    q23sub = resultado.get("quadro_23", {})
    for cod in ("122", "361", "362", "365", "367", "306"):
        ctx[f"semed_{cod}"] = _num(_g(q23sub, f"semed_{cod}"))
    ctx["semed_subtotal"] = _num(_g(q23sub, "semed_subtotal"))
    for cod in ("361", "365", "366", "367"):
        ctx[f"fundeb_{cod}"] = _num(_g(q23sub, f"fundeb_{cod}"))
    ctx["fundeb_subtotal"] = _num(_g(q23sub, "fundeb_subtotal"))
    ctx["total_geral_funcao_12"] = _num(_g(q23sub, "total_geral_funcao_12"))

    # ── Balanço Geral FUNDEB 70% por ação (dado em quadro_25) ────────────────
    q25 = resultado.get("quadro_25", {})
    for var in (
        "valor_FUND_70_MANUT_FUNDAMENTAL", "valor_FUND_70_REMUN_DOCENTES_FUNDAMENTAL",
        "valor_FUND_70_TEMPO_INTEGRAL_FUNDAMENTAL", "valor_FUND_70_MANUT_INFANTIL",
        "valor_FUND_70_VAAT50_INFANTIL", "valor_FUND_70_REMUN_DOCENTES_INFANTIL",
        "valor_FUND_70_TEMPO_INTEGRAL_INFANTIL", "valor_FUND_70_EJA",
        "valor_FUND_70_AEE_EDUC_ESPECIAL",
    ):
        ctx[var] = _num(_g(q25, var))
    ctx["total_fundeb_70"] = _num(_g(q25, "total"))

    # ── VAAT (dado em quadro_27) ─────────────────────────────────────────────
    q27 = resultado.get("quadro_27", {})
    ctx["percentual_aplicado_infantil"] = _pctbr(_g(q27, "percentual_aplicado_infantil"))
    ctx["percentual_aplicado_capital"]  = _pctbr(_g(q27, "percentual_aplicado_capital"))
    ctx["valor_aplicado_infantil"]      = _num(_g(q27, "valor_aplicado_infantil"))
    ctx["valor_aplicado_capital"]       = _num(_g(q27, "valor_aplicado_capital"))
    ctx["minimo_exigido_infantil"]      = _num(_g(q27, "minimo_exigido_infantil"))
    ctx["minimo_exigido_capital"]       = _num(_g(q27, "minimo_exigido_capital"))
    _vaat_inf = _g(q27, "percentual_aplicado_infantil")
    _vaat_cap = _g(q27, "percentual_aplicado_capital")
    ctx["vaat_capital_situacao"] = "atendeu" if (_vaat_cap or 0) >= 15 else "não atendeu"
    ctx["vaat_observacao"]  = "atendeu" if (_vaat_inf or 0) >= 50 and (_vaat_cap or 0) >= 15 else "não atendeu"
    ctx["vaat_resumo_situacao"] = "Atendeu" if (_vaat_inf or 0) >= 50 and (_vaat_cap or 0) >= 15 else "Não atendeu"

    # ── FUNDEB — totais / conformidade (texto) ───────────────────────────────
    ctx["fundeb_outras_percentual"] = "N/D"
    ctx["fundeb_total_percentual"]  = _pctbr(f70_pct) if f70_pct is not None else "N/D"
    ctx["fundeb_total_conformidade"] = "em conformidade"

    # ── Escrituração / contábil (manuais + flags) ────────────────────────────
    ctx["escrituracao_assinatura_situacao"] = m("escrit_assinatura", "foram devidamente assinadas")
    ctx["pecas_encaminhamento_situacao"]    = m("proc_envio", "foram encaminhadas")
    ctx["pecas_publicacao_situacao"]        = m("proc_publicacao", "foram publicadas")
    ctx["tem_escrituracao_info_complementar"] = False
    ctx["escrituracao_info_complementar_texto"] = ""
    ctx["tem_bp_ausencia_conta"] = False
    ctx["bp_info_complementar_texto"] = ""

    # ── Conclusão ─────────────────────────────────────────────────────────────
    ctx["conclusao_conformidade"] = "estando em conformidade com a legislação vigente"

    # ── Ocorrências (Seção 6.2) — listas por dimensão para o Mustache ─────────
    for dim in ("orcamentaria", "financeira", "contabil", "patrimonial", "operacional"):
        lst = ocorrencias.get("ocorrencias", {}).get(dim, []) if ocorrencias else []
        ctx[f"ocorrencias_{dim}"] = [
            {
                "ordem": i,
                "item": o.get("item", ""),
                "ocorrencia": o.get("ocorrencia", ""),
                "fundamentacao": o.get("fundamentacao", ""),
            }
            for i, o in enumerate(lst, 1)
        ]

    return ctx


def render_rit(
    resultado: dict,
    dados_manuais: dict,
    ocorrencias: dict,
    municipio: str,
    exercicio: str,
) -> str:
    """Renderiza o template Mustache RIT_TEMPLATE.html com todos os dados e retorna HTML."""
    template_path = TEMPLATES_DIR / "RIT_TEMPLATE.html"
    if not template_path.exists():
        raise FileNotFoundError(
            f"Template RIT não encontrado em {template_path}. "
            "Coloque o arquivo RIT_TEMPLATE.html em kora/templates/."
        )

    ctx = build_context(resultado, dados_manuais, ocorrencias, municipio, exercicio)

    # Template Mustache/Handlebars (chevron).
    template_str = template_path.read_text(encoding="utf-8")
    # 1) Remove comentários HTML (contêm exemplos {{#flag}} que o renderizador interpretaria).
    template_str = re.sub(r"<!--.*?-->", "", template_str, flags=re.S)
    # 2) Protege blocos <script> (podem conter '{{' literal em JavaScript).
    _scripts: list[str] = []

    def _stash(mobj):
        _scripts.append(mobj.group(0))
        return f"@@KORA_SCRIPT_{len(_scripts) - 1}@@"

    template_str = re.sub(r"<script.*?</script>", _stash, template_str, flags=re.S)
    html = chevron.render(template_str, ctx)
    for i, s in enumerate(_scripts):
        html = html.replace(f"@@KORA_SCRIPT_{i}@@", s)

    logger.info("RIT renderizado para %s / %s (%d chars)", municipio, exercicio, len(html))
    return html
