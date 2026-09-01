"""
Backend Conciliador — API multi-tenant.

O que mudou em relacao ao prototipo (SQLite): o isolamento entre escritorios
NAO e feito por filtros nas queries. Toda rota recebe `db` via `db_tenant`, uma
sessao ja amarrada ao escritorio do usuario logado, e a RLS do Postgres corta as
linhas dos outros tenants antes da query enxergar qualquer coisa. Por isso
voce nao vera nenhum `WHERE escritorio_id = ...` aqui — a ausencia e proposital.

Os caminhos das rotas foram mantidos (/prefeituras, /conciliacoes...) para nao
quebrar o frontend, embora no banco a tabela agora se chame `entidades` e a
conciliacao seja uma linha de `validacoes`.
"""
from datetime import datetime, timezone
from typing import Optional
import tempfile, os, uuid, shutil

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import desc, text
from sqlalchemy.orm import Session

from database import checar_saude, modo_legado
from models import Entidade, Municipio, Usuario, Validacao, normalizar
from auth import (
    UsuarioAutenticado,
    autenticar,
    db_tenant,
    get_current_user,
    require_admin,
)
from plataforma import router as plataforma_router
from kora_db import hash_senha
from conciliador import conciliar as _conciliar
from conciliador_rreo import conciliar_rreo as _conciliar_rreo

