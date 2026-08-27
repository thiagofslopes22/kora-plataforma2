"""
Engines de conexao da KORA. Dois pools, deliberadamente separados.

  APP      -> papel `kora_app`      : caminho de request do tenant. Sujeito a RLS.
  PLATAFORMA -> papel `kora_platform`: backoffice SUPER_ADMIN, cross-tenant.

A separacao e de seguranca, nao de performance: acesso cross-tenant exige um
papel de conexao diferente, entao um bug no backend de tenant nao vira acesso
global (o papel kora_app nao consegue se declarar plataforma via GUC).

Nenhum dos dois tem BYPASSRLS.
"""
from __future__ import annotations

import os
from urllib.parse import quote_plus

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Montagem da URL
# ---------------------------------------------------------------------------
# No Railway o servico Postgres injeta DATABASE_URL apontando para o usuario
# admin. NAO usamos essa URL no caminho de request — ela e so para migracao.
# Os backends conectam com kora_app/kora_platform, cujas senhas vem das envs.


def _url_base() -> str:
    """URL do banco sem credenciais de aplicacao (host/porta/database)."""
    bruta = os.getenv("DATABASE_URL", "")
    if not bruta:
        raise RuntimeError(
            "DATABASE_URL nao definida. No Railway, referencie o servico Postgres "
            "com ${{Postgres.DATABASE_URL}}."
        )
    if bruta.startswith("postgres://"):
        bruta = bruta.replace("postgres://", "postgresql://", 1)
    return bruta


def _sufixo_pooler(url) -> str:
    """No Supavisor (pooler do Supabase) o projeto vai no NOME DE USUARIO, no
    formato `papel.projectref` — o host sozinho nao identifica o projeto.

    A DATABASE_URL do projeto ja vem como `postgres.<ref>@...pooler.supabase.com`,
    entao extraimos o `<ref>` dela em vez de pedir mais uma variavel de ambiente.
    Fora do pooler, devolve string vazia e o usuario vai puro."""
    host = (url.host or "")
    if "pooler.supabase.com" not in host:
        return ""
    usuario = url.username or ""
    if "." in usuario:
        return "." + usuario.split(".", 1)[1]
    ref = os.getenv("SUPABASE_PROJECT_REF", "")
    if not ref:
        raise RuntimeError(
            "Conexao via pooler do Supabase exige o project ref no usuario. "
            "A DATABASE_URL deveria ser 'postgres.<ref>@...pooler.supabase.com'; "
            "se nao for, defina SUPABASE_PROJECT_REF."
        )
    return "." + ref


def _url_para(papel: str, env_senha: str) -> str:
    """Reescreve a DATABASE_URL trocando usuario/senha pelos do papel dado."""
    senha = os.getenv(env_senha, "")
    if not senha:
        raise RuntimeError(f"{env_senha} nao definida — necessaria para conectar como {papel}.")
    url = make_url(_url_base())
    # Pooler em transaction mode e compativel com o SET LOCAL por transacao que a
    # RLS usa (o contexto e reaplicado a cada transacao — ver contexto.py).
    pooler = os.getenv("PGBOUNCER_HOST")
    if pooler:
        url = url.set(host=pooler, port=int(os.getenv("PGBOUNCER_PORT", "6543")))
    return url.set(
        username=papel + _sufixo_pooler(url), password=senha
    ).render_as_string(hide_password=False)


def _criar_engine(papel: str, env_senha: str, pool_size: int) -> Engine:
    # pool_pre_ping troca robustez por latencia: gasta um round-trip ("SELECT 1")
    # a cada checkout de conexao. Com o banco em outra regiao isso e ~150ms
    # somados a TODO request. Fica ligado por padrao (conexao morta e pior que
    # request lento), mas da para desligar em KORA_POOL_PRE_PING=0 depois de
    # medir a estabilidade do pooler.
    pre_ping = os.getenv("KORA_POOL_PRE_PING", "1") != "0"
    eng = create_engine(
        _url_para(papel, env_senha),
        pool_size=pool_size,
        max_overflow=pool_size,
        pool_pre_ping=pre_ping,
        pool_recycle=1800,
        connect_args={"connect_timeout": int(os.getenv("KORA_CONNECT_TIMEOUT", "10"))},
        future=True,
    )

    @event.listens_for(eng, "connect")
    def _search_path_explicito(dbapi_conn, _rec):
        # search_path explicito: evita que um schema homonimo shadowe as tabelas.
        # `extensions` entra porque o Supabase instala pg_trgm/pgcrypto la — sem
        # ele, gen_random_bytes() (usado no DEFAULT de ulid_publico) nao resolve.
        with dbapi_conn.cursor() as cur:
            cur.execute("SET search_path TO public, app, extensions")

    return eng


# ---------------------------------------------------------------------------
# Instancias preguicosas (so conectam quando usadas — deixa importar sem env)
# ---------------------------------------------------------------------------
_engine_app: Engine | None = None
_engine_plataforma: Engine | None = None


def engine_app() -> Engine:
    global _engine_app
    if _engine_app is None:
        _engine_app = _criar_engine(
            "kora_app", "KORA_APP_PASSWORD", int(os.getenv("KORA_POOL_APP", "10"))
        )
    return _engine_app


def engine_plataforma() -> Engine:
    global _engine_plataforma
    if _engine_plataforma is None:
        _engine_plataforma = _criar_engine(
            "kora_platform", "KORA_PLATFORM_PASSWORD", int(os.getenv("KORA_POOL_PLATAFORMA", "3"))
        )
    return _engine_plataforma


def SessaoApp():
    return sessionmaker(bind=engine_app(), autoflush=False, future=True)()


def SessaoPlataforma():
    return sessionmaker(bind=engine_plataforma(), autoflush=False, future=True)()


def checar_saude() -> dict:
    """Ping simples nos dois pools — usado pelo /health dos backends."""
    out = {}
    for nome, fabrica in (("app", SessaoApp), ("plataforma", SessaoPlataforma)):
        try:
            s = fabrica()
            try:
                s.execute(text("SELECT 1"))
                out[nome] = "ok"
            finally:
                s.close()
        except Exception as e:  # noqa: BLE001 — health check reporta, nao propaga
            out[nome] = f"erro: {type(e).__name__}"
    return out
