import json
import logging
import re
from datetime import date

import anthropic

from backend.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_MAX_TOKENS
from backend.processors.ocorrencias_engine import detectar_ocorrencias
from pathlib import Path

# Modelo usado para refinar a prosa das ocorrências (redação técnico-jurídica).
CLAUDE_MODEL_OCORRENCIAS = "claude-sonnet-4-6"


def _extrair_json(texto: str) -> dict:
    """Extrai o primeiro objeto JSON de uma resposta da IA.

    Tolera três problemas que quebravam o parsing anterior:
      1. cercas de markdown (```json … ```);
      2. texto/prosa ANTES do JSON;
      3. qualquer explicação DEPOIS do objeto JSON (ex.: "nota técnica",
         comentários) — o caso que fazia o json.loads estourar com
         "Extra data" e derrubava todas as ocorrências para lista vazia.

    Usa raw_decode para ler apenas o 1º objeto e ignorar o que vier depois.
    """
    s = re.sub(r"^```[a-zA-Z]*\n?", "", texto.strip())  # remove cerca de abertura
    inicio = s.find("{")
    if inicio == -1:
        raise ValueError("Resposta da IA não contém objeto JSON.")
    obj, _fim = json.JSONDecoder().raw_decode(s[inicio:])
    return obj


# ── Análise de Inconformidades ────────────────────────────────────────────────

_SYSTEM_INCONFORMIDADES = """
Você é um sistema automatizado de auditoria de contas municipais do TCE-MA.
Sua função é receber os dados financeiros extraídos de uma prestação de contas municipal
e identificar INCONFORMIDADES com a legislação vigente.

REGRAS ABSOLUTAS:
1. Use SOMENTE os valores numéricos presentes no JSON fornecido. Nunca calcule, estime ou invente valores.
2. Para cada inconformidade, cite o campo exato do JSON e o valor encontrado.
3. Não especule sobre dados ausentes (chave não presente no JSON = dado não disponível).
4. Não inclua na lista algo que está conforme — apenas inconformidades reais.

LIMITES LEGAIS A VERIFICAR:

[PESSOAL — quadro_05]
Campo: despesa_com_pessoal.percentual_aplicacao_despesa_pessoal (valor em fração, ex: 0.55 = 55%)
- Acima de 0.60 (60%): IRREGULAR — Base legal: LRF art. 20, III, b
- Entre 0.54 e 0.60 (54%–60%): ALERTA — Base legal: LRF art. 22 (limite prudencial)

[SAÚDE — quadro_18]
Campo: percentual_aplicacao_saude (valor em %)
- Abaixo de 15%: IRREGULAR — Base legal: LC 141/2012 art. 7º

[MDE/EDUCAÇÃO — quadro_20]
Campo: percentual_aplicacao_ensino (valor em %)
- Abaixo de 25%: IRREGULAR — Base legal: CF art. 212 / LDBEN art. 69

[FUNDEB 70% REMUNERAÇÃO — quadro_24]
Campo: percentual_aplicado (valor em %)
- Abaixo de 70%: IRREGULAR — Base legal: Lei 14.113/2020 art. 26, I

[VAAT — quadro_27]
Campo: percentual_aplicado_infantil (valor em %)
- Abaixo de 50%: IRREGULAR — Base legal: Lei 14.113/2020 art. 30, I
Campo: percentual_aplicado_capital (valor em %)
- Abaixo de 15%: IRREGULAR — Base legal: Lei 14.113/2020 art. 30, II

[SUFICIÊNCIA DE CAIXA — quadro_15]
Campo: saldo (valor monetário)
- Negativo (< 0): IRREGULAR — Base legal: LRF art. 42 (insuficiência de caixa)

[RESULTADO FINANCEIRO — quadro_12]
Campo: superavit_deficit_atual (valor monetário)
- Negativo (< 0): ALERTA — indica déficit financeiro no exercício

[RECONCILIAÇÃO DE DEPÓSITOS — quadro_16]
Campo: diferenca (valor monetário)
- Diferente de 0: ALERTA — divergência entre Balanço Financeiro e Balanço Patrimonial

[RESULTADO ORÇAMENTÁRIO — quadro_03]
Campo: resultado_orcamentario.situacao
- Valor "Déficit": ALERTA — execução orçamentária deficitária

FORMATO DE RESPOSTA:
Responda SOMENTE com JSON válido, sem texto antes ou depois, sem ```json:

{
  "inconformidades": [
    {
      "quadro": "<ex: quadro_05>",
      "tipo": "<IRREGULAR | ALERTA>",
      "dimensao": "<Pessoal | Saúde | Educação | FUNDEB | Caixa | Financeiro | Orçamentário | Outros>",
      "campo": "<nome exato do campo no JSON>",
      "valor_apurado": <número ou string exatamente como no JSON>,
      "limite_legal": "<ex: 60% ou R$ 0,00>",
      "base_legal": "<ex: LRF art. 20, III, b>",
      "descricao": "<frase objetiva descrevendo a inconformidade com o valor encontrado>"
    }
  ],
  "resumo": {
    "total_inconformidades": <n>,
    "irregulares": <n>,
    "alertas": <n>,
    "quadros_analisados": <n>,
    "quadros_ausentes": ["<quadro_XX>", ...]
  }
}

Se não houver nenhuma inconformidade, retorne "inconformidades": [].
""".strip()


