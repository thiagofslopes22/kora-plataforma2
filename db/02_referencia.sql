-- =============================================================================
-- KORA-PLATAFORMA — 02: TABELAS DE REFERÊNCIA (GLOBAIS, SEM TENANT)
-- Estas tabelas são exceção DELIBERADA à regra "escritorio_id primeiro":
-- são dados públicos compartilhados por todos os tenants (IBGE, calendário do
-- TCE-MA, catálogo de regras). NÃO têm RLS de tenant; são somente-leitura para
-- a aplicação e escritas apenas por kora_migrator/kora_platform.
-- =============================================================================
SET ROLE kora_migrator;

-- -----------------------------------------------------------------------------
-- municipios: referência IBGE (MA tem ~217 municípios). PK BIGINT.
-- -----------------------------------------------------------------------------
CREATE TABLE municipios (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  codigo_ibge   ibge7 NOT NULL,
  nome          text  NOT NULL,
  nome_normalizado text NOT NULL,          -- unaccent+lower, preenchido pela app/trigger, p/ busca trgm
  uf            uf    NOT NULL DEFAULT 'MA',
  populacao     integer,
  criado_em     timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE municipios IS 'Referência de municípios (IBGE). Global, sem tenant, somente-leitura para a app.';
CREATE UNIQUE INDEX ux_municipios_ibge ON municipios (codigo_ibge);        -- lookup/idempotência por código IBGE
-- Busca textual por nome (sem tenant aqui, pois é referência global):
CREATE INDEX gin_municipios_nome ON municipios USING gin (nome_normalizado gin_trgm_ops); -- autocomplete de município

-- -----------------------------------------------------------------------------
-- exercicios: ano fiscal. SMALLINT como PK natural (2024, 2025, ...).
-- -----------------------------------------------------------------------------
CREATE TABLE exercicios (
  ano         smallint PRIMARY KEY CHECK (ano BETWEEN 2000 AND 2100),
  aberto      boolean NOT NULL DEFAULT true       -- exercício ainda aceita prestações
);
COMMENT ON TABLE exercicios IS 'Anos fiscais. Referência global.';

-- -----------------------------------------------------------------------------
-- competencias: períodos do calendário do TCE-MA (define prazos de entrega).
-- Global: o calendário é o mesmo para todos os tenants.
-- -----------------------------------------------------------------------------
CREATE TABLE competencias (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  exercicio      smallint NOT NULL REFERENCES exercicios(ano),
  tipo_periodo   tipo_periodo NOT NULL,
  numero         smallint NOT NULL,                -- ex.: bimestre 1..6, quadrimestre 1..3
  data_inicio    date NOT NULL,
  data_fim       date NOT NULL,
  prazo_entrega  date NOT NULL,                    -- prazo TCE-MA para a remessa
  CHECK (data_fim >= data_inicio)
);
COMMENT ON TABLE competencias IS 'Períodos de referência do TCE-MA e seus prazos. Global.';
CREATE UNIQUE INDEX ux_competencias_periodo ON competencias (exercicio, tipo_periodo, numero); -- unicidade do período
CREATE INDEX ix_competencias_prazo ON competencias (prazo_entrega);   -- alertas de prazo próximo (dashboards globais)
CREATE INDEX ix_exercicios_fk_competencias ON competencias (exercicio); -- índice do lado filho da FK

-- -----------------------------------------------------------------------------
-- regras_validacao: catálogo de checagens automáticas (por anexo do TCE-MA).
-- Global e VERSIONADO (uma prestação registra a versão da regra aplicada).
-- -----------------------------------------------------------------------------
CREATE TABLE regras_validacao (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  codigo            text NOT NULL,                 -- ex.: 'RGF-ANX02-001'
  versao            integer NOT NULL DEFAULT 1,
  tipo_prestacao    tipo_prestacao NOT NULL,
  anexo             text,                           -- ex.: 'ANX02', 'ANX05' (nomenclatura dos extractors existentes)
  descricao         text NOT NULL,
  severidade_padrao severidade NOT NULL DEFAULT 'media',
  expressao         jsonb,                          -- definição declarativa da regra (schema variável) => JSONB
  ativa             boolean NOT NULL DEFAULT true,
  criado_em         timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE regras_validacao IS 'Catálogo versionado de regras de conciliação/validação por anexo. Global.';
CREATE UNIQUE INDEX ux_regras_codigo_versao ON regras_validacao (codigo, versao);  -- identidade da regra versionada
CREATE INDEX ix_regras_ativas ON regras_validacao (tipo_prestacao, anexo) WHERE ativa; -- carregar regras ativas por tipo/anexo

-- Referência é legível por todos os papéis (inclusive readonly); escrita só migrator/plataforma.
GRANT SELECT ON municipios, exercicios, competencias, regras_validacao TO kora_app, kora_platform, kora_readonly;
GRANT INSERT, UPDATE, DELETE ON municipios, exercicios, competencias, regras_validacao TO kora_platform;

RESET ROLE;
