"""initial schema

Revision ID: 001
Revises:
Create Date: 2025-06-10

"""
from alembic import op
import sqlalchemy as sa

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'usuarios',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('nome', sa.String(255), nullable=False),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('senha_hash', sa.String(255), nullable=False),
        sa.Column('role', sa.String(50), server_default='auditor'),
        sa.Column('ativo', sa.Boolean(), server_default='1'),
        sa.Column('criado_em', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_usuarios_email', 'usuarios', ['email'])
    op.create_index('ix_usuarios_id', 'usuarios', ['id'])

    op.create_table(
        'prefeituras',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('nome', sa.String(255), nullable=False),
        sa.Column('municipio', sa.String(255), nullable=False),
        sa.Column('uf', sa.String(2), nullable=False),
        sa.Column('codigo_ibge', sa.String(20), nullable=True),
        sa.Column('instituicao_siconfi', sa.String(255), nullable=True),
        sa.Column('pessoal_lrf', sa.Float(), nullable=True),
        sa.Column('ativo', sa.Boolean(), server_default='1'),
        sa.Column('criado_em', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_prefeituras_id', 'prefeituras', ['id'])

    op.create_table(
        'conciliacoes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('prefeitura_id', sa.Integer(), sa.ForeignKey('prefeituras.id'), nullable=False),
        sa.Column('tipo', sa.String(50), server_default='RGF_SIMPLIFICADO'),
        sa.Column('arquivo_rascunho', sa.String(255), nullable=True),
        sa.Column('arquivo_homologado', sa.String(255), nullable=True),
        sa.Column('total_divergencias', sa.Integer(), server_default='0'),
        sa.Column('por_severidade', sa.JSON(), nullable=True),
        sa.Column('por_anexo', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(50), server_default='concluida'),
        sa.Column('criado_em', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('criado_por', sa.Integer(), sa.ForeignKey('usuarios.id'), nullable=True),
    )
    op.create_index('ix_conciliacoes_id', 'conciliacoes', ['id'])


def downgrade() -> None:
    op.drop_index('ix_conciliacoes_id', 'conciliacoes')
    op.drop_table('conciliacoes')
    op.drop_index('ix_prefeituras_id', 'prefeituras')
    op.drop_table('prefeituras')
    op.drop_index('ix_usuarios_email', 'usuarios')
    op.drop_index('ix_usuarios_id', 'usuarios')
    op.drop_table('usuarios')
