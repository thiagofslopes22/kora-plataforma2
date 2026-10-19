import re
import logging
from collections import defaultdict

import fitz  # PyMuPDF
import pdfplumber

logger = logging.getLogger(__name__)

NUMERO_RE = re.compile(r'\d{1,3}(?:\.\d{3})*,\d{2}')

# Aceita tanto o formato curto "2001.0000" quanto o código hierárquico completo
# "01.031.0002.2001.0000" ou com subtítulo "2001.0000.0000".
# Opcional: ponto inicial ".2001.0000" (fragmento do PyMuPDF).
ACAO_RE   = re.compile(
    r'^\.?(?:\d{1,2}\.\d{3}\.\d{4}\.)?(\d{4}\.\d{4}(?:\.\d{4})?)\s+'
)

# Regex mais amplo que cobre também códigos iniciados em 2xxx (ex: 2411.00.0.0.00.00)
_ANX10_COD_RE = re.compile(r'^(\d{4}\.\d{2}\.\d\.\d\.\d{2}\.\d{2})')
NIVEL_RE  = re.compile(r'^(\d{2,4})(?!\d)(?!\.)\s+')
ORGAO_RE  = re.compile(r'^(\d+)\s+(.+)')

# Ruído de cabeçalho/rodapé que pode aparecer solto entre linhas de ação (não é
# continuação de descrição, mesmo sem números e sem casar com ação/nível).
_LINHA_RUIDO_RE = re.compile(
    r'P[ÁA]GINA|PREFEITURA MUNICIPAL|PROGRAMA DE TRABALHO|CONSOLIDADO|ESPECIFICACAO|'
    r'C[ÓO]DIGO|EXERC[IÍ]CIO|BALAN[ÇC]O|^ANEXO\b|^T\s*O\s*T\s*A\s*L\s*$',
    re.IGNORECASE,
)


def _parse_br(s: str) -> float:
    return float(s.replace('.', '').replace(',', '.'))


def _agrupar_linhas(page) -> list[str]:
    """Agrupa palavras por linha (tolerância ±3px) e deduplica tokens consecutivos idênticos."""
    groups: dict[int, list[tuple[float, str]]] = defaultdict(list)
    for w in page.get_text('words'):
        groups[round(w[1])].append((w[0], w[4]))

    linhas = []
    for y in sorted(groups):
        partes = [t[1] for t in sorted(groups[y], key=lambda t: t[0])]
        deduped = [partes[0]]
        for p in partes[1:]:
            if p != deduped[-1]:
                deduped.append(p)
        linhas.append(' '.join(deduped))
    return linhas


def _normalizar(linha: str) -> str:
    """Remove espaços internos em fragmentos de código: '3. 1. 90' → '3.1.90'."""
    return re.sub(
        r'^\s*(\d+(?:\s*\.\s*\d+)*)',
        lambda m: m.group(0).replace(' ', ''),
        linha,
    )


def _extrair_cabecalho(linhas: list[str]) -> tuple[str, str, str]:
    municipio, exercicio, periodo = '', '', ''
    for i, linha in enumerate(linhas[:20]):
        u = linha.upper()
        if not municipio:
            m = re.search(r'PREFEITURA MUNICIPAL DE (.+)', u)
            if m:
                municipio = m.group(1).strip().split('  ')[0]
        if not exercicio and 'EXERC' in u:
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


_ORGAO_HDR_RE     = re.compile(r'org[aã]o\s*:', re.IGNORECASE)
_UNIDADE_HDR_RE   = re.compile(r'unidade\s+or[cç]ament[aá]ria\s*:', re.IGNORECASE)
_ORGAO_COD_RE_EXT = re.compile(r'^(\d{1,4})\s+(.+)')


def _processar_pagina(linhas: list[str]) -> dict | None:
    """Processa uma página (= uma Unidade Orçamentária) e retorna seus dados."""
    orgao_codigo = orgao_nome = ''
    unidade_codigo = unidade_nome = ''

    # Extrai cabeçalho da página: Orgao e Unidade Orcamentaria
    # Aceita variações de acento e capitalização (ex: "Orgao:", "Órgão:", "ORGÃO:")
    for i, linha in enumerate(linhas):
        stripped = linha.strip()
        if _ORGAO_HDR_RE.search(stripped):
            # O código/nome pode estar na mesma linha após ":" ou na próxima linha
            resto = _ORGAO_HDR_RE.split(stripped, maxsplit=1)[-1].strip()
            candidato = resto if resto else (linhas[i + 1].strip() if i + 1 < len(linhas) else '')
            m = _ORGAO_COD_RE_EXT.match(candidato)
            if m:
                orgao_codigo = m.group(1)
                orgao_nome = m.group(2).strip()
        elif _UNIDADE_HDR_RE.search(stripped):
            resto = _UNIDADE_HDR_RE.split(stripped, maxsplit=1)[-1].strip()
            candidato = resto if resto else (linhas[i + 1].strip() if i + 1 < len(linhas) else '')
            m = _ORGAO_COD_RE_EXT.match(candidato)
            if m:
                unidade_codigo = m.group(1)
                unidade_nome = m.group(2).strip()
        if orgao_codigo and unidade_codigo:
            break

    if not orgao_codigo:
        return None

    # Processa linhas para extrair hierarquia e ações
    func_atual = subfunc_atual = prog_atual = ''
    prog_atual_desc = ''
    acoes: list[dict] = []
    total_projetos = total_atividades = total_geral = 0.0

    for linha in linhas:
        linha_norm = _normalizar(linha)
        nums = NUMERO_RE.findall(linha_norm)

        # Linha TOTAL da unidade (ignora TOTAL GERAL do documento)
        stripped_norm = linha_norm.strip()
        if stripped_norm.startswith('TOTAL ') and 'GERAL' not in stripped_norm.upper() and nums:
            total_geral = _parse_br(nums[-1])
            if len(nums) >= 2:
                total_atividades = _parse_br(nums[-2])
            if len(nums) >= 3:
                total_projetos = _parse_br(nums[-3])
            continue

        # Linha de ação: padrão DDDD.DDDD
        m_acao = ACAO_RE.match(linha_norm)
        if m_acao:
            sufixo = m_acao.group(1)
            if func_atual and subfunc_atual and prog_atual:
                codigo = f"{func_atual}.{subfunc_atual}.{prog_atual}.{sufixo}"
            else:
                codigo = sufixo  # fallback sem contexto hierárquico

            total_acao = _parse_br(nums[-1]) if nums else 0.0

            pos_fim = len(sufixo)
            if nums:
                # Usa a posição do PRIMEIRO número (não do último) para delimitar a
                # descrição: quando "Atividades" e "Total" saem com o mesmo valor
                # (colunas duplicadas), rfind(nums[-1]) captura a 2ª ocorrência e o
                # valor da 1ª acaba embutido no meio da descrição.
                pos_num = linha_norm.find(nums[0])
                pos_fim_ultimo_num = linha_norm.rfind(nums[-1]) + len(nums[-1])
                descricao = linha_norm[pos_fim:pos_num].strip()
                # Texto após o último número (ex.: "%" que o PDF empurra pro fim da
                # linha, separado do "30"/"70" que o precede) pertence à descrição —
                # sem isso, rótulos como "FUNDEB - 30%" viram "FUNDEB - 30" e a
                # classificação por rótulo (`_classificar_fundeb70`) nunca bate.
                resto = linha_norm[pos_fim_ultimo_num:].strip()
                if resto and not NUMERO_RE.search(resto):
                    descricao = f"{descricao} {resto}".strip()
            else:
                descricao = linha_norm[pos_fim:].strip()

            # Projetos/atividades: best-effort pelo número de valores na linha
            if len(nums) == 3:
                projetos   = _parse_br(nums[0])
                atividades = _parse_br(nums[1])
            elif len(nums) == 2:
                # Dois números iguais pós-dedup indica atividades=total ou projetos=total
                # Sem posição X não há como distinguir — inferir pelo contexto omitido
                projetos   = 0.0
                atividades = _parse_br(nums[0])
            else:
                projetos = atividades = 0.0

            acoes.append({
                'codigo':          codigo,
                'descricao':       descricao,
                'projetos':        projetos,
                'atividades':      atividades,
                'total':           total_acao,
                # Título do programa-pai (nível de 4 dígitos, ex.: "0027 MANUT. FUNDEB 70%").
                # Usado para herdar classificação 70%/30% quando a ação-filha não rotula.
                'programa_titulo': prog_atual_desc,
            })
            continue

        # Níveis hierárquicos (função, subfunção, programa)
        m_nivel = NIVEL_RE.match(linha_norm)
        if m_nivel:
            cod = m_nivel.group(1)
            n = len(cod)
            if n == 2:
                func_atual      = cod
                subfunc_atual   = ''
                prog_atual      = ''
                prog_atual_desc = ''
            elif n == 3:
                subfunc_atual   = cod
                prog_atual      = ''
                prog_atual_desc = ''
            elif n == 4:
                prog_atual      = cod
                prog_atual_desc = linha_norm[m_nivel.end():].strip()
            continue

        # Continuação de descrição quebrada em múltiplas linhas pelo PDF (ex.: o rótulo
        # "70%"/"30%" cai sozinho na linha seguinte à ação). Reconstrói antes de classificar.
        texto_cont = stripped_norm
        if (
            acoes
            and texto_cont
            and not nums
            and not _ORGAO_HDR_RE.search(texto_cont)
            and not _UNIDADE_HDR_RE.search(texto_cont)
            and not _LINHA_RUIDO_RE.search(texto_cont)
        ):
            acoes[-1]['descricao'] = (acoes[-1]['descricao'] + ' ' + texto_cont).strip()

    return {
        'orgao_codigo':    orgao_codigo,
        'orgao_nome':      orgao_nome,
        'unidade_codigo':  unidade_codigo,
        'unidade_nome':    unidade_nome,
        'total_projetos':  total_projetos,
        'total_atividades': total_atividades,
        'total_geral':     total_geral,
        'acoes':           acoes,
    }


