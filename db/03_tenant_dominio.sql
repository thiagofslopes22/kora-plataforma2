-- =============================================================================
-- KORA-PLATAFORMA — 03: NÚCLEO DE TENANT + DOMÍNIO FISCAL
-- Regra geral: escritorio_id (o tenant_id) é a PRIMEIRA coluna de toda PK
-- composta e de todo índice tenant-scoped. FK sempre indexada do lado filho.
-- Soft delete padronizado (deleted_at). RLS aplicada no arquivo 07.
-- =============================================================================
SET ROLE kora_migrator;

-- =============================================================================
-- ESCRITÓRIOS (TENANTS) — a raiz. PK = id (é o próprio escritorio_id).
-- Somente SUPER_ADMIN cria/libera/suspende (garantido por RLS + GRANT no 07).
-- =============================================================================
CREATE TABLE escritorios (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ulid_publico   uuid NOT NULL DEFAULT app.gerar_uuidv7(),  -- identificador exposto na API (anti-enumeração)
  razao_social   text NOT NULL,
  nome_fantasia  text,
  nome_normalizado text NOT NULL,                            -- busca trgm no backoffice
  cnpj           cnpj NOT NULL,
  status         status_escritorio NOT NULL DEFAULT 'pendente',
  plano          plano_escritorio  NOT NULL DEFAULT 'trial',
  limites        jsonb NOT NULL DEFAULT '{"max_usuarios":5,"max_municipios":3}'::jsonb, -- schema variável => JSONB
  liberado_em    timestamptz,
  liberado_por   bigint,                                     -- FK -> plataforma_admins (abaixo)
  suspenso_em    timestamptz,
  suspenso_por   bigint,
  motivo_suspensao text,
  criado_em      timestamptz NOT NULL DEFAULT now(),
  atualizado_em  timestamptz NOT NULL DEFAULT now(),
  deleted_at     timestamptz,
  CHECK (status <> 'ativo'   OR liberado_em IS NOT NULL),    -- ativo exige liberação registrada
  CHECK (status <> 'suspenso' OR suspenso_em IS NOT NULL)
);
COMMENT ON TABLE escritorios IS 'Tenants. id = escritorio_id. Ciclo de vida controlado só pela plataforma (SUPER_ADMIN).';
COMMENT ON COLUMN escritorios.ulid_publico IS 'ID público (UUIDv7). Nunca exponha o BIGINT id na API.';

CREATE UNIQUE INDEX ux_escritorios_cnpj  ON escritorios (cnpj) WHERE deleted_at IS NULL;   -- unicidade de CNPJ entre tenants ativos
CREATE UNIQUE INDEX ux_escritorios_ulid  ON escritorios (ulid_publico);                    -- resolução do ID público
CREATE INDEX ix_escritorios_status       ON escritorios (status) INCLUDE (razao_social, plano, criado_em)
       WHERE deleted_at IS NULL;                                                           -- backoffice: listar por status (Index Only Scan)
CREATE INDEX gin_escritorios_nome        ON escritorios USING gin (nome_normalizado gin_trgm_ops); -- busca de escritório no backoffice

