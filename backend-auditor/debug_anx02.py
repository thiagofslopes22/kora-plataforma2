import sys
sys.path.insert(0, ".")
from backend.extractors.anx02_despesas import extrair, _agrupar_linhas, ORGAO_RE

pdf = r"C:\Users\claud\Desktop\auditor_tce6\arquivo\anx22025.pdf"

# Mostra as primeiras 60 linhas brutas
linhas = _agrupar_linhas(pdf)
print("=== PRIMEIRAS 80 LINHAS BRUTAS ===")
for i, l in enumerate(linhas[:80]):
    matched = ORGAO_RE.match(l)
    print(f"[{i:03}] {'[ORGAO]' if matched else '       '} {repr(l[:100])}")

print()
print("=== RESULTADO EXTRAIR ===")
r = extrair(pdf)
print("Municipio:", r["municipio"])
print("Exercicio:", r["exercicio"])
print("Orgaos encontrados:", len(r["orgaos"]))
for cod, o in r["orgaos"].items():
    print("  [%s] nome=%s total=%.2f pessoal=%.2f" % (cod, repr(o["nome"]), o["total"], o["pessoal_encargos"]))
print("Total itens:", len(r["itens"]))
