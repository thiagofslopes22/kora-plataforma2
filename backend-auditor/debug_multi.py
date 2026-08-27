"""
Script de diagnóstico multi-extrator.

Uso:
    cd kora
    python debug_multi.py --municipio apicum
    python debug_multi.py --municipio pinheiro
    python debug_multi.py --anx06 ../arquivo/anx6apicum.pdf
    python debug_multi.py --anx06 ../arquivo/anx6apicum.pdf --anx02 ../arquivo/anx2apicum.pdf

Mostra linhas brutas + resultado de cada extrator para diagnóstico.
"""
import argparse
import os
import sys
import re

# Adiciona o diretório kora ao path para importar backend
sys.path.insert(0, os.path.dirname(__file__))

import pdfplumber
import fitz

NUMERO_RE = re.compile(r'-?\d{1,3}(?:\.\d{3})*,\d{2}')

ARQUIVO_DIR = os.path.join(os.path.dirname(__file__), '..', 'arquivo')


def _pdf_linhas(pdf_path: str, max_paginas: int = 5) -> list[str]:
    linhas = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages[:max_paginas]):
            linhas.append(f"=== PÁGINA {i} ===")
            text = page.extract_text() or ""
            linhas.extend(text.splitlines())
    return linhas


def _pdf_palavras_linhas(pdf_path: str, max_paginas: int = 3) -> list[str]:
    """Extrai linhas via PyMuPDF agrupando por Y-coord (como faz o extrator)."""
    from collections import defaultdict
    doc = fitz.open(pdf_path)
    resultado = []
    for i, page in enumerate(doc):
        if i >= max_paginas:
            break
        resultado.append(f"=== PÁGINA {i} (PyMuPDF) ===")
        groups: dict = defaultdict(list)
        for w in page.get_text('words'):
            groups[round(w[1])].append((w[0], w[4]))
        for y in sorted(groups):
            partes = [t[1] for t in sorted(groups[y], key=lambda t: t[0])]
            deduped = [partes[0]]
            for p in partes[1:]:
                if p != deduped[-1]:
                    deduped.append(p)
            resultado.append(' '.join(deduped))
    doc.close()
    return resultado


def mostrar_linhas(titulo: str, linhas: list[str], n: int = 50) -> None:
    print(f"\n{'='*60}")
    print(f"  {titulo}")
    print(f"{'='*60}")
    for i, l in enumerate(linhas[:n]):
        nums = NUMERO_RE.findall(l)
        marcador = f" [{len(nums)}nums]" if nums else ""
        print(f"  [{i:03d}]{marcador} {l}")
    if len(linhas) > n:
        print(f"  ... ({len(linhas) - n} linhas restantes)")


def _pegar_pdf(arg: str | None, padrao_apicum: str, padrao_pinheiro: str, municipio: str) -> str | None:
    if arg:
        return os.path.abspath(arg)
    if municipio == 'apicum':
        candidato = os.path.join(ARQUIVO_DIR, padrao_apicum)
    else:
        candidato = os.path.join(ARQUIVO_DIR, padrao_pinheiro)
    if os.path.exists(candidato):
        return candidato
    return None


