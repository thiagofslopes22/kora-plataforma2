import re
import logging
from collections import defaultdict

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

NUMERO_RE = re.compile(r'\d{1,3}(?:\.\d{3})*,\d{2}')
ORGAO_RE  = re.compile(r'^(\d{2,4})\s+([A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇa-záàâãéêíóôõúüç ]*)')
CODIGO_RE = re.compile(r'^(\d{1,2}(?:\.\d{1,4}){0,4})\s+')

CAMPOS_ORGAO = {
    '3':   'despesas_correntes',
    '3.1': 'pessoal_encargos',
    '3.3': 'outras_despesas_correntes',
    '4':   'despesas_capital',
    '4.4': 'investimentos',
    '4.6': 'amortizacao_divida',
}


def _parse_br(s: str) -> float:
    return float(s.replace('.', '').replace(',', '.'))


def _agrupar_linhas(pdf_path: str) -> list[str]:
    """
    Extrai palavras com posição e agrupa por linha (tolerância ±3px).
    Deduplica tokens idênticos consecutivos (fonte duplicada no PDF).
    """
    doc = fitz.open(pdf_path)
    all_words: list[tuple[int, float, str]] = []

    for page_idx, page in enumerate(doc):
        for w in page.get_text('words'):
            y_global = page_idx * 10000 + round(w[1])
            all_words.append((y_global, w[0], w[4]))

    doc.close()

    if not all_words:
        return []

    all_words.sort()

    groups: list[list[tuple[float, str]]] = []
    cur_y = all_words[0][0]
    cur_group: list[tuple[float, str]] = [(all_words[0][1], all_words[0][2])]

    for y, x, text in all_words[1:]:
        if y - cur_y <= 3:
            cur_group.append((x, text))
        else:
            groups.append(cur_group)
            cur_group = [(x, text)]
            cur_y = y
    groups.append(cur_group)

    linhas = []
    for grp in groups:
        partes = [t[1] for t in sorted(grp, key=lambda t: t[0])]
        deduped = [partes[0]]
        for p in partes[1:]:
            if p != deduped[-1]:
                deduped.append(p)
        linhas.append(' '.join(deduped))

    return linhas


def _normalizar_linha(linha: str) -> str:
    """Remove espaços internos em fragmentos de código: '3. 1. 90' → '3.1.90'."""
    return re.sub(
        r'^\s*(\d+(?:\s*\.\s*\d+)*)',
        lambda m: m.group(0).replace(' ', ''),
        linha,
    )


def _extrair_cabecalho(linhas: list[str]) -> tuple[str, str, str]:
    municipio = ''
    exercicio = ''
    periodo   = ''

    for i, linha in enumerate(linhas[:60]):
        u = linha.upper()

        if not municipio:
            m = re.search(r'PREFEITURA MUNICIPAL DE (.+)', u)
            if m:
                municipio = m.group(1).strip().split('  ')[0]

        if not exercicio:
            if 'EXERC' in u:
                m = re.search(r'(\d{4})', linha)
                if m:
                    exercicio = m.group(1)
                elif i + 1 < len(linhas):
                    m = re.search(r'(\d{4})', linhas[i + 1])
                    if m:
                        exercicio = m.group(1)

        if not periodo:
            m = re.search(r'(\d{2}/\d{2}/\d{4})\s+AT[EÉ]\s+(\d{2}/\d{2}/\d{4})', linha)
            if m:
                periodo = f"{m.group(1)} ATÉ {m.group(2)}"

    return municipio, exercicio, periodo


