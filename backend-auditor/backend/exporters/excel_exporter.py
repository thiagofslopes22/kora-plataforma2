import json
import logging
import re
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from backend.config import OUTPUT_DIR
from backend.exporters.template_filler import fill_template

# ── Campos para preenchimento manual (aba "Dados Manuais") ───────────────────
# Tupla: (grupo_titulo | None, chave | None, descricao | None, exemplo | None)
# Quando grupo_titulo não é None → linha de cabeçalho de seção; chave=None
_CAMPOS_MANUAIS: list[tuple] = [
    ("IDENTIFICAÇÃO DO PROCESSO", None, None, None),
    (None, "rit_numero",         "Número do RIT",                       "RIT-001/2024"),
    (None, "processo_numero",    "Número do processo",                   "00100-2024"),
    (None, "processo_ano",       "Ano do processo",                      "2024"),
    (None, "relator_nome",       "Nome do relator (TCE)",                "Conselheiro João da Silva"),

    ("RESPONSÁVEL PELO MUNICÍPIO", None, None, None),
    (None, "responsavel_nome",   "Nome do responsável (Prefeito/a)",     "Maria Souza"),
    (None, "responsavel_cpf",    "CPF do responsável",                   "000.000.000-00"),

    ("LOCALIZAÇÃO GEOGRÁFICA", None, None, None),
    (None, "municipio_uf",       "Sigla do estado (ex: MA)",             "MA"),
    (None, "municipio_estado",   "Estado por extenso",                   "Maranhão"),
    (None, "municipio_regiao",   "Mesorregião / região",                 "Baixada Maranhense"),

    ("PERFIL SOCIOECONÔMICO", None, None, None),
    (None, "populacao_estimada", "População estimada (hab.)",            "48000"),
    (None, "area_territorial",   "Área territorial (km²)",               "5273.40"),
    (None, "pib_per_capita",     "PIB per capita (R$)",                  "12300.00"),
    (None, "idh",                "IDH (0,000 a 1,000)",                  "0.619"),
    (None, "classificacao_idh",  "Classificação do IDH",                 "Médio Desenvolvimento"),
    (None, "ideb",               "IDEB (0,0 a 10,0)",                    "4.2"),
    (None, "classificacao_ideb", "Classificação do IDEB",                "Abaixo da Meta Nacional"),
    (None, "descricao_atividades","Principais atividades econômicas",    "Comércio, agropecuária e serviços públicos"),

    ("CÂMARA MUNICIPAL", None, None, None),
    (None, "camara_pct_limite",  "Limite legal da Câmara (% da RCL)",   "3.5"),
    (None, "camara_repassado",   "Valor total repassado à Câmara (R$)", "1500000.00"),
    (None, "camara_pct_apurado", "Percentual apurado (%)",               "3.20"),
    (None, "camara_sit_limite",  "Situação do repasse vs. limite",       "Dentro do limite"),
    (None, "camara_prazo",       "Situação do prazo de repasse",         "Repassado até o dia 20"),

    ("TRANSPARÊNCIA", None, None, None),
    (None, "transp_faixa",       "Faixa de transparência obtida",        "Diamante"),

    ("DÍVIDA CONSOLIDADA (Q7 — preencher manualmente)", None, None, None),
    (None, "divida_saldo",       "Saldo da DCL (R$)",                    "0.00"),
    (None, "divida_pct_rcl",     "DCL apurada (% da RCL)",               "0.00"),
    (None, "divida_limite",      "Limite legal da DCL (% da RCL)",       "120"),
    (None, "divida_alerta",      "Patamar de alerta da DCL (% da RCL)", "90"),
    (None, "divida_situacao",    "Situação da dívida",                   "Dentro do limite"),

    ("DESPESA COM PESSOAL — COMPLEMENTOS", None, None, None),
    (None, "dp_pct_inicio_sem",  "% Pessoal início do 1º semestre",      "51.20"),
    (None, "dp_regime_especial", "Regime especial LRF art. 23 ativo?",   "Não"),
    (None, "dp_restricao_mandato","Observações sobre restrições",        "Não se aplica"),

    ("COMPARATIVO LOA x BALANÇO ORÇAMENTÁRIO (Q11 — preencher se a LOA não foi enviada)", None, None, None),
    (None, "q11_loa_receita",    "Receita prevista na LOA (R$)",         "50000000.00"),
    (None, "q11_loa_despesa",    "Dotação inicial da despesa na LOA (R$)","50000000.00"),

    ("FUNDEB 70% (Q24)", None, None, None),
    (None, "q24_pct_exigido",    "Percentual exigido pelo TCE (%)",      "70"),

    ("PROCESSO ORÇAMENTÁRIO", None, None, None),
    (None, "proc_envio",         "Situação do envio das peças ao TCE",   "Enviado dentro do prazo"),
    (None, "proc_publicacao",    "Situação da publicação da LOA",         "Publicada em 28/12/2023"),

    ("ESCRITURAÇÃO CONTÁBIL", None, None, None),
    (None, "escrit_relatorio",   "Situação do Relatório de Gestão Fiscal","Publicado nos prazos"),
    (None, "escrit_assinatura",  "Situação das assinaturas das peças",   "Devidamente assinadas"),
    (None, "contabil_apres",     "Demonstrações foram apresentadas?",    "Apresentadas"),
    (None, "contabil_conform",   "Conformidade geral da escrituração",   "Conforme"),
    (None, "dep_inconsistencia", "Inconsistência de depósitos (Q16)",    "Sem inconsistência"),

    ("OBSERVAÇÕES GERAIS", None, None, None),
    (None, "obs_gerais",         "Observações adicionais",               ""),
]