app = FastAPI(title="Kora — Auditoria Contábil Municipal", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("KORA_CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(plataforma_router)

JOBS: dict[str, dict] = {}


@app.on_event("startup")
def on_startup():
    # O schema e criado pelo runner (python db/migrate.py), nunca pela app:
    # criar tabela em runtime nao consegue aplicar RLS/particionamento e daria
    # um banco silenciosamente sem isolamento.
    if modo_legado():
        raise RuntimeError(
            "DATABASE_URL aponta para SQLite. Este backend agora exige o Postgres "
            "multi-tenant. Rode 'python db/migrate.py --seed' e aponte a DATABASE_URL."
        )


# ─────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    senha: str


class UserCreateRequest(BaseModel):
    nome: str
    email: str
    senha: str
    role: str = "auditor"          # 'admin' -> admin_escritorio
    prefeitura_ids: list[int] = [] # entidades; define os municipios do funcionario


class PrefeituraCreate(BaseModel):
    nome: str
    municipio: str
    uf: str = "MA"
    tipo: str = "prefeitura"
    cnpj: str | None = None


def _papel_para_role(papel: str) -> str:
    """O front fala 'admin'/'auditor'; o banco fala 'admin_escritorio'/'funcionario'."""
    return "admin" if papel == "admin_escritorio" else "auditor"


def _role_para_papel(role: str) -> str:
    return "admin_escritorio" if role == "admin" else "funcionario"


# ─────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────

@app.post("/auth/login")
def login(body: LoginRequest):
    """Login pre-tenant: o escritorio e descoberto pelo e-mail, dentro de
    app.autenticar(). Ver auth.py."""
    return autenticar(body.email, body.senha)


@app.get("/auth/me")
def me(current_user: UsuarioAutenticado = Depends(get_current_user), db: Session = Depends(db_tenant)):
    u = db.execute(
        text("SELECT nome, email, papel, status FROM usuarios WHERE id = :id"),
        {"id": current_user.id},
    ).mappings().first()
    if not u:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")

    entidades = [
        r[0] for r in db.execute(
            text(
                "SELECT e.id FROM entidades e WHERE e.deleted_at IS NULL AND e.ativo"
            )
        ).all()
    ]
    return {
        "id": current_user.id,
        "escritorio_id": current_user.escritorio_id,
        "nome": u["nome"],
        "email": u["email"],
        "papel": u["papel"],
        "role": _papel_para_role(u["papel"]),
        "ativo": u["status"] == "ativo",
        # as entidades visiveis ja vem filtradas pela RLS (escopo de municipio)
        "prefeitura_ids": entidades,
    }


@app.get("/auth/usuarios")
def list_users(
    _admin: UsuarioAutenticado = Depends(require_admin),
    db: Session = Depends(db_tenant),
):
    linhas = db.execute(
        text(
            "SELECT id, nome, email, papel, status, criado_em, ultimo_login_em "
            "FROM usuarios WHERE deleted_at IS NULL ORDER BY criado_em"
        )
    ).mappings().all()
    return [
        {
            "id": r["id"],
            "nome": r["nome"],
            "email": r["email"],
            "papel": r["papel"],
            "role": _papel_para_role(r["papel"]),
            "ativo": r["status"] == "ativo",
            "criado_em": r["criado_em"].isoformat(),
            "ultimo_login_em": r["ultimo_login_em"].isoformat() if r["ultimo_login_em"] else None,
        }
        for r in linhas
    ]


@app.post("/auth/usuarios", status_code=201)
def create_user(
    body: UserCreateRequest,
    admin: UsuarioAutenticado = Depends(require_admin),
    db: Session = Depends(db_tenant),
):
    email = (body.email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="E-mail inválido")
    if len(body.senha or "") < 8:
        raise HTTPException(status_code=422, detail="Senha deve ter ao menos 8 caracteres")

    # e-mail e unico GLOBALMENTE (o login resolve o tenant por ele), entao a
    # colisao pode ser com usuario de OUTRO escritorio — que a RLS esconde.
    # Por isso a checagem e feita pela violacao da constraint, nao por SELECT.
    try:
        usuario_id = db.execute(
            text(
                "INSERT INTO usuarios (escritorio_id, nome, email, senha_hash, papel, status, criado_por) "
                "VALUES (:esc, :nome, CAST(:email AS email_ci), :hash, "
                "        CAST(:papel AS papel_usuario), 'ativo', :criador) RETURNING id"
            ),
            {
                "esc": admin.escritorio_id,
                "nome": body.nome.strip(),
                "email": email,
                "hash": hash_senha(body.senha),
                "papel": _role_para_papel(body.role),
                "criador": admin.id,
            },
        ).scalar_one()
    except Exception as e:
        if "ux_usuarios_email" in str(e):
            raise HTTPException(status_code=409, detail="E-mail já cadastrado")
        raise

    # Funcionario so enxerga os municipios atribuidos. A atribuicao vem das
    # entidades escolhidas — e a RLS le esta tabela para montar o escopo.
    if body.prefeitura_ids:
        db.execute(
            text(
                "INSERT INTO usuarios_municipios (escritorio_id, usuario_id, municipio_id, atribuido_por) "
                "SELECT :esc, :uid, e.municipio_id, :por FROM entidades e "
                "WHERE e.id = ANY(:ids) AND e.deleted_at IS NULL "
                "ON CONFLICT DO NOTHING"
            ),
            {"esc": admin.escritorio_id, "uid": usuario_id, "por": admin.id, "ids": body.prefeitura_ids},
        )

    return {
        "id": usuario_id,
        "nome": body.nome,
        "email": email,
        "role": body.role,
        "papel": _role_para_papel(body.role),
        "ativo": True,
    }


@app.patch("/auth/usuarios/{user_id}/toggle")
def toggle_user(
    user_id: int,
    admin: UsuarioAutenticado = Depends(require_admin),
    db: Session = Depends(db_tenant),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Você não pode desativar a si mesmo")
    novo = db.execute(
        text(
            "UPDATE usuarios SET status = CASE WHEN status = 'ativo' THEN 'suspenso' ELSE 'ativo' END "
            "WHERE id = :id AND deleted_at IS NULL RETURNING status"
        ),
        {"id": user_id},
    ).scalar()
    if novo is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return {"id": user_id, "ativo": novo == "ativo", "status": novo}


# ─────────────────────────────────────────────────────────
# Entidades (rota mantida como /prefeituras p/ compatibilidade do front)
# ─────────────────────────────────────────────────────────

def _entidade_dict(r) -> dict:
    return {
        "id": r["id"],
        "nome": r["nome"],
        "municipio": r["municipio"],
        "uf": r["uf"],
        "tipo": r["tipo"],
        "ativo": r["ativo"],
        "criado_em": r["criado_em"].isoformat(),
    }


_SQL_ENTIDADES = (
    "SELECT e.id, e.nome, e.tipo, e.ativo, e.criado_em, m.nome AS municipio, m.uf "
    "FROM entidades e JOIN municipios m ON m.id = e.municipio_id "
    "WHERE e.deleted_at IS NULL"
)


def _resolver_municipio(db: Session, nome: str, uf: str, escritorio_id: int) -> int:
    """Resolve a jurisdicao da entidade. Nao exige base do IBGE: se o nome nao
    estiver na referencia (orgao estadual, consorcio, autarquia...), cria uma
    jurisdicao PERSONALIZADA do proprio escritorio (municipios.escritorio_id),
    que so este tenant enxerga. Ver db/11_municipios_personalizados.sql."""
    nome_limpo = (nome or "").strip()
    if not nome_limpo:
        raise HTTPException(status_code=422, detail="Informe o município ou órgão da entidade.")
    uf_norm = (uf or "MA").strip().upper()
    if len(uf_norm) != 2 or not uf_norm.isalpha():
        raise HTTPException(status_code=422, detail=f"UF inválida: '{uf}'.")

    params = {
        "n": normalizar(nome_limpo),
        "uf": uf_norm,
        "esc": escritorio_id,
        "nome": nome_limpo,
    }
    # A RLS ja limita o SELECT a referencia global + jurisdicoes deste tenant.
    # NULLS FIRST: se o nome existe nos dois lados, o IBGE ganha.
    mid = db.execute(
        text(
            "SELECT id FROM municipios WHERE nome_normalizado = :n AND uf = CAST(:uf AS uf) "
            "ORDER BY escritorio_id NULLS FIRST LIMIT 1"
        ),
        params,
    ).scalar()
    if mid:
        return mid

    novo = db.execute(
        text(
            "INSERT INTO municipios (escritorio_id, nome, nome_normalizado, uf) "
            "VALUES (:esc, :nome, :n, CAST(:uf AS uf)) "
            "ON CONFLICT (escritorio_id, nome_normalizado, uf) WHERE escritorio_id IS NOT NULL "
            "DO NOTHING RETURNING id"
        ),
        params,
    ).scalar()
    if novo:
        return novo
    # Corrida: outra requisicao do mesmo escritorio criou entre o SELECT e o INSERT.
    return db.execute(
        text(
            "SELECT id FROM municipios WHERE escritorio_id = :esc "
            "AND nome_normalizado = :n AND uf = CAST(:uf AS uf)"
        ),
        params,
    ).scalar_one()


@app.post("/prefeituras", status_code=201)
def create_prefeitura(
    body: PrefeituraCreate,
    admin: UsuarioAutenticado = Depends(require_admin),
    db: Session = Depends(db_tenant),
):
    municipio_id = _resolver_municipio(db, body.municipio, body.uf, admin.escritorio_id)
    novo_id = db.execute(
        text(
            "INSERT INTO entidades (escritorio_id, municipio_id, tipo, nome, nome_normalizado, cnpj) "
            "VALUES (:esc, :mid, CAST(:tipo AS tipo_entidade), :nome, :nn, CAST(:cnpj AS cnpj)) "
            "RETURNING id"
        ),
        {
            "esc": admin.escritorio_id,
            "mid": municipio_id,
            "tipo": body.tipo,
            "nome": body.nome.strip(),
            "nn": normalizar(body.nome),
            "cnpj": (body.cnpj or "").strip() or None,
        },
    ).scalar_one()
    r = db.execute(text(_SQL_ENTIDADES + " AND e.id = :id"), {"id": novo_id}).mappings().first()
    return _entidade_dict(r)


@app.get("/prefeituras")
def list_prefeituras(
    ativo: Optional[bool] = None,
    _user: UsuarioAutenticado = Depends(get_current_user),
    db: Session = Depends(db_tenant),
):
    """Sem filtro de escritorio nem de municipio aqui: a RLS ja limita ao tenant
    e, para funcionario, aos municipios atribuidos a ele."""
    sql = _SQL_ENTIDADES
    params = {}
    if ativo is not None:
        sql += " AND e.ativo = :ativo"
        params["ativo"] = ativo
    sql += " ORDER BY e.nome"
    return [_entidade_dict(r) for r in db.execute(text(sql), params).mappings().all()]


@app.get("/prefeituras/{prefeitura_id}")
def get_prefeitura(
    prefeitura_id: int,
    _user: UsuarioAutenticado = Depends(get_current_user),
    db: Session = Depends(db_tenant),
):
    r = db.execute(text(_SQL_ENTIDADES + " AND e.id = :id"), {"id": prefeitura_id}).mappings().first()
    if not r:
        raise HTTPException(status_code=404, detail="Prefeitura não encontrada")
    return _entidade_dict(r)


@app.put("/prefeituras/{prefeitura_id}")
def update_prefeitura(
    prefeitura_id: int,
    body: PrefeituraCreate,
    admin: UsuarioAutenticado = Depends(require_admin),
    db: Session = Depends(db_tenant),
):
    municipio_id = _resolver_municipio(db, body.municipio, body.uf, admin.escritorio_id)
    afetadas = db.execute(
        text(
            "UPDATE entidades SET nome = :nome, nome_normalizado = :nn, municipio_id = :mid, "
            "  tipo = CAST(:tipo AS tipo_entidade) "
            "WHERE id = :id AND deleted_at IS NULL"
        ),
        {
            "id": prefeitura_id,
            "nome": body.nome.strip(),
            "nn": normalizar(body.nome),
            "mid": municipio_id,
            "tipo": body.tipo,
        },
    ).rowcount
    if not afetadas:
        raise HTTPException(status_code=404, detail="Prefeitura não encontrada")
    r = db.execute(text(_SQL_ENTIDADES + " AND e.id = :id"), {"id": prefeitura_id}).mappings().first()
    return _entidade_dict(r)


@app.delete("/prefeituras/{prefeitura_id}", status_code=204)
def delete_prefeitura(
    prefeitura_id: int,
    _admin: UsuarioAutenticado = Depends(require_admin),
    db: Session = Depends(db_tenant),
):
    """Soft delete. O historico de analises da entidade permanece auditavel —
    apagar de verdade destruiria a trilha exigida em contexto de prestacao de
    contas.

    O `set_config` antes do UPDATE nao e detalhe: a politica de RLS `p_iso` tem
    `deleted_at IS NULL OR app.incluir_excluidos()` no USING, e o Postgres avalia
    esse predicado tambem contra a linha RESULTANTE. Ao gravar `deleted_at`, a
    linha deixa de satisfazer a politica que a protegia e o UPDATE e recusado com
    "new row violates row-level security policy" — mesmo sendo admin do
    escritorio. Ligar `app.incluir_excluidos` declara que esta transacao opera
    sobre a linha independentemente do estado de exclusao, que e exatamente a
    semantica de excluir (e de restaurar). O escopo e a transacao (3o argumento
    = true), entao nao vaza para o resto da sessao.
    """
    db.execute(text("SELECT set_config('app.incluir_excluidos', 'on', true)"))
    afetadas = db.execute(
        text("UPDATE entidades SET deleted_at = now() WHERE id = :id AND deleted_at IS NULL"),
        {"id": prefeitura_id},
    ).rowcount
    if not afetadas:
        raise HTTPException(status_code=404, detail="Prefeitura não encontrada")
    return None


@app.patch("/prefeituras/{prefeitura_id}/toggle")
def toggle_prefeitura(
    prefeitura_id: int,
    _admin: UsuarioAutenticado = Depends(require_admin),
    db: Session = Depends(db_tenant),
):
    novo = db.execute(
        text(
            "UPDATE entidades SET ativo = NOT ativo WHERE id = :id AND deleted_at IS NULL "
            "RETURNING ativo"
        ),
        {"id": prefeitura_id},
    ).scalar()
    if novo is None:
        raise HTTPException(status_code=404, detail="Prefeitura não encontrada")
    return {"id": prefeitura_id, "ativo": novo}


# ─────────────────────────────────────────────────────────
# Conciliação
# ─────────────────────────────────────────────────────────

def _entidade_ou_404(db: Session, entidade_id: int):
    """Se a entidade nao for do tenant (ou estiver fora do escopo do funcionario)
    a RLS ja a torna invisivel e caimos no 404 — sem checagem manual de acesso."""
    r = db.execute(
        text(
            "SELECT e.id, e.nome, e.municipio_id FROM entidades e "
            "WHERE e.id = :id AND e.deleted_at IS NULL AND e.ativo"
        ),
        {"id": entidade_id},
    ).mappings().first()
    if not r:
        raise HTTPException(status_code=404, detail="Prefeitura não encontrada")
    return r


def _registrar_analise(
    db: Session,
    *,
    escritorio_id: int,
    entidade,
    tipo_analise: str,
    total: int,
    por_severidade: dict,
    por_anexo: dict,
    status_conc: str,
    arquivos: dict,
    usuario_id: int,
) -> int:
    """Grava a execucao em `validacoes` — a tabela unica de analise, compartilhada
    com o backend-auditor (que usa tipo_analise='auditoria_rit')."""
    import json

    resumo = {
        "status_conciliacao": status_conc,
        "por_anexo": por_anexo or {},
        "arquivos": arquivos,
        "arquivado": False,
        "criado_por": usuario_id,
    }
    return db.execute(
        text(
            "INSERT INTO validacoes (escritorio_id, entidade_id, municipio_id, exercicio, "
            "  tipo_analise, status_analise, concluida_em, total_inconsistencias, "
            "  por_severidade, resumo) "
            "VALUES (:esc, :ent, :mun, :ex, CAST(:tipo AS tipo_analise), 'concluida', now(), "
            "        :total, CAST(:sev AS jsonb), CAST(:resumo AS jsonb)) RETURNING id"
        ),
        {
            "esc": escritorio_id,
            "ent": entidade["id"],
            "mun": entidade["municipio_id"],
            "ex": datetime.now(timezone.utc).year,
            "tipo": tipo_analise,
            "total": total,
            "sev": json.dumps(por_severidade or {}),
            "resumo": json.dumps(resumo),
        },
    ).scalar_one()


@app.post("/conciliar")
async def conciliar_endpoint(
    rascunho: UploadFile = File(...),
    homologado: UploadFile = File(...),
    prefeitura_id: int = Form(...),
    current_user: UsuarioAutenticado = Depends(get_current_user),
    db: Session = Depends(db_tenant),
):
    entidade = _entidade_ou_404(db, prefeitura_id)

    job_id = str(uuid.uuid4())
    tmp_dir = tempfile.mkdtemp()

    try:
        r_path = os.path.join(tmp_dir, f"rascunho_{rascunho.filename}")
        h_path = os.path.join(tmp_dir, f"homologado_{homologado.filename}")

        with open(r_path, "wb") as f:
            f.write(await rascunho.read())
        with open(h_path, "wb") as f:
            f.write(await homologado.read())

        out_path = os.path.join(tmp_dir, f"conciliado_{job_id}.xlsx")
        result = _conciliar(r_path, h_path, out_path)

        por_severidade = result.get("por_severidade", {})
        total_div = result.get("total_divergencias", 0)
        criticas = por_severidade.get("CRÍTICA", 0)

        if total_div == 0:
            status_conc = "sem_divergencias"
        elif criticas > 0:
            status_conc = "com_divergencias"
        else:
            status_conc = "concluida"

        conc_id = _registrar_analise(
            db,
            escritorio_id=current_user.escritorio_id,
            entidade=entidade,
            tipo_analise="conciliacao_rgf",
            total=total_div,
            por_severidade=por_severidade,
            por_anexo=result.get("por_anexo"),
            status_conc=status_conc,
            arquivos={"rascunho": rascunho.filename, "homologado": homologado.filename},
            usuario_id=current_user.id,
        )

        JOBS[job_id] = {"status": "ok", "path": out_path, "tmp_dir": tmp_dir, "stats": result}
        return {"job_id": job_id, "stats": result, "conciliacao_id": conc_id}

    except HTTPException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/conciliar-rreo")
async def conciliar_rreo_endpoint(
    rascunho_msc: UploadFile = File(...),
    siconfi_homologado: UploadFile = File(...),
    prefeitura_id: int = Form(...),
    current_user: UsuarioAutenticado = Depends(get_current_user),
    db: Session = Depends(db_tenant),
):
    entidade = _entidade_ou_404(db, prefeitura_id)

    for upload in (rascunho_msc, siconfi_homologado):
        ext = os.path.splitext(upload.filename or "")[1].lower()
        if ext not in (".xls", ".xlsx"):
            raise HTTPException(
                status_code=400,
                detail=f"Formato não suportado: '{upload.filename}'. "
                       "Confirme se é um .xls ou .xlsx exportado do SICONFI/MSC.",
            )

    job_id = str(uuid.uuid4())
    tmp_dir = tempfile.mkdtemp()

    try:
        r_path = os.path.join(tmp_dir, f"rascunho_{rascunho_msc.filename}")
        h_path = os.path.join(tmp_dir, f"siconfi_{siconfi_homologado.filename}")

        with open(r_path, "wb") as f:
            f.write(await rascunho_msc.read())
        with open(h_path, "wb") as f:
            f.write(await siconfi_homologado.read())

        out_path = os.path.join(tmp_dir, f"rreo_conciliado_{job_id}.xlsx")
        audit_path = os.path.join(tmp_dir, f"rreo_auditoria_{job_id}.xlsx")

        resultado = _conciliar_rreo(r_path, h_path, out_path, audit_path, workdir=tmp_dir)
        result_dict = resultado.to_dict()

        por_classificacao = result_dict.get("por_classificacao", {})
        total_div = result_dict.get("total_divergencias", 0)
        criticas = por_classificacao.get("CRÍTICA", 0)

        if total_div == 0:
            status_conc = "sem_divergencias"
        elif criticas > 0:
            status_conc = "com_divergencias"
        else:
            status_conc = "concluida"

        conc_id = _registrar_analise(
            db,
            escritorio_id=current_user.escritorio_id,
            entidade=entidade,
            tipo_analise="conciliacao_rreo",
            total=total_div,
            por_severidade=por_classificacao,
            por_anexo=result_dict.get("por_sheet"),
            status_conc=status_conc,
            arquivos={
                "rascunho": rascunho_msc.filename,
                "homologado": siconfi_homologado.filename,
                "auditoria": audit_path,
            },
            usuario_id=current_user.id,
        )

        JOBS[job_id] = {
            "status": "ok",
            "path": out_path,
            "audit_path": audit_path,
            "tmp_dir": tmp_dir,
            "stats": result_dict,
        }
        return {"job_id": job_id, "stats": result_dict, "conciliacao_id": conc_id}

    except HTTPException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/download/{job_id}")
def download(job_id: str, _user: UsuarioAutenticado = Depends(get_current_user)):
    job = JOBS.get(job_id)
    if not job or not os.path.exists(job["path"]):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado ou expirado")
    return FileResponse(
        job["path"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=os.path.basename(job["path"]),
    )


@app.get("/download-auditoria/{job_id}")
def download_auditoria(job_id: str, _user: UsuarioAutenticado = Depends(get_current_user)):
    job = JOBS.get(job_id)
    if not job or not job.get("audit_path") or not os.path.exists(job["audit_path"]):
        raise HTTPException(status_code=404, detail="Arquivo de auditoria não encontrado")
    return FileResponse(
        job["audit_path"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=os.path.basename(job["audit_path"]),
    )


# ─────────────────────────────────────────────────────────
# Histórico de análises
# ─────────────────────────────────────────────────────────

_SQL_ANALISES = (
    "SELECT v.id, v.entidade_id, v.tipo_analise, v.total_inconsistencias, "
    "       v.por_severidade, v.resumo, v.iniciada_em, e.nome AS entidade_nome, "
    "       u.nome AS criado_por_nome "
    "FROM validacoes v "
    "JOIN entidades e ON e.escritorio_id = v.escritorio_id AND e.id = v.entidade_id "
    "LEFT JOIN usuarios u ON u.escritorio_id = v.escritorio_id "
    "     AND u.id = (v.resumo->>'criado_por')::bigint "
    "WHERE v.tipo_analise IN ('conciliacao_rgf','conciliacao_rreo')"
)


def _analise_dict(r) -> dict:
    resumo = r["resumo"] or {}
    return {
        "id": r["id"],
        "prefeitura_id": r["entidade_id"],
        "prefeitura_nome": r["entidade_nome"],
        "tipo": "RREO" if r["tipo_analise"] == "conciliacao_rreo" else "RGF_SIMPLIFICADO",
        "total_divergencias": r["total_inconsistencias"],
        "por_severidade": r["por_severidade"] or {},
        "por_anexo": resumo.get("por_anexo", {}),
        "arquivo_rascunho": resumo.get("arquivos", {}).get("rascunho"),
        "arquivo_homologado": resumo.get("arquivos", {}).get("homologado"),
        "status": resumo.get("status_conciliacao", "concluida"),
        "arquivado": bool(resumo.get("arquivado", False)),
        "criado_em": r["iniciada_em"].isoformat(),
        "criado_por_nome": r["criado_por_nome"],
    }


@app.get("/conciliacoes")
def list_conciliacoes(
    prefeitura_id: Optional[int] = None,
    limit: int = 50,
    _user: UsuarioAutenticado = Depends(get_current_user),
    db: Session = Depends(db_tenant),
):
    sql = _SQL_ANALISES
    params = {"limit": limit}
    if prefeitura_id:
        sql += " AND v.entidade_id = :ent"
        params["ent"] = prefeitura_id
    sql += " ORDER BY v.iniciada_em DESC LIMIT :limit"
    return [_analise_dict(r) for r in db.execute(text(sql), params).mappings().all()]


@app.get("/conciliacoes/{conciliacao_id}")
def get_conciliacao(
    conciliacao_id: int,
    _user: UsuarioAutenticado = Depends(get_current_user),
    db: Session = Depends(db_tenant),
):
    r = db.execute(
        text(_SQL_ANALISES + " AND v.id = :id"), {"id": conciliacao_id}
    ).mappings().first()
    if not r:
        raise HTTPException(status_code=404, detail="Conciliação não encontrada")
    return _analise_dict(r)


@app.get("/prefeituras/{prefeitura_id}/conciliacoes")
def prefeitura_conciliacoes(
    prefeitura_id: int,
    _user: UsuarioAutenticado = Depends(get_current_user),
    db: Session = Depends(db_tenant),
):
    p = db.execute(
        text(_SQL_ENTIDADES + " AND e.id = :id"), {"id": prefeitura_id}
    ).mappings().first()
    if not p:
        raise HTTPException(status_code=404, detail="Prefeitura não encontrada")
    linhas = db.execute(
        text(_SQL_ANALISES + " AND v.entidade_id = :ent ORDER BY v.iniciada_em DESC"),
        {"ent": prefeitura_id},
    ).mappings().all()
    return {
        "prefeitura": {
            "id": p["id"],
            "nome": p["nome"],
            "municipio": p["municipio"],
            "uf": p["uf"],
        },
        "conciliacoes": [_analise_dict(r) for r in linhas],
    }


@app.patch("/conciliacoes/{conciliacao_id}/arquivar")
def arquivar_conciliacao(
    conciliacao_id: int,
    _user: UsuarioAutenticado = Depends(get_current_user),
    db: Session = Depends(db_tenant),
):
    """`arquivado` vive dentro de resumo (JSONB) — o schema modela `validacoes`
    como execucao de analise, e arquivar e um estado de UI, nao do dominio."""
    novo = db.execute(
        text(
            "UPDATE validacoes SET resumo = jsonb_set("
            "    coalesce(resumo, '{}'::jsonb), '{arquivado}', "
            "    to_jsonb(NOT coalesce((resumo->>'arquivado')::boolean, false))) "
            "WHERE id = :id RETURNING (resumo->>'arquivado')::boolean"
        ),
        {"id": conciliacao_id},
    ).scalar()
    if novo is None:
        raise HTTPException(status_code=404, detail="Conciliação não encontrada")
    return {"id": conciliacao_id, "arquivado": novo}


# ─────────────────────────────────────────────────────────
# Dashboard do escritório
# ─────────────────────────────────────────────────────────

@app.get("/dashboard")
def dashboard(
    _user: UsuarioAutenticado = Depends(get_current_user),
    db: Session = Depends(db_tenant),
):
    """Resumo do escritório logado. Reescrito sobre `validacoes` (o prototipo
    agregava a tabela `conciliacoes`); os números são do tenant por RLS."""
    entidades = db.execute(
        text(
            "SELECT e.id, e.nome, m.nome AS municipio, m.uf FROM entidades e "
            "JOIN municipios m ON m.id = e.municipio_id "
            "WHERE e.deleted_at IS NULL AND e.ativo ORDER BY e.nome"
        )
    ).mappings().all()

    agregado = db.execute(
        text(
            "SELECT count(*) AS total, "
            "       coalesce(sum(total_inconsistencias), 0) AS divergencias, "
            "       count(*) FILTER (WHERE iniciada_em >= date_trunc('month', now())) AS no_mes "
            "FROM validacoes WHERE tipo_analise IN ('conciliacao_rgf','conciliacao_rreo')"
        )
    ).mappings().first()

    ultimas = db.execute(
        text(_SQL_ANALISES + " ORDER BY v.iniciada_em DESC LIMIT 10")
    ).mappings().all()

    return {
        "total_prefeituras": len(entidades),
        "total_conciliacoes": agregado["total"],
        "total_divergencias": agregado["divergencias"],
        "conciliacoes_no_mes": agregado["no_mes"],
        "prefeituras": [
            {"id": e["id"], "nome": e["nome"], "municipio": e["municipio"], "uf": e["uf"]}
            for e in entidades
        ],
        "ultimas_conciliacoes": [_analise_dict(r) for r in ultimas],
    }


# ─────────────────────────────────────────────────────────
# Municípios (referência global — usado no cadastro de entidade)
# ─────────────────────────────────────────────────────────

@app.get("/municipios")
def listar_municipios(
    busca: Optional[str] = None,
    uf: str = "MA",
    _user: UsuarioAutenticado = Depends(get_current_user),
    db: Session = Depends(db_tenant),
):
    # A RLS entrega referencia do IBGE + jurisdicoes personalizadas deste tenant.
    sql = ("SELECT id, codigo_ibge, nome, uf, escritorio_id IS NOT NULL AS personalizado "
           "FROM municipios WHERE uf = CAST(:uf AS uf)")
    params = {"uf": uf.upper()}
    if busca:
        sql += " AND nome_normalizado LIKE :b"
        params["b"] = f"%{normalizar(busca)}%"
    sql += " ORDER BY nome LIMIT 300"
    return [dict(r) for r in db.execute(text(sql), params).mappings().all()]


@app.get("/health")
def health():
    return {"status": "ok", "versao": app.version, "banco": checar_saude()}
