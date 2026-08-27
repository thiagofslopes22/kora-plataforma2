"""
Testes de regressão dos extratores — Pinheiro e Apicum.

Execute na pasta kora/:
    pytest tests/ -v

Os PDFs são lidos de ../arquivo/ (relativo à kora/).
"""
import logging
import os
import pytest

logging.disable(logging.CRITICAL)

# ── Caminhos ───────────────────────────────────────────────────────────────────
BASE = os.path.join(os.path.dirname(__file__), '..', '..', 'arquivo')

def _p(nome: str) -> str:
    return os.path.join(BASE, nome)

# Pinheiro
ANX6_PIN   = _p('anx6.pdf')
ANX10_PIN  = _p('anx102025.pdf')
ANX10_PIN_ANT = _p('anx102024.pdf')
ANX14_PIN  = _p('BPapicum.pdf')   # reutiliza BP apicum — Pinheiro usa BP.pdf
BP_PIN     = _p('BP.pdf')
BP_APICUM  = _p('BPapicum.pdf')

# Apicum
ANX6_APC   = _p('anx6apicum.pdf')
ANX10_APC  = _p('anx10atualapicum.pdf')
ANX10_APC_ANT = _p('anx10anteriorapicum.pdf')
ANX2_APC   = _p('anx2apicum.pdf')

# Presidente Dutra
ANX6_PRESI  = _p('anx6presi.pdf')
ANX10_PRESI = _p('anx10presi.pdf')


def approx(valor: float, esperado: float, tol: float = 1.0) -> bool:
    """Tolerância de R$ 1,00 por padrão."""
    return abs(valor - esperado) <= tol


# ══════════════════════════════════════════════════════════════════════════════
# PINHEIRO
# ══════════════════════════════════════════════════════════════════════════════

class TestPinheiroFundeb:
    """Q24/Q26/Q27 — FUNDEB Pinheiro (valores de referência pré-alterações)."""

    def test_q24_valor_aplicado(self):
        from backend.extractors.anx06_programa_trabalho import extrair_fundeb70_balanco
        r = extrair_fundeb70_balanco(ANX6_PIN, ANX10_PIN)
        assert approx(r['valor_aplicado_remuneracao'], 120_838_339.39), \
            f"Q24 70% magistério: {r['valor_aplicado_remuneracao']:,.2f}"

    def test_q24_percentual(self):
        from backend.extractors.anx06_programa_trabalho import extrair_fundeb70_balanco
        r = extrair_fundeb70_balanco(ANX6_PIN, ANX10_PIN)
        assert abs(r['percentual_aplicado'] - 73.49) < 0.01, \
            f"Q24 percentual: {r['percentual_aplicado']:.2f}%"

    def test_q26_valor_outras(self):
        # Pinheiro não rotula nenhuma ação do Anexo 6 com "30%"/outras despesas
        # explicitamente (diferente de Apicum) — o extrator não deve mais inferir
        # esse valor por subtração (total - 70%, que incluía capital indevidamente);
        # deve ficar em 0,00 e sinalizar a ausência de rótulo via alerta.
        from backend.extractors.anx06_programa_trabalho import extrair_q26
        r = extrair_q26(ANX6_PIN, ANX10_PIN)
        assert r['valor_aplicado_outras_despesas'] == 0.0, \
            f"Q26 30% outras: {r['valor_aplicado_outras_despesas']:,.2f} (esperado 0,00 — sem rótulo no Anexo 6)"
        assert any('rótulo explícito' in a for a in r['alertas']), \
            "Q26 deveria alertar sobre a ausência de rótulo '30%' no Anexo 6 de Pinheiro"

    def test_q27_capital(self):
        from backend.extractors.anx06_programa_trabalho import extrair_q27
        r = extrair_q27(ANX6_PIN, ANX10_PIN)
        assert approx(r['valor_aplicado_capital'], 15_888_953.28), \
            f"Q27 capital VAAT: {r['valor_aplicado_capital']:,.2f}"

    def test_q27_infantil(self):
        from backend.extractors.anx06_programa_trabalho import extrair_q27
        r = extrair_q27(ANX6_PIN, ANX10_PIN)
        assert approx(r['valor_aplicado_infantil'], 25_390_276.68), \
            f"Q27 infantil VAAT: {r['valor_aplicado_infantil']:,.2f}"