def analisar_inconformidades(resultado: dict, municipio: str, exercicio: str) -> dict:
    """Envia o JSON completo de dados extraídos para Claude identificar inconformidades.

    Retorna dict com 'inconformidades' e 'resumo'. Em caso de falha, retorna dict com '_erro'.
    """
    if not ANTHROPIC_API_KEY:
        return {'_erro': 'ANTHROPIC_API_KEY não configurada.', 'inconformidades': [], 'resumo': {}}

    quadros_esperados = [f"quadro_{str(i).zfill(2)}" for i in [1, 3, 5, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 27]]
    quadros_ausentes = [q for q in quadros_esperados if q not in resultado]

    dados_json = json.dumps(resultado, ensure_ascii=False, indent=2)

    user_msg = (
        f"Município: {municipio}\n"
        f"Exercício: {exercicio}\n"
        f"Quadros ausentes (documentos não enviados): {', '.join(quadros_ausentes) or 'nenhum'}\n\n"
        "Analise os dados abaixo e identifique todas as inconformidades conforme as regras do sistema:\n\n"
        f"<dados>\n{dados_json}\n</dados>"
    )

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            temperature=0.0,
            system=_SYSTEM_INCONFORMIDADES,
            messages=[{"role": "user", "content": user_msg}],
        )
        texto = "".join(b.text for b in resp.content if b.type == "text")
        analise = _extrair_json(texto)

        # Garante campos mínimos no resumo
        resumo = analise.get("resumo", {})
        incs = analise.get("inconformidades", [])
        resumo.setdefault("total_inconformidades", len(incs))
        resumo.setdefault("irregulares", sum(1 for i in incs if i.get("tipo") == "IRREGULAR"))
        resumo.setdefault("alertas", sum(1 for i in incs if i.get("tipo") == "ALERTA"))
        resumo.setdefault("quadros_analisados", len(resultado))
        resumo.setdefault("quadros_ausentes", quadros_ausentes)
        analise["resumo"] = resumo

        analise["municipio"] = municipio
        analise["exercicio"] = exercicio
        analise["data_analise"] = date.today().isoformat()

        logger.info(
            "Análise de inconformidades: %d irregulares, %d alertas",
            resumo["irregulares"], resumo["alertas"],
        )
        return analise

    except Exception as exc:
        logger.warning("analisar_inconformidades falhou: %s", exc)
        return {
            '_erro': str(exc),
            'municipio': municipio,
            'exercicio': exercicio,
            'inconformidades': [],
            'resumo': {
                'total_inconformidades': 0,
                'irregulares': 0,
                'alertas': 0,
                'quadros_analisados': len(resultado),
                'quadros_ausentes': quadros_ausentes,
            },
        }


