"""
kora_db — camada de dados comum aos backends conciliador e auditor.

Existe para que os dois falem com o MESMO banco multi-tenant da mesma forma:
conectando com o papel `kora_app` e carregando o contexto de tenant em toda
transacao, para a RLS do Postgres fazer o isolamento entre escritorios.

Uso tipico numa rota FastAPI:

    from kora_db import sessao_tenant

    with sessao_tenant(usuario.escritorio_id, usuario.id) as db:
        entidades = db.execute(text("SELECT * FROM entidades")).mappings().all()
        # ^ so retorna as entidades DESTE escritorio, garantido pelo banco
"""
from .contexto import sessao_plataforma, sessao_sem_tenant, sessao_tenant
from .engine import SessaoApp, SessaoPlataforma, checar_saude, engine_app, engine_plataforma
from .seguranca import (
    criar_token_plataforma,
    criar_token_usuario,
    decodificar_token,
    hash_senha,
    verificar_senha,
)

__all__ = [
    "sessao_tenant",
    "sessao_sem_tenant",
    "sessao_plataforma",
    "SessaoApp",
    "SessaoPlataforma",
    "engine_app",
    "engine_plataforma",
    "checar_saude",
    "hash_senha",
    "verificar_senha",
    "criar_token_usuario",
    "criar_token_plataforma",
    "decodificar_token",
]