def diagnosticar_anx06(pdf_path: str) -> None:
    print(f"\n{'#'*60}")
    print(f"  ANX06 — {pdf_path}")
    print(f"{'#'*60}")

    linhas_pdfplumber = _pdf_linhas(pdf_path)
    mostrar_linhas("Linhas brutas (pdfplumber, 3 pág.)", linhas_pdfplumber, 60)

    linhas_pymupdf = _pdf_palavras_linhas(pdf_path)
    mostrar_linhas("Linhas brutas (PyMuPDF agrupado, 3 pág.)", linhas_pymupdf, 60)

    # Busca padrões de cabeçalho
    print("\n--- Busca de padrões 'Orgao:' e 'Unidade Orcamentaria:' ---")
    for i, l in enumerate(linhas_pymupdf):
        u = l.upper()
        if 'ORG' in u and ':' in l:
            print(f"  [{i:03d}] ORGAO-like: {l!r}")
        if 'UNIDADE' in u:
            print(f"  [{i:03d}] UNIDADE: {l!r}")

    # Tenta rodar o extrator real
    print("\n--- Resultado extrair() ---")
    try:
        from backend.extractors.anx06_programa_trabalho import extrair
        d = extrair(pdf_path)
        print(f"  municipio: {d.get('municipio')!r}")
        print(f"  exercicio: {d.get('exercicio')!r}")
        unidades = d.get('unidades', [])
        print(f"  unidades: {len(unidades)}")
        for u in unidades[:5]:
            print(f"    [{u['orgao_codigo']}] {u['orgao_nome']} | {u['unidade_nome']}")
            print(f"         atividades={u['total_atividades']:.2f}  geral={u['total_geral']:.2f}  acoes={len(u.get('acoes',[]))}")
    except Exception as e:
        print(f"  ERRO: {e}")


def diagnosticar_anx02(pdf_path: str) -> None:
    print(f"\n{'#'*60}")
    print(f"  ANX02 — {pdf_path}")
    print(f"{'#'*60}")

    linhas = _pdf_palavras_linhas(pdf_path, max_paginas=2)
    mostrar_linhas("Linhas brutas (PyMuPDF, 2 pág.)", linhas, 40)

    print("\n--- Busca de padrões ORGAO ---")
    orgao_re = re.compile(r'^(\d{2,3})\s+([A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ ]*)')
    for i, l in enumerate(linhas[:80]):
        m = orgao_re.match(l.strip())
        if m:
            print(f"  [{i:03d}] MATCH 2-3dig: {l!r}")
        elif re.match(r'^\d{2,4}\s+', l.strip()):
            print(f"  [{i:03d}] num-espaco: {l!r}")

    print("\n--- Resultado extrair() ---")
    try:
        from backend.extractors.anx02_despesas import extrair
        d = extrair(pdf_path)
        print(f"  municipio: {d.get('municipio')!r}")
        print(f"  exercicio: {d.get('exercicio')!r}")
        orgaos = d.get('orgaos', {})
        print(f"  orgaos: {len(orgaos)}")
        for cod, o in orgaos.items():
            print(f"    [{cod}] {o['nome']}")
            print(f"         total={o.get('total', 0):.2f} pessoal={o.get('pessoal_encargos', 0):.2f}")
        print(f"  itens: {len(d.get('itens', []))}")
    except Exception as e:
        print(f"  ERRO: {e}")


def diagnosticar_anx14_qb(pdf_path: str) -> None:
    print(f"\n{'#'*60}")
    print(f"  ANX14 Quadro B — {pdf_path}")
    print(f"{'#'*60}")

    from collections import defaultdict
    doc = fitz.open(pdf_path)
    n_paginas = len(doc)
    print(f"  Número de páginas no PDF: {n_paginas}")

    for pag_idx in range(min(n_paginas, 4)):
        page = doc[pag_idx]
        mid = page.rect.width / 2
        esq: dict = defaultdict(list)
        dir_: dict = defaultdict(list)
        for w in page.get_text('words'):
            y_key = round(w[1])
            (esq if w[0] < mid else dir_)[y_key].append((w[0], w[4]))

        def montar(d):
            return [" ".join(w for _, w in sorted(d[y])) for y in sorted(d) if d[y]]

        linhas_esq = montar(esq)
        linhas_dir = montar(dir_)

        if any("FINANCEIRO" in l.upper() or "ATIVO" in l.upper() or "PASSIVO" in l.upper()
               for l in linhas_esq + linhas_dir):
            print(f"\n  === Página {pag_idx} (esquerda) ===")
            for l in linhas_esq[:20]:
                print(f"    {l!r}")
            print(f"\n  === Página {pag_idx} (direita) ===")
            for l in linhas_dir[:20]:
                print(f"    {l!r}")
    doc.close()

    print("\n--- Resultado extrair() ---")
    try:
        from backend.extractors.anx14_balanco_patrimonial import extrair
        d = extrair(pdf_path)
        qb = d.get('quadro_b', {})
        print(f"  ativo_financeiro:   {qb.get('ativo_financeiro', {})}")
        print(f"  passivo_financeiro: {qb.get('passivo_financeiro', {})}")
        print(f"  saldo_patrimonial:  {qb.get('saldo_patrimonial', {})}")
        pl = d.get('patrimonio_liquido', {})
        print(f"  total_pl: {pl.get('total_pl', {})}")
    except Exception as e:
        print(f"  ERRO: {e}")


