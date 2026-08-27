import logging
import re
from collections import defaultdict

import fitz
import pdfplumber

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


def _linhas_metade(pdf_path: str, lado: str, pagina: int = 0) -> list[str]:
    linhas = []
    with pdfplumber.open(pdf_path) as pdf:
        if pagina >= len(pdf.pages):
            return linhas
        page = pdf.pages[pagina]
        mid = page.width / 2
        region = page.crop((0, 0, mid, page.height) if lado == "esquerda" else (mid, 0, page.width, page.height))
        text = region.extract_text() or ""
        linhas = text.splitlines()
    return linhas


def _palavras_por_lado(pdf_path: str, pagina: int) -> tuple[list[str], list[str]]:
    """PyMuPDF word-level extraction separando colunas pelo centro da página."""
    doc = fitz.open(pdf_path)
    page = doc[pagina]
    mid = page.rect.width / 2
    words = page.get_text("words")
    doc.close()

    esq: dict[int, list] = defaultdict(list)
    dir_: dict[int, list] = defaultdict(list)
    for w in words:
        x0, y0, word = w[0], w[1], w[4]
        y_key = round(y0)
        (esq if x0 < mid else dir_)[y_key].append((x0, word))

    def montar(d: dict) -> list[str]:
        return [" ".join(w for _, w in sorted(d[y])) for y in sorted(d) if d[y]]

    return montar(esq), montar(dir_)


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


def _buscar(linhas: list[str], *termos: str, idx: int = 0) -> float:
    termos_up = [t.upper() for t in termos]
    for line in linhas:
        upper = line.upper()
        if all(t in upper for t in termos_up):
            nums = NUMERO_RE.findall(line)
            if len(nums) > idx:
                return _parse(nums[idx])
    return 0.0


def _row(linhas: list[str], *termos: str, idx_a: int = 0, idx_ant: int = 1) -> dict:
    """Retorna {atual, anterior} da primeira linha com números que contém todos os termos."""
    termos_up = [t.upper() for t in termos]
    for line in linhas:
        upper = line.upper()
        if all(t in upper for t in termos_up):
            nums = NUMERO_RE.findall(line)
            if not nums:
                continue  # pula linhas de cabeçalho sem valores
            return {
                "atual":    _parse(nums[idx_a])  if len(nums) > idx_a  else 0.0,
                "anterior": _parse(nums[idx_ant]) if len(nums) > idx_ant else 0.0,
            }
    return {"atual": 0.0, "anterior": 0.0}


def _total_final(linhas: list[str]) -> dict:
    """Retorna o último TOTAL da lista (o grand total, não TOTAL PASSIVO ou TOTAL PL)."""
    for line in reversed(linhas):
        upper = line.upper()
        if "TOTAL" in upper and "PASSIVO" not in upper and "QUIDO" not in upper:
            nums = NUMERO_RE.findall(line)
            if nums:
                return {
                    "atual":    _parse(nums[0]),
                    "anterior": _parse(nums[1]) if len(nums) > 1 else 0.0,
                }
    return {"atual": 0.0, "anterior": 0.0}