class TestPinheiroMDE:
    """Q20 MDE — Pinheiro."""

    def test_q20_total_mde(self):
        from backend.extractors.anx06_programa_trabalho import extrair_q20
        from backend.extractors.anx10_legislativo import extrair_q19
        base = extrair_q19(ANX10_PIN)['base_bruta']
        r = extrair_q20(ANX6_PIN, ANX10_PIN, base_calculo_bruta=base)
        # Ações típicas de MDE = FUNDEB (subtotal Q23) + SEMED/MDE (subtotal Q23,
        # exposto na linha "Ensino Fundamental"); "Educação Infantil" e o 1º
        # quadrimestre ficam em 0,00 para não contar valor em duplicidade.
        assert approx(r['total_acoes_tipicas_mde'], 201_959_791.34, tol=500), \
            f"Q20 total_mde: {r['total_acoes_tipicas_mde']:,.2f}"

    def test_q20_limite(self):
        from backend.extractors.anx06_programa_trabalho import extrair_q20
        from backend.extractors.anx10_legislativo import extrair_q19
        base = extrair_q19(ANX10_PIN)['base_bruta']
        r = extrair_q20(ANX6_PIN, ANX10_PIN, base_calculo_bruta=base)
        assert approx(r['total_despesas_para_fins_de_limite'], 34_010_052.78, tol=500), \
            f"Q20 limite: {r['total_despesas_para_fins_de_limite']:,.2f}"


class TestPinheiroANX10:
    """Q22 FUNDEB — Pinheiro."""

    def test_q22_receitas_recebidas(self):
        from backend.extractors.anx10_legislativo import extrair_q22
        r = extrair_q22(ANX10_PIN)
        assert approx(r['receitas_recebidas_fundeb_e'], 164_756_114.38, tol=500), \
            f"Q22 receitas recebidas: {r['receitas_recebidas_fundeb_e']:,.2f}"

    def test_q22_liquido(self):
        from backend.extractors.anx10_legislativo import extrair_q22
        r = extrair_q22(ANX10_PIN)
        assert approx(r['resultado_liquido_transferencias_fundeb_k'], 49_881_936.18, tol=500), \
            f"Q22 resultado líquido: {r['resultado_liquido_transferencias_fundeb_k']:,.2f}"


class TestPinheiroANX14:
    """Q12 Balanço Patrimonial — Pinheiro."""

    def test_q12_ativo_financeiro(self):
        from backend.extractors.anx14_balanco_patrimonial import extrair
        r = extrair(BP_PIN)
        af = r['quadro_b']['ativo_financeiro']['atual']
        assert af > 0, f"Ativo financeiro deve ser positivo, got {af}"

    def test_q12_passivo_financeiro(self):
        from backend.extractors.anx14_balanco_patrimonial import extrair
        r = extrair(BP_PIN)
        pf = r['quadro_b']['passivo_financeiro']['atual']
        assert pf >= 0, f"Passivo financeiro deve ser não-negativo, got {pf}"


# ══════════════════════════════════════════════════════════════════════════════
# APICUM
# ══════════════════════════════════════════════════════════════════════════════