# ── Geração de Ocorrências para o RIT (Seção 6.2) ────────────────────────────


_SYSTEM_REFINAR_PROSA = """
Você é um auditor sênior do TCE-MA revisando a redação da Seção 6.2 — Síntese das Ocorrências
de um Relatório de Instrução Técnica (RIT) de Prestação de Contas Municipal.

As ocorrências JÁ FORAM DETECTADAS por um motor de regras determinístico. Sua ÚNICA tarefa é
APRIMORAR A REDAÇÃO (clareza, formalidade, coesão técnico-jurídica) do campo "ocorrencia" de
cada item. Você NÃO decide o que é ou não desconformidade.

REGRAS ABSOLUTAS:
1. NÃO adicione ocorrências novas. NÃO remova ocorrências. Devolva EXATAMENTE os mesmos itens
   (mesmo "item", mesmo "tipo", mesma "fundamentacao", mesma dimensão) que recebeu.
2. NÃO altere valores, percentuais, limites legais ou a fundamentação — apenas melhore a prosa.
3. Preserve todos os números e a base legal EXATAMENTE como fornecidos.
4. Redija em 2–4 frases formais, 3ª pessoa, padrão TCE-MA.

RESPONDA EXCLUSIVAMENTE COM JSON PURO (o 1º caractere deve ser "{"), sem markdown, no formato:
{
  "ocorrencias": {
    "orcamentaria": [ { "item": "6.2.1.1", "tipo": "...", "ocorrencia": "<prosa refinada>", "fundamentacao": "..." } ],
    "financeira": [], "contabil": [], "patrimonial": [], "operacional": []
  }
}
""".strip()


def _refinar_prosa_ia(base: dict, municipio: str, exercicio: str) -> dict | None:
    """Usa a IA para melhorar apenas a redação das ocorrências já detectadas.

    Recebe a estrutura do motor de regras e devolve uma cópia com o campo
    'ocorrencia' reescrito (mesmos itens/tipos/fundamentação). Retorna None se a
    IA falhar ou divergir do conjunto detectado — nesse caso o chamador mantém a
    prosa determinística.
    """
    if not ANTHROPIC_API_KEY:
        return None

    _DIMS = ["orcamentaria", "financeira", "contabil", "patrimonial", "operacional"]
    payload = {
        "ocorrencias": {
            dim: [
                {"item": o["item"], "tipo": o["tipo"],
                 "ocorrencia": o["ocorrencia"], "fundamentacao": o["fundamentacao"]}
                for o in base["ocorrencias"].get(dim, [])
            ]
            for dim in _DIMS
        }
    }
    user_msg = (
        f"Município: {municipio}\nExercício: {exercicio}\n\n"
        "Aprimore a redação do campo 'ocorrencia' de cada item abaixo, sem alterar "
        "itens, tipos, valores ou fundamentação:\n\n"
        f"<ocorrencias>\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n</ocorrencias>"
    )

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=CLAUDE_MODEL_OCORRENCIAS,
            max_tokens=4096,
            temperature=0.0,
            system=_SYSTEM_REFINAR_PROSA,
            messages=[{"role": "user", "content": user_msg}],
        )
        texto = "".join(b.text for b in resp.content if b.type == "text")
        refinado = _extrair_json(texto)

        # Indexa a prosa refinada por 'item' e sobrescreve APENAS o texto,
        # preservando tudo o mais do conjunto determinístico (autoridade).
        prosa_por_item = {}
        for dim in _DIMS:
            for o in refinado.get("ocorrencias", {}).get(dim, []):
                item = o.get("item")
                nova = (o.get("ocorrencia") or "").strip()
                if item and nova:
                    prosa_por_item[item] = " ".join(nova.split())

        if not prosa_por_item:
            return None

        merged = {"ocorrencias": {}, "resumo": dict(base["resumo"])}
        for dim in _DIMS:
            merged["ocorrencias"][dim] = [
                {**o, "ocorrencia": prosa_por_item.get(o["item"], o["ocorrencia"])}
                for o in base["ocorrencias"].get(dim, [])
            ]
        return merged

    except Exception as exc:
        logger.warning("_refinar_prosa_ia falhou (mantendo prosa determinística): %s", exc)
        return None