def diagnosticar_dfc(pdf_path: str) -> None:
    print(f"\n{'#'*60}")
    print(f"  DFC — {pdf_path}")
    print(f"{'#'*60}")

    linhas = _pdf_linhas(pdf_path)
    mostrar_linhas("Linhas brutas (pdfplumber, todas)", linhas, 80)

    # Busca padrões de seção
    print("\n--- Padrões de seção detectados ---")
    SECOES = [
        "FLUXOS DE CAIXA", "OPERACIONAL", "INVESTIMENTO", "FINANCIAMENTO",
        "APURA", "I+II+III", "INICIAL", "FINAL",
    ]
    for i, l in enumerate(linhas):
        u = l.upper()
        for s in SECOES:
            if s in u:
                print(f"  [{i:03d}] ({s}): {l!r}")
                break

    print("\n--- Resultado extrair() ---")
    try:
        from backend.extractors.anx_dfc import extrair
        d = extrair(pdf_path)
        print(f"  municipio: {d.get('municipio')!r}")
        print(f"  geracao_liquida_atual: {d.get('geracao_liquida_atual')}")
        print(f"  caixa_inicial_atual:   {d.get('caixa_inicial_atual')}")
        print(f"  caixa_final_atual:     {d.get('caixa_final_atual')}")
    except Exception as e:
        print(f"  ERRO: {e}")


def main():
    parser = argparse.ArgumentParser(description="Diagnóstico de extratores")
    parser.add_argument('--municipio', choices=['apicum', 'pinheiro'], default='apicum')
    parser.add_argument('--anx06', help="Caminho explícito para o ANX06 PDF")
    parser.add_argument('--anx02', help="Caminho explícito para o ANX02 PDF")
    parser.add_argument('--bp', help="Caminho explícito para o BP (ANX14) PDF")
    parser.add_argument('--dfc', help="Caminho explícito para o DFC PDF")
    parser.add_argument('--only', choices=['anx06', 'anx02', 'bp', 'dfc'], help="Rodar só um diagnóstico")
    args = parser.parse_args()

    mun = args.municipio

    p_anx06 = _pegar_pdf(args.anx06, 'anx6apicum.pdf', 'anx6.pdf', mun)
    p_anx02 = _pegar_pdf(args.anx02, 'anx2apicum.pdf', 'anx22025.pdf', mun)
    p_bp    = _pegar_pdf(args.bp,    'BPapicum.pdf',   'BP.pdf', mun)
    p_dfc   = _pegar_pdf(args.dfc,   'fluxocatualapicum.pdf', 'dfc.pdf', mun)

    print(f"\nMunicípio: {mun.upper()}")
    print(f"  ANX06: {p_anx06}")
    print(f"  ANX02: {p_anx02}")
    print(f"  BP:    {p_bp}")
    print(f"  DFC:   {p_dfc}")

    only = args.only

    if (not only or only == 'anx06') and p_anx06 and os.path.exists(p_anx06):
        diagnosticar_anx06(p_anx06)

    if (not only or only == 'anx02') and p_anx02 and os.path.exists(p_anx02):
        diagnosticar_anx02(p_anx02)

    if (not only or only == 'bp') and p_bp and os.path.exists(p_bp):
        diagnosticar_anx14_qb(p_bp)

    if (not only or only == 'dfc') and p_dfc and os.path.exists(p_dfc):
        diagnosticar_dfc(p_dfc)


if __name__ == '__main__':
    main()
