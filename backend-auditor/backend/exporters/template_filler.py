import logging
import re
from pathlib import Path

import openpyxl
from openpyxl import load_workbook
from openpyxl.styles import Alignment

logger = logging.getLogger(__name__)

NUM_FMT     = '"R$ "#,##0.00'
NUM_FMT_PCT = '0.00%'

_PCT_WORDS = ('percentual', 'percent', '_pct', 'pct_')
PLACEHOLDER_RE = re.compile(r"^\{([\w.]+)\}$")


def _resolve(dados: dict, chave: str):
    """Resolve chave simples ou caminho pontilhado (ex: 'receita_tributaria.iptu') em dict aninhado.
    Tenta primeiro a chave literal (cobre casos como 'valor_12.361.0311.2011')."""
    if chave in dados:
        return dados[chave]
    parts = chave.split(".")
    value = dados
    for part in parts:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def get_key_map(template_path: Path) -> dict[str, tuple[int, int]]:
    """
    Lê o template e retorna {chave: (linha, coluna)} para cada célula
    que contenha um placeholder {chave}.
    """
    wb = load_workbook(template_path, data_only=False)
    ws = wb.active
    key_map = {}

    for row in ws.iter_rows():
        for cell in row:
            if cell.value and isinstance(cell.value, str):
                m = PLACEHOLDER_RE.match(cell.value.strip())
                if m:
                    key_map[m.group(1)] = (cell.row, cell.column)

    return key_map


def get_expected_keys(template_path: Path) -> list[str]:
    """Lista ordenada de chaves (pela posição no template) — usada para injetar no prompt."""
    key_map = get_key_map(template_path)
    return sorted(key_map.keys(), key=lambda k: key_map[k])


def fill_template(template_path: Path, dados: dict) -> openpyxl.Workbook:
    """
    Abre o template, substitui cada {placeholder} pelo valor correspondente
    e retorna o workbook preenchido.
    Suporta múltiplas células com o mesmo placeholder no mesmo template.
    """
    wb = load_workbook(template_path)
    ws = wb.active

    # Coleta TODAS as ocorrências de placeholders (incluindo duplicatas)
    all_cells: list[tuple[str, int, int]] = []
    for row in ws.iter_rows():
        for cell in row:
            if cell.value and isinstance(cell.value, str):
                m = PLACEHOLDER_RE.match(cell.value.strip())
                if m:
                    all_cells.append((m.group(1), cell.row, cell.column))

    chaves_unicas = len({c[0] for c in all_cells})
    preenchidos = 0
    for chave, linha, coluna in all_cells:
        valor = _resolve(dados, chave)
        cell = ws.cell(row=linha, column=coluna)

        is_pct_key = any(p in chave.lower() for p in _PCT_WORDS)

        if valor is None:
            cell.value = 0.0
            if cell.number_format in ("General", "@", ""):
                cell.number_format = NUM_FMT_PCT if is_pct_key else NUM_FMT
            cell.alignment = Alignment(horizontal="right")
            logger.debug("Chave '%s' ausente no JSON — preenchido com 0", chave)
            continue

        if isinstance(valor, (int, float)):
            original_fmt = cell.number_format
            val = float(valor)
            if '"%"' in original_fmt:
                # Sufixo % literal: extrator retorna fração (ex: 0.5075) → multiplica por 100
                val = round(val * 100, 4)
            elif '%' in original_fmt:
                # Formato % nativo do Excel: Excel multiplica por 100 ao exibir,
                # mas extratores já retornam em % (ex: 73.49) → divide por 100
                val = round(val / 100, 6)
            elif original_fmt in ("General", "@", "") and is_pct_key:
                # Célula sem formato definida mas chave é percentual:
                # aplicar formato % e converter (extratores retornam em %, ex: 73.49)
                cell.number_format = NUM_FMT_PCT
                val = round(val / 100, 6)
            cell.value = val
            if original_fmt in ("General", "@", "") and not is_pct_key:
                cell.number_format = NUM_FMT
            cell.alignment = Alignment(horizontal="right")
        else:
            cell.value = str(valor)
            cell.alignment = Alignment(horizontal="left")

        preenchidos += 1

    logger.info("Template %s: %d/%d chaves preenchidas (%d células)", template_path.name, preenchidos, chaves_unicas, len(all_cells))
    return wb
