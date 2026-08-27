"""
Contexto de tenant por transacao — o elo entre o JWT da aplicacao e a RLS.

A RLS do banco le dois GUCs:
    app.current_tenant   -> escritorio_id
    app.current_user_id  -> usuarios.id

Sem eles, `app.tenant_atual()` retorna NULL e NENHUMA linha e visivel
(fail-closed). Este modulo garante que toda transacao aberta na sessao carregue
o contexto — inclusive as que comecam DEPOIS de um commit.

Por que um listener em vez de um SET LOCAL solto no inicio do request:
`SET LOCAL` vale ate o fim da transacao. Se a rota faz dois commits, a segunda
transacao voltaria sem contexto e as queries silenciosamente nao veriam nada.
O hook `after_begin` reaplica o contexto em toda transacao da sessao.

Usamos `set_config(..., true)` (equivalente a SET LOCAL) com bind parameters —
`SET LOCAL` nao aceita parametros e exigiria interpolar string na query.
"""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from .engine import SessaoApp, SessaoPlataforma

_CHAVE = "kora_contexto"


@event.listens_for(Session, "after_begin")
def _ao_iniciar_transacao(sessao: Session, _transacao, conexao) -> None:
    """Reaplica o contexto em CADA transacao da sessao (inclusive pos-commit).

    Executa na CONEXAO entregue pelo evento, nao em `sessao.execute()`: neste
    ponto a sessao ainda esta provisionando a conexao, e reentrar nela levanta
    'this session is provisioning a new connection'."""
    ctx = sessao.info.get(_CHAVE)
    if not ctx:
        return
    escritorio_id, usuario_id = ctx
    # Os dois GUCs num UNICO statement: com o banco em outra regiao (app no
    # Railway/EUA, Postgres em SP) cada ida custa ~150ms, e isto roda em TODA
    # transacao. Duas queries aqui dobrariam esse custo fixo por request.
    conexao.execute(
        text(
            "SELECT set_config('app.current_tenant', :t, true), "
            "       set_config('app.current_user_id', :u, true)"
        ),
        {"t": str(escritorio_id), "u": "" if usuario_id is None else str(usuario_id)},
    )


@contextmanager
def sessao_tenant(escritorio_id: int, usuario_id: int | None = None):
    """Sessao de aplicacao amarrada a um tenant. Tudo que passar por aqui e
    filtrado pela RLS ao escritorio informado."""
    if escritorio_id is None:
        raise ValueError("escritorio_id obrigatorio — sem ele a RLS bloqueia tudo.")
    s = SessaoApp()
    s.info[_CHAVE] = (escritorio_id, usuario_id)
    try:
        # Forca o inicio da transacao para o listener disparar ja no primeiro uso.
        s.execute(text("SELECT 1"))
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


@contextmanager
def sessao_sem_tenant():
    """Sessao de aplicacao SEM contexto de tenant. Use apenas para o login
    (`app.autenticar`, que e SECURITY DEFINER) e leitura de tabelas de
    referencia global (municipios/exercicios/competencias).

    Qualquer SELECT em tabela de tenant aqui volta VAZIO — isso e proposital."""
    s = SessaoApp()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


@contextmanager
def sessao_plataforma():
    """Sessao do backoffice SUPER_ADMIN — enxerga todos os escritorios.

    Conecta com o papel `kora_platform`; as politicas de RLS liberam o acesso
    cross-tenant via `app.eh_plataforma()`. Nunca use no caminho de request de
    um usuario de escritorio."""
    s = SessaoPlataforma()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