def gerar_ocorrencias_rit(
    resultado: dict,
    municipio: str,
    exercicio: str,
    dados_manuais: dict | None = None,
) -> dict:
    """Detecta as ocorrências da Seção 6.2 do RIT e devolve prosa técnico-jurídica.

    Pipeline robusto:
      1. Motor de regras determinístico (`detectar_ocorrencias`) decide QUAIS
         ocorrências existem — limites legais fixos sobre os valores extraídos.
         Sempre roda, sem depender de API paga.
      2. Se houver ocorrências e a API estiver disponível, a IA apenas REFINA a
         redação (nunca adiciona/remove). Se a IA falhar, mantém-se a prosa das
         regras — a Seção 6.2 é preenchida de forma confiável em qualquer caso.

    Retorna dict com 'ocorrencias' (por dimensão), 'resumo' e '_fonte'
    ('regras' ou 'regras+ia'); '_ia_erro' quando o refino por IA falhou.
    """
    base = detectar_ocorrencias(resultado, municipio, exercicio, dados_manuais)
    base["_fonte"] = "regras"

    total = base["resumo"]["total_inconformidades"]
    if total == 0:
        logger.info("gerar_ocorrencias_rit: nenhuma desconformidade detectada pelas regras.")
        return base

    refinado = _refinar_prosa_ia(base, municipio, exercicio)
    if refinado is not None:
        refinado["_fonte"] = "regras+ia"
        logger.info(
            "gerar_ocorrencias_rit: %d ocorrências (prosa refinada por IA).", total,
        )
        return refinado

    base["_ia_erro"] = "Refino por IA indisponível — prosa determinística mantida."
    logger.info(
        "gerar_ocorrencias_rit: %d ocorrências (prosa determinística; IA indisponível).", total,
    )
    return base


TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"

logger = logging.getLogger(__name__)

DOC_LABELS = {
    "ANX_10_ATUAL":    "ANEXO 10 — Receita Orçada x Arrecadada (Ano Atual)",
    "ANX_10_ANTERIOR": "ANEXO 10 — Receita Orçada x Arrecadada (Ano Anterior)",
    "ANX_12":          "ANEXO 12 — Balanço Orçamentário",
    "ANX_06":          "ANEXO 06 — Programa de Trabalho",
    "ANX_02":          "ANEXO 02 — Natureza da Despesa por Órgão",
    "ANX_13":          "ANEXO 13 — Balanço Financeiro (MCASP)",
    "ANX_14":          "ANEXO 14 — Balanço Patrimonial",
    "DFC":             "Demonstração dos Fluxos de Caixa",
    "LOA":             "Lei Orçamentária Anual",
}