TEMPLATES_DIR = OUTPUT_DIR.parent / "templates"

logger = logging.getLogger(__name__)

# ── Paleta Kora — azul (abas de dados) ──────────────────────────────────────
COR_HEADER    = "1E3A5F"
COR_SUBHEADER = "2E86AB"
COR_ALT_ROW   = "F0F4F8"

FILL_HEADER    = PatternFill("solid", fgColor=COR_HEADER)
FILL_SUBHEADER = PatternFill("solid", fgColor=COR_SUBHEADER)
FILL_ALT       = PatternFill("solid", fgColor=COR_ALT_ROW)

FONT_HEADER = Font(bold=True, color="FFFFFF", size=11)
FONT_SUB    = Font(bold=True, color="FFFFFF", size=10)
FONT_NORMAL = Font(size=10)
FONT_BOLD   = Font(bold=True, size=10)

NUM_FMT = '#,##0.00'

# ── Paleta Kora — dourado (aba Status) ───────────────────────────────────────
FILL_KORA_DARK  = PatternFill("solid", fgColor="7B5500")   # cabeçalho título
FILL_KORA_MID   = PatternFill("solid", fgColor="B8860B")   # cabeçalho colunas
FILL_KORA_LIGHT = PatternFill("solid", fgColor="FFF3CD")   # linha alternada

FONT_KORA_TITLE = Font(bold=True, color="FFFFFF", size=13)
FONT_KORA_COL   = Font(bold=True, color="FFFFFF", size=10)

# Status semânticos (aba Status)
FILL_ST_OK        = PatternFill("solid", fgColor="D5E8D4")  # verde  — gerado sem problemas
FILL_ST_ALERTA    = PatternFill("solid", fgColor="FFE6B3")  # âmbar  — atenção / próximo ao limite
FILL_ST_IRREGULAR = PatternFill("solid", fgColor="F8CECC")  # vermelho — abaixo do mínimo / excede limite
FILL_ST_FALTANDO  = PatternFill("solid", fgColor="DAE8FC")  # azul   — documentos faltando
FILL_ST_NAO_IMP   = PatternFill("solid", fgColor="E2E3E5")  # cinza  — não implementado

# ── Regras de alerta por quadro ───────────────────────────────────────────────
# paths: lista de caminhos alternativos no dict resultado (tentados em ordem)
# mult:  multiplicador para converter o valor do extrator em % (1 se já for %, 100 se fração)
# min/max: limite legal; aviso_max: zona de atenção abaixo do máximo
_STATUS_RULES: dict[str, list[dict]] = {
    'quadro_05': [{
        'paths': [
            ('despesa_com_pessoal', 'percentual_aplicacao_despesa_pessoal'),
            ('percentual_aplicacao_despesa_pessoal',),
        ],
        'mult': 100, 'max': 60.0, 'aviso_max': 54.0,
        'label': 'Despesa c/ Pessoal', 'limite': '60% (LRF art. 20)',
    }],
    'quadro_18': [{
        'paths': [('percentual_aplicacao_saude',)],
        'mult': 1, 'min': 15.0,
        'label': 'Aplicação Saúde', 'limite': '15%',
    }],
    'quadro_20': [{
        'paths': [('percentual_aplicacao_ensino',)],
        'mult': 1, 'min': 25.0,
        'label': 'Aplicação MDE', 'limite': '25%',
    }],
    'quadro_24': [{
        'paths': [('percentual_aplicado',)],
        'mult': 1, 'min': 70.0,
        'label': 'FUNDEB 70% Remun.', 'limite': '70%',
    }],
    'quadro_27': [
        {
            'paths': [('percentual_aplicado_infantil',)],
            'mult': 1, 'min': 50.0,
            'label': 'VAAT Infantil', 'limite': '50%',
        },
        {
            'paths': [('percentual_aplicado_capital',)],
            'mult': 1, 'min': 15.0,
            'label': 'VAAT Capital', 'limite': '15%',
        },
    ],
}