-- =============================================================================
-- PLATAFORMA_ADMINS (SUPER_ADMIN) — fora do modelo de tenant.
-- Não tem escritorio_id. Autentica em fluxo próprio. Senha Argon2id (app calcula).
-- =============================================================================
CREATE TABLE plataforma_admins (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ulid_publico   uuid NOT NULL DEFAULT app.gerar_uuidv7(),
  nome           text NOT NULL,
  email          email_ci NOT NULL,
  senha_hash     text NOT NULL,                              -- Argon2id (formato PHC $argon2id$...)
  mfa_secret_cif bytea,                                      -- TOTP secret cifrado (envelope/KMS) — NUNCA em claro
  ativo          boolean NOT NULL DEFAULT true,
  ultimo_login_em timestamptz,
  criado_em      timestamptz NOT NULL DEFAULT now(),
  atualizado_em  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE plataforma_admins IS 'SUPER_ADMIN da plataforma. Sem tenant. Acesso via papel kora_platform.';
CREATE UNIQUE INDEX ux_plataforma_admins_email ON plataforma_admins (email);   -- login global do backoffice
CREATE UNIQUE INDEX ux_plataforma_admins_ulid  ON plataforma_admins (ulid_publico);

-- Agora fecha as FKs de escritorios -> plataforma_admins
ALTER TABLE escritorios
  ADD CONSTRAINT fk_escritorios_liberado_por FOREIGN KEY (liberado_por) REFERENCES plataforma_admins(id),
  ADD CONSTRAINT fk_escritorios_suspenso_por FOREIGN KEY (suspenso_por) REFERENCES plataforma_admins(id);
CREATE INDEX ix_escritorios_liberado_por ON escritorios (liberado_por); -- índice do lado filho da FK
CREATE INDEX ix_escritorios_suspenso_por ON escritorios (suspenso_por); -- índice do lado filho da FK

-- =============================================================================
-- USUÁRIOS — pertencem a UM escritório. PK composta (escritorio_id, id).
-- email é GLOBAL-único: o login ocorre ANTES de haver contexto de tenant,
-- então precisamos resolver o tenant pelo email (ver função autenticar no 04).
-- =============================================================================
CREATE TABLE usuarios (
  escritorio_id    bigint  NOT NULL REFERENCES escritorios(id),
  id               bigint  GENERATED ALWAYS AS IDENTITY,
  ulid_publico     uuid    NOT NULL DEFAULT app.gerar_uuidv7(),
  nome             text    NOT NULL,
  email            email_ci NOT NULL,
  senha_hash       text    NOT NULL,                         -- Argon2id
  papel            papel_usuario NOT NULL DEFAULT 'funcionario',
  status           status_usuario NOT NULL DEFAULT 'convidado',
  mfa_secret_cif   bytea,
  tentativas_falhas smallint NOT NULL DEFAULT 0,
  bloqueado_ate    timestamptz,                              -- lockout por brute force
  ultimo_login_em  timestamptz,
  criado_por       bigint,
  criado_em        timestamptz NOT NULL DEFAULT now(),
  atualizado_em    timestamptz NOT NULL DEFAULT now(),
  deleted_at       timestamptz,
  PRIMARY KEY (escritorio_id, id)                            -- tenant_id PRIMEIRO (localidade/poda)
);
COMMENT ON TABLE usuarios IS 'Usuários de um escritório (admin_escritorio/funcionario). email global-único para login pré-tenant.';
-- (O id é globalmente único por vir de uma única sequência IDENTITY; as FKs
--  compostas apontam para a PK (escritorio_id, id), então NÃO há índice extra em id.)
CREATE UNIQUE INDEX ux_usuarios_email     ON usuarios (email) WHERE deleted_at IS NULL; -- LOGIN: resolução tenant por email
CREATE UNIQUE INDEX ux_usuarios_ulid      ON usuarios (ulid_publico);                -- resolução do ID público
CREATE INDEX ix_usuarios_tenant_ativos    ON usuarios (escritorio_id, papel)
       INCLUDE (nome, email, status) WHERE deleted_at IS NULL;                       -- listar usuários do tenant (Index Only Scan)
CREATE INDEX ix_usuarios_criado_por       ON usuarios (escritorio_id, criado_por);   -- índice do lado filho da FK (self)
ALTER TABLE usuarios
  ADD CONSTRAINT fk_usuarios_criado_por FOREIGN KEY (escritorio_id, criado_por)
      REFERENCES usuarios(escritorio_id, id);

-- =============================================================================
-- ENTIDADES — prefeitura/câmara/SAAE/... Pertencem a um município e a um tenant.
-- (substitui/evolui a antiga tabela `prefeituras` do protótipo)
-- =============================================================================
CREATE TABLE entidades (
  escritorio_id    bigint NOT NULL REFERENCES escritorios(id),
  id               bigint GENERATED ALWAYS AS IDENTITY,
  ulid_publico     uuid   NOT NULL DEFAULT app.gerar_uuidv7(),
  municipio_id     bigint NOT NULL REFERENCES municipios(id),
  tipo             tipo_entidade NOT NULL,
  nome             text NOT NULL,
  nome_normalizado text NOT NULL,
  cnpj             cnpj,
  codigo_siconfi   text,
  instituicao_siconfi text,                                  -- vindo do protótipo (backend-conciliador)
  ativo            boolean NOT NULL DEFAULT true,
  criado_em        timestamptz NOT NULL DEFAULT now(),
  atualizado_em    timestamptz NOT NULL DEFAULT now(),
  deleted_at       timestamptz,
  PRIMARY KEY (escritorio_id, id)
);
COMMENT ON TABLE entidades IS 'Entidades que prestam contas (prefeitura/câmara/SAAE...). Pertencem a município (ref) e a tenant.';
CREATE UNIQUE INDEX ux_entidades_ulid      ON entidades (ulid_publico);
CREATE UNIQUE INDEX ux_entidades_tenant_cnpj ON entidades (escritorio_id, cnpj)
       WHERE deleted_at IS NULL AND cnpj IS NOT NULL;                                -- 1 CNPJ por entidade no tenant
CREATE INDEX ix_entidades_tenant_municipio ON entidades (escritorio_id, municipio_id)
       INCLUDE (tipo, nome) WHERE deleted_at IS NULL;                                -- listar entidades por município (funcionário)
CREATE INDEX ix_entidades_fk_municipio     ON entidades (municipio_id);              -- índice do lado filho da FK global
CREATE INDEX gin_entidades_nome            ON entidades USING gin (escritorio_id, nome_normalizado gin_trgm_ops); -- busca textual COM poda por tenant (btree_gin)

-- =============================================================================
-- USUARIOS_MUNICIPIOS — atribuição explícita de FUNCIONÁRIO a município.
-- Base do 3º nível de acesso (app.pode_ver_municipio).
-- =============================================================================
CREATE TABLE usuarios_municipios (
  escritorio_id  bigint NOT NULL,
  usuario_id     bigint NOT NULL,
  municipio_id   bigint NOT NULL REFERENCES municipios(id),
  atribuido_por  bigint,
  criado_em      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (escritorio_id, usuario_id, municipio_id),
  FOREIGN KEY (escritorio_id, usuario_id) REFERENCES usuarios(escritorio_id, id) ON DELETE CASCADE
);
COMMENT ON TABLE usuarios_municipios IS 'Quais municípios cada funcionário pode acessar. FK composta força consistência de tenant.';
CREATE INDEX ix_um_por_municipio ON usuarios_municipios (escritorio_id, municipio_id); -- "quem atende este município?"
CREATE INDEX ix_um_fk_municipio  ON usuarios_municipios (municipio_id);                -- índice do lado filho da FK global

-- =============================================================================
-- PRESTAÇÕES DE CONTAS — o envio ao TCE-MA. Fato central do domínio.
-- Denormalizamos entidade_id + municipio_id para permitir RLS de funcionário
-- LOCAL (sem join) e poda de índice. Versionamento por retificação.
-- =============================================================================
CREATE TABLE prestacoes_contas (
  escritorio_id  bigint NOT NULL REFERENCES escritorios(id),
  id             bigint GENERATED ALWAYS AS IDENTITY,
  ulid_publico   uuid   NOT NULL DEFAULT app.gerar_uuidv7(),
  entidade_id    bigint NOT NULL,
  municipio_id   bigint NOT NULL,                            -- denormalizado da entidade (RLS/poda)
  competencia_id bigint NOT NULL REFERENCES competencias(id),
  exercicio      smallint NOT NULL,                          -- denormalizado (usado em partição de tabelas filhas)
  tipo           tipo_prestacao NOT NULL,
  status         status_prestacao NOT NULL DEFAULT 'rascunho',
  versao         integer NOT NULL DEFAULT 1,
  substitui_id   bigint,                                     -- retificação: aponta p/ a prestação anterior
  prazo          date,
  transmitida_em timestamptz,
  protocolo_tce  text,
  criado_por     bigint,
  criado_em      timestamptz NOT NULL DEFAULT now(),
  atualizado_em  timestamptz NOT NULL DEFAULT now(),
  deleted_at     timestamptz,
  PRIMARY KEY (escritorio_id, id),
  FOREIGN KEY (escritorio_id, entidade_id) REFERENCES entidades(escritorio_id, id)
);
COMMENT ON TABLE prestacoes_contas IS 'Prestação/remessa ao TCE-MA. municipio_id denormalizado para RLS de funcionário sem join.';
CREATE UNIQUE INDEX ux_prestacoes_ulid      ON prestacoes_contas (ulid_publico);
-- 1 prestação ATIVA por (entidade, competência, tipo). Retificadas saem do índice.
CREATE UNIQUE INDEX ux_prestacoes_unica_ativa ON prestacoes_contas (escritorio_id, entidade_id, competencia_id, tipo)
       WHERE deleted_at IS NULL AND status <> 'retificada';
-- Dashboard: prestações pendentes/abertas por tenant (igualdade status -> sort prazo), covering:
CREATE INDEX ix_prestacoes_pendentes ON prestacoes_contas (escritorio_id, status, prazo)
       INCLUDE (entidade_id, municipio_id, tipo, competencia_id)
       WHERE deleted_at IS NULL AND status IN ('rascunho','em_validacao','com_inconsistencias','pronta');
CREATE INDEX ix_prestacoes_por_entidade ON prestacoes_contas (escritorio_id, entidade_id, exercicio)
       WHERE deleted_at IS NULL;                              -- histórico por entidade/exercício
CREATE INDEX ix_prestacoes_fk_entidade ON prestacoes_contas (escritorio_id, entidade_id); -- lado filho FK composta
CREATE INDEX ix_prestacoes_fk_competencia ON prestacoes_contas (competencia_id);          -- lado filho FK global

-- =============================================================================
-- DOCUMENTOS / ARQUIVOS — metadados; binário fica em storage externo (S3).
-- Dedup por hash SHA-256 por tenant. Busca por nome via trgm.
-- =============================================================================
CREATE TABLE documentos (
  escritorio_id  bigint NOT NULL REFERENCES escritorios(id),
  id             bigint GENERATED ALWAYS AS IDENTITY,
  ulid_publico   uuid   NOT NULL DEFAULT app.gerar_uuidv7(),
  prestacao_id   bigint,
  entidade_id    bigint NOT NULL,
  municipio_id   bigint NOT NULL,
  anexo          text,                                       -- 'ANX02'... (alinha com extractors existentes)
  tipo_documento text,
  nome_original  text NOT NULL,
  nome_normalizado text NOT NULL,
  storage_bucket text NOT NULL,
  storage_key    text NOT NULL,
  hash_sha256    bytea NOT NULL,                             -- 32 bytes; dedup/integridade
  tamanho_bytes  bigint NOT NULL,
  mime           text,
  criado_por     bigint,
  criado_em      timestamptz NOT NULL DEFAULT now(),
  deleted_at     timestamptz,
  PRIMARY KEY (escritorio_id, id),
  FOREIGN KEY (escritorio_id, entidade_id) REFERENCES entidades(escritorio_id, id),
  FOREIGN KEY (escritorio_id, prestacao_id) REFERENCES prestacoes_contas(escritorio_id, id)
);
COMMENT ON TABLE documentos IS 'Metadados de arquivos (binário em S3). hash_sha256 para dedup/integridade.';
CREATE UNIQUE INDEX ux_documentos_ulid ON documentos (ulid_publico);
CREATE UNIQUE INDEX ux_documentos_hash ON documentos (escritorio_id, hash_sha256)
       WHERE deleted_at IS NULL;                              -- dedup: mesmo arquivo não entra 2x no tenant
CREATE INDEX ix_documentos_por_prestacao ON documentos (escritorio_id, prestacao_id)
       WHERE deleted_at IS NULL;                              -- anexos de uma prestação
CREATE INDEX ix_documentos_fk_entidade ON documentos (escritorio_id, entidade_id);
CREATE INDEX gin_documentos_nome ON documentos USING gin (escritorio_id, nome_normalizado gin_trgm_ops); -- busca de documento por nome (poda por tenant)

-- =============================================================================
-- VALIDAÇÕES — uma execução do motor de checagem sobre uma prestação.
-- (as inconsistências individuais ficam em tabela particionada — arquivo 05)
-- =============================================================================
CREATE TABLE validacoes (
  escritorio_id     bigint NOT NULL REFERENCES escritorios(id),
  id                bigint GENERATED ALWAYS AS IDENTITY,
  prestacao_id      bigint NOT NULL,
  municipio_id      bigint NOT NULL,
  exercicio         smallint NOT NULL,
  iniciada_em       timestamptz NOT NULL DEFAULT now(),
  concluida_em      timestamptz,
  total_inconsistencias integer NOT NULL DEFAULT 0,
  por_severidade    jsonb,                                   -- {"critica":3,"alta":5,...} (resumo pré-computado)
  regras_versao     jsonb,                                   -- versões das regras aplicadas (auditabilidade)
  PRIMARY KEY (escritorio_id, id),
  FOREIGN KEY (escritorio_id, prestacao_id) REFERENCES prestacoes_contas(escritorio_id, id)
);
COMMENT ON TABLE validacoes IS 'Execução do motor de conciliação/validação sobre uma prestação.';
CREATE INDEX ix_validacoes_por_prestacao ON validacoes (escritorio_id, prestacao_id, iniciada_em DESC); -- última validação de uma prestação

RESET ROLE;
