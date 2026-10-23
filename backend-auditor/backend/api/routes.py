import logging
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from backend.exporters.excel_exporter import generate_excel
from backend.extractors.anx10_legislativo import _indexar as anx10_indexar, extrair as extrair_anx10, extrair_q04 as extrair_anx10_q04, extrair_q17 as extrair_anx10_q17, extrair_q19 as extrair_anx10_q19, extrair_q21 as extrair_anx10_q21, extrair_q22 as extrair_anx10_q22
from backend.extractors.anx06_funcoes import eh_formato_funcoes as anx06_eh_formato_funcoes
from backend.extractors.anx06_programa_trabalho import formato_incompativel as anx06_formato_incompativel, extrair_q18 as extrair_anx06_q18, extrair_q20 as extrair_anx06_q20, extrair_subfuncao_func12 as extrair_anx06_q23, extrair_fundeb70_balanco as extrair_anx06_q24, extrair_q25 as extrair_anx06_q25, extrair_q27 as extrair_anx06_q27
from backend.extractors.anx12_resultado import extrair as extrair_anx12
from backend.extractors.anx08_receitas import extrair as extrair_anx08
from backend.extractors.anx09_despesas import extrair as extrair_anx09
from backend.extractors.anx10_tributaria import extrair as extrair_anx10_trib
from backend.extractors.anx05_pessoal import extrair as extrair_anx05
from backend.extractors.anx14_balanco_patrimonial import extrair as extrair_anx14
from backend.extractors.anx12_restos_pagar import extrair as extrair_anx12_rp
from backend.extractors.anx13_balanco_financeiro import extrair_q16 as extrair_anx13_q16
from backend.extractors.loa_comparativo import extrair_q11
from backend.extractors.rgf_despesa_pessoal import extrair_q06
from backend.extractors.rgf_divida import extrair_q07
from backend.extractors.anx_dfc import extrair as extrair_dfc
from backend.processors.prompt_loader import TABELA_CONFIG
from backend.processors.claude_processor import analisar_inconformidades, gerar_ocorrencias_rit
from backend.exporters.excel_reader import ler_excel_atualizado
from backend.exporters.rit_filler import render_rit

logger = logging.getLogger(__name__)
router = APIRouter()

EXTRATORES_IMPLEMENTADOS = {"quadro_01", "quadro_03", "quadro_04", "quadro_05", "quadro_06", "quadro_07", "quadro_08", "quadro_09", "quadro_10", "quadro_11", "quadro_12", "quadro_13", "quadro_14", "quadro_15", "quadro_16", "quadro_17", "quadro_18", "quadro_19", "quadro_20", "quadro_21", "quadro_22", "quadro_23", "quadro_24", "quadro_25", "quadro_27"}


@router.get("/health")
def health():
    return {"status": "ok", "service": "Kora API"}


@router.get("/quadros")
def listar_quadros():
    return [
        {
            "chave": chave,
            "descricao": cfg["descricao"],
            "docs_necessarios": cfg["docs"],
            "docs_alternativos": cfg.get("docs_alternativos", []),
            "implementado": chave in EXTRATORES_IMPLEMENTADOS,
        }
        for chave, cfg in TABELA_CONFIG.items()
    ]


def _build_tabelas_status(resultado: dict, enviados: dict, file_list: list[dict] | None = None) -> list[dict]:
    # Documentos enviados mas recusados na validacao (ex.: Anexo 6 no formato errado)
    recusados = {f["doc_type"]: f["incompativel"] for f in (file_list or []) if f.get("incompativel")}
    # Documento aceito, mas que não serve para um quadro específico (ex.: Anexo 6 por Funções no Q24)
    limitados = {(f["doc_type"], q): motivo for f in (file_list or []) for q, motivo in f.get("limita", {}).items()}
    tabelas = []
    for chave, cfg in TABELA_CONFIG.items():
        docs_faltando = [f"{d} ({recusados[d]})" if d in recusados else
                         f"{d} ({limitados[(d, chave)]})" if (d, chave) in limitados else d
                         for d in cfg["docs"] if d not in enviados or d in recusados or (d, chave) in limitados]
        # Modelo alternativo completo (ex.: RGF semestral no lugar do quadrimestral)
        if docs_faltando and any(all(d in enviados and d not in recusados for d in alt)
                                 for alt in cfg.get("docs_alternativos", [])):
            docs_faltando = []
        implementado = chave in EXTRATORES_IMPLEMENTADOS
        tabelas.append({
            "chave": chave,
            "descricao": cfg["descricao"],
            "docs_necessarios": cfg["docs"],
            "docs_alternativos": cfg.get("docs_alternativos", []),
            "docs_faltando": docs_faltando,
            "pode_gerar": chave in resultado,
            "prompt_existe": implementado,
        })
    return tabelas


