#!/usr/bin/env python3
"""
Cria o PRIMEIRO super-admin da plataforma — o ovo-e-galinha do onboarding.

Sem ele nao ha como criar o primeiro escritorio pela API, porque toda rota do
backoffice exige um token de plataforma. Rode UMA vez depois da migracao.

  export DATABASE_URL=...            # mesma URL usada na migracao
  export KORA_ADMIN_EMAIL=voce@dominio.com
  export KORA_ADMIN_SENHA='...'      # min. 12 caracteres
  export KORA_ADMIN_NOME='Seu Nome'
  python db/bootstrap.py

Idempotente: se o e-mail ja existir, nao recria nem sobrescreve a senha (para
nao virar um caminho silencioso de troca de credencial). Use --resetar-senha
se a intencao for exatamente essa.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import carregar_env  # noqa: E402
from kora_db.seguranca import hash_senha  # noqa: E402


def main() -> None:
    carregar_env()
    url = os.getenv("DATABASE_URL", "")
    if not url:
        sys.exit("ERRO: DATABASE_URL nao definida.")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    email = (os.getenv("KORA_ADMIN_EMAIL", "") or "").strip().lower()
    senha = os.getenv("KORA_ADMIN_SENHA", "")
    nome = os.getenv("KORA_ADMIN_NOME", "Super Admin").strip()
    resetar = "--resetar-senha" in sys.argv

    if not email or "@" not in email:
        sys.exit("ERRO: KORA_ADMIN_EMAIL invalida ou ausente.")
    if len(senha) < 12:
        sys.exit("ERRO: KORA_ADMIN_SENHA ausente ou com menos de 12 caracteres.")

    conn = psycopg2.connect(url)
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM plataforma_admins WHERE email = %s", (email,))
            existente = cur.fetchone()

            if existente and not resetar:
                print(f"Super-admin '{email}' ja existe (id={existente[0]}). Nada a fazer.")
                print("Para trocar a senha: python db/bootstrap.py --resetar-senha")
                return

            if existente:
                cur.execute(
                    "UPDATE plataforma_admins SET senha_hash = %s, ativo = true WHERE id = %s",
                    (hash_senha(senha), existente[0]),
                )
                print(f"Senha do super-admin '{email}' redefinida (id={existente[0]}).")
                return

            cur.execute(
                "INSERT INTO plataforma_admins (nome, email, senha_hash, ativo) "
                "VALUES (%s, %s, %s, true) RETURNING id",
                (nome, email, hash_senha(senha)),
            )
            novo_id = cur.fetchone()[0]
            print(f"Super-admin criado: {email} (id={novo_id})")
            print("\nProximo passo — criar o primeiro escritorio:")
            print("  POST /conc/plataforma/login       -> pega o token")
            print("  POST /conc/plataforma/escritorios -> cria escritorio + admin dele")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