class TestApicumFundeb:
    """Q24/Q26/Q27 — FUNDEB Apicum (valores do RIT oficial)."""

    def test_q24_valor_aplicado(self):
        from backend.extractors.anx06_programa_trabalho import extrair_fundeb70_balanco
        r = extrair_fundeb70_balanco(ANX6_APC, ANX10_APC)
        assert approx(r['valor_aplicado_remuneracao'], 30_875_341.87), \
            f"Q24 70% magistério: {r['valor_aplicado_remuneracao']:,.2f} (esperado 30.875.341,87)"

    def test_q24_base(self):
        from backend.extractors.anx06_programa_trabalho import extrair_fundeb70_balanco
        r = extrair_fundeb70_balanco(ANX6_APC, ANX10_APC)
        assert approx(r['base_calculo'], 39_745_390.53, tol=100), \
            f"Q24 base: {r['base_calculo']:,.2f}"

    def test_q24_percentual(self):
        from backend.extractors.anx06_programa_trabalho import extrair_fundeb70_balanco
        r = extrair_fundeb70_balanco(ANX6_APC, ANX10_APC)
        assert abs(r['percentual_aplicado'] - 77.68) < 0.01, \
            f"Q24 percentual: {r['percentual_aplicado']:.2f}% (esperado 77,68%)"

    def test_q26_valor_outras(self):
        # Apicum rotula as ações "FUNDEB - 30%" explicitamente no Anexo 6 — soma das
        # ações rotuladas (4.503.719,27), não mais "total da unidade menos 70%"
        # (que incluía indevidamente capital e ações não classificadas).
        from backend.extractors.anx06_programa_trabalho import extrair_q26
        r = extrair_q26(ANX6_APC, ANX10_APC)
        assert approx(r['valor_aplicado_outras_despesas'], 4_503_719.27), \
            f"Q26 30% outras: {r['valor_aplicado_outras_despesas']:,.2f} (esperado 4.503.719,27)"

    def test_q27_capital_vaat(self):
        from backend.extractors.anx06_programa_trabalho import extrair_q27
        r = extrair_q27(ANX6_APC, ANX10_APC)
        assert approx(r['valor_aplicado_capital'], 1_640_098.38), \
            f"Q27 capital VAAT: {r['valor_aplicado_capital']:,.2f} (esperado 1.640.098,38)"

    def test_q27_capital_percentual(self):
        from backend.extractors.anx06_programa_trabalho import extrair_q27
        r = extrair_q27(ANX6_APC, ANX10_APC)
        assert abs(r['percentual_aplicado_capital'] - 17.94) < 0.01, \
            f"Q27 % capital: {r['percentual_aplicado_capital']:.2f}% (esperado 17,94%)"

    def test_q27_base_vaat(self):
        from backend.extractors.anx06_programa_trabalho import extrair_q27
        r = extrair_q27(ANX6_APC, ANX10_APC)
        assert approx(r['base_calculo_vaat'], 9_140_650.87, tol=100), \
            f"Q27 base VAAT: {r['base_calculo_vaat']:,.2f}"


class TestApicumANX10:
    """Q22 FUNDEB — Apicum."""

    def test_q22_receitas_recebidas(self):
        from backend.extractors.anx10_legislativo import extrair_q22
        r = extrair_q22(ANX10_APC)
        assert approx(r['receitas_recebidas_fundeb_e'], 39_745_390.53, tol=100), \
            f"Q22 receitas recebidas: {r['receitas_recebidas_fundeb_e']:,.2f}"

    def test_q22_vaaf(self):
        from backend.extractors.anx10_legislativo import extrair_q22
        r = extrair_q22(ANX10_APC)
        assert approx(r['complementacao_uniao_vaaf_g'], 12_877_058.03, tol=100), \
            f"Q22 VAAF: {r['complementacao_uniao_vaaf_g']:,.2f}"

    def test_q22_vaat(self):
        from backend.extractors.anx10_legislativo import extrair_q22
        r = extrair_q22(ANX10_APC)
        assert approx(r['complementacao_uniao_vaat_h'], 9_140_650.87, tol=100), \
            f"Q22 VAAT: {r['complementacao_uniao_vaat_h']:,.2f}"

    def test_q22_resultado_liquido(self):
        from backend.extractors.anx10_legislativo import extrair_q22
        r = extrair_q22(ANX10_APC)
        assert approx(r['resultado_liquido_transferencias_fundeb_k'], 10_881_371.39, tol=100), \
            f"Q22 resultado líquido: {r['resultado_liquido_transferencias_fundeb_k']:,.2f}"


class TestApicumANX14:
    """Q12 Balanço Patrimonial — Apicum (valores do RIT)."""

    def test_q12_ativo_financeiro(self):
        from backend.extractors.anx14_balanco_patrimonial import extrair
        r = extrair(BP_APICUM)
        af = r['quadro_b']['ativo_financeiro']['atual']
        assert approx(af, 6_473_160.74), \
            f"Q12 ativo financeiro: {af:,.2f} (esperado 6.473.160,74)"

    def test_q12_passivo_financeiro_atual(self):
        from backend.extractors.anx14_balanco_patrimonial import extrair
        r = extrair(BP_APICUM)
        pf = r['quadro_b']['passivo_financeiro']['atual']
        assert approx(pf, 4_438_469.70), \
            f"Q12 passivo financeiro atual: {pf:,.2f} (esperado 4.438.469,70)"

    def test_q12_passivo_financeiro_anterior(self):
        from backend.extractors.anx14_balanco_patrimonial import extrair
        r = extrair(BP_APICUM)
        pf_ant = r['quadro_b']['passivo_financeiro']['anterior']
        assert approx(pf_ant, 8_331_073.93, tol=500), \
            f"Q12 passivo financeiro anterior: {pf_ant:,.2f} (esperado 8.331.073,93)"


