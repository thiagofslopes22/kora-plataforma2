"""
Autenticacao multi-tenant.

O ponto delicado do login em SaaS multi-tenant: para achar o usuario e preciso
consultar a tabela `usuarios`, mas ainda NAO se sabe o tenant — e sem contexto
a RLS (corretamente) esconde tudo. A saida e uma unica funcao SECURITY DEFINER
no banco, `app.autenticar(email)`, que faz esse lookup especifico e nada mais.
E a unica porta pre-tenant, e ela so devolve o necessario para validar a senha.

Depois do login, o tenant vem do TOKEN, nunca de um parametro da request — o
cliente nao escolhe em qual escritorio quer entrar.

O papel (`admin_escritorio`/`funcionario`) viaja no token por conveniencia da
UI, mas a autoridade real e do banco: as politicas de RLS chamam
`app.eh_admin_escritorio()`, que le a tabela `usuarios`. Um token forjado com
papel elevado nao amplia o que a RLS deixa ver.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text

_RAIZ = Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from kora_db import (  # noqa: E402
    criar_token_usuario,
    decodificar_token,
    hash_senha,
    sessao_sem_tenant,
    sessao_tenant,
    verificar_senha,
)

MAX_TENTATIVAS = 5
BLOQUEIO_MINUTOS = 15


class UsuarioAutenticado:
    """Identidade resolvida do token. Nao e o ORM — e so o contexto do request."""

    def __init__(self, escritorio_id: int, id: int, email: str, papel: str):
        self.escritorio_id = escritorio_id
        self.id = id
        self.email = email
        self.papel = papel

    @property
    def eh_admin(self) -> bool:
        return self.papel == "admin_escritorio"


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
def autenticar(email: str, senha: str) -> dict:
    """Valida credenciais e devolve o payload de login.

    Levanta HTTPException(401) com mensagem generica em qualquer falha de
    credencial — nao distingue 'email inexistente' de 'senha errada' para nao
    virar um oraculo de enumeracao de usuarios."""
    email = (email or "").strip().lower()
    generico = HTTPException(status_code=401, detail="Email ou senha incorretos")

    with sessao_sem_tenant() as s:
        linha = s.execute(
            text(
                "SELECT escritorio_id, usuario_id, senha_hash, papel, "
                "       usuario_status, bloqueado_ate, escritorio_status "
                "FROM app.autenticar(CAST(:email AS email_ci))"
            ),
            {"email": email},
        ).mappings().first()

    if not linha:
        raise generico

    if linha["bloqueado_ate"] and linha["bloqueado_ate"] > datetime.now(timezone.utc):
        raise HTTPException(
            status_code=429,
            detail=f"Conta bloqueada por excesso de tentativas. Tente em {BLOQUEIO_MINUTOS} minutos.",
        )

    confere, precisa_rehash = verificar_senha(senha, linha["senha_hash"])
    if not confere:
        _registrar_falha(linha["escritorio_id"], linha["usuario_id"])
        raise generico

    if linha["usuario_status"] != "ativo":
        raise HTTPException(
            status_code=403,
            detail="Usuario ainda nao ativado ou suspenso. Fale com o admin do seu escritorio.",
        )
    if linha["escritorio_status"] != "ativo":
        raise HTTPException(
            status_code=403,
            detail=f"Escritorio com status '{linha['escritorio_status']}'. Acesso indisponivel.",
        )

    escritorio_id = linha["escritorio_id"]
    usuario_id = linha["usuario_id"]

    # Login OK: zera contador, marca ultimo acesso e promove bcrypt -> Argon2id.
    with sessao_tenant(escritorio_id, usuario_id) as s:
        if precisa_rehash:
            s.execute(
                text(
                    "UPDATE usuarios SET senha_hash = :h, tentativas_falhas = 0, "
                    "bloqueado_ate = NULL, ultimo_login_em = now() WHERE id = :id"
                ),
                {"h": hash_senha(senha), "id": usuario_id},
            )
        else:
            s.execute(
                text(
                    "UPDATE usuarios SET tentativas_falhas = 0, bloqueado_ate = NULL, "
                    "ultimo_login_em = now() WHERE id = :id"
                ),
                {"id": usuario_id},
            )
        dados = s.execute(
            text("SELECT nome, email, papel FROM usuarios WHERE id = :id"),
            {"id": usuario_id},
        ).mappings().first()

    token = criar_token_usuario(escritorio_id, usuario_id, dados["papel"], dados["email"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "id": usuario_id,
        "escritorio_id": escritorio_id,
        "nome": dados["nome"],
        "email": dados["email"],
        "papel": dados["papel"],
        # alias p/ compatibilidade com o front atual, que le `role`
        "role": "admin" if dados["papel"] == "admin_escritorio" else "auditor",
    }


def _registrar_falha(escritorio_id: int, usuario_id: int) -> None:
    """Incrementa o contador e bloqueia ao atingir o limite. Falha de escrita
    aqui nao pode derrubar o login — o retorno ao cliente ja e 401."""
    try:
        with sessao_tenant(escritorio_id, usuario_id) as s:
            s.execute(
                text(
                    "UPDATE usuarios "
                    "SET tentativas_falhas = tentativas_falhas + 1, "
                    "    bloqueado_ate = CASE WHEN tentativas_falhas + 1 >= :max "
                    "                         THEN now() + make_interval(mins => :mins) "
                    "                         ELSE bloqueado_ate END "
                    "WHERE id = :id"
                ),
                {"id": usuario_id, "max": MAX_TENTATIVAS, "mins": BLOQUEIO_MINUTOS},
            )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Dependencias FastAPI
# ---------------------------------------------------------------------------
def _token_do_header(request: Request) -> str:
    cabecalho = request.headers.get("Authorization", "")
    if not cabecalho.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Nao autenticado")
    return cabecalho[7:]


def get_current_user(request: Request) -> UsuarioAutenticado:
    payload = decodificar_token(_token_do_header(request))
    if not payload or payload.get("tipo") != "usuario":
        raise HTTPException(status_code=401, detail="Token invalido ou expirado")
    return UsuarioAutenticado(
        escritorio_id=payload["esc"],
        id=payload["uid"],
        email=payload.get("sub", ""),
        papel=payload.get("papel", "funcionario"),
    )


def require_admin(usuario: UsuarioAutenticado = Depends(get_current_user)) -> UsuarioAutenticado:
    """Checagem de conveniencia para responder 403 cedo, com mensagem clara.

    Nao e a fronteira de seguranca: mesmo que ela falhasse, a RLS continuaria
    barrando escrita de quem nao e admin do escritorio."""
    if not usuario.eh_admin:
        raise HTTPException(status_code=403, detail="Acesso restrito ao admin do escritorio")
    return usuario


def db_tenant(usuario: UsuarioAutenticado = Depends(get_current_user)):
    """Dependency principal: sessao ja amarrada ao escritorio do usuario logado.

    Toda query feita com esta sessao e filtrada pela RLS. Rotas nao precisam
    (nem devem) escrever `WHERE escritorio_id = ...`."""
    with sessao_tenant(usuario.escritorio_id, usuario.id) as s:
        yield s


# ---------------------------------------------------------------------------
# Admin de plataforma (super-admin) — fluxo separado, fora do modelo de tenant
# ---------------------------------------------------------------------------
class AdminPlataforma:
    def __init__(self, id: int, email: str):
        self.id = id
        self.email = email


def get_admin_plataforma(request: Request) -> AdminPlataforma:
    payload = decodificar_token(_token_do_header(request))
    if not payload or payload.get("tipo") != "plataforma":
        raise HTTPException(status_code=403, detail="Acesso restrito ao super-admin da plataforma")
    return AdminPlataforma(id=payload["aid"], email=payload.get("sub", ""))