def _extrair_total_geral(linhas: list[str]) -> tuple[float, float, float] | None:
    """Procura linha 'TOTAL GERAL' com 3 valores — aparece na última página."""
    for linha in linhas:
        if 'TOTAL GERAL' in linha.upper():
            nums = NUMERO_RE.findall(linha)
            if len(nums) >= 3:
                return _parse_br(nums[-3]), _parse_br(nums[-2]), _parse_br(nums[-1])
            elif len(nums) == 1:
                return 0.0, 0.0, _parse_br(nums[-1])
    return None


def _sus_arrecadada(anx10_path: str, codigo: str) -> float:
    """
    Extrai ARRECADADA de um código do Anexo 10.
    Regra crítica: 2 valores iguais na linha → arrecadada = 0,00 (nada arrecadado).
    """
    with pdfplumber.open(anx10_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                stripped = line.strip()
                m = _ANX10_COD_RE.match(stripped)
                if not m or m.group(1) != codigo:
                    continue
                nums = NUMERO_RE.findall(stripped)
                if len(nums) >= 3:
                    return _parse_br(nums[1])
                if len(nums) == 2:
                    return 0.0 if nums[0] == nums[1] else _parse_br(nums[1])
    return 0.0


# "VAAT" pode chegar quebrado pelo PDF (ex.: "VA AT", "V AAT") — mesma tolerância a
# espaços internos usada nos rótulos "70%"/"30%" (_ROTULO_70_RE). Sem isso, ações VAAT
# legítimas (ex.: 12.365.0314.2502 de Pinheiro, "...RECURSO DO VA AT 50%") ficariam de fora.
_VAAT_RE = re.compile(r'V\s*A\s*A\s*T')


def _eh_unidade_fundeb(nome_u: str) -> bool:
    """Identifica a(s) unidade(s) orçamentária(s) do FUNDEB pelo nome (Passo 1 do prompt).

    Case-insensitive; cobre variações comuns de nomenclatura entre municípios.
    Pode haver mais de uma unidade — o chamador deve iterar todas, não parar na primeira.
    """
    nu = nome_u.upper()
    if 'FUNDEB' in nu or 'FMDE' in nu:
        return True
    if 'FUNDO DE MANUT' in nu and 'EDUCA' in nu:
        return True
    if 'MANUTENCAO E DESENVOLVIMENTO DA EDUCACAO BASICA' in _sem_acento(nu):
        return True
    return False


def formato_incompativel(pdf_path: str) -> str | None:
    """Motivo pelo qual o PDF NAO e um Anexo 6 'Programa de Trabalho', ou None se for.

    Os quadros 18/20/23/24/25/27 precisam de Orgao > Unidade > Funcao/Subfuncao > Acao.
    Alguns sistemas contabeis emitem como 'Anexo 06' o demonstrativo 'Despesa por
    Funcoes e Categorias Economicas', que so agrupa por funcao — sem subfuncao nem
    acao. Extrair dele gera percentuais absurdos (ex.: saude negativa).
    """
    doc = fitz.open(pdf_path)
    try:
        texto = _sem_acento(" ".join(p.get_text("text") for p in doc).upper())
    finally:
        doc.close()
    if "UNIDADE ORCAMENTARIA" in texto:
        return None
    if "FUNCOES E CATEGORIAS ECONOMICAS" in texto:
        return ("formato incompatível: é o 'Despesa por Funções e Categorias Econômicas'; "
                "envie o Anexo 6 'Programa de Trabalho' (por Órgão/Unidade/Ação)")
    return ("formato não reconhecido: o Anexo 6 precisa ser o 'Programa de Trabalho' "
            "(com Órgão e Unidade Orçamentária)")


def _sem_acento(s: str) -> str:
    """Normaliza acentos comuns em maiúsculas para comparação tolerante a mojibake do PDF."""
    trocas = str.maketrans('ÁÀÃÂÉÊÍÓÕÔÚÇ', 'AAAAEEIOOOUC')
    return s.translate(trocas)


# ── Quadro 25 — rubricas canônicas FUNDEB 70% por FUNÇÃO.SUBFUNÇÃO ─────────────
# Cada município numera PROGRAMA/AÇÃO à sua maneira, mas FUNÇÃO.SUBFUNÇÃO (os 7
# primeiros dígitos do código, ex. "12.361") é padronizado nacionalmente pelo
# MCASP/Portaria STN — é nisso que a classificação abaixo se ancora, junto com
# palavras-chave da descrição (não no código completo de programa/ação).
_RUBRICAS_FUNDEB70_EDUC_ORDEM = [
    'FUND_70_MANUT_FUNDAMENTAL',
    'FUND_70_REMUN_DOCENTES_FUNDAMENTAL',
    'FUND_70_TEMPO_INTEGRAL_FUNDAMENTAL',
    'FUND_70_MANUT_INFANTIL',
    'FUND_70_VAAT50_INFANTIL',
    'FUND_70_REMUN_DOCENTES_INFANTIL',
    'FUND_70_TEMPO_INTEGRAL_INFANTIL',
    'FUND_70_EJA',
    'FUND_70_AEE_EDUC_ESPECIAL',
]

_RUBRICAS_FUNDEB70_EDUC_LABEL = {
    'FUND_70_MANUT_FUNDAMENTAL':          'Manutenção e Desenvolvimento do Ensino Fundamental',
    'FUND_70_REMUN_DOCENTES_FUNDAMENTAL': 'Remuneração dos Docentes — Ensino Fundamental',
    'FUND_70_TEMPO_INTEGRAL_FUNDAMENTAL': 'Tempo Integral — Ensino Fundamental',
    'FUND_70_MANUT_INFANTIL':             'Manutenção e Desenvolvimento da Educação Infantil',
    'FUND_70_VAAT50_INFANTIL':            'VAAT 50% — Educação Infantil',
    'FUND_70_REMUN_DOCENTES_INFANTIL':    'Remuneração dos Docentes — Educação Infantil',
    'FUND_70_TEMPO_INTEGRAL_INFANTIL':    'Tempo Integral — Educação Infantil',
    'FUND_70_EJA':                        'Educação de Jovens e Adultos (EJA)',
    'FUND_70_AEE_EDUC_ESPECIAL':          'Atendimento Educacional Especializado (AEE) / Educação Especial',
}

_RUBRICAS_FUNDEB70_EDUC_SUBFUNCAO = {
    'FUND_70_MANUT_FUNDAMENTAL':          '361',
    'FUND_70_REMUN_DOCENTES_FUNDAMENTAL': '361',
    'FUND_70_TEMPO_INTEGRAL_FUNDAMENTAL': '361',
    'FUND_70_MANUT_INFANTIL':             '365',
    'FUND_70_VAAT50_INFANTIL':            '365',
    'FUND_70_REMUN_DOCENTES_INFANTIL':    '365',
    'FUND_70_TEMPO_INTEGRAL_INFANTIL':    '365',
    'FUND_70_EJA':                        '366',
    'FUND_70_AEE_EDUC_ESPECIAL':          '367',
}


_ROTULO_30_RE = re.compile(r'3\s*0\s*%')
_ROTULO_70_RE = re.compile(r'7\s*0\s*%')


def _classificar_rubrica_fundeb70_educ(
    subfuncao: str, descricao: str, forcar_agregado: bool = False,
) -> tuple[str | None, bool]:
    """Casa uma ação em uma das 9 rubricas canônicas do Q25, por palavras-chave
    dentro da subfunção correspondente (ver tabela acima). Ordem de checagem dentro
    de cada subfunção vai do rótulo mais específico (remuneração/tempo integral/VAAT)
    para o mais genérico (manutenção), para uma ação nunca cair em duas rubricas.

    Retorna (codigo_canonico, segregado). Quando a ação não bate com nenhuma
    palavra-chave específica (ex.: "atividades administrativas do FUNDEB 70%", sem
    mencionar "ensino fundamental"/"infantil" nem remuneração/tempo integral/VAAT
    explicitamente), a rubrica de manutenção correspondente (FUND_70_MANUT_FUNDAMENTAL
    / FUND_70_MANUT_INFANTIL / FUND_70_EJA / FUND_70_AEE_EDUC_ESPECIAL) funciona como
    conta agregada — segregado=False, sem inventar rateio entre as sub-rubricas.

    `forcar_agregado=True` faz o balde agregado valer mesmo sem "70%" no texto da
    própria ação — usado quando o chamador já confirmou por outra via (ex.:
    `_coletar_fundeb70`, que também herda o rótulo do título do programa-pai) que a
    ação é FUNDEB 70%, garantindo que toda ação nas 4 subfunções educacionais caia em
    alguma rubrica e o total bata exatamente com o quadro 24.

    Ações rotuladas "30%" (outras despesas — quadro_26) são explicitamente excluídas
    daqui, mesmo que a subfunção/palavra-chave combine com alguma das 9 rubricas: o
    rótulo do próprio município já diz que aquele valor não é do balde dos 70%.
    """
    d = _sem_acento(descricao.upper())
    rotulado_70 = bool(_ROTULO_70_RE.search(d)) or forcar_agregado
    rotulado_30_only = bool(_ROTULO_30_RE.search(d)) and not _ROTULO_70_RE.search(d)
    if rotulado_30_only:
        return None, False

    if subfuncao == '361':
        if 'REMUNERACAO' in d and ('DOCENTE' in d or 'PROFISSIONAIS DO ENSINO' in d):
            return 'FUND_70_REMUN_DOCENTES_FUNDAMENTAL', True
        if 'TEMPO INTEGRAL' in d:
            return 'FUND_70_TEMPO_INTEGRAL_FUNDAMENTAL', True
        if ('MANUTENCAO' in d or 'DESENVOLVIMENTO' in d) and 'ENSINO FUNDAMENTAL' in d:
            return 'FUND_70_MANUT_FUNDAMENTAL', True
        if 'FUNDEB 70' in d and 'ENSINO FUNDAMENTAL' in d:
            return 'FUND_70_MANUT_FUNDAMENTAL', True
        if rotulado_70:
            return 'FUND_70_MANUT_FUNDAMENTAL', False
        return None, False

    if subfuncao == '365':
        if 'REMUNERACAO' in d and ('DOCENTE' in d or 'PROFISSIONAIS DO ENSINO' in d):
            return 'FUND_70_REMUN_DOCENTES_INFANTIL', True
        if 'TEMPO INTEGRAL' in d:
            return 'FUND_70_TEMPO_INTEGRAL_INFANTIL', True
        if 'VAAT' in d and '50' in d:
            return 'FUND_70_VAAT50_INFANTIL', True
        if ('MANUTENCAO' in d or 'DESENVOLVIMENTO' in d) and (
            'ENSINO INFANTIL' in d or 'PRE ESCOLA' in d or 'CRECHE' in d
        ):
            return 'FUND_70_MANUT_INFANTIL', True
        if rotulado_70:
            return 'FUND_70_MANUT_INFANTIL', False
        return None, False

    if subfuncao == '366':
        if 'EJA' in d or 'JOVENS E ADULTOS' in d or rotulado_70:
            return 'FUND_70_EJA', ('EJA' in d or 'JOVENS E ADULTOS' in d)
        return None, False

    if subfuncao == '367':
        eh_aee = 'AEE' in d or 'EDUCACAO ESPECIAL' in d or 'ATENDIMENTO EDUCACIONAL ESPECIALIZADO' in d
        if eh_aee or rotulado_70:
            return 'FUND_70_AEE_EDUC_ESPECIAL', eh_aee
        return None, False

    return None, False


def _classificar_fundeb70(acao: dict) -> str:
    """Classifica uma ação da unidade FUNDEB em FUNDEB_70 / FUNDEB_30 / CAPITAL / NAO_CLASSIFICADO.

    Ordem de prioridade (Passo 2 do prompt):
    1. "30%" na própria descrição → FUNDEB_30
    2. "70%" na própria descrição → FUNDEB_70
    3. Sem rótulo na própria ação → herda do título do programa-pai (ex.: "0027 MANUT. FUNDEB 70%")
    4. Código da ação (4º bloco) inicia em "1" (Projeto/capital) e sem rótulo → CAPITAL
    5. Nenhuma das anteriores → NAO_CLASSIFICADO (não soma em nenhum bucket)

    Dígitos e "%" são casados com espaço opcional entre eles (`3\\s*0\\s*%`): quando o
    rótulo cai quebrado em duas (ou três) linhas do PDF — comum em Apicum-Açu, onde o
    layout chega a partir "70%" em "...FUNDEB 7" + "0%" — a reconstrução da descrição
    junta os pedaços com espaço no meio em vez de "70%" colado.
    """
    desc = acao.get('descricao', '').upper()
    if _ROTULO_30_RE.search(desc):
        return 'FUNDEB_30'
    if _ROTULO_70_RE.search(desc):
        return 'FUNDEB_70'

    titulo = (acao.get('programa_titulo') or '').upper()
    if _ROTULO_30_RE.search(titulo):
        return 'FUNDEB_30'
    if _ROTULO_70_RE.search(titulo):
        return 'FUNDEB_70'

    parts = acao.get('codigo', '').split('.')
    if len(parts) >= 4 and parts[3].startswith('1'):
        return 'CAPITAL'

    return 'NAO_CLASSIFICADO'


def _coletar_fundeb70(dados: dict) -> dict:
    """Coleta e classifica todas as ações das unidades FUNDEB (Passos 1-3 do prompt).

    Percorre TODAS as unidades cujo nome bate com `_eh_unidade_fundeb` (pode haver mais
    de uma), classifica cada ação em FUNDEB_70/FUNDEB_30/CAPITAL/NAO_CLASSIFICADO e
    confere o cross-check: soma das 4 categorias deve bater com o TOTAL GERAL das unidades.
    """
    buckets: dict[str, dict[str, float]] = {
        'FUNDEB_70': {}, 'FUNDEB_30': {}, 'CAPITAL': {}, 'NAO_CLASSIFICADO': {},
    }
    descricoes: dict[str, str] = {}
    total_geral_unidades = 0.0

    for u in dados.get('unidades', []):
        if not _eh_unidade_fundeb(u.get('unidade_nome', '')):
            continue
        total_geral_unidades = round(total_geral_unidades + u.get('total_geral', 0.0), 2)
        for acao in u.get('acoes', []):
            cod = acao.get('codigo', '')
            val = acao.get('total', 0.0)
            categoria = _classificar_fundeb70(acao)
            buckets[categoria][cod] = round(buckets[categoria].get(cod, 0.0) + val, 2)
            if cod not in descricoes:
                descricoes[cod] = acao.get('descricao', '')

    soma_70   = round(sum(buckets['FUNDEB_70'].values()), 2)
    soma_30   = round(sum(buckets['FUNDEB_30'].values()), 2)
    soma_cap  = round(sum(buckets['CAPITAL'].values()), 2)
    soma_nc   = round(sum(buckets['NAO_CLASSIFICADO'].values()), 2)
    soma_categorias = round(soma_70 + soma_30 + soma_cap + soma_nc, 2)
    diferenca = round(soma_categorias - total_geral_unidades, 2)

    return {
        'fundeb_70':            buckets['FUNDEB_70'],
        'fundeb_30':            buckets['FUNDEB_30'],
        'capital':              buckets['CAPITAL'],
        'nao_classificado':     buckets['NAO_CLASSIFICADO'],
        'descricoes':           descricoes,
        'soma_70':              soma_70,
        'soma_30':              soma_30,
        'soma_capital':         soma_cap,
        'soma_nao_classificado': soma_nc,
        'total_geral_unidades': total_geral_unidades,
        'cross_check_bate':     abs(diferenca) < 0.01,
        'cross_check_diferenca': diferenca,
    }


def _base_calculo_fundeb(anx10_at_path: str = None) -> tuple[float, dict, list[str]]:
    """Base de cálculo comum aos Quadros 24 e 26: receita FUNDEB arrecadada no ANX_10 —
    cota-parte (1751.50) + complementações da União VAAT (1715.50) + VAAF (1715.51) +
    VAAR (1715.52), sempre pela coluna ARRECADADA, código analítico "-PRINCIPAL"
    (0.1.00.00) com fallback pro sintético (0.0.00.00) quando o analítico não existir
    no documento.

    Retorna (base_calculo, receita_detalhe, codigos_ausentes).
    """
    receita_detalhe = {
        'cota_parte_1751':               0.0,
        'complementacao_uniao_1715_vaat': 0.0,
        'complementacao_uniao_1715_vaaf': 0.0,
        'complementacao_uniao_1715_vaar': 0.0,
    }
    codigos_ausentes: list[str] = []

    if not anx10_at_path:
        return 0.0, receita_detalhe, codigos_ausentes

    from backend.extractors.anx10_legislativo import _indexar

    idx = _indexar(anx10_at_path)
    campos = (
        ('cota_parte_1751',               '1751.50'),
        ('complementacao_uniao_1715_vaat', '1715.50'),
        ('complementacao_uniao_1715_vaaf', '1715.51'),
        ('complementacao_uniao_1715_vaar', '1715.52'),
    )
    for chave, prefixo in campos:
        analitico = f'{prefixo}.0.1.00.00'
        sintetico = f'{prefixo}.0.0.00.00'
        if analitico in idx:
            valor = idx[analitico]
        elif sintetico in idx:
            valor = idx[sintetico]
        else:
            valor = 0.0
            codigos_ausentes.append(prefixo)
        receita_detalhe[chave] = valor

    base_calculo = round(sum(receita_detalhe.values()), 2)
    return base_calculo, receita_detalhe, codigos_ausentes


def extrair_fundeb70_balanco(anx06_path: str, anx10_at_path: str = None,
                             bo_fundeb_path: str = None) -> dict:
    """Q24 — Balanço Geral FUNDEB 70% (aplicação em remuneração dos profissionais).

    Classifica as ações do(s) ANX_06 FUNDEB por rótulo textual (70%/30%/capital/não
    classificado), com herança do título do programa-pai quando a ação-filha não rotula
    (ver `_classificar_fundeb70`).

    Base de cálculo do mínimo (decisão do usuário): parte de `_base_calculo_fundeb`
    (cota-parte + VAAT + VAAF + VAAR), INCLUI a receita de aplicação financeira do FUNDEB
    (RECEITA PATRIMONIAL realizada do Balanço isolado — `bo_fundeb_path`) e EXCLUI o VAAR
    (complementação condicionada ao resultado, que não integra o mínimo dos 70%).

    `percentual_exigido` sai em 70% (padrão) e pode ser sobrescrito pelo campo manual
    homônimo no RIT — mínimo, percentual e situação são recalculados lá.
    """
    dados = extrair(anx06_path)
    municipio = dados.get('municipio', '')
    exercicio = dados.get('exercicio', '')

    coleta = _coletar_fundeb70(dados)
    total_fundeb_70 = coleta['soma_70']

    base_bruta, receita_detalhe, codigos_ausentes = _base_calculo_fundeb(anx10_at_path)
    vaar_removido = receita_detalhe.get('complementacao_uniao_1715_vaar', 0.0)
    receita_aplicacao_financeira = 0.0
    if bo_fundeb_path:
        from backend.extractors.bo_fundeb import extrair as extrair_bo_fundeb
        receita_aplicacao_financeira = extrair_bo_fundeb(bo_fundeb_path)['receita_patrimonial_realizada']
    base_calculo = round(base_bruta + receita_aplicacao_financeira - vaar_removido, 2)

    percentual_exigido         = 70.0  # padrão; sobrescrito pelo campo manual no RIT
    minimo_exigido             = round(base_calculo * percentual_exigido / 100, 2)
    rp_sem_disponibilidade     = 0.0
    superavit_exercicio_anterior = 0.0
    valor_aplicado_remuneracao = round(
        total_fundeb_70 - rp_sem_disponibilidade - superavit_exercicio_anterior, 2
    )
    percentual_aplicado = (
        round((valor_aplicado_remuneracao / base_calculo) * 100, 2)
        if base_calculo else 0.0
    )

    # Alertas obrigatórios (Passo 7 do prompt)
    alertas: list[str] = []
    if not coleta['cross_check_bate']:
        soma_categorias = round(
            coleta['soma_70'] + coleta['soma_30'] + coleta['soma_capital'] + coleta['soma_nao_classificado'], 2
        )
        alertas.append(
            f"Cross-check não bateu: soma das categorias (R$ {soma_categorias:,.2f}) diverge do "
            f"TOTAL GERAL da(s) unidade(s) FUNDEB (R$ {coleta['total_geral_unidades']:,.2f}) "
            f"em R$ {coleta['cross_check_diferenca']:,.2f}."
        )
    if coleta['total_geral_unidades'] and coleta['soma_nao_classificado'] > 0.01 * coleta['total_geral_unidades']:
        alertas.append(
            f"R$ {coleta['soma_nao_classificado']:,.2f} em ações não classificadas "
            "(sem rótulo 70%/30% e fora do padrão de capital) — revisão manual recomendada."
        )
    if base_calculo and percentual_aplicado < percentual_exigido:
        alertas.append(
            f"Percentual aplicado ({percentual_aplicado:.2f}%) abaixo do mínimo de "
            f"{percentual_exigido:.0f}%."
        )
    if codigos_ausentes:
        alertas.append(
            f"Códigos de receita FUNDEB ausentes no Anexo 10: {', '.join(codigos_ausentes)} (tratados como 0)."
        )
    alertas.append(
        "Restos a Pagar sem disponibilidade e despesas custeadas com superávit financeiro do "
        "exercício anterior não constam nos Anexos 6/10 — \"Valor Aplicado\" é bruto (sem essas "
        "duas deduções). Para o demonstrativo auditável pelo TCE-MA, buscar RGF (Anexo 12/13) "
        "ou Balanço Patrimonial."
    )

    logger.info(
        "ANX06 Q24: total_70pct=%.2f base=%.2f minimo=%.2f pct=%.2f%% cross_check=%s (diff=%.2f)",
        total_fundeb_70, base_calculo, minimo_exigido, percentual_aplicado,
        coleta['cross_check_bate'], coleta['cross_check_diferenca'],
    )
    return {
        'municipio':                    municipio,
        'exercicio':                    exercicio,
        # Chaves do template
        'minimo_exigido':               minimo_exigido,
        'percentual_exigido':           percentual_exigido,
        'valor_aplicado_remuneracao':   valor_aplicado_remuneracao,
        'rp_sem_disponibilidade':       rp_sem_disponibilidade,
        'superavit_exercicio_anterior': superavit_exercicio_anterior,
        'base_calculo':                 base_calculo,
        'base_calculo_bruta':           base_bruta,
        'receita_aplicacao_financeira': receita_aplicacao_financeira,
        'vaar_removido':                vaar_removido,
        'percentual_aplicado':          percentual_aplicado,
        # Diagnóstico
        'total_fundeb_70':              total_fundeb_70,
        'acoes_encontradas':            [
            {'codigo': c, 'descricao': coleta['descricoes'].get(c, ''), 'valor': v}
            for c, v in sorted(coleta['fundeb_70'].items())
        ],
        'fundeb_30_total':              coleta['soma_30'],
        'capital_total':                coleta['soma_capital'],
        'nao_classificado_total':       coleta['soma_nao_classificado'],
        'nao_classificado_itens':       [
            {'codigo': c, 'descricao': coleta['descricoes'].get(c, ''), 'valor': v}
            for c, v in sorted(coleta['nao_classificado'].items())
        ],
        'cross_check_bate':             coleta['cross_check_bate'],
        'cross_check_diferenca':        coleta['cross_check_diferenca'],
        'total_geral_unidades_fundeb':  coleta['total_geral_unidades'],
        'receita_fundeb_detalhe':       receita_detalhe,
        'codigos_receita_ausentes':     codigos_ausentes,
        'alertas':                      alertas,
    }


def extrair_q25(anx06_path: str) -> dict:
    """Q25 — Balanço Geral FUNDEB 70% — Detalhamento por Ação, em 9 rubricas canônicas.

    Detalha exatamente o mesmo total do quadro 24 (`total_fundeb_70`, calculado por
    `_coletar_fundeb70`) — este quadro não recalcula nem recupera dinheiro extra; ele
    reclassifica as MESMAS ações já confirmadas como FUNDEB 70% (rótulo próprio ou
    herdado do título do programa-pai) nas 9 rubricas canônicas, ancorando em
    FUNÇÃO.SUBFUNÇÃO (12.361/365/366/367 — padronizado nacionalmente pelo MCASP/
    Portaria STN) + palavras-chave da descrição (ver `_classificar_rubrica_fundeb70_educ`),
    em vez do código completo de programa/ação (numeração própria de cada município).
    Dentro dessas 4 subfunções, toda ação cai em alguma rubrica (a de manutenção
    correspondente serve de conta agregada quando não há palavra-chave específica —
    `forcar_agregado=True`), garantindo soma das 9 rubricas = total do quadro 24.
    Ações em subfunção fora dessas 4 (ex.: 122 — administração) ficam à parte, em
    `fora_das_9_rubricas`, para a reconciliação continuar exata e auditável.
    """
    dados = extrair(anx06_path)
    coleta = _coletar_fundeb70(dados)
    municipio = dados.get('municipio', '')
    exercicio = dados.get('exercicio', '')

    unidades_fundeb = [
        u.get('unidade_nome', '') for u in dados.get('unidades', [])
        if _eh_unidade_fundeb(u.get('unidade_nome', ''))
    ]

    buckets: dict[str, dict] = {
        cod: {'valor_total': 0.0, 'componentes': [], 'segregado': True}
        for cod in _RUBRICAS_FUNDEB70_EDUC_ORDEM
    }
    fora_das_9_rubricas: list[dict] = []

    for codigo, valor in coleta['fundeb_70'].items():
        parts = codigo.split('.')
        subfuncao = parts[1] if len(parts) >= 2 else ''
        descricao = coleta['descricoes'].get(codigo, '')

        if subfuncao not in ('361', '365', '366', '367'):
            fora_das_9_rubricas.append({'codigo_fonte': codigo, 'descricao_fonte': descricao, 'valor': valor})
            continue

        cod_canonico, segregado = _classificar_rubrica_fundeb70_educ(subfuncao, descricao, forcar_agregado=True)
        bucket = buckets[cod_canonico]
        bucket['valor_total'] = round(bucket['valor_total'] + valor, 2)
        if not segregado:
            bucket['segregado'] = False
        bucket['componentes'].append({'codigo_fonte': codigo, 'descricao_fonte': descricao, 'valor': valor})

    rubricas: list[dict] = []
    for cod in _RUBRICAS_FUNDEB70_EDUC_ORDEM:
        bucket = buckets[cod]
        encontrado = bool(bucket['componentes'])
        if not encontrado:
            observacao = 'Rubrica não encontrada no Anexo 6 deste município.'
        elif not bucket['segregado']:
            observacao = (
                'Valor da conta agregada da subfunção (rótulo genérico "70%", sem linha '
                'própria para esta sub-rubrica) — município não segrega em conta separada.'
            )
        else:
            observacao = ''
        rubricas.append({
            'codigo_canonico': cod,
            'label':           _RUBRICAS_FUNDEB70_EDUC_LABEL[cod],
            'subfuncao':       _RUBRICAS_FUNDEB70_EDUC_SUBFUNCAO[cod],
            'encontrado':      encontrado,
            'segregado':       bucket['segregado'] if encontrado else False,
            'valor_total':     bucket['valor_total'] if encontrado else None,
            'componentes':     bucket['componentes'],
            'observacao':      observacao,
        })

    total_9_rubricas = round(sum(r['valor_total'] or 0.0 for r in rubricas), 2)
    total_fora = round(sum(x['valor'] for x in fora_das_9_rubricas), 2)
    total = round(total_9_rubricas + total_fora, 2)

    # Listagem plana (código/descrição/valor) para o RIT — uma linha por componente,
    # agrupada na ordem das rubricas canônicas.
    acoes = [
        {'codigo': c['codigo_fonte'], 'descricao': c['descricao_fonte'], 'valor': c['valor']}
        for r in rubricas for c in r['componentes']
    ] + [
        {'codigo': x['codigo_fonte'], 'descricao': x['descricao_fonte'], 'valor': x['valor']}
        for x in fora_das_9_rubricas
    ]

    # Chaves fixas por rubrica (município-independentes) para o template Excel —
    # substitui as antigas `valor_<código>`, que só faziam sentido para Pinheiro.
    valores_por_rubrica = {
        f"valor_{r['codigo_canonico']}": (r['valor_total'] if r['encontrado'] else 0.0)
        for r in rubricas
    }

    logger.info(
        "ANX06 Q25: total=%.2f (== quadro_24? %s), rubricas_encontradas=%d/9, fora_das_9=%.2f, unidades_fundeb=%s",
        total, abs(total - coleta['soma_70']) < 0.01,
        sum(1 for r in rubricas if r['encontrado']), total_fora, unidades_fundeb,
    )

    return {
        'municipio':                   municipio,
        'exercicio':                   exercicio,
        'unidade_orcamentaria_fundeb': '; '.join(unidades_fundeb),
        'rubricas':                    rubricas,
        'fora_das_9_rubricas':         fora_das_9_rubricas,
        'total_fora_das_9_rubricas':   total_fora,
        'total':                       total,
        # Compatibilidade com o RIT (tabela do quadro 25 lê "acoes")
        'acoes':                       acoes,
        # Compatibilidade com o template Excel (chaves fixas por rubrica canônica)
        **valores_por_rubrica,
    }


def extrair_q26(anx06_path: str, anx10_at_path: str = None) -> dict:
    """Q26 — FUNDEB 30% Outras Despesas (não-magistério).

    O limite de 30% é um TETO, não um piso (Lei 14.113/2020, art. 26): pelo menos 70%
    dos recursos do FUNDEB devem ir para remuneração do magistério (Q24); os até 30%
    restantes cobrem as demais despesas de MDE. Exceder 30% aqui é o que indica
    inconformidade — normalmente reflexo de o piso de 70% do Q24 não ter sido atingido.

    valor_fundeb_outras_despesas = soma das ações rotuladas FUNDEB 30% (mesma
    classificação do Q24 — rótulo "30%" na própria ação ou herdado do título do
    programa-pai; ver `_classificar_fundeb70`). NÃO é "tudo que não é 70%": ações de
    capital ou não classificadas (`_coletar_fundeb70`) ficam de fora dessa soma.
    base_calculo: ver `_base_calculo_fundeb` — mesma fórmula do Q24, para os dois
    quadros serem sempre consistentes entre si.
    """
    dados = extrair(anx06_path)
    municipio = dados.get('municipio', '')
    exercicio = dados.get('exercicio', '')

    coleta = _coletar_fundeb70(dados)
    valor_fundeb_outras_despesas = coleta['soma_30']

    base_calculo, receita_detalhe, codigos_ausentes = _base_calculo_fundeb(anx10_at_path)

    valor_maximo                 = round(base_calculo * 0.30, 2)
    rp_sem_disponibilidade       = 0.0
    superavit_exercicio_anterior = 0.0
    valor_aplicado_outras_despesas = round(
        valor_fundeb_outras_despesas - rp_sem_disponibilidade - superavit_exercicio_anterior, 2
    )
    percentual_aplicado = (
        round((valor_aplicado_outras_despesas / base_calculo) * 100, 2)
        if base_calculo else 0.0
    )

    # Alertas (mesmo espírito do Q24 — ver `extrair_fundeb70_balanco`)
    alertas: list[str] = []
    if not coleta['cross_check_bate']:
        soma_categorias = round(
            coleta['soma_70'] + coleta['soma_30'] + coleta['soma_capital'] + coleta['soma_nao_classificado'], 2
        )
        alertas.append(
            f"Cross-check não bateu: soma das categorias (R$ {soma_categorias:,.2f}) diverge do "
            f"TOTAL GERAL da(s) unidade(s) FUNDEB (R$ {coleta['total_geral_unidades']:,.2f}) "
            f"em R$ {coleta['cross_check_diferenca']:,.2f}."
        )
    if base_calculo and percentual_aplicado > 30.0:
        alertas.append(
            f"Percentual aplicado em outras despesas ({percentual_aplicado:.2f}%) ACIMA do teto de "
            "30% — indício de que o piso de 70% em remuneração do magistério (Q24) não foi atingido."
        )
    if valor_fundeb_outras_despesas == 0.0 and coleta['soma_nao_classificado'] > 0.01:
        alertas.append(
            f"Nenhuma ação do Anexo 6 traz rótulo explícito de \"30%\"/outras despesas — "
            f"R$ {coleta['soma_nao_classificado']:,.2f} ficaram em NAO_CLASSIFICADO "
            "(sem rótulo 70%/30% e fora do padrão de capital). Este município provavelmente não "
            "rotula as ações individualmente (diferente do padrão com rótulo explícito); revisar "
            "manualmente se esse total corresponde à aplicação em outras despesas do FUNDEB."
        )
    if codigos_ausentes:
        alertas.append(
            f"Códigos de receita FUNDEB ausentes no Anexo 10: {', '.join(codigos_ausentes)} (tratados como 0)."
        )
    alertas.append(
        "Restos a Pagar sem disponibilidade e despesas custeadas com superávit financeiro do "
        "exercício anterior não constam nos Anexos 6/10 — \"Valor Aplicado\" é bruto (sem essas "
        "duas deduções). Para o demonstrativo auditável pelo TCE-MA, buscar RGF (Anexo 12/13) "
        "ou Balanço Patrimonial."
    )

    logger.info(
        "ANX06 Q26: outras=%.2f base=%.2f maximo=%.2f pct=%.2f%% cross_check=%s (diff=%.2f)",
        valor_fundeb_outras_despesas, base_calculo, valor_maximo, percentual_aplicado,
        coleta['cross_check_bate'], coleta['cross_check_diferenca'],
    )
    return {
        'municipio':                      municipio,
        'exercicio':                      exercicio,
        # Chaves do template
        'valor_maximo':                   valor_maximo,
        'valor_fundeb_outras_despesas':   valor_fundeb_outras_despesas,
        'rp_sem_disponibilidade':         rp_sem_disponibilidade,
        'superavit_exercicio_anterior':   superavit_exercicio_anterior,
        'valor_aplicado_outras_despesas': valor_aplicado_outras_despesas,
        'base_calculo':                   base_calculo,
        'percentual_teto':                30.0,
        'percentual_aplicado':            percentual_aplicado,
        # Diagnóstico / rastreabilidade
        'acoes_encontradas':              [
            {'codigo': c, 'descricao': coleta['descricoes'].get(c, ''), 'valor': v}
            for c, v in sorted(coleta['fundeb_30'].items())
        ],
        'total_fundeb_70':                coleta['soma_70'],
        'capital_total':                  coleta['soma_capital'],
        'nao_classificado_total':         coleta['soma_nao_classificado'],
        'cross_check_bate':               coleta['cross_check_bate'],
        'cross_check_diferenca':          coleta['cross_check_diferenca'],
        'receita_fundeb_detalhe':         receita_detalhe,
        'codigos_receita_ausentes':       codigos_ausentes,
        'alertas':                        alertas,
    }


def extrair_q27(anx06_path: str, anx10_at_path: str = None) -> dict:
    """Q27 — VAAT: Educação Infantil (mín. 50%) e Despesas de Capital (mín. 15%).

    Regra dura (por ação da(s) Unidade(s) FUNDEB): só entra na soma a ação cuja
    DESCRIÇÃO cite "VAAT" literalmente — nunca por proximidade de código/subfunção.
      - Infantil (50%): ações da subfunção 365 com "VAAT" na descrição.
      - Capital  (15%): ações de PROJETO (4º bloco do código inicia em 1), de
        qualquer subfunção, com "VAAT" na descrição (atividades 2xxx nunca entram).
    Base: VAAT arrecadado (1715.50.0.0.00.00) do ANX_10 — sem inferir de outra fonte.
    """
    from backend.extractors.anx10_legislativo import _indexar

    base_calculo_vaat = 0.0
    if anx10_at_path:
        idx = _indexar(anx10_at_path)
        base_calculo_vaat = idx.get('1715.50.0.0.00.00', 0.0)

    dados = extrair(anx06_path)
    municipio = dados.get('municipio', '')
    exercicio = dados.get('exercicio', '')

    det_infantil: dict[str, float] = {}
    det_capital:  dict[str, float] = {}

    for u in dados.get('unidades', []):
        if not _eh_unidade_fundeb(u.get('unidade_nome', '')):
            continue
        for acao in u.get('acoes', []):
            cod   = acao.get('codigo', '')
            val   = acao.get('total', 0.0)
            desc  = acao.get('descricao', '').upper()
            parts = cod.split('.')

            # Filtro obrigatório: a descrição da ação deve citar "VAAT" (tolerante a
            # espaços internos que o PDF insere, ex.: "VA AT").
            if not _VAAT_RE.search(desc):
                continue

            chave = '.'.join(parts[:4]) if len(parts) >= 4 else cod

            # Infantil (50%): subfunção 365, com "VAAT" na descrição.
            if len(parts) >= 2 and parts[1] == '365':
                det_infantil[chave] = round(det_infantil.get(chave, 0.0) + val, 2)

            # Capital (15%): ação de projeto (4º bloco inicia em 1), qualquer subfunção,
            # com "VAAT" na descrição. Atividades (2xxx) nunca entram.
            if len(parts) >= 4 and parts[3].startswith('1'):
                det_capital[chave] = round(det_capital.get(chave, 0.0) + val, 2)

    valor_infantil = round(sum(det_infantil.values()), 2)
    valor_capital  = round(sum(det_capital.values()), 2)

    minimo_infantil = round(base_calculo_vaat * 0.50, 2)
    minimo_capital  = round(base_calculo_vaat * 0.15, 2)
    pct_infantil = round((valor_infantil / base_calculo_vaat) * 100, 2) if base_calculo_vaat else 0.0
    pct_capital  = round((valor_capital  / base_calculo_vaat) * 100, 2) if base_calculo_vaat else 0.0

    logger.info(
        "ANX06 Q27: vaat=%.2f infantil=%.2f (%.2f%%) capital=%.2f (%.2f%%)",
        base_calculo_vaat, valor_infantil, pct_infantil, valor_capital, pct_capital,
    )
    return {
        'municipio':                    municipio,
        'exercicio':                    exercicio,
        'minimo_exigido_infantil':      minimo_infantil,
        'valor_aplicado_infantil':      valor_infantil,
        'percentual_aplicado_infantil': pct_infantil,
        'minimo_exigido_capital':       minimo_capital,
        'valor_aplicado_capital':       valor_capital,
        'percentual_aplicado_capital':  pct_capital,
        'base_calculo_vaat':            base_calculo_vaat,
        # Diagnóstico
        'detalhamento_infantil':        det_infantil,
        'detalhamento_capital':         det_capital,
    }


def extrair_q18(anx06_path: str, anx10_path: str, base_calculo: float = 0.0) -> dict:
    """Extrai dados para Q18 — Despesas com Ações e Serviços de Saúde."""
    dados = extrair(anx06_path)
    municipio = dados.get('municipio', '')
    exercicio = dados.get('exercicio', '')

    # Soma gastos por subfunção do FUNDO MUNICIPAL DE SAÚDE (função 10).
    # Exceção: 122 (Administração Geral) soma Fundo + Secretaria de Saúde, pois
    # despesas administrativas da função saúde costumam ficar lançadas na Secretaria
    # (fora do Fundo). Para as demais subfunções (301-306), a Secretaria fica de fora
    # para evitar dupla contagem das ações finalísticas já lançadas no Fundo.
    sf: dict[str, float] = {s: 0.0 for s in ('301', '302', '303', '304', '305', '306', '122')}
    for u in dados['unidades']:
        nome_u = u['unidade_nome'].upper()
        # "SAÚDE" chega acentuado (Ú = U+00DA) — comparar sem acento para não depender
        # do proxy frágil "SA" (que também casaria "SANEAMENTO"/"SOCIAL").
        nome_sa = _sem_acento(nome_u)
        tem_saude = 'SAUDE' in nome_sa
        eh_fundo_saude = ('FUNDO' in nome_u and tem_saude) or 'FMS' in nome_u
        # A unidade da Secretaria de Saúde aparece tanto por extenso ("SECRETARIA
        # MUNICIPAL DE SAÚDE", ex.: Presidente Dutra) quanto abreviada ("SEC. MUN. DE
        # SAÚDE E SANEAMENTO", ex.: Dom Pedro) — sem cobrir "SEC." a subfunção 122 dessa
        # unidade some do quadro 18.
        eh_secretaria = bool(re.search(r'SECRETARIA|SEC\.|\bSEC\b', nome_u))
        eh_secretaria_saude = eh_secretaria and tem_saude
        if not (eh_fundo_saude or eh_secretaria_saude):
            continue
        for acao in u['acoes']:
            parts = acao['codigo'].split('.')
            if len(parts) < 2 or parts[0] != '10' or parts[1] not in sf:
                continue
            subfunc = parts[1]
            if subfunc != '122' and not eh_fundo_saude:
                continue  # 301-306: apenas o Fundo, para evitar dupla contagem
            sf[subfunc] = round(sf[subfunc] + acao['total'], 2)

    atencao_basica                      = sf['301']
    assistencia_hospitalar_ambulatorial = sf['302']
    suporte_profilatico_terapeutico     = sf['303']
    vigilancia_sanitaria                = sf['304']
    vigilancia_epidemiologica           = sf['305']
    alimentacao_nutricao                = sf['306']
    outras_subfuncoes                   = sf['122']

    total_despesas_saude = round(
        atencao_basica + assistencia_hospitalar_ambulatorial +
        suporte_profilatico_terapeutico + vigilancia_sanitaria +
        vigilancia_epidemiologica + alimentacao_nutricao + outras_subfuncoes,
        2,
    )

    # Deduções: recursos SUS (ANX_10)
    sus_corrente = _sus_arrecadada(anx10_path, '1713.00.0.0.00.00')
    sus_capital  = _sus_arrecadada(anx10_path, '2411.00.0.0.00.00')
    custeadas_outros_recursos = round(sus_corrente + sus_capital, 2)

    # Demais deduções vêm do RGF — padrão 0,00 quando não disponível
    rp_nao_processados        = 0.0
    inativos_pensionistas     = 0.0
    assistencia_nao_universal = 0.0
    outras_acoes              = 0.0
    rpp_sem_disponibilidade   = 0.0
    disp_vinculada_rp         = 0.0
    recursos_ex_anteriores    = 0.0

    total_para_fins_apuracao = round(
        total_despesas_saude
        - rp_nao_processados - inativos_pensionistas - assistencia_nao_universal
        - custeadas_outros_recursos - outras_acoes - rpp_sem_disponibilidade
        - disp_vinculada_rp - recursos_ex_anteriores,
        2,
    )

    percentual_aplicado = (
        round((total_para_fins_apuracao / base_calculo) * 100, 2)
        if base_calculo > 0 else 0.0
    )
    situacao = (
        "Aprovado — acima do mínimo de 15%"
        if percentual_aplicado >= 15.0
        else "Irregular — abaixo do mínimo de 15%"
    )

    logger.info(
        "ANX06 Q18: total_saude=%.2f sus=%.2f total_apuracao=%.2f pct=%.2f%%",
        total_despesas_saude, custeadas_outros_recursos,
        total_para_fins_apuracao, percentual_aplicado,
    )
    return {
        'municipio':  municipio,
        'exercicio':  exercicio,
        'atencao_basica':                       atencao_basica,
        'assistencia_hospitalar_ambulatorial':   assistencia_hospitalar_ambulatorial,
        'suporte_profilatico_terapeutico':      suporte_profilatico_terapeutico,
        'vigilancia_sanitaria':                 vigilancia_sanitaria,
        'vigilancia_epidemiologica':            vigilancia_epidemiologica,
        'alimentacao_nutricao':                 alimentacao_nutricao,
        'outras_subfuncoes':                    outras_subfuncoes,
        'total_despesas_saude':                 total_despesas_saude,
        'despesas_nao_computadas_rpp':          rp_nao_processados,
        'despesas_inativos_pensionistas':       inativos_pensionistas,
        'despesa_nao_acesso_universal':         assistencia_nao_universal,
        'despesas_outros_recursos':             custeadas_outros_recursos,
        'outras_acoes_nao_computadas':          outras_acoes,
        'rpp_inscritos_indevidamente':          rpp_sem_disponibilidade,
        'despesas_caixa_rp_cancelados':         disp_vinculada_rp,
        'despesas_recursos_vinculados_exerc_anteriores': recursos_ex_anteriores,
        'total_despesas_saude_percentual_minimo': total_para_fins_apuracao,
        'base_calculo_informada':               base_calculo,
        'percentual_aplicacao_saude':           percentual_aplicado,
        'sus_corrente_1713':                    sus_corrente,
        'sus_capital_2411':                     sus_capital,
        'situacao':                             situacao,
    }


def extrair_subfuncao_func12(anx06_path: str) -> dict:
    """Q23 — Despesas da Educação Função 12 por Subfunção (SEMED + FUNDEB).

    SEMED: subfunções 122, 361, 362, 365, 367, 306 (EJA/366 não compõe o SEMED —
           só é contabilizada via FUNDEB)
    FUNDEB: subfunções 361, 365, 366, 367
    Soma das ações individuais por subfunção = total consolidado da subfunção.
    """
    dados = extrair(anx06_path)
    municipio = dados.get('municipio', '')
    exercicio = dados.get('exercicio', '')

    SUBFUNC_SEMED  = {'122', '361', '362', '365', '367', '306'}
    SUBFUNC_FUNDEB = {'361', '365', '366', '367'}

    semed:  dict[str, float] = {sf: 0.0 for sf in SUBFUNC_SEMED}
    fundeb: dict[str, float] = {sf: 0.0 for sf in SUBFUNC_FUNDEB}
    observacoes: list[str] = []

    for u in dados.get('unidades', []):
        nome_u = u.get('unidade_nome', '').upper()
        eh_semed  = ('EDUCA' in nome_u or 'ENSINO' in nome_u or 'SEMED' in nome_u) and 'FUNDEB' not in nome_u
        eh_fundeb = 'FUNDEB' in nome_u
        if not (eh_semed or eh_fundeb):
            continue
        for acao in u.get('acoes', []):
            parts = acao.get('codigo', '').split('.')
            if len(parts) < 2 or parts[0] != '12':
                continue
            sf = parts[1]
            val = acao.get('total', 0.0)
            codigo = acao.get('codigo', '')
            descricao = acao.get('descricao', '')
            if eh_semed and sf in semed:
                semed[sf] = round(semed[sf] + val, 2)
                if val == 0.0:
                    observacoes.append(f"SEMED — subfunção {sf}: '{descricao}' ({codigo}) = 0,00")
            elif eh_fundeb and sf in fundeb:
                fundeb[sf] = round(fundeb[sf] + val, 2)
                if val == 0.0:
                    observacoes.append(f"FUNDEB — subfunção {sf}: '{descricao}' ({codigo}) = 0,00")
            elif eh_fundeb and sf not in fundeb:
                # FUNDEB só pode custear as subfunções 361/365/366/367 — despesa fora
                # desse escopo (ex: 122 Administração Geral) é um desvio a verificar.
                observacoes.append(
                    f"FUNDEB — despesa em subfunção não usual {sf}: '{descricao}' ({codigo}) = {val:,.2f}"
                )
            elif eh_semed and sf not in semed:
                # EJA (366) não compõe mais o subtotal SEMED (só é contabilizada via
                # FUNDEB) — despesa de EJA lançada na unidade SEMED é reportada aqui
                # para não ficar invisível, sem entrar no total.
                observacoes.append(
                    f"SEMED — despesa em subfunção fora do escopo atual {sf}: '{descricao}' ({codigo}) = {val:,.2f} (não somada ao subtotal)"
                )

    semed_subtotal  = round(sum(semed.values()), 2)
    fundeb_subtotal = round(sum(fundeb.values()), 2)
    total_geral     = round(semed_subtotal + fundeb_subtotal, 2)

    logger.info(
        "ANX06 Q23: semed=%.2f (122=%.2f 361=%.2f 362=%.2f 365=%.2f 367=%.2f 306=%.2f) "
        "fundeb=%.2f total=%.2f observacoes=%d",
        semed_subtotal, semed['122'], semed['361'], semed['362'], semed['365'], semed['367'], semed['306'],
        fundeb_subtotal, total_geral, len(observacoes),
    )
    return {
        'municipio':             municipio,
        'exercicio':             exercicio,
        # Chaves do template — SEMED
        'semed_122':             semed['122'],
        'semed_361':             semed['361'],
        'semed_362':             semed['362'],
        'semed_365':             semed['365'],
        'semed_367':             semed['367'],
        'semed_306':             semed['306'],
        'semed_subtotal':        semed_subtotal,
        # Chaves do template — FUNDEB
        'fundeb_361':            fundeb['361'],
        'fundeb_365':            fundeb['365'],
        'fundeb_366':            fundeb['366'],
        'fundeb_367':            fundeb['367'],
        'fundeb_subtotal':       fundeb_subtotal,
        # Total geral
        'total_geral_funcao_12': total_geral,
        # Achados: campos zerados ou desvios relevantes na composição SEMED/FUNDEB
        'observacoes':           observacoes,
    }


def extrair_q20(anx06_path: str, anx10_at_path: str, base_calculo_bruta: float = 0.0,
                bo_fundeb_path: str = None) -> dict:
    """Q20 — Despesas MDE (Manutenção e Desenvolvimento do Ensino).

    Fonte ANX_06 (via Q23 — quadro de subfunção): total ações típicas de MDE =
      FUNDEB (subtotal, cobre 361/365/366/367) + Educação Infantil (SEMED/365)
      + Ensino Fundamental (SEMED/361) + 1º quadrimestre (fixo em 0.0)
    Fonte ANX_10_ATUAL: FUNDEB recebido/destinado, complementação, outros recursos
    base_calculo_bruta: Q19.base_bruta (impostos + transf + fpm_extra, SEM deduzir FUNDEB)
    bo_fundeb_path: Balanço Orçamentário isolado do FUNDEB — dele saem duas deduções:
      "(-) Receita de Aplicação Financeira do FUNDEB" (= RECEITA PATRIMONIAL realizada) e
      "(-) Despesas Custeadas com Superávit Financeiro do Exercício Anterior" (só quando a
      despesa empenhada do FUNDEB supera a receita realizada). Sem esse anexo, ambas caem
      no fallback histórico (aplicação financeira = 0; superávit estimado por ANX_06/10).
    """
    from backend.extractors.anx10_legislativo import _indexar

    # ── ANX_06: despesas com educação ────────────────────────────────────────
    # Reaproveita o mesmo cálculo do quadro de subfunção (Q23) — SEMED/FUNDEB por
    # subfunção da Função 12 — para não duplicar a lógica de agregação.
    q23 = extrair_subfuncao_func12(anx06_path)
    municipio = q23['municipio']
    exercicio = q23['exercicio']

    semed_total  = q23['semed_subtotal']
    # "Total custeado com FUNDEB" (linha 5 do Quadro 20) = subtotal FUNDEB do Q23.
    fundeb_total = q23['fundeb_subtotal']
    # "Ensino Fundamental" (linha 8) recebe o subtotal inteiro do SEMED/MDE do Q23.
    # "Educação Infantil" (linha 7) fica zerada para não contar esse valor em
    # duplicidade (já está dentro do subtotal SEMED). TOTAL DAS AÇÕES TÍPICAS DE
    # MDE = FUNDEB + SEMED (linhas 5 + 8; 1º quadrimestre e infantil ficam em 0).
    educacao_infantil  = 0.0
    ensino_fundamental = semed_total
    total_fundeb_primeiro_quadrimestre = 0.0
    total_mde = round(
        fundeb_total + total_fundeb_primeiro_quadrimestre + educacao_infantil + ensino_fundamental,
        2,
    )
    observacoes = q23['observacoes']

    # ── ANX_10: receitas FUNDEB e outros recursos ─────────────────────────────
    idx = _indexar(anx10_at_path)

    def r(codigo: str) -> float:
        return idx.get(codigo, 0.0)

    # FUNDEB recebido (transferências do FUNDEB ao município)
    fundeb_recebido = r('1751.50.0.0.00.00')

    # Complementação total (VAAF + VAAT + VAAR + ETI) — usa sintético 1715.00
    complementacao = r('1715.00.0.0.00.00')

    # FUNDEB destinado — 20% retidos (9xxxx, positivos no index)
    fundeb_destinado = round(
        r('91711.51.1.0.00.00') + r('91711.52.0.0.00.00') +
        r('91721.50.0.0.00.00') + r('91721.51.0.0.00.00') + r('91721.52.0.0.00.00'),
        2,
    )

    resultado_liquido_fundeb = round(fundeb_recebido - fundeb_destinado, 2)

    # "(-) Despesas Custeadas com Outros Recursos" = transferências do FNDE, código
    # sintético 1714.00 ("TRANSF. RECURSOS FUNDO NAC. DESENVOLVIMENTO EDUCAÇÃO - FNDE"),
    # que já engloba salário-educação/PNAE/PNATE/demais. Somar os sub-códigos + capital
    # (2412) inflava o valor sempre que havia FNDE de capital ou sub-rubrica fora da lista.
    # Fallback para o analítico "-PRINCIPAL" (0.1.00.00) quando o sintético não existir.
    outros_recursos = round(
        r('1714.00.0.0.00.00') or r('1714.00.0.1.00.00'),
        2,
    )

    # Receita de Aplicação Financeira e Superávit do exercício anterior:
    # fonte preferencial é o Balanço Orçamentário isolado do FUNDEB, quando enviado.
    if bo_fundeb_path:
        from backend.extractors.bo_fundeb import extrair as extrair_bo_fundeb
        bo = extrair_bo_fundeb(bo_fundeb_path)
        aplic_financeira   = bo['receita_patrimonial_realizada']
        superavit_anterior = bo['superavit_exercicio_anterior']
    else:
        # Fallback histórico (sem o BO isolado do FUNDEB): aplicação financeira
        # indisponível (0,00) e superávit estimado por despesas FUNDEB > receitas FUNDEB.
        receitas_fundeb_total = round(fundeb_recebido + complementacao, 2)
        aplic_financeira   = 0.0
        superavit_anterior = round(max(0.0, fundeb_total - receitas_fundeb_total), 2)

    # Campos sem fonte disponível (RGF) — padrão 0,00
    rp_sem_dispon   = 0.0
    cancelamento_rp  = 0.0

    total_limite = round(
        total_mde
        - resultado_liquido_fundeb
        - complementacao
        - aplic_financeira
        - superavit_anterior
        - outros_recursos
        - rp_sem_dispon
        - cancelamento_rp,
        2,
    )

    percentual = round((total_limite / base_calculo_bruta * 100) if base_calculo_bruta else 0.0, 2)

    logger.info(
        "ANX06 Q20: total_mde=%.2f liq_fundeb=%.2f compl=%.2f outros=%.2f super=%.2f limite=%.2f pct=%.2f%%",
        total_mde, resultado_liquido_fundeb, complementacao, outros_recursos,
        superavit_anterior, total_limite, percentual,
    )
    return {
        'municipio':                             municipio,
        'exercicio':                             exercicio,
        'total_fundeb_impostos_transferencias':  fundeb_total,
        'total_fundeb_primeiro_quadrimestre':    total_fundeb_primeiro_quadrimestre,
        'educacao_infantil':                     educacao_infantil,
        'ensino_fundamental':                    ensino_fundamental,
        'total_acoes_tipicas_mde':               total_mde,
        'resultado_liquido_fundeb':              resultado_liquido_fundeb,
        'complementacao_fundeb_exercicio':       complementacao,
        'receita_aplicacao_financeira_fundeb':   aplic_financeira,
        'superavit_exercicio_anterior_fundeb':   superavit_anterior,
        'outros_recursos':                       outros_recursos,
        'rp_sem_disponibilidade_financeira':     rp_sem_dispon,
        'cancelamento_rp_com_disponibilidade':   cancelamento_rp,
        'total_despesas_para_fins_de_limite':    total_limite,
        'base_calculo_informada':                base_calculo_bruta,
        'percentual_aplicacao_ensino':           percentual,
        # Achados herdados do Q23 (campos zerados/desvios na composição SEMED/FUNDEB)
        'observacoes':       observacoes,
        # campos adicionais (diagnóstico)
        'semed_total':       semed_total,
        'fundeb_total':      fundeb_total,
        'fundeb_recebido':   fundeb_recebido,
        'fundeb_destinado':  fundeb_destinado,
        'complementacao':    complementacao,
    }


def formatar_texto(pdf_path: str) -> str:
    """Retorna texto estruturado e limpo do ANX06 para consumo pela IA."""
    r = extrair(pdf_path)

    out = []
    out.append("ANEXO 06 — PROGRAMA DE TRABALHO")
    out.append(f"MUNICÍPIO: {r['municipio']} | EXERCÍCIO: {r['exercicio']} | PERÍODO: {r['periodo']}")
    out.append(f"TOTAL GERAL: projetos={r['total_geral']['projetos']:,.2f}  atividades={r['total_geral']['atividades']:,.2f}  total={r['total_geral']['total']:,.2f}")
    out.append("")

    for u in r['unidades']:
        out.append(f"{'='*70}")
        out.append(f"ÓRGÃO {u['orgao_codigo']} — {u['orgao_nome']}")
        out.append(f"UNIDADE {u['unidade_codigo']} — {u['unidade_nome']} | TOTAL: {u['total_geral']:,.2f}")
        out.append(f"  {'CÓDIGO':<24} {'TOTAL':>16}  DESCRIÇÃO")
        out.append("  " + "-"*75)
        for a in u['acoes']:
            out.append(f"  {a['codigo']:<24}  {a['total']:>16,.2f}  {a['descricao'][:50]}")
        out.append("")

    return "\n".join(out)


def _linhas_pdfplumber_pagina(pdf_path: str, pagina: int) -> list[str]:
    """Extrai linhas de uma página usando pdfplumber."""
    with pdfplumber.open(pdf_path) as pdf:
        if pagina >= len(pdf.pages):
            return []
        return (pdf.pages[pagina].extract_text() or "").splitlines()


_DUPLIC_RE = re.compile(r'(.)\1{3,}')  # 4+ repetições do mesmo caractere


def _tem_duplicacao(linhas: list[str]) -> bool:
    """Detecta se o texto tem artefato de fonte duplicada (ex: 'PPPPRRRROOOO...')."""
    amostra = " ".join(linhas[:10])
    return bool(_DUPLIC_RE.search(amostra))


def extrair(pdf_path: str) -> dict:
    """
    Extrai o Anexo 06 e retorna estrutura com todas as unidades orçamentárias e ações.

    Estratégia de extração por página:
    - pdfplumber como primário (agrupa melhor tabelas de PDFs padrão como Apicum)
    - PyMuPDF como fallback quando pdfplumber mostra artefato de fonte duplicada
      (ex: "OOOOrrrrgggg..." comum em PDFs como Pinheiro)
    """
    doc = fitz.open(pdf_path)

    # Cabeçalho via PyMuPDF (deduplica texto, mais estável)
    linhas_p1 = _agrupar_linhas(doc[0])
    municipio, exercicio, periodo = _extrair_cabecalho(linhas_p1)

    unidades_raw: list[dict] = []
    total_geral_doc = None

    with pdfplumber.open(pdf_path) as pdf_pl:
        for i, page in enumerate(doc):
            pl_text = pdf_pl.pages[i].extract_text() if i < len(pdf_pl.pages) else None
            pl_linhas = pl_text.splitlines() if pl_text else []

            # Usa PyMuPDF quando pdfplumber mostra texto com duplicação de fonte
            if not pl_linhas or _tem_duplicacao(pl_linhas):
                linhas = _agrupar_linhas(page)
            else:
                linhas = pl_linhas

            # Captura TOTAL GERAL do documento (aparece só na última página)
            tg = _extrair_total_geral(linhas)
            if tg:
                total_geral_doc = tg

            unidade = _processar_pagina(linhas)
            if unidade:
                unidades_raw.append(unidade)

    doc.close()

    # Mescla páginas de continuação da mesma unidade
    merged: dict[tuple, dict] = {}
    for u in unidades_raw:
        key = (u['orgao_codigo'], u['unidade_codigo'])
        if key not in merged:
            merged[key] = {**u, 'acoes': list(u['acoes'])}
        else:
            merged[key]['acoes'].extend(u['acoes'])
            if u['total_geral'] > 0:
                merged[key]['total_geral']     = u['total_geral']
                merged[key]['total_projetos']  = u['total_projetos']
                merged[key]['total_atividades'] = u['total_atividades']

    unidades = list(merged.values())

    if total_geral_doc:
        tg_dict = {
            'projetos':   round(total_geral_doc[0], 2),
            'atividades': round(total_geral_doc[1], 2),
            'total':      round(total_geral_doc[2], 2),
        }
    else:
        tg_dict = {
            'projetos':   round(sum(u['total_projetos'] for u in unidades), 2),
            'atividades': round(sum(u['total_atividades'] for u in unidades), 2),
            'total':      round(sum(u['total_geral'] for u in unidades), 2),
        }

    return {
        'municipio':   municipio,
        'exercicio':   exercicio,
        'periodo':     periodo,
        'unidades':    unidades,
        'total_geral': tg_dict,
    }
