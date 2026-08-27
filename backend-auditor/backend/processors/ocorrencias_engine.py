"""Motor determinístico de detecção de ocorrências para a Seção 6.2 do RIT.

Aplica os limites legais fixos (LRF, CF/88, LC 141/2012, Lei 14.113/2020 …) aos
valores extraídos dos PDFs — SEM depender da API da Anthropic. Cada regra é uma
verificação objetiva sobre um campo exato do JSON, produzindo uma ocorrência com
tipo (IRREGULAR/ALERTA), fundamentação legal e prosa técnico-jurídica padrão.

Por que determinístico: os thresholds e a fundamentação legal de um relatório
oficial do TCE-MA não podem ser "inventados" nem silenciosamente omitidos por uma
falha de API. O motor SEMPRE roda; a IA (quando disponível) apenas refina a
redação da prosa — nunca decide *quais* ocorrências existem.

Estrutura de retorno (idêntica à esperada por rit_filler.build_context):
    {
      "ocorrencias": {
        "orcamentaria": [ {item, ordem, tipo, ocorrencia, fundamentacao, dimensao, campo, valor}, ... ],
        "financeira": [...], "contabil": [...], "patrimonial": [...], "operacional": [...]
      },
      "resumo": {"total_inconformidades": N, "irregulares": N, "alertas": N},
    }
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Índice de cada dimensão para a numeração dos itens "6.2.<D>.<N>"
_DIMS = ["orcamentaria", "financeira", "contabil", "patrimonial", "operacional"]
_DIM_IDX = {d: i + 1 for i, d in enumerate(_DIMS)}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _g(d, *keys, default=None):
    """Navega dict aninhado com segurança."""
    v = d
    for k in keys:
        if not isinstance(v, dict):
            return default
        v = v.get(k)
    return v if v is not None else default


def _f(v):
    """Converte para float; devolve None se não for numérico."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _brl(v) -> str:
    """Formata valor monetário em Real brasileiro. Ex.: 'R$ 1.234.567,89'."""
    n = _f(v)
    if n is None:
        return "R$ 0,00"
    s = f"{abs(n):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if n < 0 else ''}R$ {s}"


def _pct(v, casas: int = 2) -> str:
    """Formata percentual em formato brasileiro. Ex.: '52,75%'."""
    n = _f(v)
    if n is None:
        return "N/D"
    return f"{n:.{casas}f}".replace(".", ",") + "%"


# ── Motor de regras ───────────────────────────────────────────────────────────

