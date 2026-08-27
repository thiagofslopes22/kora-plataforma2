"""
Backoffice da plataforma (SUPER_ADMIN) — onboarding de escritorios.

Este e o unico lugar do sistema que enxerga mais de um escritorio. Ele roda
sobre um pool de conexao separado, com o papel `kora_platform`; as politicas de
RLS liberam o acesso cross-tenant checando `app.eh_plataforma()`, que depende do
PAPEL DA CONEXAO — nao de um GUC. Ou seja: o backend de tenant nao consegue
alcancar estas operacoes nem com um token adulterado, porque ele sequer conecta
com o papel certo.

Fluxo de onboarding de um escritorio de contabilidade novo:
  1. POST /plataforma/escritorios  -> cria o escritorio JA ativo e o primeiro
                                      usuario admin_escritorio dele
  2. o admin loga em /auth/login e passa a gerir os proprios usuarios,
     entidades e municipios, sem nunca ver outro escritorio.
"""
from __future__ import annotations

import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from auth import AdminPlataforma, get_admin_plataforma
from database import db_plataforma
from kora_db import criar_token_plataforma, hash_senha, verificar_senha

router = APIRouter(prefix="/plataforma", tags=["plataforma"])


def _normalizar(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def _so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class LoginPlataforma(BaseModel):
    email: str
    senha: str


class EscritorioCreate(BaseModel):
    razao_social: str = Field(min_length=3)
    cnpj: str
    nome_fantasia: str | None = None
    plano: str = "trial"
    max_usuarios: int = 5
    max_municipios: int = 3
    # primeiro admin do escritorio
    admin_nome: str = Field(min_length=3)
    admin_email: str
    admin_senha: str = Field(min_length=8)


class SuspenderRequest(BaseModel):
    motivo: str = Field(min_length=3)


# ---------------------------------------------------------------------------
# Login do super-admin (fluxo proprio, fora do modelo de tenant)
# ---------------------------------------------------------------------------
@router.post("/login")
def login_plataforma(body: LoginPlataforma, db: Session = Depends(db_plataforma)):
    email = (body.email or "").strip().lower()
    linha = db.execute(
        text(
            "SELECT id, nome, email, senha_hash, ativo FROM plataforma_admins "
            "WHERE email = CAST(:e AS email_ci)"
        ),
        {"e": email},
    ).mappings().first()

    generico = HTTPException(status_code=401, detail="Email ou senha incorretos")
    if not linha or not linha["ativo"]:
        raise generico
    confere, _ = verificar_senha(body.senha, linha["senha_hash"])
    if not confere:
        raise generico

    db.execute(
        text("UPDATE plataforma_admins SET ultimo_login_em = now() WHERE id = :id"),
        {"id": linha["id"]},
    )
    return {
        "access_token": criar_token_plataforma(linha["id"], linha["email"]),
        "token_type": "bearer",
        "id": linha["id"],
        "nome": linha["nome"],
        "email": linha["email"],
        "tipo": "plataforma",
    }


# ---------------------------------------------------------------------------
# Escritorios
# ---------------------------------------------------------------------------
@router.get("/escritorios")
def listar_escritorios(
    _admin: AdminPlataforma = Depends(get_admin_plataforma),
    db: Session = Depends(db_plataforma),
):
    linhas = db.execute(
        text(
            "SELECT e.id, e.ulid_publico, e.razao_social, e.nome_fantasia, e.cnpj, "
            "       e.status, e.plano, e.limites, e.criado_em, e.liberado_em, "
            "       (SELECT count(*) FROM usuarios u "
            "          WHERE u.escritorio_id = e.id AND u.deleted_at IS NULL) AS total_usuarios, "
            "       (SELECT count(*) FROM entidades en "
            "          WHERE en.escritorio_id = e.id AND en.deleted_at IS NULL) AS total_entidades "
            "FROM escritorios e WHERE e.deleted_at IS NULL ORDER BY e.criado_em DESC"
        )
    ).mappings().all()
    return [dict(r) for r in linhas]


@router.post("/escritorios", status_code=201)
def criar_escritorio(
    body: EscritorioCreate,
    admin: AdminPlataforma = Depends(get_admin_plataforma),
    db: Session = Depends(db_plataforma),
):
    """Cria o escritorio e seu primeiro admin numa unica transacao.

    Escritorio sem admin e um tenant orfao — ninguem consegue entrar nele para
    consertar. Por isso os dois nascem juntos ou nenhum nasce."""
    cnpj = _so_digitos(body.cnpj)
    if len(cnpj) != 14:
        raise HTTPException(status_code=422, detail="CNPJ deve ter 14 digitos")

    email = (body.admin_email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="E-mail do admin invalido")

    if db.execute(
        text("SELECT 1 FROM escritorios WHERE cnpj = CAST(:c AS cnpj) AND deleted_at IS NULL"),
        {"c": cnpj},
    ).first():
        raise HTTPException(status_code=409, detail="Ja existe escritorio com este CNPJ")

    # email e unico GLOBALMENTE (o login resolve o tenant pelo email)
    if db.execute(
        text("SELECT 1 FROM usuarios WHERE email = CAST(:e AS email_ci) AND deleted_at IS NULL"),
        {"e": email},
    ).first():
        raise HTTPException(
            status_code=409,
            detail="Este e-mail ja pertence a um usuario de outro escritorio.",
        )

    escritorio_id = db.execute(
        text(
            "INSERT INTO escritorios "
            "  (razao_social, nome_fantasia, nome_normalizado, cnpj, status, plano, "
            "   limites, liberado_em, liberado_por) "
            "VALUES (:rs, :nf, :nn, CAST(:cnpj AS cnpj), 'ativo', CAST(:plano AS plano_escritorio), "
            "        CAST(:limites AS jsonb), now(), :admin_id) "
            "RETURNING id"
        ),
        {
            "rs": body.razao_social.strip(),
            "nf": (body.nome_fantasia or "").strip() or None,
            "nn": _normalizar(body.nome_fantasia or body.razao_social),
            "cnpj": cnpj,
            "plano": body.plano,
            "limites": (
                '{"max_usuarios": %d, "max_municipios": %d}'
                % (int(body.max_usuarios), int(body.max_municipios))
            ),
            "admin_id": admin.id,
        },
    ).scalar_one()

    usuario_id = db.execute(
        text(
            "INSERT INTO usuarios (escritorio_id, nome, email, senha_hash, papel, status) "
            "VALUES (:esc, :nome, CAST(:email AS email_ci), :hash, 'admin_escritorio', 'ativo') "
            "RETURNING id"
        ),
        {
            "esc": escritorio_id,
            "nome": body.admin_nome.strip(),
            "email": email,
            "hash": hash_senha(body.admin_senha),
        },
    ).scalar_one()

    return {
        "id": escritorio_id,
        "razao_social": body.razao_social,
        "cnpj": cnpj,
        "status": "ativo",
        "admin": {"id": usuario_id, "nome": body.admin_nome, "email": email},
    }


@router.patch("/escritorios/{escritorio_id}/suspender")
def suspender_escritorio(
    escritorio_id: int,
    body: SuspenderRequest,
    admin: AdminPlataforma = Depends(get_admin_plataforma),
    db: Session = Depends(db_plataforma),
):
    """Suspende o escritorio. O corte e no login (auth.autenticar checa o status
    do escritorio), entao sessoes ja emitidas expiram junto com o token."""
    afetadas = db.execute(
        text(
            "UPDATE escritorios SET status = 'suspenso', suspenso_em = now(), "
            "  suspenso_por = :admin, motivo_suspensao = :motivo "
            "WHERE id = :id AND deleted_at IS NULL"
        ),
        {"id": escritorio_id, "admin": admin.id, "motivo": body.motivo},
    ).rowcount
    if not afetadas:
        raise HTTPException(status_code=404, detail="Escritorio nao encontrado")
    return {"id": escritorio_id, "status": "suspenso", "motivo": body.motivo}


@router.patch("/escritorios/{escritorio_id}/reativar")
def reativar_escritorio(
    escritorio_id: int,
    admin: AdminPlataforma = Depends(get_admin_plataforma),
    db: Session = Depends(db_plataforma),
):
    afetadas = db.execute(
        text(
            "UPDATE escritorios SET status = 'ativo', liberado_em = coalesce(liberado_em, now()), "
            "  liberado_por = coalesce(liberado_por, :admin), suspenso_em = NULL, "
            "  suspenso_por = NULL, motivo_suspensao = NULL "
            "WHERE id = :id AND deleted_at IS NULL"
        ),
        {"id": escritorio_id, "admin": admin.id},
    ).rowcount
    if not afetadas:
        raise HTTPException(status_code=404, detail="Escritorio nao encontrado")
    return {"id": escritorio_id, "status": "ativo"}