def formatar_texto(pdf_path: str) -> str:
    """Retorna texto estruturado e limpo do ANX02 para consumo pela IA."""
    r = extrair(pdf_path)

    out = []
    out.append("ANEXO 02 — NATUREZA DA DESPESA POR ÓRGÃO")
    out.append(f"MUNICÍPIO: {r['municipio']} | EXERCÍCIO: {r['exercicio']} | PERÍODO: {r['periodo']}")
    out.append(f"TOTAL GERAL: {r['total_geral']:,.2f}")
    out.append("")

    for cod, orgao in r['orgaos'].items():
        out.append(f"{'='*70}")
        out.append(f"ÓRGÃO {cod} — {orgao['nome']} | TOTAL: {orgao['total']:,.2f}")
        out.append(f"  Despesas Correntes:         {orgao['despesas_correntes']:>18,.2f}")
        out.append(f"  Pessoal e Encargos:         {orgao['pessoal_encargos']:>18,.2f}")
        out.append(f"  Outras Despesas Correntes:  {orgao['outras_despesas_correntes']:>18,.2f}")
        out.append(f"  Despesas de Capital:        {orgao['despesas_capital']:>18,.2f}")
        out.append(f"  Investimentos:              {orgao['investimentos']:>18,.2f}")
        out.append(f"  Amortização da Dívida:      {orgao['amortizacao_divida']:>18,.2f}")
        out.append("")

    itens_orgao: dict[str, list] = {}
    for item in r['itens']:
        itens_orgao.setdefault(item['orgao_codigo'], []).append(item)

    for cod, itens in itens_orgao.items():
        orgao_nome = r['orgaos'].get(cod, {}).get('nome', cod)
        out.append(f"DETALHAMENTO — ÓRGÃO {cod} {orgao_nome}")
        out.append(f"  {'CÓDIGO':<22} {'NIV'} {'VALOR':>16}  DESCRIÇÃO")
        out.append("  " + "-"*80)
        for item in itens:
            indent = "  " * (item['nivel'] - 1)
            out.append(f"  {item['codigo']:<22}  {item['nivel']}  {item['valor']:>16,.2f}  {indent}{item['descricao'][:50]}")
        out.append("")

    return "\n".join(out)


_ELEMENTO_RE    = re.compile(r'^\d\.\d\.\d{2}\.\d{2}(?:\.\d{2})?$')
_PODER_ORGAO_RE = re.compile(r'^\d{4}$')
_VALOR_RE       = re.compile(r'^-?\d{1,3}(?:\.\d{3})*,\d{2}$')
# Primeiros 2 dígitos da coluna "Poder/Órgão" = Poder (padrão TCE/MA)
_NOMES_PODER    = {'01': 'PODER LEGISLATIVO', '02': 'PODER EXECUTIVO'}


def _eh_demonstrativo_por_fonte(pdf_path: str) -> bool:
    """'Demonstrativo Nº 3 — Despesa segundo a Categoria Econômica por Fonte de Recursos'
    (IN TCE/MA 083): uma linha por Poder/Órgão × Unidade × Elemento × Fonte, com colunas
    Dotação Inicial | Créditos Adicionais | Dotação Atualizada | Liquidado | Pago. Alguns
    municípios (ex.: Magalhães de Almeida) enviam este no lugar do Anexo 02 da Lei 4.320."""
    doc = fitz.open(pdf_path)
    try:
        texto = doc[0].get_text('text').upper()
    finally:
        doc.close()
    return 'POR FONTE DE RECURSOS' in texto and 'LIQUIDADO' in texto and 'ELEMENTO' in texto


