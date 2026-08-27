#!/usr/bin/env python3
"""
KORA-PLATAFORMA — runner de migracao do schema multi-tenant.

Aplica os arquivos db/00..10 em ordem contra o DATABASE_URL, uma unica vez cada,
registrando o que ja rodou em `kora_schema_migrations`. Feito para rodar tanto
local quanto no Railway (`python db/migrate.py`), sem assumir superusuario.

Variaveis de ambiente:
  DATABASE_URL            (obrigatoria) conexao do dono/admin do banco.
                          No Railway: a URL do servico Postgres.
  KORA_APP_PASSWORD       senha do papel kora_app      (usado pelos backends)
  KORA_PLATFORM_PASSWORD  senha do papel kora_platform (backoffice super-admin)
  KORA_READONLY_PASSWORD  senha do papel kora_readonly (BI/suporte)

As senhas sao substituidas nos placeholders ${...} do arquivo 00 e REAPLICADAS
a cada execucao (ALTER ROLE), entao rotacionar senha = trocar a env e re-rodar.

Uso:
  python db/migrate.py              aplica o que falta
  python db/migrate.py --status     so mostra o que ja foi aplicado
  python db/migrate.py --seed       aplica migracoes + seeds de referencia
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import carregar_env  # noqa: E402

DB_DIR = Path(__file__).resolve().parent
SEED_DIR = DB_DIR / "seeds"

# Ordem importa. O 09 e um catalogo de queries de exemplo, nao schema — fora.
MIGRACOES = [
    "00_papeis_extensoes.sql",
    "01_tipos_funcoes.sql",
    "02_referencia.sql",
    "03_tenant_dominio.sql",
    "04_seguranca_auth.sql",
    "05_particionamento.sql",
    "06_triggers.sql",
    "07_rls.sql",
    "08_agregados_views.sql",
    "10_auditor.sql",
]

TABELA_CONTROLE = """
CREATE TABLE IF NOT EXISTS kora_schema_migrations (
  arquivo      text PRIMARY KEY,
  sha256       text NOT NULL,
  aplicado_em  timestamptz NOT NULL DEFAULT now()
)
"""


def normalizar_url(url: str) -> str:
    """Railway expoe postgres://; psycopg2 aceita, mas normalizamos por higiene."""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def senhas_do_ambiente() -> dict[str, str]:
    """Le as senhas dos papeis. Falha cedo se faltar alguma — melhor do que
    criar papeis com senha placeholder e so descobrir em producao."""
    faltando, out = [], {}
    for var in ("KORA_APP_PASSWORD", "KORA_PLATFORM_PASSWORD", "KORA_READONLY_PASSWORD"):
        valor = os.getenv(var, "")
        if not valor:
            faltando.append(var)
        elif "'" in valor:
            sys.exit(f"ERRO: {var} contem aspa simples — nao suportado no ALTER ROLE.")
        else:
            out[var] = valor
    if faltando:
        sys.exit(
            "ERRO: defina as senhas dos papeis antes de migrar:\n  "
            + "\n  ".join(faltando)
            + "\n\nEx.: export KORA_APP_PASSWORD=$(openssl rand -base64 24)"
        )
    return out


def substituir_placeholders(texto: str, senhas: dict[str, str]) -> str:
    def troca(m: re.Match) -> str:
        var = m.group(1)
        if var not in senhas:
            sys.exit(f"ERRO: placeholder ${{{var}}} sem valor correspondente.")
        return senhas[var]

    return re.sub(r"\$\{(KORA_[A-Z_]+)\}", troca, texto)


