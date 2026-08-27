"""
ORM do conciliador sobre o schema multi-tenant.

Mapeamento em relacao ao prototipo (SQLite):
    prefeituras   -> entidades          (agora com escritorio_id + municipio_id do IBGE)
    conciliacoes  -> validacoes         (tipo_analise = conciliacao_rgf|conciliacao_rreo)
    usuarios      -> usuarios           (agora com escritorio_id + papel)

Duas coisas mudam de lugar e explicam o resto do arquivo:

1. PK COMPOSTA. Toda tabela de tenant tem PRIMARY KEY (escritorio_id, id), com
   escritorio_id primeiro. O `id` continua vindo de IDENTITY, entao no ORM ele e
   `autoincrement=True` e o escritorio_id e informado pela aplicacao.

2. FILTRO POR TENANT NAO APARECE NAS QUERIES. Nenhum `.filter(escritorio_id=...)`
   e necessario: as sessoes vem de `kora_db.sessao_tenant()`, que carrega o
   contexto lido pela RLS. O banco corta as linhas de outros escritorios antes
   de a query ver qualquer coisa. Adicionar o filtro na mao seria redundante —
   e, pior, daria a impressao de que o isolamento depende da aplicacao lembrar.
"""
from __future__ import annotations

import unicodedata
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def normalizar(s: str) -> str:
    """unaccent + lower, para alimentar as colunas *_normalizado (busca trigram)."""
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


# ---------------------------------------------------------------------------
# Referencia global (sem tenant, sem RLS, somente leitura para a app)
# ---------------------------------------------------------------------------
class Municipio(Base):
    __tablename__ = "municipios"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo_ibge: Mapped[str] = mapped_column(String(7))
    nome: Mapped[str] = mapped_column(Text)
    nome_normalizado: Mapped[str] = mapped_column(Text)
    uf: Mapped[str] = mapped_column(String(2))
    populacao: Mapped[int | None] = mapped_column(Integer)


class Competencia(Base):
    __tablename__ = "competencias"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    exercicio: Mapped[int] = mapped_column(SmallInteger)
    tipo_periodo: Mapped[str] = mapped_column(Text)
    numero: Mapped[int] = mapped_column(SmallInteger)
    data_inicio: Mapped[Date] = mapped_column(Date)
    data_fim: Mapped[Date] = mapped_column(Date)
    prazo_entrega: Mapped[Date] = mapped_column(Date)


# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------
class Escritorio(Base):
    """O tenant. Lido pelo app; criado/liberado so pelo backoffice da plataforma."""

    __tablename__ = "escritorios"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ulid_publico: Mapped[str] = mapped_column(UUID(as_uuid=True))
    razao_social: Mapped[str] = mapped_column(Text)
    nome_fantasia: Mapped[str | None] = mapped_column(Text)
    nome_normalizado: Mapped[str] = mapped_column(Text)
    cnpj: Mapped[str] = mapped_column(String(14))
    status: Mapped[str] = mapped_column(Text)
    plano: Mapped[str] = mapped_column(Text)
    limites: Mapped[dict] = mapped_column(JSONB)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Usuario(Base):
    __tablename__ = "usuarios"

    escritorio_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("escritorios.id"), primary_key=True, autoincrement=False
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ulid_publico: Mapped[str] = mapped_column(UUID(as_uuid=True))
    nome: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    senha_hash: Mapped[str] = mapped_column(Text)
    # 'admin_escritorio' | 'funcionario'
    papel: Mapped[str] = mapped_column(Text, default="funcionario")
    # 'convidado' | 'ativo' | 'suspenso'
    status: Mapped[str] = mapped_column(Text, default="ativo")
    tentativas_falhas: Mapped[int] = mapped_column(SmallInteger, default=0)
    bloqueado_ate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ultimo_login_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    criado_por: Mapped[int | None] = mapped_column(BigInteger)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def eh_admin(self) -> bool:
        return self.papel == "admin_escritorio"


class UsuarioMunicipio(Base):
    """Escopo do FUNCIONARIO: quais municipios ele enxerga. A RLS le esta tabela
    (via app.municipios_do_usuario) — nao e um filtro da aplicacao."""

    __tablename__ = "usuarios_municipios"

    escritorio_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    usuario_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    municipio_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("municipios.id"), primary_key=True, autoincrement=False
    )
    atribuido_por: Mapped[int | None] = mapped_column(BigInteger)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["escritorio_id", "usuario_id"], ["usuarios.escritorio_id", "usuarios.id"]
        ),
    )


class Entidade(Base):
    """O que o prototipo chamava de `prefeitura`. Agora e qualquer entidade que
    presta contas (prefeitura/camara/SAAE/fundo/...) ligada a um municipio IBGE."""

    __tablename__ = "entidades"

    escritorio_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("escritorios.id"), primary_key=True, autoincrement=False
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ulid_publico: Mapped[str] = mapped_column(UUID(as_uuid=True))
    municipio_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("municipios.id"))
    tipo: Mapped[str] = mapped_column(Text, default="prefeitura")
    nome: Mapped[str] = mapped_column(Text)
    nome_normalizado: Mapped[str] = mapped_column(Text)
    cnpj: Mapped[str | None] = mapped_column(String(14))
    codigo_siconfi: Mapped[str | None] = mapped_column(Text)
    instituicao_siconfi: Mapped[str | None] = mapped_column(Text)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Validacao(Base):
    """Uma execucao de analise. Unifica os dois backends via `tipo_analise`:
    conciliacao_rgf / conciliacao_rreo (conciliador) e auditoria_rit (auditor).

    `prestacao_id` e opcional de proposito: hoje a conciliacao roda sobre
    arquivos avulsos, sem prestacao formal ao TCE."""

    __tablename__ = "validacoes"

    escritorio_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("escritorios.id"), primary_key=True, autoincrement=False
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    prestacao_id: Mapped[int | None] = mapped_column(BigInteger)
    entidade_id: Mapped[int | None] = mapped_column(BigInteger)
    municipio_id: Mapped[int] = mapped_column(BigInteger)
    exercicio: Mapped[int] = mapped_column(SmallInteger)
    competencia_id: Mapped[int | None] = mapped_column(BigInteger)
    tipo_analise: Mapped[str] = mapped_column(Text, default="conciliacao_rgf")
    status_analise: Mapped[str] = mapped_column(Text, default="concluida")
    iniciada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    concluida_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_inconsistencias: Mapped[int] = mapped_column(Integer, default=0)
    por_severidade: Mapped[dict | None] = mapped_column(JSONB)
    regras_versao: Mapped[dict | None] = mapped_column(JSONB)
    dados_manuais: Mapped[dict | None] = mapped_column(JSONB)
    resumo: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        ForeignKeyConstraint(
            ["escritorio_id", "entidade_id"], ["entidades.escritorio_id", "entidades.id"]
        ),
    )

    # ---- compatibilidade com o vocabulario do prototipo -------------------
    # O front e as rotas falam "arquivado" e "por_anexo"; no schema novo isso
    # vive dentro de `resumo` (JSONB), que e onde cabe metadado de execucao.
    @property
    def arquivado(self) -> bool:
        return bool((self.resumo or {}).get("arquivado", False))

    @property
    def por_anexo(self) -> dict:
        return (self.resumo or {}).get("por_anexo", {})

    @property
    def arquivos(self) -> dict:
        return (self.resumo or {}).get("arquivos", {})
