import logging
from backend.config import PROMPTS_DIR

logger = logging.getLogger(__name__)

TABELA_CONFIG = {
    "quadro_01":        {"arquivo": "quadro_01.txt",        "docs": ["ANX_10_ANTERIOR"],       "descricao": "Base de Cálculo para Repasse à Câmara Municipal"},
    "quadro_02":        {"arquivo": "quadro_02.txt",        "docs": ["ANX_10_ATUAL"],          "descricao": "Repasses Financeiros à Câmara Municipal (Duodécimo)"},
    "quadro_03":        {"arquivo": "quadro_03.txt",        "docs": ["ANX_12"],                "descricao": "Resultado Orçamentário"},
    "quadro_04":        {"arquivo": "quadro_04.txt",        "docs": ["ANX_10_ATUAL"],          "descricao": "Receita Corrente Líquida"},
    "quadro_05":        {"arquivo": "quadro_05.txt",        "docs": ["ANX_02", "ANX_10_ATUAL"], "descricao": "Despesa com Pessoal"},
    "quadro_06":        {"arquivo": "quadro_06.txt",        "docs": ["RGF_3QUAD", "RGF_2QUAD"], "docs_alternativos": [["RGF_2SEM", "RGF_1SEM"]], "descricao": "Comportamento da Despesa com Pessoal no Exercício"},
    "quadro_07":        {"arquivo": "quadro_07.txt",        "docs": ["RGF_3QUAD"],             "docs_alternativos": [["RGF_2SEM"]], "descricao": "Dívida Consolidada e Mobiliária"},
    "quadro_08":        {"arquivo": "quadro_08.txt",        "docs": ["ANX_12"],                "descricao": "Balanço Orçamentário - Receitas"},
    "quadro_09":        {"arquivo": "quadro_09.txt",        "docs": ["ANX_12"],                "descricao": "Balanço Orçamentário - Despesas"},
    "quadro_10":        {"arquivo": "quadro_10.txt",        "docs": ["ANX_12"],                "descricao": "Efetividade na Arrecadação de Receitas"},
    "quadro_11":        {"arquivo": "quadro_11.txt",        "docs": ["LOA", "ANX_12"],         "descricao": "Comparativo LOA x Balanço Orçamentário"},
    "quadro_12":        {"arquivo": "quadro_12.txt",        "docs": ["ANX_14"],                "descricao": "Apuração do Resultado Financeiro"},
    "quadro_13":        {"arquivo": "quadro_13.txt",        "docs": ["ANX_14"],                "descricao": "Evolução do Patrimônio Líquido"},
    "quadro_14":        {"arquivo": "quadro_14.txt",        "docs": ["DFC"],                   "descricao": "Apuração do Fluxo de Caixa do Período"},
    "quadro_15":        {"arquivo": "quadro_15.txt",        "docs": ["ANX_12", "ANX_14"],      "descricao": "Suficiência de Caixa"},
    "quadro_16":        {"arquivo": "quadro_16.txt",        "docs": ["ANX_13", "ANX_14"],      "descricao": "Análise de Depósitos Restituíveis e Valores Vinculados"},
    "quadro_17":        {"arquivo": "quadro_17.txt",        "docs": ["ANX_10_ATUAL"],          "descricao": "Base de Cálculo do Índice de Saúde"},
    "quadro_18":        {"arquivo": "quadro_18.txt",        "docs": ["ANX_06", "ANX_10_ATUAL"],"descricao": "Despesas com Ações e Serviços de Saúde"},
    "quadro_19":        {"arquivo": "quadro_19.txt",        "docs": ["ANX_10_ATUAL"],          "descricao": "Base de Cálculo do Índice de MDE"},
    "quadro_20":        {"arquivo": "quadro_20.txt",        "docs": ["ANX_06", "ANX_10_ATUAL", "BO_FUNDEB"],"descricao": "Despesas com Manutenção e Desenvolvimento do Ensino (MDE)"},
    "quadro_21":        {"arquivo": "quadro_21.txt",        "docs": ["ANX_10_ATUAL"],          "descricao": "Recursos Destinados à Formação do FUNDEB"},
    "quadro_22":        {"arquivo": "quadro_22.txt",        "docs": ["ANX_10_ATUAL"],                    "descricao": "Transferências de Recursos ao FUNDEB"},
    "quadro_23":        {"arquivo": "quadro_23.txt",        "docs": ["ANX_06"],                          "descricao": "Despesas por Subfunção — Educação Função 12"},
    "quadro_24":        {"arquivo": "quadro_24.txt",        "docs": ["ANX_06", "ANX_10_ATUAL"],          "descricao": "Balanço Geral FUNDEB 70% — Remuneração"},
    "quadro_25":        {"arquivo": "quadro_25.txt",        "docs": ["ANX_06"],                          "descricao": "Balanço Geral FUNDEB 70% — Detalhamento por Ação"},
    "quadro_27":        {"arquivo": "quadro_27.txt",        "docs": ["ANX_06", "ANX_10_ATUAL"],          "descricao": "VAAT — Educação Infantil (50%) e Despesas de Capital (15%)"},
}


def load_prompt(arquivo: str) -> str | None:
    path = PROMPTS_DIR / arquivo
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8").strip()
    return content if content else None


def get_tabelas_disponiveis(docs: dict) -> list[dict]:
    tabelas = []
    for chave, cfg in TABELA_CONFIG.items():
        docs_faltando = [d for d in cfg["docs"] if d not in docs]
        docs_ok = len(docs_faltando) == 0

        # Verifica existência do prompt independente dos documentos disponíveis
        prompt_content = load_prompt(cfg["arquivo"])
        prompt_existe = prompt_content is not None

        pode_gerar = docs_ok and prompt_existe

        # Inclui conteúdo do prompt apenas quando for gerar
        prompt = prompt_content if pode_gerar else None

        tabelas.append({
            "chave": chave,
            "descricao": cfg["descricao"],
            "docs_necessarios": cfg["docs"],
            "docs_faltando": docs_faltando,
            "pode_gerar": pode_gerar,
            "prompt_existe": prompt_existe,
            "prompt": prompt,
        })

    geraveis = sum(1 for t in tabelas if t["pode_gerar"])
    logger.info("%d/%d tabelas podem ser geradas", geraveis, len(tabelas))
    return tabelas