def _extrair_quadro_c(qc_ll: list[str]) -> dict:
    """
    Quadro C tem ATIVO e PASSIVO potenciais na mesma linha de texto:
    'ATOS POTENCIAIS ATIVO 1.436.987,95 0,00 ATOS POTENCIAIS PASSIVO 151.831.623,09 5.248.799,88'
    """
    resultado = {
        "atos_potenciais_ativo":   {"atual": 0.0, "anterior": 0.0},
        "direitos_contratuais":    {"atual": 0.0, "anterior": 0.0},
        "total_ativo_potencial":   {"atual": 0.0, "anterior": 0.0},
        "atos_potenciais_passivo": {"atual": 0.0, "anterior": 0.0},
        "obrigacoes_contratuais":  {"atual": 0.0, "anterior": 0.0},
        "total_passivo_potencial": {"atual": 0.0, "anterior": 0.0},
    }

    for line in qc_ll:
        upper = line.upper()
        nums = NUMERO_RE.findall(line)
        if not nums:
            continue

        # Linha combinada: ATOS POTENCIAIS ATIVO ... ATOS POTENCIAIS PASSIVO ...
        if "ATOS POTENCIAIS ATIVO" in upper and "ATOS POTENCIAIS PASSIVO" in upper:
            resultado["atos_potenciais_ativo"]   = {"atual": _parse(nums[0]) if len(nums) > 0 else 0.0,
                                                    "anterior": _parse(nums[1]) if len(nums) > 1 else 0.0}
            resultado["atos_potenciais_passivo"] = {"atual": _parse(nums[2]) if len(nums) > 2 else 0.0,
                                                    "anterior": _parse(nums[3]) if len(nums) > 3 else 0.0}

        # Linha: DIREITOS CONTRATUAIS ... OBRIGAÇÕES CONVENIADAS ... (mesma linha)
        elif "DIREITOS CONTRATUAIS" in upper:
            resultado["direitos_contratuais"] = {"atual": _parse(nums[0]) if len(nums) > 0 else 0.0,
                                                 "anterior": _parse(nums[1]) if len(nums) > 1 else 0.0}

        # Linha: TOTAL ... OBRIGAÇÕES CONTRATUAIS ...
        elif "TOTAL" in upper and "CONTRAT" in upper:
            resultado["total_ativo_potencial"]  = {"atual": _parse(nums[0]) if len(nums) > 0 else 0.0,
                                                   "anterior": _parse(nums[1]) if len(nums) > 1 else 0.0}
            resultado["obrigacoes_contratuais"] = {"atual": _parse(nums[2]) if len(nums) > 2 else 0.0,
                                                   "anterior": _parse(nums[3]) if len(nums) > 3 else 0.0}

        # Linha: TOTAL 151.831.623,09 5.248.799,88 (somente passivo)
        elif "TOTAL" in upper and "CONTRAT" not in upper and "ATIVO" not in upper:
            resultado["total_passivo_potencial"] = {"atual": _parse(nums[0]) if len(nums) > 0 else 0.0,
                                                    "anterior": _parse(nums[1]) if len(nums) > 1 else 0.0}

    return resultado


def _passivo_financeiro_qb(linhas: list[str]) -> dict:
    """
    Extrai passivo financeiro do Quadro B de forma robusta.

    O PDF pode ter dois formatos na linha "FINANCEIRO":
      - Simples: "PASSIVO FINANCEIRO 8.000.000,00 7.500.000,00"
        → 2 valores: [atual, anterior]
      - Com RP: "FINANCEIRO (8.000.000,00)+RP não Proc.(100,00) 8.000.100,00 7.500.000,00"
        → 4 valores: [sem_rp, rp, total_atual, total_anterior]
        Os dois últimos são os totais corretos.
    """
    for line in linhas:
        if "FINANCEIRO" not in line.upper():
            continue
        nums = NUMERO_RE.findall(line)
        if not nums:
            continue
        parsed = [_parse(n) for n in nums]
        if len(parsed) >= 4:
            # Formato com RP: toma os dois últimos (total atual, total anterior)
            return {"atual": parsed[-2], "anterior": parsed[-1]}
        if len(parsed) >= 2:
            # Formato simples: toma os dois primeiros
            return {"atual": parsed[0], "anterior": parsed[1]}
        if len(parsed) == 1:
            return {"atual": parsed[0], "anterior": 0.0}
    return {"atual": 0.0, "anterior": 0.0}