def build_prompt(docs: dict, tabelas: list[dict]) -> str:
    geraveis = [t for t in tabelas if t["pode_gerar"]]

    lines = []
    lines.append("Você é um especialista em contabilidade pública brasileira (MCASP/DCASP).")
    lines.append("Abaixo estão os textos extraídos dos documentos contábeis de uma prefeitura.")
    lines.append("Processe TODAS as tabelas listadas e retorne um JSON único com todas elas.")
    lines.append("Retorne APENAS JSON válido, sem markdown, sem texto adicional, sem explicações.")
    lines.append("")
    lines.append("=" * 60)
    lines.append("DOCUMENTOS CONTÁBEIS")
    lines.append("=" * 60)
    lines.append("")

    for doc_key, doc_data in docs.items():
        label = DOC_LABELS.get(doc_key, doc_key)
        lines.append(f"--- {label} ---")
        lines.append(doc_data["text"])
        lines.append("")

    lines.append("=" * 60)
    lines.append("TABELAS A GERAR")
    lines.append("=" * 60)
    lines.append("")

    chaves_geraveis = []
    for tabela in geraveis:
        chave = tabela["chave"]
        chave_upper = chave.upper()
        lines.append(f"[{chave_upper}] — {tabela['descricao']}")
        lines.append(tabela["prompt"])

        # Se existe template, injeta as chaves obrigatórias (planas, sem aninhamento)
        template_path = TEMPLATES_DIR / f"{chave}.xlsx"
        if template_path.exists():
            try:
                from backend.exporters.template_filler import get_expected_keys
                keys = get_expected_keys(template_path)
                if keys:
                    lines.append(f"\nATENÇÃO OBRIGATÓRIO para {chave_upper}:")
                    lines.append("Retorne um objeto JSON PLANO (sem nenhum aninhamento) com EXATAMENTE estas chaves:")
                    lines.append(", ".join(keys))
                    lines.append("Não use grupos, não use sub-objetos. Cada chave mapeia diretamente para um número.")
            except Exception:
                pass

        lines.append("")
        chaves_geraveis.append(chave)

    lines.append("=" * 60)
    lines.append("INSTRUÇÃO FINAL")
    lines.append("=" * 60)
    lines.append("Retorne APENAS um JSON válido exatamente neste formato:")

    exemplo = {chave: f"... json completo desta tabela ..." for chave in chaves_geraveis}
    lines.append(json.dumps(exemplo, ensure_ascii=False, indent=2))

    lines.append("")
    lines.append("Regras obrigatórias:")
    lines.append("- Nenhum texto antes ou depois do JSON")
    lines.append("- Nenhum bloco ```json``` ou marcação markdown")
    lines.append("- Valores monetários: sempre número com 2 casas decimais (ex: 1234567.89)")
    lines.append("- Campo não encontrado no documento: usar 0.00")
    lines.append("- Extrair município e exercício do cabeçalho dos documentos")

    return "\n".join(lines)


def call_claude(prompt: str) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    logger.info("Enviando prompt para Claude (%d chars)...", len(prompt))
    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=CLAUDE_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text

    try:
        return _extrair_json(raw)
    except (ValueError, json.JSONDecodeError):
        logger.error("Resposta inválida do Claude (primeiros 500 chars): %s", raw[:500])
        raise ValueError(
            f"Claude retornou resposta que não é JSON válido. "
            f"Início da resposta: {raw[:200]}"
        )


def process(docs: dict, tabelas: list[dict]) -> dict:
    geraveis = [t for t in tabelas if t["pode_gerar"]]

    if not geraveis:
        raise ValueError(
            "Nenhuma tabela pode ser gerada. "
            "Adicione os arquivos .txt de prompt na pasta prompts/ conforme o LEIA-ME.txt."
        )

    logger.info("Gerando %d tabelas em uma única chamada à Claude API...", len(geraveis))
    prompt = build_prompt(docs, tabelas)
    resultado_raw = call_claude(prompt)

    # Filtra para aceitar apenas os quadros que foram solicitados
    # Claude às vezes retorna quadros extras espontaneamente
    chaves_solicitadas = {t["chave"] for t in geraveis}
    resultado = {k: v for k, v in resultado_raw.items() if k in chaves_solicitadas}

    extras = set(resultado_raw.keys()) - chaves_solicitadas
    if extras:
        logger.warning("Claude retornou quadros não solicitados (ignorados): %s", extras)

    logger.info("Claude retornou %d chaves no JSON (%d aceitas)", len(resultado_raw), len(resultado))
    return resultado