def _get_path(d: dict, *keys):
    """Navega dict aninhado por chaves; retorna None se qualquer nível falhar."""
    v = d
    for k in keys:
        if not isinstance(v, dict):
            return None
        v = v.get(k)
    return v if isinstance(v, (int, float)) else None


def _avaliar_quadro(chave: str, dados: dict) -> tuple[str, str]:
    """Avalia o quadro contra limites legais.
    Retorna (nivel, mensagem): nivel = 'ok' | 'alerta' | 'irregular'.
    """
    rules = _STATUS_RULES.get(chave)
    if not rules:
        return 'ok', ''

    msgs_irregular: list[str] = []
    msgs_alerta:    list[str] = []
    msgs_ok:        list[str] = []

    for rule in rules:
        val = None
        for path in rule['paths']:
            val = _get_path(dados, *path)
            if val is not None:
                break
        if val is None:
            continue

        pct = val * rule.get('mult', 1)

        if 'min' in rule:
            lim = rule['min']
            if pct < lim:
                msgs_irregular.append(
                    f"{rule['label']}: {pct:.2f}% — ABAIXO do mínimo de {rule['limite']}"
                )
            else:
                msgs_ok.append(f"{rule['label']}: {pct:.2f}%  ✓")

        if 'max' in rule:
            lim     = rule['max']
            aviso   = rule.get('aviso_max', lim * 0.90)
            if pct > lim:
                msgs_irregular.append(
                    f"{rule['label']}: {pct:.2f}% — EXCEDE limite de {rule['limite']}"
                )
            elif pct >= aviso:
                msgs_alerta.append(
                    f"{rule['label']}: {pct:.2f}% — próximo ao limite de {rule['limite']}"
                )
            else:
                msgs_ok.append(f"{rule['label']}: {pct:.2f}%  ✓")

    if msgs_irregular:
        return 'irregular', '  |  '.join(msgs_irregular + msgs_alerta + msgs_ok)
    if msgs_alerta:
        return 'alerta', '  |  '.join(msgs_alerta + msgs_ok)
    if msgs_ok:
        return 'ok', '  |  '.join(msgs_ok)
    return 'ok', ''


def detect_render_type(data) -> str:
    if isinstance(data, list) and len(data) > 0:
        if all(isinstance(item, dict) for item in data):
            keys = [frozenset(item.keys()) for item in data]
            if all(k == keys[0] for k in keys):
                return "table"
        return "list_blocks"
    if isinstance(data, dict):
        return "nested_dict"
    return "simple"


def _write_nested_dict(ws, data, start_row: int, level: int = 0) -> int:
    row = start_row
    indent = "    " * level

    for key, value in data.items():
        display_key = f"{indent}{key}"

        if isinstance(value, dict):
            cell = ws.cell(row=row, column=1, value=display_key)
            cell.font = FONT_BOLD
            row += 1
            row = _write_nested_dict(ws, value, row, level + 1)

        elif isinstance(value, list):
            ws.cell(row=row, column=1, value=display_key).font = FONT_BOLD
            row += 1
            for i, item in enumerate(value, start=1):
                if isinstance(item, dict):
                    row = _write_nested_dict(ws, item, row, level + 1)
                else:
                    ws.cell(row=row, column=1, value=f"{'    ' * (level + 1)}{i}. {item}").font = FONT_NORMAL
                    row += 1

        elif isinstance(value, (int, float)):
            ws.cell(row=row, column=1, value=display_key).font = FONT_NORMAL
            cell_val = ws.cell(row=row, column=2, value=value)
            cell_val.number_format = NUM_FMT
            cell_val.alignment = Alignment(horizontal="right")
            cell_val.font = FONT_NORMAL
            row += 1

        else:
            ws.cell(row=row, column=1, value=display_key).font = FONT_NORMAL
            cell_val = ws.cell(row=row, column=2, value=str(value) if value is not None else "")
            cell_val.alignment = Alignment(horizontal="left")
            cell_val.font = FONT_NORMAL
            row += 1

    return row


