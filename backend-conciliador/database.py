"""
Dependencias de sessao do conciliador.

Tres portas de entrada, com poderes bem diferentes — escolher a errada e o
unico jeito de furar o isolamento, entao elas tem nomes explicitos:

    db_tenant       sessao do usuario logado. RLS ativa, so ve o proprio
                    escritorio. E a que quase toda rota deve usar.
    db_sem_tenant   sem contexto. So para login e leitura de referencia
                    global (municipios/competencias). Tabela de tenant lida
                    aqui volta VAZIA — de proposito.
    db_plataforma   papel kora_platform, cross-tenant. So o backoffice do
                    super-admin.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# kora_db vive na raiz do repositorio (compartilhado com o backend-auditor).
_RAIZ = Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

# Em desenvolvimento, le as credenciais do .env.supabase da raiz. Em producao
# (Railway) o arquivo nao existe e as variaveis vem do proprio ambiente — o
# carregador nunca sobrescreve variavel ja definida, entao os dois convivem.
sys.path.insert(0, str(_RAIZ / "db"))
try:
    from _env import carregar_env

    carregar_env(verboso=False)
except ImportError:
    pass

from kora_db import (  # noqa: E402
    checar_saude,
    sessao_plataforma,
    sessao_sem_tenant,
    sessao_tenant,
)
from kora_db.engine import engine_app  # noqa: E402

__all__ = [
    "db_sem_tenant",
    "db_plataforma",
    "sessao_tenant",
    "checar_saude",
    "engine_app",
]


def db_sem_tenant():
    """FastAPI dependency: sessao sem contexto de tenant (login/referencia)."""
    with sessao_sem_tenant() as s:
        yield s


def db_plataforma():
    """FastAPI dependency: sessao do backoffice (cross-tenant)."""
    with sessao_plataforma() as s:
        yield s


def modo_legado() -> bool:
    """True quando ainda apontando para o SQLite do prototipo.

    Serve para dar erro claro no boot em vez de falhar com 'relation does not
    exist' na primeira request."""
    return "sqlite" in os.getenv("DATABASE_URL", "sqlite:///./kora.db")