def sha(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def aplicados(cur) -> dict[str, str]:
    cur.execute("SELECT arquivo, sha256 FROM kora_schema_migrations")
    return dict(cur.fetchall())


def aplicar(conn, nome: str, caminho: Path, senhas: dict[str, str], ja: dict[str, str]) -> bool:
    """Aplica um arquivo numa transacao propria. Retorna True se rodou agora."""
    bruto = caminho.read_text(encoding="utf-8")
    sql_texto = substituir_placeholders(bruto, senhas)
    # O hash e do arquivo BRUTO: trocar a senha por env nao deve marcar o
    # arquivo como alterado.
    digest = sha(bruto)

    if nome in ja:
        if ja[nome] != digest:
            print(f"  ! {nome}: ja aplicado, mas o arquivo MUDOU desde entao.")
            print("    O runner nao re-aplica automaticamente (risco de DDL destrutivo).")
            print("    Escreva uma migracao nova ou limpe o registro manualmente.")
        else:
            print(f"  = {nome} (ja aplicado)")
        return False

    with conn.cursor() as cur:
        # search_path reaplicado DENTRO da transacao de cada arquivo, e nao uma
        # vez por sessao: atras de um pooler em transaction mode a conexao volta
        # ao pool a cada commit e o estado de sessao se perde. Assim o runner
        # funciona igual em conexao direta, session pooler ou transaction pooler.
        cur.execute("SET search_path TO public, app, extensions")
        cur.execute(sql_texto)
        cur.execute(
            "INSERT INTO kora_schema_migrations (arquivo, sha256) VALUES (%s, %s)",
            (nome, digest),
        )
    conn.commit()
    print(f"  + {nome}")
    return True


def reaplicar_senhas(conn, senhas: dict[str, str]) -> None:
    """Sincroniza as senhas dos papeis a cada execucao, mesmo quando o 00 ja
    foi aplicado — assim rotacionar senha nao exige mexer no banco na mao."""
    mapa = {
        "kora_app": senhas["KORA_APP_PASSWORD"],
        "kora_platform": senhas["KORA_PLATFORM_PASSWORD"],
        "kora_readonly": senhas["KORA_READONLY_PASSWORD"],
    }
    with conn.cursor() as cur:
        for papel, senha in mapa.items():
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (papel,))
            if cur.fetchone():
                cur.execute(
                    sql.SQL("ALTER ROLE {} WITH PASSWORD %s").format(sql.Identifier(papel)),
                    (senha,),
                )
    conn.commit()
    print("  = senhas dos papeis sincronizadas com o ambiente")


def rodar_seeds(conn, senhas: dict[str, str], ja: dict[str, str]) -> int:
    if not SEED_DIR.is_dir():
        print("\nSeeds: diretorio db/seeds nao existe — pulando.")
        return 0
    arquivos = sorted(p for p in SEED_DIR.glob("*.sql"))
    if not arquivos:
        print("\nSeeds: nenhum arquivo — pulando.")
        return 0
    print("\nSeeds de referencia:")
    n = 0
    for caminho in arquivos:
        if aplicar(conn, f"seeds/{caminho.name}", caminho, senhas, ja):
            n += 1
    return n


def main() -> None:
    carregar_env()
    url = os.getenv("DATABASE_URL", "")
    if not url:
        sys.exit("ERRO: DATABASE_URL nao definida.")
    url = normalizar_url(url)

    so_status = "--status" in sys.argv
    com_seed = "--seed" in sys.argv
    senhas = {} if so_status else senhas_do_ambiente()

    conn = psycopg2.connect(url)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            # `extensions` no search_path: o Supabase instala pg_trgm/pgcrypto
            # nesse schema, e o DDL referencia gin_trgm_ops / gen_random_bytes.
            # Sem isso a criacao dos indices trigram falha em Postgres gerenciado.
            cur.execute("SET search_path TO public, app, extensions")
            cur.execute(TABELA_CONTROLE)
        conn.commit()

        with conn.cursor() as cur:
            ja = aplicados(cur)
            cur.execute("SELECT current_database(), current_user")
            banco, usuario = cur.fetchone()

        print(f"Banco: {banco}  |  conectado como: {usuario}")

        if so_status:
            print("\nMigracoes aplicadas:")
            for nome in MIGRACOES:
                print(f"  {'OK ' if nome in ja else '-- '} {nome}")
            for nome in sorted(k for k in ja if k.startswith("seeds/")):
                print(f"  OK  {nome}")
            return

        print("\nSchema:")
        novas = 0
        for nome in MIGRACOES:
            caminho = DB_DIR / nome
            if not caminho.is_file():
                sys.exit(f"ERRO: arquivo ausente: {caminho}")
            if aplicar(conn, nome, caminho, senhas, ja):
                novas += 1

        reaplicar_senhas(conn, senhas)

        if com_seed:
            novas += rodar_seeds(conn, senhas, ja)

        print(f"\nConcluido. {novas} arquivo(s) aplicado(s) nesta execucao.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