def _write_table(ws, data: list, start_row: int) -> int:
    if not data:
        return start_row

    headers = list(data[0].keys())
    row = start_row

    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=col_idx, value=header)
        cell.fill = FILL_SUBHEADER
        cell.font = FONT_SUB
        cell.alignment = Alignment(horizontal="center")
    row += 1

    for item_idx, item in enumerate(data):
        fill = FILL_ALT if item_idx % 2 == 1 else None
        for col_idx, header in enumerate(headers, start=1):
            value = item.get(header)
            cell = ws.cell(row=row, column=col_idx, value=value)
            cell.font = FONT_NORMAL
            if fill:
                cell.fill = fill
            if isinstance(value, (int, float)):
                cell.number_format = NUM_FMT
                cell.alignment = Alignment(horizontal="right")
            else:
                cell.alignment = Alignment(horizontal="left")
        row += 1

    return row


def _write_list_blocks(ws, data: list, start_row: int) -> int:
    row = start_row
    for i, item in enumerate(data, start=1):
        ws.cell(row=row, column=1, value=f"— Item {i} —").font = FONT_BOLD
        row += 1
        if isinstance(item, dict):
            row = _write_nested_dict(ws, item, row, level=1)
        else:
            ws.cell(row=row, column=1, value=str(item)).font = FONT_NORMAL
            row += 1
        row += 1
    return row


def _write_table_sheet(ws, chave: str, descricao: str, dados):
    ws.merge_cells("A1:D1")
    title_cell = ws["A1"]
    title_cell.value = descricao
    title_cell.fill = FILL_HEADER
    title_cell.font = FONT_HEADER
    title_cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 24

    # Linha 2 em branco
    start_row = 3

    render_type = detect_render_type(dados)
    if render_type == "table":
        _write_table(ws, dados, start_row)
    elif render_type == "nested_dict":
        _write_nested_dict(ws, dados, start_row)
    elif render_type == "list_blocks":
        _write_list_blocks(ws, dados, start_row)
    else:
        ws.cell(row=start_row, column=1, value=str(dados))

    # Ajusta largura das colunas
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            if cell.value:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = min(max_len + 2, 60)