def detectar_ocorrencias(
    resultado: dict,
    municipio: str,
    exercicio: str,
    dados_manuais: dict | None = None,
) -> dict:
    """Aplica todas as regras legais e devolve as ocorrências por dimensão.

    Determinístico: mesma entrada ⇒ mesma saída. Só lista itens que VIOLAM o
    limite (valor conforme ⇒ nenhuma ocorrência).
    """
    dados_manuais = dados_manuais or {}
    mun = (municipio or "").strip() or "o Município"
    ex = str(exercicio or "").strip() or "em análise"

    # acumulador: dim -> lista de dicts (sem item/ordem ainda)
    acc: dict[str, list[dict]] = {d: [] for d in _DIMS}

    def add(dim, tipo, campo, valor, ocorrencia, fundamentacao):
        acc[dim].append({
            "tipo": tipo,
            "dimensao": dim,
            "campo": campo,
            "valor": valor,
            "ocorrencia": " ".join(ocorrencia.split()),
            "fundamentacao": fundamentacao,
        })

    # ── ORÇAMENTÁRIA ─────────────────────────────────────────────────────────
    # Q3 — Resultado orçamentário deficitário
    ro = _g(resultado, "quadro_03", "resultado_orcamentario", default={})
    res_orc = _f(_g(ro, "resultado"))
    situacao = str(_g(ro, "situacao", default="")).lower()
    is_deficit = (res_orc is not None and res_orc < 0) or "défic" in situacao or "defic" in situacao
    if is_deficit and res_orc is not None:
        add(
            "orcamentaria", "ALERTA", "quadro_03.resultado_orcamentario", res_orc,
            f"A execução orçamentária de {mun}, no exercício de {ex}, resultou em déficit "
            f"de {_brl(abs(res_orc))}, evidenciando que a despesa realizada superou a receita "
            f"arrecadada no período, o que enseja alerta quanto ao equilíbrio das contas públicas "
            f"(art. 1º, §1º, da LC nº 101/2000).",
            "Art. 1º, §1º, da LRF (LC nº 101/2000)",
        )

    # ── FINANCEIRA ───────────────────────────────────────────────────────────
    # Q5 — Despesa total com pessoal (fração da RCL)
    dp = _f(_g(resultado, "quadro_05", "despesa_com_pessoal", "percentual_aplicacao_despesa_pessoal"))
    if dp is not None:
        pct = dp * 100
        if pct > 60:
            add(
                "financeira", "IRREGULAR", "quadro_05.percentual_aplicacao_despesa_pessoal", pct,
                f"No exercício de {ex}, a despesa total com pessoal de {mun} correspondeu a "
                f"{_pct(pct)} da Receita Corrente Líquida (RCL), superando o limite máximo de 60% "
                f"estabelecido para o Poder Executivo Municipal, em descumprimento ao art. 20, III, "
                f"'b', da Lei de Responsabilidade Fiscal.",
                "Art. 20, III, 'b', da LRF (LC nº 101/2000)",
            )
        elif pct > 54:
            add(
                "financeira", "ALERTA", "quadro_05.percentual_aplicacao_despesa_pessoal", pct,
                f"No exercício de {ex}, a despesa total com pessoal de {mun} atingiu {_pct(pct)} da "
                f"Receita Corrente Líquida (RCL), ultrapassando o limite prudencial de 54% (95% do "
                f"limite máximo legal), o que enseja a emissão de alerta nos termos do art. 22, "
                f"parágrafo único, da Lei de Responsabilidade Fiscal.",
                "Art. 22, parágrafo único, da LRF (LC nº 101/2000)",
            )

    # Q15 — Suficiência de caixa (saldo negativo)
    saldo15 = _f(_g(resultado, "quadro_15", "saldo"))
    if saldo15 is not None and saldo15 < 0:
        add(
            "financeira", "IRREGULAR", "quadro_15.saldo", saldo15,
            f"A apuração da suficiência de caixa de {mun}, ao final do exercício de {ex}, revelou "
            f"saldo negativo de {_brl(saldo15)}, evidenciando insuficiência de disponibilidade "
            f"financeira para a cobertura das obrigações e dos restos a pagar inscritos, em "
            f"desacordo com o art. 42 da Lei de Responsabilidade Fiscal.",
            "Art. 42 da LRF (LC nº 101/2000)",
        )

    # Q12 — Resultado financeiro deficitário
    rf = _f(_g(resultado, "quadro_12", "superavit_deficit_atual"))
    if rf is not None and rf < 0:
        add(
            "financeira", "ALERTA", "quadro_12.superavit_deficit_atual", rf,
            f"O resultado financeiro do exercício de {ex} apresentou déficit de {_brl(abs(rf))}, "
            f"indicando que o passivo financeiro superou o ativo financeiro ao encerramento do "
            f"exercício, situação que enseja alerta quanto ao equilíbrio das finanças municipais.",
            "Art. 1º, §1º, da LRF (LC nº 101/2000)",
        )

    # ── CONTÁBIL ─────────────────────────────────────────────────────────────
    # Q16 — Divergência de depósitos restituíveis (BF x BP)
    dif16 = _f(_g(resultado, "quadro_16", "diferenca"))
    if dif16 is not None and abs(dif16) >= 0.01:
        add(
            "contabil", "ALERTA", "quadro_16.diferenca", dif16,
            f"Constatou-se divergência de {_brl(abs(dif16))} entre o saldo de depósitos e valores "
            f"restituíveis apurado no Balanço Financeiro e o registrado no Balanço Patrimonial "
            f"referente ao exercício de {ex}, o que compromete a fidedignidade e a correspondência "
            f"entre as peças contábeis.",
            "Lei nº 4.320/64 e MCASP",
        )

    # ── PATRIMONIAL ──────────────────────────────────────────────────────────
    # Q13 — Variação atípica do Patrimônio Líquido
    var13 = _f(_g(resultado, "quadro_13", "variacao_percentual"))
    if var13 is not None and abs(var13) > 50:
        sentido = "acréscimo" if var13 >= 0 else "decréscimo"
        add(
            "patrimonial", "ALERTA", "quadro_13.variacao_percentual", var13,
            f"O Patrimônio Líquido de {mun} registrou {sentido} de {_pct(abs(var13))} em relação ao "
            f"exercício anterior, variação atípica que requer verificação da consistência das peças "
            f"contábeis e da correta escrituração das variações patrimoniais no exercício de {ex}.",
            "Lei nº 4.320/64 e MCASP (variações patrimoniais)",
        )

    # ── OPERACIONAL ──────────────────────────────────────────────────────────
    # Q18 — Aplicação em Saúde (< 15%)
    saude = _f(_g(resultado, "quadro_18", "percentual_aplicacao_saude"))
    if saude is not None and saude < 15:
        add(
            "operacional", "IRREGULAR", "quadro_18.percentual_aplicacao_saude", saude,
            f"No exercício de {ex}, {mun} aplicou {_pct(saude)} da receita resultante de impostos e "
            f"transferências em ações e serviços públicos de saúde, percentual inferior ao mínimo "
            f"constitucional de 15%, em descumprimento ao art. 77, III, do ADCT (EC nº 29/2000) e ao "
            f"art. 7º da LC nº 141/2012.",
            "Art. 7º da LC nº 141/2012 (mínimo de 15%)",
        )

    # Q20 — Aplicação em MDE (< 25%)
    mde = _f(_g(resultado, "quadro_20", "percentual_aplicacao_ensino"))
    if mde is not None and mde < 25:
        add(
            "operacional", "IRREGULAR", "quadro_20.percentual_aplicacao_ensino", mde,
            f"Na Manutenção e Desenvolvimento do Ensino (MDE), {mun} aplicou {_pct(mde)} da receita "
            f"resultante de impostos no exercício de {ex}, percentual inferior ao mínimo de 25% "
            f"exigido pelo art. 212 da Constituição Federal e pelo art. 69 da LDBEN (Lei nº 9.394/96).",
            "Art. 212 da CF/88 e art. 69 da LDBEN (mínimo de 25%)",
        )

    # Q24 — FUNDEB, aplicação em remuneração dos profissionais (< pct exigido, padrão 70%)
    f70 = _f(_g(resultado, "quadro_24", "percentual_aplicado"))
    pct_exig_q24 = _f(dados_manuais.get("q24_pct_exigido")) or 70.0
    if f70 is not None and f70 < pct_exig_q24:
        add(
            "operacional", "IRREGULAR", "quadro_24.percentual_aplicado", f70,
            f"Dos recursos do FUNDEB, {mun} destinou {_pct(f70)} à remuneração dos profissionais da "
            f"educação básica no exercício de {ex}, percentual inferior ao mínimo de {_pct(pct_exig_q24)} "
            f"exigido pelo art. 26, caput, da Lei nº 14.113/2020.",
            "Art. 26, caput, da Lei nº 14.113/2020",
        )

    # Q27 — VAAT: educação infantil (< 50%) e despesas de capital (< 15%)
    vaat_inf = _f(_g(resultado, "quadro_27", "percentual_aplicado_infantil"))
    if vaat_inf is not None and vaat_inf < 50:
        add(
            "operacional", "IRREGULAR", "quadro_27.percentual_aplicado_infantil", vaat_inf,
            f"Da complementação-VAAT do FUNDEB, {mun} aplicou {_pct(vaat_inf)} em educação infantil no "
            f"exercício de {ex}, percentual inferior ao mínimo de 50% previsto no art. 30, I, da "
            f"Lei nº 14.113/2020.",
            "Art. 30, I, da Lei nº 14.113/2020 (mínimo de 50%)",
        )
    vaat_cap = _f(_g(resultado, "quadro_27", "percentual_aplicado_capital"))
    if vaat_cap is not None and vaat_cap < 15:
        add(
            "operacional", "IRREGULAR", "quadro_27.percentual_aplicado_capital", vaat_cap,
            f"Da complementação-VAAT do FUNDEB, {mun} aplicou {_pct(vaat_cap)} em despesas de capital no "
            f"exercício de {ex}, percentual inferior ao mínimo de 15% previsto no art. 30, II, da "
            f"Lei nº 14.113/2020.",
            "Art. 30, II, da Lei nº 14.113/2020 (mínimo de 15%)",
        )

    # ── Numeração e resumo ───────────────────────────────────────────────────
    ocorrencias: dict[str, list[dict]] = {}
    total = irregulares = alertas = 0
    for dim in _DIMS:
        lst = []
        for n, oc in enumerate(acc[dim], 1):
            oc = dict(oc)
            oc["ordem"] = n
            oc["item"] = f"6.2.{_DIM_IDX[dim]}.{n}"
            lst.append(oc)
            total += 1
            if oc["tipo"] == "IRREGULAR":
                irregulares += 1
            elif oc["tipo"] == "ALERTA":
                alertas += 1
        ocorrencias[dim] = lst

    logger.info(
        "detectar_ocorrencias: %d ocorrências (%d irregulares, %d alertas) — %s/%s",
        total, irregulares, alertas, municipio, exercicio,
    )

    return {
        "ocorrencias": ocorrencias,
        "resumo": {
            "total_inconformidades": total,
            "irregulares": irregulares,
            "alertas": alertas,
        },
    }