def _extrair_demonstrativo_por_fonte(pdf_path: str) -> dict:
    """Lê o Demonstrativo por Fonte pela posição das colunas e devolve a mesma estrutura do
    Anexo 02 consolidado (órgão '00' + itens). O valor de cada elemento é a coluna LIQUIDADO —
    este demonstrativo não tem coluna de Empenhado."""
    doc = fitz.open(pdf_path)
    acum: dict[tuple[str, str], float] = defaultdict(float)
    total_doc = None
    x_liq = None
    for page in doc:
        words = page.get_text('words')
        for w in words:
            if w[4].upper() == 'LIQUIDADO':
                x_liq = w[2]
        if x_liq is None:
            continue
        # Agrupa palavras por linha (tolerância de 3px no topo)
        linhas: list[list] = []
        for w in sorted(words, key=lambda w: w[1]):
            if linhas and w[1] - linhas[-1][0][1] <= 3:
                linhas[-1].append(w)
            else:
                linhas.append([w])
        for ws in linhas:
            ws.sort(key=lambda w: w[0])
            textos = [w[4] for w in ws]
            if textos and textos[0].upper() == 'TOTAL':
                vals = [w for w in ws if _VALOR_RE.match(w[4])]
                if vals:
                    total_doc = _parse_br(min(vals, key=lambda w: abs(w[2] - x_liq))[4])
                continue
            poder = next((t for t in textos if _PODER_ORGAO_RE.match(t)), None)
            elemento = next((t for t in textos if _ELEMENTO_RE.match(t)), None)
            if not (poder and elemento):
                continue
            # Valor da coluna Liquidado = número alinhado à direita sob o cabeçalho
            vals = [w for w in ws if _VALOR_RE.match(w[4]) and abs(w[2] - x_liq) < 25]
            if not vals:
                continue
            acum[(poder[:2], elemento)] += _parse_br(vals[0][4])
    doc.close()

    def _novo_orgao(nome: str) -> dict:
        return {'nome': nome, 'total': 0.0,
                'despesas_correntes': 0.0, 'pessoal_encargos': 0.0, 'outras_despesas_correntes': 0.0,
                'despesas_capital': 0.0, 'investimentos': 0.0, 'amortizacao_divida': 0.0}

    # O Quadro 5 usa o município CONSOLIDADO (Legislativo + Executivo), como no Anexo 02
    # da Lei 4.320 — que não separa os Poderes. A abertura por Poder fica em 'poderes'.
    consolidado = _novo_orgao('CONSOLIDADO')
    poderes: dict[str, dict] = {}
    por_elemento: dict[str, float] = defaultdict(float)
    for (poder, elemento), valor in sorted(acum.items()):
        p = poderes.setdefault(poder, _novo_orgao(_NOMES_PODER.get(poder, f'ÓRGÃO {poder}')))
        for prefixo, campo in CAMPOS_ORGAO.items():
            if elemento == prefixo or elemento.startswith(prefixo + '.'):
                p[campo] = round(p[campo] + valor, 2)
                consolidado[campo] = round(consolidado[campo] + valor, 2)
        por_elemento[elemento] += valor
    for o in (consolidado, *poderes.values()):
        o['total'] = round(o['despesas_correntes'] + o['despesas_capital'], 2)
    orgaos = {'00': consolidado}
    itens = [{
        'orgao_codigo': '00', 'orgao_nome': 'CONSOLIDADO', 'codigo': elemento,
        'descricao': '', 'valor': round(valor, 2), 'nivel': elemento.count('.') + 1,
    } for elemento, valor in sorted(por_elemento.items())]

    total_geral = round(sum(o['total'] for o in orgaos.values()), 2)
    if total_doc is not None and abs(total_doc - total_geral) > 0.01:
        logger.warning("ANX_02 (demonstrativo por fonte): soma dos elementos %.2f ≠ Total do documento %.2f",
                       total_geral, total_doc)
    logger.info("ANX_02 (demonstrativo por fonte, coluna Liquidado): consolidado pessoal=%.2f; por Poder: %s",
                consolidado['pessoal_encargos'], {k: (v['nome'], v['pessoal_encargos']) for k, v in poderes.items()})
    return {
        'municipio':   '',
        'exercicio':   '',
        'periodo':     '',
        'orgaos':      orgaos,
        'total_geral': total_geral,
        'total_documento': total_doc,
        'itens':       itens,
        'poderes':     poderes,
        'formato':     'demonstrativo_por_fonte',
    }