def _write_status_sheet(ws, tabelas: list[dict], resultado: dict,
                        municipio: str = '', exercicio: str = ''):
    NC = 6  # número de colunas

    # ── Pré-computar status de cada linha ─────────────────────────────────────
    rows: list[tuple] = []
    n_gerados = n_alertas = n_irregulares = 0

    for tabela in tabelas:
        chave = tabela["chave"]
        if chave in resultado:
            nivel, obs = _avaliar_quadro(chave, resultado[chave])
            n_gerados += 1
            if nivel == 'irregular':
                n_irregulares += 1
                status_txt = "✗ Irregular"
                st_fill    = FILL_ST_IRREGULAR
            elif nivel == 'alerta':
                n_alertas += 1
                status_txt = "⚠ Alerta"
                st_fill    = FILL_ST_ALERTA
            else:
                status_txt = "✓ Gerado"
                st_fill    = FILL_ST_OK
        elif not tabela["prompt_existe"]:
            obs        = "Extrator ainda não desenvolvido"
            status_txt = "— Não implementado"
            st_fill    = FILL_ST_NAO_IMP
        else:
            obs        = "Faltam: " + ", ".join(tabela["docs_faltando"])
            status_txt = "◌ Docs Faltando"
            st_fill    = FILL_ST_FALTANDO

        rows.append((tabela, status_txt, st_fill, obs))

    total = len(tabelas)

    # ── Linha 1 — Título principal ────────────────────────────────────────────
    ws.merge_cells(f"A1:{get_column_letter(NC)}1")
    cell = ws["A1"]
    cell.value = "KORA  —  Status da Geração de Tabelas"
    cell.fill  = FILL_KORA_DARK
    cell.font  = FONT_KORA_TITLE
    cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 32

    # ── Linha 2 — Resumo executivo ────────────────────────────────────────────
    ws.merge_cells(f"A2:{get_column_letter(NC)}2")
    cell = ws["A2"]
    mun_part = f"{municipio.title()}  ·  Exercício {exercicio}  ·  " if municipio else ""
    irr_part = f"  ·  ✗ Irregulares: {n_irregulares}" if n_irregulares else "  ·  ✓ Sem irregularidades"
    alt_part = f"  ·  ⚠ Alertas: {n_alertas}" if n_alertas else ""
    cell.value = f"{mun_part}Gerados: {n_gerados}/{total}{alt_part}{irr_part}"
    cell.fill  = FILL_KORA_MID
    cell.font  = Font(bold=True, color="FFFFFF", size=11)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 24

    # ── Linha 3 — Separador ───────────────────────────────────────────────────
    ws.row_dimensions[3].height = 6

    # ── Linha 4 — Cabeçalho das colunas ──────────────────────────────────────
    COL_LABELS = ["Nº", "Quadro", "Descrição", "Docs Necessários", "Status", "Resultado / Alerta"]
    for col_idx, label in enumerate(COL_LABELS, start=1):
        cell = ws.cell(row=4, column=col_idx, value=label)
        cell.fill      = FILL_KORA_MID
        cell.font      = FONT_KORA_COL
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[4].height = 20

    # ── Linhas 5+ — Dados ─────────────────────────────────────────────────────
    for i, (tabela, status_txt, st_fill, obs) in enumerate(rows, start=5):
        chave = tabela["chave"]
        num   = chave.replace("quadro_", "").upper()

        row_fill = FILL_KORA_LIGHT if i % 2 == 1 else None

        valores = [
            num,
            chave,
            tabela["descricao"],
            ", ".join(tabela["docs_necessarios"]) or "—",
            status_txt,
            obs,
        ]

        for col_idx, val in enumerate(valores, start=1):
            cell = ws.cell(row=i, column=col_idx, value=val)
            cell.font      = Font(size=10, bold=(col_idx == 5))
            cell.alignment = Alignment(
                horizontal="center" if col_idx in (1, 5) else "left",
                vertical="center",
                wrap_text=(col_idx == 6),
            )
            if col_idx == 5:
                cell.fill = st_fill
            elif row_fill:
                cell.fill = row_fill

        ws.row_dimensions[i].height = 18

    # ── Larguras das colunas ──────────────────────────────────────────────────
    for col_idx, width in enumerate([5, 18, 48, 28, 20, 58], start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = width


def _get_arquivo_prompt(tabela: dict) -> str:
    from backend.processors.prompt_loader import TABELA_CONFIG
    return TABELA_CONFIG.get(tabela["chave"], {}).get("arquivo", "")


def _sanitize_sheet_name(name: str) -> str:
    name = re.sub(r"[/\\*?\[\]]", "", name)
    return name[:28].strip()


def _write_dados_manuais_sheet(ws, municipio: str = "", exercicio: str = "") -> None:
    """Cria a aba 'Dados Manuais' com campos para o usuário preencher antes de gerar o RIT."""
    FILL_TOPO  = PatternFill("solid", fgColor="1E3A5F")
    FILL_SEC   = PatternFill("solid", fgColor="2E86AB")
    FILL_INPUT = PatternFill("solid", fgColor="FFFDE7")
    FILL_HINT  = PatternFill("solid", fgColor="F5F5F5")
    FONT_TOPO  = Font(bold=True, color="FFFFFF", size=12)
    FONT_SEC   = Font(bold=True, color="FFFFFF", size=10)
    FONT_KEY   = Font(size=10)
    FONT_HINT  = Font(italic=True, color="888888", size=9)

    # Cabeçalho geral
    ws.merge_cells("A1:D1")
    ws["A1"].value = f"DADOS PARA PREENCHIMENTO MANUAL — {municipio.upper()}  /  EXERCÍCIO {exercicio}"
    ws["A1"].fill = FILL_TOPO
    ws["A1"].font = FONT_TOPO
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:D2")
    ws["A2"].value = (
        "Preencha a coluna B (VALOR). Após salvar, re-envie este arquivo para gerar o Relatório RIT."
    )
    ws["A2"].font = Font(italic=True, color="555555", size=10)
    ws["A2"].alignment = Alignment(horizontal="center")
    ws.row_dimensions[2].height = 18

    # Cabeçalho das colunas
    for col, label in enumerate(["CAMPO", "VALOR", "DESCRIÇÃO", "EXEMPLO"], start=1):
        c = ws.cell(row=3, column=col, value=label)
        c.fill = FILL_SEC
        c.font = FONT_SEC
        c.alignment = Alignment(horizontal="center")
    ws.row_dimensions[3].height = 20

    row = 4
    for grupo, chave, descricao, exemplo in _CAMPOS_MANUAIS:
        if grupo is not None:
            # Linha de seção
            ws.merge_cells(f"A{row}:D{row}")
            c = ws.cell(row=row, column=1, value=f"  {grupo}")
            c.fill = FILL_SEC
            c.font = FONT_SEC
            c.alignment = Alignment(vertical="center")
            ws.row_dimensions[row].height = 18
        else:
            # Linha de campo
            ws.cell(row=row, column=1, value=chave).font = FONT_KEY
            ws.cell(row=row, column=1).fill = FILL_HINT

            val_cell = ws.cell(row=row, column=2, value="")
            val_cell.fill = FILL_INPUT
            val_cell.alignment = Alignment(horizontal="left")

            ws.cell(row=row, column=3, value=descricao).font = FONT_HINT
            ws.cell(row=row, column=4, value=exemplo).font = FONT_HINT
            ws.row_dimensions[row].height = 16

        row += 1

    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 38
    ws.column_dimensions["C"].width = 42
    ws.column_dimensions["D"].width = 38


def _write_hidden_json_sheet(ws, resultado: dict, municipio: str, exercicio: str) -> None:
    """Armazena o JSON completo extraído em aba oculta para releitura posterior."""
    payload = json.dumps(
        {"resultado": resultado, "municipio": municipio, "exercicio": exercicio},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    # Excel limita célula a ~32k chars; fatia em blocos
    chunk = 30_000
    for i, start in enumerate(range(0, len(payload), chunk), start=1):
        ws.cell(row=i, column=1, value=payload[start:start + chunk])


def generate_excel(resultado: dict, tabelas: list[dict], municipio: str, exercicio: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mun_safe = re.sub(r"[^A-Z0-9]", "_", municipio.upper())[:20] if municipio else "MUNICIPIO"
    filename = f"RIT_{mun_safe}_{exercicio}_{timestamp}.xlsx"
    filepath = OUTPUT_DIR / filename

    wb = Workbook()

    # Aba de status (primeira)
    ws_status = wb.active
    ws_status.title = "Status"
    _write_status_sheet(ws_status, tabelas, resultado, municipio, exercicio)

    # Uma aba por tabela gerada
    tabelas_by_chave = {t["chave"]: t for t in tabelas}
    for chave, dados in resultado.items():
        descricao = tabelas_by_chave.get(chave, {}).get("descricao", chave)
        sheet_name = _sanitize_sheet_name(descricao) or chave

        template_path = TEMPLATES_DIR / f"{chave}.xlsx"
        if template_path.exists():
            try:
                wb_tpl = fill_template(template_path, dados)
                ws_tpl = wb_tpl.active
                ws_tpl.title = sheet_name
                # Copia a aba preenchida para o workbook de saída
                ws_dest = wb.create_sheet(title=sheet_name)
                for row in ws_tpl.iter_rows():
                    for cell in row:
                        new_cell = ws_dest.cell(row=cell.row, column=cell.column, value=cell.value)
                        if cell.has_style:
                            new_cell.font      = cell.font.copy()
                            new_cell.fill      = cell.fill.copy()
                            new_cell.border    = cell.border.copy()
                            new_cell.alignment = cell.alignment.copy()
                            new_cell.number_format = cell.number_format
                # Preserva larguras de coluna e alturas de linha
                for col, dim in ws_tpl.column_dimensions.items():
                    ws_dest.column_dimensions[col].width = dim.width
                for row_n, dim in ws_tpl.row_dimensions.items():
                    ws_dest.row_dimensions[row_n].height = dim.height
                logger.info("Aba '%s' gerada via template", sheet_name)
                continue
            except Exception as exc:
                logger.error("Falha ao usar template para %s: %s — usando fallback", chave, exc)

        ws = wb.create_sheet(title=sheet_name)
        try:
            _write_table_sheet(ws, chave, descricao, dados)
        except Exception as exc:
            logger.error("Erro ao escrever aba %s: %s", chave, exc)
            ws.cell(row=1, column=1, value=f"Erro ao renderizar: {exc}")

    # Aba JSON oculta (para releitura pelo endpoint /relatorio)
    ws_hidden = wb.create_sheet(title="_dados_")
    ws_hidden.sheet_state = "hidden"
    _write_hidden_json_sheet(ws_hidden, resultado, municipio, exercicio)

    # Aba de dados manuais (usuário preenche antes de re-enviar)
    ws_manual = wb.create_sheet(title="Dados Manuais")
    _write_dados_manuais_sheet(ws_manual, municipio, exercicio)

    wb.save(filepath)
    logger.info("Excel salvo em: %s", filepath)
    return filepath