def _extrair_todos(file_list: list[dict]) -> tuple[dict, str, str]:
    """Roda todos os extratores e devolve (resultado, municipio, exercicio)."""
    # Valida o formato do Anexo 6 antes de extrair: o documento errado nao falha,
    # gera percentuais absurdos. Marca no file_list (o status mostra o motivo).
    for f in file_list:
        if f["doc_type"] == "ANX_06":
            motivo = anx06_formato_incompativel(f["path"])
            if motivo:
                f["incompativel"] = motivo
                logger.warning("ANX_06 recusado: %s", motivo)
            elif anx06_eh_formato_funcoes(f["path"]):
                # 'Despesa por Funções': sem subfunção/ação → Q18/Q20/Q23 saem pelo total da
                # função; os quadros que dependem de ações rotuladas não podem ser montados.
                f["formato"] = "funcoes"
                motivo_acao = ("formato 'Despesa por Funções' não identifica as ações {}; "
                               "envie o Anexo 6 'Programa de Trabalho' para este quadro")
                f["limita"] = {
                    "quadro_24": motivo_acao.format("do FUNDEB 70%"),
                    "quadro_25": motivo_acao.format("do FUNDEB 70%"),
                    "quadro_27": motivo_acao.format("do VAAT"),
                }
        elif f["doc_type"] in ("ANX_10_ATUAL", "ANX_10_ANTERIOR"):
            # Sem nenhum código de receita lido (PDF escaneado/formato desconhecido) os quadros
            # sairiam todos zerados e marcados como gerados.
            if not anx10_indexar(f["path"]):
                f["incompativel"] = ("não foi possível ler os códigos de receita — o PDF parece escaneado "
                                     "(imagem) ou está em formato não reconhecido; envie o Anexo 10 gerado "
                                     "pelo sistema contábil")
                logger.warning("%s recusado: nenhum código de receita lido", f["doc_type"])
    file_list = [f for f in file_list if not f.get("incompativel")]
    anx06_limita = next((f.get("limita", {}) for f in file_list if f["doc_type"] == "ANX_06"), {})

    municipio = ""
    exercicio = "2025"
    resultado: dict = {}

    path_anx10_ant = next((f["path"] for f in file_list if f["doc_type"] == "ANX_10_ANTERIOR"), None)
    path_anx12     = next((f["path"] for f in file_list if f["doc_type"] == "ANX_12"), None)
    path_anx02     = next((f["path"] for f in file_list if f["doc_type"] == "ANX_02"), None)
    path_anx10_at  = next((f["path"] for f in file_list if f["doc_type"] == "ANX_10_ATUAL"), None)
    path_anx06     = next((f["path"] for f in file_list if f["doc_type"] == "ANX_06"), None)
    path_anx14     = next((f["path"] for f in file_list if f["doc_type"] == "ANX_14"), None)
    path_anx13     = next((f["path"] for f in file_list if f["doc_type"] == "ANX_13"), None)
    path_dfc       = next((f["path"] for f in file_list if f["doc_type"] == "DFC"), None)
    path_loa       = next((f["path"] for f in file_list if f["doc_type"] == "LOA"), None)
    def _doc(tipo):
        return next((f["path"] for f in file_list if f["doc_type"] == tipo), None)

    # RGF quadrimestral (atual) com fallback para o semestral (legado).
    # final = ultimo periodo do exercicio; intermediario = 2º quad / 1º sem.
    path_rgf_final = _doc("RGF_3QUAD") or _doc("RGF_2SEM")
    path_rgf_inter = _doc("RGF_2QUAD") or _doc("RGF_1SEM")
    # Q7: a tabela do periodo mais recente ja traz todos os anteriores
    path_rgf_q7    = path_rgf_final or _doc("RGF_2QUAD") or _doc("RGF_1QUAD")
    path_bo_fundeb = next((f["path"] for f in file_list if f["doc_type"] == "BO_FUNDEB"), None)
    path_ff_saude  = next((f["path"] for f in file_list if f["doc_type"] == "FF_SAUDE"), None)

    # Q7 — Dívida Consolidada (RGF mais recente) ou vazio para preenchimento manual
    if path_rgf_q7:
        try:
            dados_q7 = extrair_q07(path_rgf_q7)
            resultado["quadro_07"] = dados_q7
            if not municipio and dados_q7.get("municipio"):
                municipio = dados_q7["municipio"]
        except Exception as exc:
            logger.warning("Extrator Q7 falhou (%s)", exc)
            resultado["quadro_07"] = {}
    else:
        resultado["quadro_07"] = {}

    # Q1 — ANX_10_ANTERIOR
    if path_anx10_ant:
        try:
            dados_q1 = extrair_anx10(path_anx10_ant)
            resultado["quadro_01"] = dados_q1
            if not municipio and dados_q1.get("municipio"):
                municipio = dados_q1["municipio"]
            if dados_q1.get("exercicio"):
                exercicio = dados_q1["exercicio"]
            logger.info("Q1: base_calculo=%s", dados_q1["totais"]["base_calculo"])
        except Exception as exc:
            logger.warning("Extrator Q1 falhou (%s)", exc)

    # Q4 — ANX_10_ATUAL
    if path_anx10_at:
        try:
            dados_q4 = extrair_anx10_q04(path_anx10_at)
            resultado["quadro_04"] = dados_q4
            if not municipio and dados_q4.get("municipio"):
                municipio = dados_q4["municipio"]
            rcl = dados_q4["receita_corrente_liquida"]
            logger.info("Q4: total_rc=%.2f rcl=%.2f",
                        rcl["total_receita_corrente"],
                        rcl["receita_corrente_liquida_declarada"])
        except Exception as exc:
            logger.warning("Extrator Q4 falhou (%s)", exc)

    # Q3, Q8, Q9 — ANX_12
    if path_anx12:
        try:
            dados_q3 = extrair_anx12(path_anx12)
            resultado["quadro_03"] = dados_q3
            if not municipio and dados_q3.get("municipio"):
                municipio = dados_q3["municipio"]
            if dados_q3.get("exercicio"):
                exercicio = dados_q3["exercicio"]
            ro = dados_q3["resultado_orcamentario"]
            logger.info("Q3: resultado=%.2f (%s)", ro["resultado"], ro["situacao"])
        except Exception as exc:
            logger.warning("Extrator Q3 falhou (%s)", exc)

        try:
            dados_q8 = extrair_anx08(path_anx12)
            resultado["quadro_08"] = dados_q8
            if not municipio and dados_q8.get("municipio"):
                municipio = dados_q8["municipio"]
            logger.info("Q8: total_realizada=%.2f", dados_q8["total"]["realizada_c"])
        except Exception as exc:
            logger.warning("Extrator Q8 falhou (%s)", exc)

        try:
            dados_q9 = extrair_anx09(path_anx12)
            resultado["quadro_09"] = dados_q9
            if not municipio and dados_q9.get("municipio"):
                municipio = dados_q9["municipio"]
            logger.info("Q9: total_empenhada=%.2f", dados_q9["total"]["empenhada_f"])
        except Exception as exc:
            logger.warning("Extrator Q9 falhou (%s)", exc)

    # Q5 — ANX_02 + ANX_10_ATUAL
    if path_anx02 and path_anx10_at:
        try:
            dados_q5 = extrair_anx05(path_anx02, path_anx10_at, path_ff_saude)
            resultado["quadro_05"] = dados_q5
            if not municipio and dados_q5.get("municipio"):
                municipio = dados_q5["municipio"]
            dp = dados_q5["despesa_com_pessoal"]
            logger.info("Q5: liquida=%.2f pct=%.2f%%",
                        dp["despesa_liquida_com_pessoal"],
                        dp["percentual_aplicacao_despesa_pessoal"] * 100)
        except Exception as exc:
            logger.exception("Extrator Q5 falhou — detalhes completos:")

    # Q6 — RGF 3º quad + 2º quad (opcional) + RCL do Q5
    if path_rgf_final:
        try:
            rcl_q5 = resultado.get("quadro_05", {}).get("despesa_com_pessoal", {}).get("base_calculo_rcl", 0.0)
            dados_q6 = extrair_q06(path_rgf_final, path_rgf_inter, rcl_tce=rcl_q5)
            resultado["quadro_06"] = dados_q6
            if not municipio and dados_q6.get("municipio"):
                municipio = dados_q6["municipio"]
            q6p = dados_q6["quadro_6_despesa_pessoal"]
            logger.info("Q6: final dtp=%.2f rcl_q5=%.2f pct=%.2f%%",
                        q6p["apurado_pelo_tce"]["total_despesa"],
                        q6p["apurado_pelo_tce"]["receita_corrente_liquida"],
                        q6p["apurado_pelo_tce"]["percentual_apurado"] * 100)
        except Exception as exc:
            logger.warning("Extrator Q6 falhou (%s)", exc)

    # Q10 — ANX_12
    if path_anx12:
        try:
            dados_q10 = extrair_anx10_trib(anx12_path=path_anx12)
            resultado["quadro_10"] = dados_q10
            logger.info("Q10: orcada=%.2f arrecadada=%.2f situacao=%s",
                        dados_q10["receita_tributaria_atualizada"],
                        dados_q10["receita_tributaria_realizada"],
                        dados_q10["situacao"])
        except Exception as exc:
            logger.warning("Extrator Q10 falhou (%s)", exc)

    # Q17 — ANX_10_ATUAL
    if path_anx10_at:
        try:
            dados_q17 = extrair_anx10_q17(path_anx10_at)
            resultado["quadro_17"] = dados_q17
            if not municipio and dados_q17.get("municipio"):
                municipio = dados_q17["municipio"]
            logger.info("Q17: base_calculo=%.2f aplic_min=%.2f",
                        dados_q17["base_calculo"], dados_q17["aplicacao_minima"])
        except Exception as exc:
            logger.warning("Extrator Q17 falhou (%s)", exc)

    # Q19 — ANX_10_ATUAL
    if path_anx10_at:
        try:
            dados_q19 = extrair_anx10_q19(path_anx10_at)
            resultado["quadro_19"] = dados_q19
            if not municipio and dados_q19.get("municipio"):
                municipio = dados_q19["municipio"]
            logger.info("Q19: impostos=%.2f transf=%.2f fpm_extra=%.2f fundeb=%.2f base_liq=%.2f aplic=%.2f",
                        dados_q19["total_receita_impostos"], dados_q19["total_receita_transferencias"],
                        dados_q19["fpm_extraordinario"], dados_q19["deducao_fundeb"],
                        dados_q19["base_liquida"], dados_q19["aplicacao_minima"])
        except Exception as exc:
            logger.warning("Extrator Q19 falhou (%s)", exc)

    # Q21 — ANX_10_ATUAL
    if path_anx10_at:
        try:
            dados_q21 = extrair_anx10_q21(path_anx10_at)
            resultado["quadro_21"] = dados_q21
            if not municipio and dados_q21.get("municipio"):
                municipio = dados_q21["municipio"]
            logger.info("Q21: A=%.2f B=%.2f C=%.2f D=%.2f%%",
                        dados_q21["receitas_destinadas_ao_fundeb_a"],
                        dados_q21["total_excedido_fundeb_b"],
                        dados_q21["total_destinado_fundeb_apurado_c"],
                        dados_q21["percentual_destinado_fundeb_d"])
        except Exception as exc:
            logger.warning("Extrator Q21 falhou (%s)", exc)

    # Q22 — ANX_10_ATUAL (+ BO_FUNDEB para a receita de aplicação financeira J)
    if path_anx10_at:
        try:
            dados_q22 = extrair_anx10_q22(path_anx10_at, path_bo_fundeb)
            resultado["quadro_22"] = dados_q22
            if not municipio and dados_q22.get("municipio"):
                municipio = dados_q22["municipio"]
            logger.info("Q22: recebidas=%.2f transf=%.2f destinadas=%.2f resultado=%.2f",
                        dados_q22["receitas_recebidas_fundeb_e"],
                        dados_q22["transferencias_recursos_fundeb_f"],
                        dados_q22["total_destinado_fundeb_apurado_c"],
                        dados_q22["resultado_liquido_transferencias_fundeb_k"])
        except Exception as exc:
            logger.warning("Extrator Q22 falhou (%s)", exc)

    # Q24 — ANX_06 (+ ANX_10_ATUAL + BO_FUNDEB para receita de aplicação financeira na base)
    if path_anx06 and "quadro_24" not in anx06_limita:
        try:
            dados_q24 = extrair_anx06_q24(path_anx06, path_anx10_at, path_bo_fundeb)
            resultado["quadro_24"] = dados_q24
            if not municipio and dados_q24.get("municipio"):
                municipio = dados_q24["municipio"]
            logger.info("Q24: total_70pct=%.2f base=%.2f minimo=%.2f pct=%.2f%%",
                        dados_q24["total_fundeb_70"], dados_q24["base_calculo"],
                        dados_q24["minimo_exigido"], dados_q24["percentual_aplicado"])
        except Exception as exc:
            logger.warning("Extrator Q24 falhou (%s)", exc)

    # Q23 — ANX_06
    if path_anx06:
        try:
            dados_q23 = extrair_anx06_q23(path_anx06)
            resultado["quadro_23"] = dados_q23
            if not municipio and dados_q23.get("municipio"):
                municipio = dados_q23["municipio"]
            logger.info("Q23: semed=%.2f fundeb=%.2f total=%.2f",
                        dados_q23["semed_subtotal"], dados_q23["fundeb_subtotal"],
                        dados_q23["total_geral_funcao_12"])
        except Exception as exc:
            logger.warning("Extrator Q23 falhou (%s)", exc)

    # Q25 — ANX_06
    if path_anx06 and "quadro_25" not in anx06_limita:
        try:
            dados_q25 = extrair_anx06_q25(path_anx06)
            resultado["quadro_25"] = dados_q25
            if not municipio and dados_q25.get("municipio"):
                municipio = dados_q25["municipio"]
            logger.info("Q25: total_70pct=%.2f", dados_q25["total"])
        except Exception as exc:
            logger.warning("Extrator Q25 falhou (%s)", exc)

    # Q27 — ANX_06 (+ ANX_10_ATUAL)
    if path_anx06 and "quadro_27" not in anx06_limita:
        try:
            dados_q27 = extrair_anx06_q27(path_anx06, path_anx10_at)
            resultado["quadro_27"] = dados_q27
            if not municipio and dados_q27.get("municipio"):
                municipio = dados_q27["municipio"]
            logger.info("Q27: infantil=%.2f (%.2f%%) capital=%.2f (%.2f%%)",
                        dados_q27["valor_aplicado_infantil"], dados_q27["percentual_aplicado_infantil"],
                        dados_q27["valor_aplicado_capital"],  dados_q27["percentual_aplicado_capital"])
        except Exception as exc:
            logger.warning("Extrator Q27 falhou (%s)", exc)

    # Q18 — ANX_06 + ANX_10_ATUAL + base Q17
    if path_anx06 and path_anx10_at:
        try:
            base_q17 = resultado.get("quadro_17", {}).get("base_calculo", 0.0)
            dados_q18 = extrair_anx06_q18(path_anx06, path_anx10_at, base_q17)
            resultado["quadro_18"] = dados_q18
            if not municipio and dados_q18.get("municipio"):
                municipio = dados_q18["municipio"]
            logger.info("Q18: total_saude=%.2f sus=%.2f total_apuracao=%.2f pct=%.2f%%",
                        dados_q18["total_despesas_saude"], dados_q18["despesas_outros_recursos"],
                        dados_q18["total_despesas_saude_percentual_minimo"],
                        dados_q18["percentual_aplicacao_saude"])
        except Exception as exc:
            logger.warning("Extrator Q18 falhou (%s)", exc)

    # Q20 — ANX_06 + ANX_10_ATUAL + BO_FUNDEB (obrigatório) + base Q19
    if path_anx06 and path_anx10_at and path_bo_fundeb:
        try:
            base_q19_bruta = resultado.get("quadro_19", {}).get("base_bruta", 0.0)
            dados_q20 = extrair_anx06_q20(path_anx06, path_anx10_at, base_q19_bruta, path_bo_fundeb)
            resultado["quadro_20"] = dados_q20
            if not municipio and dados_q20.get("municipio"):
                municipio = dados_q20["municipio"]
            logger.info("Q20: total_mde=%.2f liq_fundeb=%.2f compl=%.2f outros=%.2f limite=%.2f pct=%.2f%%",
                        dados_q20["total_fundeb_impostos_transferencias"],
                        dados_q20["resultado_liquido_fundeb"], dados_q20["complementacao_fundeb_exercicio"],
                        dados_q20["outros_recursos"], dados_q20["total_despesas_para_fins_de_limite"],
                        dados_q20["percentual_aplicacao_ensino"])
        except Exception as exc:
            logger.warning("Extrator Q20 falhou (%s)", exc)
    elif path_anx06 and path_anx10_at and not path_bo_fundeb:
        logger.warning("Q20 não gerado: Balanço Orçamentário isolado do FUNDEB (BO_FUNDEB) é obrigatório e não foi enviado.")

    # Q11 — Comparativo LOA x Balanço Orçamentário (ANX_12/BO)
    # A LOA é opcional (valor preenchido manualmente quando ausente); o
    # quadro é sempre gerado, com o lado BO extraído do ANX_12 assim que
    # esse anexo for enviado ao sistema.
    if path_anx12:
        try:
            dados_q11 = extrair_q11(path_loa, path_anx12)
            resultado["quadro_11"] = dados_q11
            if not municipio and dados_q11.get("municipio"):
                municipio = dados_q11["municipio"]
            logger.info("Q11: receita loa=%s bo=%.2f situacao=%s | despesa loa=%s bo=%.2f situacao=%s",
                        dados_q11["receita_prevista_loa"], dados_q11["receita_prevista_bo"],
                        dados_q11["receita_prevista_situacao"],
                        dados_q11["dotacao_inicial_loa"], dados_q11["dotacao_inicial_bo"],
                        dados_q11["dotacao_inicial_situacao"])
        except Exception as exc:
            logger.warning("Extrator Q11 falhou (%s)", exc)
            resultado["quadro_11"] = {}
    else:
        resultado["quadro_11"] = {}

    # Q12 e Q13 — ANX_14
    if path_anx14:
        try:
            dados_bp = extrair_anx14(path_anx14)
            if not municipio and dados_bp.get("municipio"):
                municipio = dados_bp["municipio"]
            if dados_bp.get("exercicio"):
                exercicio = dados_bp["exercicio"]
            qb = dados_bp.get("quadro_b", {})
            af_a   = qb.get("ativo_financeiro",  {}).get("atual",    0.0)
            af_ant = qb.get("ativo_financeiro",  {}).get("anterior", 0.0)
            pf_a   = qb.get("passivo_financeiro", {}).get("atual",    0.0)
            pf_ant = qb.get("passivo_financeiro", {}).get("anterior", 0.0)
            resultado["quadro_12"] = {
                "ativo_financeiro_atual":       af_a,
                "ativo_financeiro_anterior":    af_ant,
                "passivo_financeiro_atual":     pf_a,
                "passivo_financeiro_anterior":  pf_ant,
                "creditos_adicionais_atual":    0.0,
                "creditos_adicionais_anterior": 0.0,
                "superavit_deficit_atual":      round(af_a  - pf_a  + 0.0, 2),
                "superavit_deficit_anterior":   round(af_ant - pf_ant + 0.0, 2),
            }
            logger.info("Q12: af=%.2f pf=%.2f superavit=%.2f",
                        af_a, pf_a, resultado["quadro_12"]["superavit_deficit_atual"])

            pl     = dados_bp.get("patrimonio_liquido", {}).get("total_pl", {})
            pl_ant = pl.get("anterior", 0.0)
            pl_at  = pl.get("atual",    0.0)
            var_abs = round(pl_at - pl_ant, 2)
            var_pct = round((var_abs / abs(pl_ant)) * 100, 2) if pl_ant != 0 else 0.0
            resultado["quadro_13"] = {
                "patrimonio_liquido_anterior": pl_ant,
                "patrimonio_liquido_atual":    pl_at,
                "variacao_absoluta":           var_abs,
                "variacao_percentual":         var_pct,
            }
            logger.info("Q13: pl_ant=%.2f pl_at=%.2f var_abs=%.2f var_pct=%.2f%%",
                        pl_ant, pl_at, var_abs, var_pct)
        except Exception as exc:
            logger.warning("Extrator Q12/Q13 falhou (%s)", exc)

    # Q14 — DFC atual (a coluna "exercício anterior" já vem do próprio documento)
    if path_dfc:
        try:
            d_at = extrair_dfc(path_dfc)
            if not municipio and d_at.get("municipio"):
                municipio = d_at["municipio"]
            if d_at.get("exercicio"):
                exercicio = d_at["exercicio"]

            resultado["quadro_14"] = d_at
            logger.info("Q14: geracao=%.2f/%.2f caixa_ini=%.2f/%.2f caixa_fin=%.2f/%.2f",
                        d_at["geracao_liquida_atual"], d_at["geracao_liquida_anterior"],
                        d_at["caixa_inicial_atual"],   d_at["caixa_inicial_anterior"],
                        d_at["caixa_final_atual"],     d_at["caixa_final_anterior"])
        except Exception as exc:
            logger.warning("Extrator Q14 falhou (%s)", exc)

    # Q15 — ANX_14 + ANX_12
    if path_anx14 and path_anx12:
        try:
            dados_bp15 = extrair_anx14(path_anx14)
            dados_rp   = extrair_anx12_rp(path_anx12)

            a  = dados_bp15["ativo"]["caixa_equivalentes_caixa"]["atual"]
            b  = dados_bp15["passivo"]["valores_restituiveis"]["atual"]
            c  = round(
                dados_bp15["passivo"]["outras_obrigacoes_curto_prazo"]["atual"]
                + dados_bp15["passivo"]["fornecedores_contas_pagar"]["atual"],
                2,
            )
            d  = round(a - b - c, 2)
            np_ = dados_rp["rp_nao_processados"]
            p_  = dados_rp["rp_processados"]
            e  = round(np_["anteriores"] + p_["anteriores"], 2)
            f  = round(p_["inscritos"], 2)
            g  = round(np_["inscritos"], 2)
            h  = round(e + f + g, 2)
            i_ = round(np_["pagos"] + p_["pagos"], 2)
            j  = round(np_["cancelados"] + p_["cancelados"], 2)
            k  = 0.0
            l  = round(h - i_ - j - k, 2)
            m  = round(d - l, 2)
            situacao = "Suficiente" if m >= 0 else "Insuficiente"

            resultado["quadro_15"] = {
                "disponibilidade_caixa_bruta":    a,
                "depositos_consignacoes":         b,
                "outras_obrigacoes":              c,
                "disponibilidade_caixa_liquida":  d,
                "rp_exercicios_anteriores":       e,
                "rp_processados_inscritos":       f,
                "rp_nao_processados_inscritos":   g,
                "total_rp_nao_pago":              h,
                "rp_pago":                        i_,
                "rp_cancelado":                   j,
                "rp_baixado":                     k,
                "total_rp":                       l,
                "saldo":                          m,
                "situacao":                       situacao,
                "valor_a": a, "valor_b": b, "valor_c": c, "valor_d": d,
                "valor_e": e, "valor_f": f, "valor_g": g, "valor_h": h,
                "valor_i": i_, "valor_j": j, "valor_k": k, "valor_l": l, "valor_m": m,
                "descricao": [
                    {"item": "Disponibilidades de Caixa Bruta (A)", "valor": a},
                    {"item": "(-) Depósitos/Consignações (B)", "valor": b},
                    {"item": "(-) Outras Obrigações (C)", "valor": c},
                    {"item": "DISPONIBILIDADE DE CAIXA LÍQUIDA (D)=(A)-(B)-(C)", "valor": d},
                    {"item": "(-) Restos a Pagar (exercícios anteriores) (E)", "valor": e},
                    {"item": "(-) Restos a Pagar PROCESSADOS (inscritos no exercício) (F)", "valor": f},
                    {"item": "(-) Restos a Pagar NÃO PROCESSADOS (inscritos no exercício) (G)", "valor": g},
                    {"item": "TOTAL RESTO A PAGAR NÃO PAGO (H)=(E)+(F)+(G)", "valor": h},
                    {"item": "(+) Restos a Pagar (pago) (I)", "valor": i_},
                    {"item": "(+) Restos a Pagar (Cancelados) (J)", "valor": j},
                    {"item": "(+) Restos a Pagar (Baixados) (K)", "valor": k},
                    {"item": "TOTAL RESTO A PAGAR (L)=(H)-(I)-(J)-(K)", "valor": l},
                    {"item": "SALDO (M)=(D)-(L)", "valor": m},
                ],
            }
            logger.info("Q15: D=%.2f L=%.2f M=%.2f situacao=%s", d, l, m, situacao)
        except Exception as exc:
            logger.warning("Extrator Q15 falhou (%s)", exc)

    # Q16 — ANX_13 + ANX_14
    if path_anx13 and path_anx14:
        try:
            dados_bf16 = extrair_anx13_q16(path_anx13)
            dados_bp16 = extrair_anx14(path_anx14)

            vr_ant    = dados_bp16["passivo"]["valores_restituiveis"]["anterior"]
            vr_at     = dados_bp16["passivo"]["valores_restituiveis"]["atual"]
            saldo_c_bp = round(vr_at - vr_ant, 2)
            saldo_c_bf = dados_bf16["saldo_c_bf"]
            diferenca  = round(saldo_c_bf - saldo_c_bp, 2)
            situacao   = "Reconciliado" if diferenca == 0.0 else "Divergência"

            resultado["quadro_16"] = {
                "recebimentos_depositos_bf":                  dados_bf16["recebimentos_depositos_bf"],
                "pagamentos_depositos_bf":                    dados_bf16["pagamentos_depositos_bf"],
                "saldo_c_bf":                                 saldo_c_bf,
                "depositos_restituiveis_saldo_seguinte_bf":   dados_bf16["depositos_restituiveis_saldo_seguinte_bf"],
                "saldo_e_bf":                                 dados_bf16["saldo_e_bf"],
                "valores_restituiveis_exercicio_anterior":    vr_ant,
                "valores_restituiveis_exercicio_atual":       vr_at,
                "saldo_c_bp":  saldo_c_bp,
                "diferenca":   diferenca,
                "situacao":    situacao,
            }
            logger.info("Q16: saldo_c_bf=%.2f saldo_c_bp=%.2f diferenca=%.2f situacao=%s",
                        saldo_c_bf, saldo_c_bp, diferenca, situacao)
        except Exception as exc:
            logger.warning("Extrator Q16 falhou (%s)", exc)

    # Garante ordem numérica
    ORDEM = [f"quadro_{str(i).zfill(2)}" for i in range(1, 30)]
    resultado = {k: resultado[k] for k in ORDEM if k in resultado}

    return resultado, municipio, exercicio