class TestApicumPessoal:
    """Q5 Despesa Pessoal — Apicum."""

    def test_q5_pessoal_ativo(self):
        from backend.extractors.anx05_pessoal import extrair
        r = extrair(ANX2_APC, ANX10_APC)
        dp = r['despesa_com_pessoal']
        assert approx(dp['pessoal_ativo'], 47_853_011.55, tol=500), \
            f"Q5 pessoal ativo: {dp['pessoal_ativo']:,.2f} (esperado ~47.853.011,55)"

    def test_q5_rcl(self):
        from backend.extractors.anx05_pessoal import extrair
        r = extrair(ANX2_APC, ANX10_APC)
        rcl = r['despesa_com_pessoal']['base_calculo_rcl']
        assert approx(rcl, 94_034_056.85, tol=500), \
            f"Q5 RCL: {rcl:,.2f} (esperado 94.034.056,85)"


# ══════════════════════════════════════════════════════════════════════════════
# QUADRO 25 — Balanço Geral FUNDEB 70% (9 rubricas canônicas por função.subfunção)
# ══════════════════════════════════════════════════════════════════════════════

class TestQuadro25Rubricas:
    """Classificação por FUNÇÃO.SUBFUNÇÃO (12.361/365/366/367) + palavra-chave, não
    pelo código completo de programa/ação — que cada município numera à sua maneira.
    O total do quadro 25 é sempre o detalhamento do MESMO total do quadro 24 (nunca
    recalcula/recupera valor a mais — só reclassifica as ações já confirmadas 70%).
    """

    def test_pinheiro_total_bate_com_quadro_24(self):
        from backend.extractors.anx06_programa_trabalho import extrair_q25, extrair_fundeb70_balanco
        r = extrair_q25(ANX6_PIN)
        q24 = extrair_fundeb70_balanco(ANX6_PIN, ANX10_PIN)
        assert approx(r['total'], q24['total_fundeb_70']), \
            f"Q25 total ({r['total']:,.2f}) deveria bater com Q24 ({q24['total_fundeb_70']:,.2f})"
        assert r['total_fora_das_9_rubricas'] == 0.0
        encontradas = {x['codigo_canonico'] for x in r['rubricas'] if x['encontrado']}
        assert 'FUND_70_MANUT_FUNDAMENTAL' in encontradas
        assert 'FUND_70_REMUN_DOCENTES_FUNDAMENTAL' in encontradas
        assert 'FUND_70_EJA' in encontradas
        assert 'FUND_70_AEE_EDUC_ESPECIAL' in encontradas

    def test_apicum_nao_conta_acoes_rotuladas_30pct(self):
        # As duas ações "MANUTENÇÃO DAS ATIVIDADES DO FUNDEB - 30%" (subfunções 361 e
        # 365, R$ 3.735.246,61 + R$ 768.472,66) são outras despesas (quadro_26) — não
        # podem aparecer em nenhuma rubrica do quadro 25, mesmo compartilhando a mesma
        # subfunção das rubricas de manutenção.
        from backend.extractors.anx06_programa_trabalho import extrair_q25, extrair_fundeb70_balanco
        r = extrair_q25(ANX6_APC)
        q24 = extrair_fundeb70_balanco(ANX6_APC, ANX10_APC)
        for rub in r['rubricas']:
            for c in rub['componentes']:
                assert c['codigo_fonte'] not in ('12.361.0003.2018.0000', '12.365.0003.2018.0000'), \
                    f"Ação rotulada 30% vazou para rubrica 70%: {c}"
        assert approx(r['total'], q24['total_fundeb_70']), \
            f"Q25 total ({r['total']:,.2f}) deveria bater com Q24 ({q24['total_fundeb_70']:,.2f})"

    def test_presidente_dutra_eja_segregado_e_total_bate_com_quadro_24(self):
        from backend.extractors.anx06_programa_trabalho import extrair_q25, extrair_fundeb70_balanco
        r = extrair_q25(ANX6_PRESI)
        q24 = extrair_fundeb70_balanco(ANX6_PRESI, ANX10_PRESI)
        por_codigo = {x['codigo_canonico']: x for x in r['rubricas']}
        assert por_codigo['FUND_70_EJA']['encontrado']
        assert por_codigo['FUND_70_EJA']['segregado']
        assert approx(r['total'], q24['total_fundeb_70']), \
            f"Q25 total ({r['total']:,.2f}) deveria bater com Q24 ({q24['total_fundeb_70']:,.2f})"