def _detectar_paginas_bp(pdf_path: str) -> tuple[int, int]:
    """
    Detecta dinamicamente as páginas do Quadro B e Quadro C no BP.
    Retorna (pag_quadro_b, pag_quadro_c).
    Fallback: (1, 2) para PDFs no formato padrão.
    """
    pag_qb = 1
    pag_qc = 2
    with pdfplumber.open(pdf_path) as pdf:
        n = len(pdf.pages)
        for i in range(1, n):
            text = (pdf.pages[i].extract_text() or "").upper()
            if "ATIVO FINANCEIRO" in text or "PASSIVO FINANCEIRO" in text:
                pag_qb = i
                pag_qc = i + 1 if i + 1 < n else i
                break
    return pag_qb, pag_qc


def _pl_extra_linhas(pdf_path: str, pag_inicio: int, pag_fim_exclusivo: int) -> list[str]:
    """
    Retorna linhas das páginas intermediárias entre página 0 e o Quadro B.
    Usado quando o PL ocupa uma página de continuação (formato de 4+ páginas).
    """
    linhas: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for i in range(pag_inicio, min(pag_fim_exclusivo, len(pdf.pages))):
            text = pdf.pages[i].extract_text() or ""
            linhas.extend(text.splitlines())
    return linhas


def extrair(pdf_path: str) -> dict:
    municipio, exercicio = _extrair_cabecalho(pdf_path)

    # ── Página 0: duas colunas (Ativo e Passivo) ──
    ativo_ll   = _linhas_metade(pdf_path, "esquerda", pagina=0)
    passivo_ll = _linhas_metade(pdf_path, "direita",  pagina=0)

    # ── Quadro B: detecta página dinamicamente ──
    pag_qb, pag_qc = _detectar_paginas_bp(pdf_path)

    # Se houver páginas entre a pág 0 e o Quadro B (ex: Apicum tem PL na pág 1),
    # inclui essas linhas no passivo_ll para que _row() encontre o PATRIMÔNIO LÍQUIDO.
    if pag_qb > 1:
        passivo_ll = passivo_ll + _pl_extra_linhas(pdf_path, 1, pag_qb)

    qb_esq, qb_dir = _palavras_por_lado(pdf_path, pagina=pag_qb)

    # ── Quadro C ──
    with pdfplumber.open(pdf_path) as pdf:
        qc_ll = pdf.pages[pag_qc].extract_text().splitlines() if pag_qc < len(pdf.pages) else []

    dados = {
        "municipio": municipio,
        "exercicio": exercicio,

        # ── ATIVO (lado esquerdo, página 1) ──
        "ativo": {
            "ativo_circulante":                      _row(ativo_ll, "ATIVO CIRCULANTE"),
            "caixa_equivalentes_caixa":              _row(ativo_ll, "CAIXA E EQUIVALENTES DE CAIXA"),
            "caixa_moeda_nacional":                  _row(ativo_ll, "MOEDA NACIONAL"),
            "caixa":                                 _row(ativo_ll, "CAIXA F"),
            "conta_unica":                           _row(ativo_ll, "CONTA"),
            "aplicacoes_uso_geral":                  _row(ativo_ll, "USO"),
            "aplicacoes_rpps":                       _row(ativo_ll, "RPPS"),
            # "VINCULADOS" é cortado pelo crop; busca por "CAIXA" + "RESTITU" identifica a linha
            "caixa_valores_restituiveis_vinculados": _row(ativo_ll, "CAIXA", "RESTITU"),
            "outros_valores_restituiveis":           _row(ativo_ll, "OUTROS", "RESTITU"),
            "demais_creditos_curto_prazo":           _row(ativo_ll, "DEMAIS CR"),
            "outros_creditos_receber":               _row(ativo_ll, "OUTROS CR"),
            "valores_transito_realizaveis":          _row(ativo_ll, "TR", "REALIZ"),
            "ativo_nao_circulante":                  _row(ativo_ll, "ATIVO N", "CIRCULANTE"),
            "imobilizado":                           _row(ativo_ll, "IMOBILIZADO"),
            "bens_moveis":                           _row(ativo_ll, "BENS MOVEIS"),
            # Accent issues: MÁQUINAS → "QUINAS"; MÓVEIS → "UTENS"; VEÍCULOS → "CULOS"
            "maquinas_aparelhos":                    _row(ativo_ll, "QUINAS"),
            "moveis_utensilios":                     _row(ativo_ll, "UTENS"),
            "veiculos":                              _row(ativo_ll, "CULOS"),
            # "BENS IM" matches BENS IMÓVEIS first (before sub-items with ANDAMENTO/ESPECIAL)
            "bens_imoveis":                          _row(ativo_ll, "BENS IM"),
            "bens_uso_especial":                     _row(ativo_ll, "USO ESPECIAL"),
            "bens_uso_comum_povo":                   _row(ativo_ll, "USO COMUM"),
            "bens_imoveis_andamento":                _row(ativo_ll, "ANDAMENTO"),
            "demais_bens_imoveis":                   _row(ativo_ll, "DEMAIS BENS"),
            "total":                                 _row(ativo_ll, "TOTAL"),
        },

        # ── PASSIVO (lado direito, página 1) ──
        "passivo": {
            "passivo_circulante":                   _row(passivo_ll, "PASSIVO CIRCULANTE"),
            "obrigacoes_trabalhistas":              _row(passivo_ll, "TRABALHISTAS"),
            "pessoal_pagar":                        _row(passivo_ll, "PESSOAL A PAGAR"),
            "fornecedores_contas_pagar":            _row(passivo_ll, "FORNECEDORES E CONTAS A PAGAR A CURTO"),
            "fornecedores_nacionais":               _row(passivo_ll, "FORNECEDORES NACIONAIS"),
            "adiantamento_clientes_obrigacoes":     _row(passivo_ll, "ADIANTAMENTO"),
            "valores_restituiveis":                 _row(passivo_ll, "VALORES RESTITU"),
            # "CONSIG" (sem acento) encontra "CONSIGNAÇÕES" — retorna o primeiro (maior)
            "consignacoes":                         _row(passivo_ll, "CONSIG"),
            "depositos_judiciais":                  _row(passivo_ll, "DEPOSITOS JUDICIAIS"),
            "outras_obrigacoes_curto_prazo":        _row(passivo_ll, "OUTRAS OBRIG"),
            "transferencias_orcamentarias_liberar": _row(passivo_ll, "LIBERAR"),
            "total_passivo":                        _row(passivo_ll, "TOTAL PASSIVO"),
        },

        # ── PATRIMÔNIO LÍQUIDO (lado direito, página 1) ──
        "patrimonio_liquido": {
            # "LIQUIDO" (sem acento) encontra "PATRIMÔNIO LIQUIDO" (escrito sem acento no PDF)
            "patrimonio_liquido":                       _row(passivo_ll, "LIQUIDO"),
            "resultados_acumulados":                    _row(passivo_ll, "RESULTADOS ACUMULADOS"),
            # "FICITS" + "ACUMUL" → DÉFICITS ACUMULADOS (sem acento em FICITS é suficiente)
            "superavits_deficits_acumulados":           _row(passivo_ll, "FICITS", "ACUMUL"),
            "superavit_deficit_exercicio":              _row(passivo_ll, "DO EXERC"),
            "superavit_deficit_exercicios_anteriores":  _row(passivo_ll, "ANTERIORES"),
            "total_pl":                                 _row(passivo_ll, "TOTAL", "QUIDO"),
            # Grand total no final do lado direito (não é TOTAL PASSIVO nem TOTAL PL)
            "total":                                    _total_final(passivo_ll),
        },

        # ── QUADRO B (página 2, PyMuPDF) ──
        "quadro_b": {
            # qb_esq tem: "ATIVO FINANCEIRO 20.926.930,14 7.566.465,55 PASSIVO"
            "ativo_financeiro":   _row(qb_esq, "ATIVO FINANCEIRO"),
            "ativo_permanente":   _row(qb_esq, "ATIVO PERMANENTE"),
            "passivo_financeiro": _passivo_financeiro_qb(qb_dir),
            "passivo_permanente": _row(qb_dir, "PERMANENTE"),
            "saldo_patrimonial":  _row(qb_dir, "PATRIMONIAL"),
        },

        # ── QUADRO C (página 3, linhas combinadas) ──
        "quadro_c": _extrair_quadro_c(qc_ll),

        # Listas brutas completas (para preview e auditoria completa)
        "_itens_ativo":   _parse_itens(ativo_ll),
        "_itens_passivo": _parse_itens(passivo_ll),
    }

    logger.info(
        "ANX14 BP: ativo=%.2f passivo=%.2f pl=%.2f saldo_patrimonial=%.2f",
        dados["ativo"]["total"]["atual"],
        dados["passivo"]["total_passivo"]["atual"],
        dados["patrimonio_liquido"]["total_pl"]["atual"],
        dados["quadro_b"]["saldo_patrimonial"]["atual"],
    )
    return dados


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
        "ANEXO 14 — BALANÇO PATRIMONIAL",
        f"MUNICÍPIO: {municipio} | EXERCÍCIO: {exercicio}",
    ]

    # ── ATIVO ──
    out += cabecalho_secao("A) ATIVO")
    for item in d["_itens_ativo"]:
        out.append(linha(item["descricao"], item["atual"], item["anterior"]))

    # ── PASSIVO + PL ──
    out += cabecalho_secao("A) PASSIVO E PATRIMÔNIO LÍQUIDO")
    for item in d["_itens_passivo"]:
        out.append(linha(item["descricao"], item["atual"], item["anterior"]))

    # ── QUADRO B ──
    qb = d["quadro_b"]
    out += cabecalho_secao("B) ATIVOS E PASSIVOS FINANCEIROS E PERMANENTES")
    out.append(linha("Ativo Financeiro",   qb["ativo_financeiro"]["atual"],   qb["ativo_financeiro"]["anterior"]))
    out.append(linha("Ativo Permanente",   qb["ativo_permanente"]["atual"],   qb["ativo_permanente"]["anterior"]))
    out.append(linha("Passivo Financeiro", qb["passivo_financeiro"]["atual"], qb["passivo_financeiro"]["anterior"]))
    out.append(linha("Passivo Permanente", qb["passivo_permanente"]["atual"], qb["passivo_permanente"]["anterior"]))
    out.append(linha("Saldo Patrimonial",  qb["saldo_patrimonial"]["atual"],  qb["saldo_patrimonial"]["anterior"]))

    # ── QUADRO C ──
    qc = d["quadro_c"]
    out += cabecalho_secao("C) CONTAS DE COMPENSAÇÃO (CONTROLE)")
    out.append(linha("Atos Potenciais Ativo",    qc["atos_potenciais_ativo"]["atual"],   qc["atos_potenciais_ativo"]["anterior"]))
    out.append(linha("  Direitos Contratuais",   qc["direitos_contratuais"]["atual"],    qc["direitos_contratuais"]["anterior"]))
    out.append(linha("  TOTAL",                  qc["total_ativo_potencial"]["atual"],   qc["total_ativo_potencial"]["anterior"]))
    out.append(linha("Atos Potenciais Passivo",  qc["atos_potenciais_passivo"]["atual"], qc["atos_potenciais_passivo"]["anterior"]))
    out.append(linha("  Obrigações Contratuais", qc["obrigacoes_contratuais"]["atual"],  qc["obrigacoes_contratuais"]["anterior"]))
    out.append(linha("  TOTAL",                  qc["total_passivo_potencial"]["atual"], qc["total_passivo_potencial"]["anterior"]))

    out.append(SEP)
    return "\n".join(out)