async def _receber_uploads(uploads: dict) -> tuple[list[dict], dict, str]:
    """Salva uploads em tmp e devolve (file_list, enviados, tmp_dir)."""
    enviados = {k: v for k, v in uploads.items() if v is not None}
    if not enviados:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado.")

    tmp_dir = tempfile.mkdtemp()
    file_list = []
    for doc_type, upload in enviados.items():
        dest = Path(tmp_dir) / upload.filename
        content = await upload.read()
        dest.write_bytes(content)
        file_list.append({"filename": upload.filename, "path": str(dest), "doc_type": doc_type})

    return file_list, enviados, tmp_dir


def _uploads_form(
    anx_10_atual:    Optional[UploadFile] = File(None),
    anx_10_anterior: Optional[UploadFile] = File(None),
    anx_12:          Optional[UploadFile] = File(None),
    anx_06:          Optional[UploadFile] = File(None),
    anx_02:          Optional[UploadFile] = File(None),
    anx_13:          Optional[UploadFile] = File(None),
    anx_14:          Optional[UploadFile] = File(None),
    dfc:             Optional[UploadFile] = File(None),
    loa:             Optional[UploadFile] = File(None),
    rgf1quadrimestre: Optional[UploadFile] = File(None),
    rgf2quadrimestre: Optional[UploadFile] = File(None),
    rgf3quadrimestre: Optional[UploadFile] = File(None),
    rgf2semestre:    Optional[UploadFile] = File(None),   # legado (RGF semestral)
    rgf1semestre:    Optional[UploadFile] = File(None),   # legado (RGF semestral)
    bo_fundeb:       Optional[UploadFile] = File(None),
    ff_saude:        Optional[UploadFile] = File(None),
) -> dict:
    return {
        "ANX_10_ATUAL":    anx_10_atual,
        "ANX_10_ANTERIOR": anx_10_anterior,
        "ANX_12":          anx_12,
        "ANX_06":          anx_06,
        "ANX_02":          anx_02,
        "ANX_13":          anx_13,
        "ANX_14":          anx_14,
        "DFC":             dfc,
        "LOA":             loa,
        "RGF_1QUAD":       rgf1quadrimestre,
        "RGF_2QUAD":       rgf2quadrimestre,
        "RGF_3QUAD":       rgf3quadrimestre,
        "RGF_2SEM":        rgf2semestre,
        "RGF_1SEM":        rgf1semestre,
        "BO_FUNDEB":       bo_fundeb,
        "FF_SAUDE":        ff_saude,
    }