def extrair(pdf_path: str) -> dict:
    """
    Extrai o Anexo 02 e retorna estrutura completa com órgãos, totais e itens.
    """
    if _eh_demonstrativo_por_fonte(pdf_path):
        return _extrair_demonstrativo_por_fonte(pdf_path)

    linhas_raw = _agrupar_linhas(pdf_path)
    municipio, exercicio, periodo = _extrair_cabecalho(linhas_raw)

    orgaos: dict[str, dict] = {}
    orgao_atual: str | None = None
    preenchidos: set[tuple[str, str]] = set()
    itens: list[dict] = []

    for linha_raw in linhas_raw:
        linha = _normalizar_linha(linha_raw)
        nums  = NUMERO_RE.findall(linha)

        # Cabeçalho de órgão verificado ANTES do filtro de números,
        # pois alguns layouts imprimem o total na linha seguinte.
        m_orgao = ORGAO_RE.match(linha)
        if m_orgao:
            codigo_orgao = m_orgao.group(1)
            nome_orgao   = m_orgao.group(2).strip()
            orgao_atual  = codigo_orgao
            # Só cria o dict na primeira vez — páginas seguintes repetem o cabeçalho
            if codigo_orgao not in orgaos:
                valor_orgao = _parse_br(nums[-1]) if nums else 0.0
                orgaos[codigo_orgao] = {
                    'nome':                      nome_orgao,
                    'total':                     valor_orgao,
                    'despesas_correntes':        0.0,
                    'pessoal_encargos':          0.0,
                    'outras_despesas_correntes': 0.0,
                    'despesas_capital':          0.0,
                    'investimentos':             0.0,
                    'amortizacao_divida':        0.0,
                }
                logger.info("Órgão: %s %s — total: %s", codigo_orgao, nome_orgao, valor_orgao)
            continue

        if not nums:
            continue

        valor = _parse_br(nums[-1])

        # Linha de despesa com código contábil
        m_codigo = CODIGO_RE.match(linha)
        if not m_codigo or not orgao_atual:
            continue

        codigo = m_codigo.group(1)
        nivel  = codigo.count('.') + 1

        # Atualiza campo do órgão para os códigos-chave. Vale a 1ª ocorrência: alguns
        # sistemas repetem o cabeçalho do órgão nas seções "por unidade/subunidade"
        # (ex.: Governador Luiz Rocha) e o "3.1" de cada unidade sobrescrevia o total do órgão.
        if codigo in CAMPOS_ORGAO and orgao_atual in orgaos and (orgao_atual, codigo) not in preenchidos:
            orgaos[orgao_atual][CAMPOS_ORGAO[codigo]] = valor
            preenchidos.add((orgao_atual, codigo))

        # Descrição: texto entre o código e o último número
        pos_fim_codigo = len(codigo)
        pos_num        = linha.rfind(nums[-1])
        descricao      = linha[pos_fim_codigo:pos_num].strip()

        itens.append({
            'orgao_codigo': orgao_atual,
            'orgao_nome':   orgaos.get(orgao_atual, {}).get('nome', ''),
            'codigo':       codigo,
            'descricao':    descricao,
            'valor':        valor,
            'nivel':        nivel,
        })

    # Formato consolidado: nenhum cabeçalho de órgão detectado.
    # Cria órgão sintético "00 CONSOLIDADO" e repassa o documento.
    if not orgaos:
        logger.info(
            "ANX_02: formato consolidado detectado em %s — criando órgão '00 CONSOLIDADO'",
            pdf_path,
        )
        orgaos["00"] = {
            'nome':                      'CONSOLIDADO',
            'total':                     0.0,
            'despesas_correntes':        0.0,
            'pessoal_encargos':          0.0,
            'outras_despesas_correntes': 0.0,
            'despesas_capital':          0.0,
            'investimentos':             0.0,
            'amortizacao_divida':        0.0,
        }
        for linha_raw in linhas_raw:
            linha = _normalizar_linha(linha_raw)
            nums  = NUMERO_RE.findall(linha)
            if not nums:
                continue
            valor = _parse_br(nums[-1])
            m_codigo = CODIGO_RE.match(linha)
            if not m_codigo:
                continue
            codigo = m_codigo.group(1)
            nivel  = codigo.count('.') + 1
            if codigo in CAMPOS_ORGAO:
                orgaos["00"][CAMPOS_ORGAO[codigo]] = valor
            pos_fim_codigo = len(codigo)
            pos_num        = linha.rfind(nums[-1])
            descricao      = linha[pos_fim_codigo:pos_num].strip()
            itens.append({
                'orgao_codigo': '00',
                'orgao_nome':   'CONSOLIDADO',
                'codigo':       codigo,
                'descricao':    descricao,
                'valor':        valor,
                'nivel':        nivel,
            })
        dc  = orgaos["00"]["despesas_correntes"]
        cap = orgaos["00"]["despesas_capital"]
        orgaos["00"]["total"] = round(dc + cap, 2)
        logger.info(
            "ANX_02 CONSOLIDADO: pessoal_encargos=%.2f total=%.2f",
            orgaos["00"]["pessoal_encargos"],
            orgaos["00"]["total"],
        )

    total_geral = round(sum(o['total'] for o in orgaos.values()), 2)

    return {
        'municipio':   municipio,
        'exercicio':   exercicio,
        'periodo':     periodo,
        'orgaos':      orgaos,
        'total_geral': total_geral,
        'itens':       itens,
    }