@router.post("/gerar")
async def gerar(
    anx_10_atual:    Optional[UploadFile] = File(None),
    anx_10_anterior: Optional[UploadFile] = File(None),
    anx_12:          Optional[UploadFile] = File(None),
    anx_06:          Optional[UploadFile] = File(None),
    anx_02:          Optional[UploadFile] = File(None),
    anx_13:          Optional[UploadFile] = File(None),
    anx_14:          Optional[UploadFile] = File(None),
    dfc:             Optional[UploadFile] = File(None),
    loa:             Optional[UploadFile] = File(None),
    rgf1quadrimestre: Optional[UploadFile] = File(None),
    rgf2quadrimestre: Optional[UploadFile] = File(None),
    rgf3quadrimestre: Optional[UploadFile] = File(None),
    rgf2semestre:    Optional[UploadFile] = File(None),   # legado (RGF semestral)
    rgf1semestre:    Optional[UploadFile] = File(None),   # legado (RGF semestral)
    bo_fundeb:       Optional[UploadFile] = File(None),
    ff_saude:        Optional[UploadFile] = File(None),
):
    uploads = {
        "ANX_10_ATUAL":    anx_10_atual,
        "ANX_10_ANTERIOR": anx_10_anterior,
        "ANX_12":          anx_12,
        "ANX_06":          anx_06,
        "ANX_02":          anx_02,
        "ANX_13":          anx_13,
        "ANX_14":          anx_14,
        "DFC":             dfc,
        "LOA":             loa,
        "RGF_1QUAD":       rgf1quadrimestre,
        "RGF_2QUAD":       rgf2quadrimestre,
        "RGF_3QUAD":       rgf3quadrimestre,
        "RGF_2SEM":        rgf2semestre,
        "RGF_1SEM":        rgf1semestre,
        "BO_FUNDEB":       bo_fundeb,
        "FF_SAUDE":        ff_saude,
    }

    file_list, enviados, tmp_dir = await _receber_uploads(uploads)
    try:
        resultado, municipio, exercicio = _extrair_todos(file_list)

        if not resultado:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Documentos recebidos: {', '.join(enviados.keys())}. "
                    "Nenhum quadro pôde ser gerado com os documentos enviados."
                ),
            )

        tabelas = _build_tabelas_status(resultado, enviados, file_list)

        filepath = generate_excel(resultado, tabelas, municipio, exercicio)

        response = FileResponse(
            path=str(filepath),
            filename=filepath.name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response.headers["X-Tabelas-Geradas"] = str(len(resultado))
        response.headers["X-Municipio"] = municipio
        return response

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Erro interno em /gerar")
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(exc)}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.post("/dados")
async def dados_json(
    anx_10_atual:    Optional[UploadFile] = File(None),
    anx_10_anterior: Optional[UploadFile] = File(None),
    anx_12:          Optional[UploadFile] = File(None),
    anx_06:          Optional[UploadFile] = File(None),
    anx_02:          Optional[UploadFile] = File(None),
    anx_13:          Optional[UploadFile] = File(None),
    anx_14:          Optional[UploadFile] = File(None),
    dfc:             Optional[UploadFile] = File(None),
    loa:             Optional[UploadFile] = File(None),
    rgf1quadrimestre: Optional[UploadFile] = File(None),
    rgf2quadrimestre: Optional[UploadFile] = File(None),
    rgf3quadrimestre: Optional[UploadFile] = File(None),
    rgf2semestre:    Optional[UploadFile] = File(None),   # legado (RGF semestral)
    rgf1semestre:    Optional[UploadFile] = File(None),   # legado (RGF semestral)
    bo_fundeb:       Optional[UploadFile] = File(None),
    ff_saude:        Optional[UploadFile] = File(None),
):
    """Retorna todos os dados extraídos como JSON (mesmos dados que iriam para o Excel)."""
    uploads = {
        "ANX_10_ATUAL":    anx_10_atual,
        "ANX_10_ANTERIOR": anx_10_anterior,
        "ANX_12":          anx_12,
        "ANX_06":          anx_06,
        "ANX_02":          anx_02,
        "ANX_13":          anx_13,
        "ANX_14":          anx_14,
        "DFC":             dfc,
        "LOA":             loa,
        "RGF_1QUAD":       rgf1quadrimestre,
        "RGF_2QUAD":       rgf2quadrimestre,
        "RGF_3QUAD":       rgf3quadrimestre,
        "RGF_2SEM":        rgf2semestre,
        "RGF_1SEM":        rgf1semestre,
        "BO_FUNDEB":       bo_fundeb,
        "FF_SAUDE":        ff_saude,
    }

    file_list, enviados, tmp_dir = await _receber_uploads(uploads)
    try:
        resultado, municipio, exercicio = _extrair_todos(file_list)

        if not resultado:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Documentos recebidos: {', '.join(enviados.keys())}. "
                    "Nenhum quadro pôde ser gerado com os documentos enviados."
                ),
            )

        return JSONResponse(content={
            "municipio":  municipio,
            "exercicio":  exercicio,
            "quadros_gerados": list(resultado.keys()),
            "dados": resultado,
        })

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Erro interno em /dados")
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(exc)}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.post("/relatorio")
async def gerar_relatorio(
    excel: UploadFile = File(...),
):
    """Recebe o Excel atualizado (com campos manuais preenchidos), aciona a IA para
    gerar as ocorrências do RIT e renderiza o template HTML.

    Fluxo:
      1. Lê aba oculta _dados_ → resultado extraído dos PDFs
      2. Lê aba 'Dados Manuais' → campos preenchidos pelo usuário
      3. Chama IA → gera ocorrências em prosa RIT (Seção 6.2)
      4. Renderiza RIT_TEMPLATE.html com todos os dados
      5. Retorna HTML do relatório
    """
    tmp_dir = tempfile.mkdtemp()
    try:
        # Salva Excel em tmp
        dest = Path(tmp_dir) / excel.filename
        content = await excel.read()
        dest.write_bytes(content)

        # 1–2. Lê dados do Excel
        resultado, dados_manuais, municipio, exercicio = ler_excel_atualizado(dest)

        if not resultado:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Não foi possível ler os dados do Excel. "
                    "Certifique-se de que o arquivo foi gerado pelo Kora (aba _dados_ presente)."
                ),
            )

        # 3. Motor de regras (+ refino por IA) → ocorrências RIT (Seção 6.2)
        ocorrencias_rit = gerar_ocorrencias_rit(resultado, municipio, exercicio, dados_manuais)
        if ocorrencias_rit.get("_ia_erro"):
            logger.warning("Refino por IA indisponível: %s", ocorrencias_rit["_ia_erro"])

        # 4–5. Renderiza template
        try:
            html = render_rit(resultado, dados_manuais, ocorrencias_rit, municipio, exercicio)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        from fastapi.responses import HTMLResponse
        return HTMLResponse(
            content=html,
            headers={
                "Content-Disposition": f'inline; filename="RIT_{municipio}_{exercicio}.html"',
                "X-Municipio": municipio,
                "X-Exercicio": exercicio,
                "X-Irregulares": str(ocorrencias_rit.get("resumo", {}).get("irregulares", 0)),
                "X-Alertas":     str(ocorrencias_rit.get("resumo", {}).get("alertas", 0)),
            },
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Erro interno em /relatorio")
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(exc)}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.post("/auditar")
async def auditar(
    anx_10_atual:    Optional[UploadFile] = File(None),
    anx_10_anterior: Optional[UploadFile] = File(None),
    anx_12:          Optional[UploadFile] = File(None),
    anx_06:          Optional[UploadFile] = File(None),
    anx_02:          Optional[UploadFile] = File(None),
    anx_13:          Optional[UploadFile] = File(None),
    anx_14:          Optional[UploadFile] = File(None),
    dfc:             Optional[UploadFile] = File(None),
    loa:             Optional[UploadFile] = File(None),
    rgf1quadrimestre: Optional[UploadFile] = File(None),
    rgf2quadrimestre: Optional[UploadFile] = File(None),
    rgf3quadrimestre: Optional[UploadFile] = File(None),
    rgf2semestre:    Optional[UploadFile] = File(None),   # legado (RGF semestral)
    rgf1semestre:    Optional[UploadFile] = File(None),   # legado (RGF semestral)
    bo_fundeb:       Optional[UploadFile] = File(None),
    ff_saude:        Optional[UploadFile] = File(None),
):
    """Extrai todos os dados dos PDFs e aciona a IA para identificar inconformidades.

    Retorna JSON com:
    - dados: todos os valores extraídos por quadro
    - inconformidades: lista de achados (IRREGULAR / ALERTA) com base legal
    - resumo: contadores e quadros ausentes
    """
    uploads = {
        "ANX_10_ATUAL":    anx_10_atual,
        "ANX_10_ANTERIOR": anx_10_anterior,
        "ANX_12":          anx_12,
        "ANX_06":          anx_06,
        "ANX_02":          anx_02,
        "ANX_13":          anx_13,
        "ANX_14":          anx_14,
        "DFC":             dfc,
        "LOA":             loa,
        "RGF_1QUAD":       rgf1quadrimestre,
        "RGF_2QUAD":       rgf2quadrimestre,
        "RGF_3QUAD":       rgf3quadrimestre,
        "RGF_2SEM":        rgf2semestre,
        "RGF_1SEM":        rgf1semestre,
        "BO_FUNDEB":       bo_fundeb,
        "FF_SAUDE":        ff_saude,
    }

    file_list, enviados, tmp_dir = await _receber_uploads(uploads)
    try:
        resultado, municipio, exercicio = _extrair_todos(file_list)

        if not resultado:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Documentos recebidos: {', '.join(enviados.keys())}. "
                    "Nenhum quadro pôde ser gerado com os documentos enviados."
                ),
            )

        analise = analisar_inconformidades(resultado, municipio, exercicio)

        return JSONResponse(content={
            "municipio":        municipio,
            "exercicio":        exercicio,
            "quadros_gerados":  list(resultado.keys()),
            "dados":            resultado,
            "inconformidades":  analise.get("inconformidades", []),
            "resumo":           analise.get("resumo", {}),
            "data_analise":     analise.get("data_analise", ""),
            **({"_erro_ia": analise["_erro"]} if "_erro" in analise else {}),
        })

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Erro interno em /auditar")
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(exc)}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
