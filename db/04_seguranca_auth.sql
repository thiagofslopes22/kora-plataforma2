-- =============================================================================
-- KORA-PLATAFORMA — 04: AUTENTICAÇÃO, SESSÕES, CONVITES, CREDENCIAIS TCE
-- =============================================================================
SET ROLE kora_migrator;

-- =============================================================================
-- SESSÕES / REFRESH TOKENS — armazenados como HASH (nunca em claro).
-- Decisão: tokens de sessão/refresh/convite são ALEATÓRIOS de alta entropia
-- (>=256 bits). Para esses, SHA-256 é suficiente e correto — Argon2id é para
-- SENHAS (baixa entropia) e só adicionaria latência aqui. Comparação em tempo
-- constante fica na app; no banco guardamos apenas o digest.
-- NÃO particionamos sessoes: o lookup é por hash do token (índice único
-- GLOBAL); particionar quebraria essa unicidade. Em vez disso: autovacuum
-- agressivo + expurgo periódico (ver 08).
-- =============================================================================
CREATE TABLE sessoes (
  escritorio_id     bigint NOT NULL REFERENCES escritorios(id),
  id                bigint GENERATED ALWAYS AS IDENTITY,
  usuario_id        bigint NOT NULL,
  refresh_hash      bytea  NOT NULL,                    -- SHA-256 do refresh token
  ip               inet,
  user_agent        text,
  criado_em         timestamptz NOT NULL DEFAULT now(),
  ultima_atividade  timestamptz NOT NULL DEFAULT now(),
  expira_em         timestamptz NOT NULL,
  revogada_em       timestamptz,
  PRIMARY KEY (escritorio_id, id),
  FOREIGN KEY (escritorio_id, usuario_id) REFERENCES usuarios(escritorio_id, id) ON DELETE CASCADE
);
COMMENT ON TABLE sessoes IS 'Sessões/refresh tokens (SHA-256). Revogáveis e expiráveis. Não particionada (unicidade global do hash).';
CREATE UNIQUE INDEX ux_sessoes_refresh ON sessoes (refresh_hash);                        -- lookup do refresh token
CREATE INDEX ix_sessoes_usuario_ativas ON sessoes (escritorio_id, usuario_id)
       WHERE revogada_em IS NULL;                                                        -- sessões ativas de um usuário
CREATE INDEX ix_sessoes_expira ON sessoes (expira_em) WHERE revogada_em IS NULL;         -- expurgo de sessões vencidas

-- =============================================================================
-- CONVITES — token de uso único, expirável e HASHEADO.
-- =============================================================================
CREATE TABLE convites (
  escritorio_id  bigint NOT NULL REFERENCES escritorios(id),
  id             bigint GENERATED ALWAYS AS IDENTITY,
  ulid_publico   uuid NOT NULL DEFAULT app.gerar_uuidv7(),
  email          email_ci NOT NULL,
  papel          papel_usuario NOT NULL DEFAULT 'funcionario',
  token_hash     bytea NOT NULL,                        -- SHA-256 do token enviado por e-mail
  municipios_ids bigint[] NOT NULL DEFAULT '{}',        -- municípios que o convidado poderá acessar
  convidado_por  bigint NOT NULL,
  expira_em      timestamptz NOT NULL,
  aceito_em      timestamptz,
  revogado_em    timestamptz,
  criado_em      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (escritorio_id, id),
  FOREIGN KEY (escritorio_id, convidado_por) REFERENCES usuarios(escritorio_id, id)
);
COMMENT ON TABLE convites IS 'Convites de usuário: token único hasheado, expirável, uso único (aceito_em).';
CREATE UNIQUE INDEX ux_convites_token ON convites (token_hash);                          -- validação do convite
CREATE UNIQUE INDEX ux_convites_pendente ON convites (escritorio_id, email)
       WHERE aceito_em IS NULL AND revogado_em IS NULL;                                  -- 1 convite pendente por e-mail/tenant
CREATE INDEX ix_convites_fk_convidado_por ON convites (escritorio_id, convidado_por);   -- lado filho da FK

-- =============================================================================
-- TENTATIVAS_LOGIN — append-only, para rate limiting / lockout.
-- PRE-TENANT: o login acontece antes de conhecer o tenant, então NÃO é
-- tenant-scoped e NÃO tem RLS de tenant. Particionada por mês (append gigante).
-- (Definição da partição-mestre e rotinas ficam no 05; aqui só a intenção.)
-- Observação de arquitetura: rate limiting de caminho quente é MELHOR no Redis;
-- esta tabela serve para lockout persistente/auditoria de segurança.
-- =============================================================================
CREATE TABLE tentativas_login (
  id           bigint GENERATED ALWAYS AS IDENTITY,
  email        text NOT NULL,                            -- pode não existir (não vaza se conta existe)
  escritorio_id bigint,                                  -- preenchido só se o email resolveu um tenant
  ip           inet NOT NULL,
  sucesso      boolean NOT NULL,
  motivo       text,
  criado_em    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (criado_em, id)                            -- inclui a coluna de partição (RANGE por criado_em)
) PARTITION BY RANGE (criado_em);
COMMENT ON TABLE tentativas_login IS 'Auditoria de tentativas de login para lockout. Append-only, particionada por mês, sem RLS de tenant.';
CREATE INDEX ix_tentativas_email_tempo ON tentativas_login (email, criado_em DESC);      -- contar falhas recentes por e-mail
CREATE INDEX ix_tentativas_ip_tempo    ON tentativas_login (ip, criado_em DESC);         -- contar falhas recentes por IP

-- =============================================================================
-- CREDENCIAIS_TCE — segredos de acesso aos sistemas do TCE-MA por entidade.
-- Criptografia: ENVELOPE ENCRYPTION (recomendado sobre pgcrypto). A app gera
-- um DEK, cifra o segredo (AES-256-GCM), e "embrulha" o DEK numa KMS (AWS KMS /
-- GCP KMS / Vault Transit). O banco guarda apenas ciphertext + DEK embrulhado +
-- id da chave KMS. A chave-mestra NUNCA entra no Postgres — nem em params, nem
-- em logs. TDE/disco só protege mídia roubada, não um papel de banco comprometido.
-- =============================================================================
CREATE TABLE credenciais_tce (
  escritorio_id  bigint NOT NULL REFERENCES escritorios(id),
  id             bigint GENERATED ALWAYS AS IDENTITY,
  entidade_id    bigint NOT NULL,
  municipio_id   bigint NOT NULL,
  sistema        text NOT NULL,                          -- ex.: 'SACOP', 'SIFGE', portal do TCE-MA
  usuario_tce    text NOT NULL,
  segredo_cif    bytea NOT NULL,                         -- AES-256-GCM(senha)
  dek_cif        bytea NOT NULL,                         -- DEK embrulhado pela KMS
  kms_key_id     text NOT NULL,
  atualizado_por bigint,
  criado_em      timestamptz NOT NULL DEFAULT now(),
  atualizado_em  timestamptz NOT NULL DEFAULT now(),
  deleted_at     timestamptz,
  PRIMARY KEY (escritorio_id, id),
  FOREIGN KEY (escritorio_id, entidade_id) REFERENCES entidades(escritorio_id, id)
);
COMMENT ON TABLE credenciais_tce IS 'Credenciais TCE-MA cifradas via envelope encryption (KMS). Banco nunca vê a chave-mestra.';
CREATE UNIQUE INDEX ux_credenciais_entidade_sistema ON credenciais_tce (escritorio_id, entidade_id, sistema)
       WHERE deleted_at IS NULL;                          -- 1 credencial por (entidade, sistema)
CREATE INDEX ix_credenciais_fk_entidade ON credenciais_tce (escritorio_id, entidade_id);

-- GRANT restritivo: credenciais TCE não são legíveis pelo readonly/BI.
REVOKE ALL ON credenciais_tce FROM kora_readonly;

-- =============================================================================
-- FUNÇÃO DE LOGIN (exceção controlada à RLS) — PORTÁVEL (sem BYPASSRLS)
-- O login é PRÉ-TENANT: achamos o usuário por e-mail antes de setar o contexto.
-- Padrão portável (funciona em Postgres gerenciado sem superusuário, ex.: Supabase):
-- a função é SECURITY DEFINER DONA de kora_migrator (dono das tabelas). Como
-- usuarios/escritorios NÃO têm FORCE RLS (ver 07), o dono é isento de RLS ali
-- (owner-exemption) — sem precisar de um papel BYPASSRLS. O app (kora_app) NUNCA
-- é dono, então continua 100% sujeito à RLS nessas tabelas.
-- =============================================================================
CREATE OR REPLACE FUNCTION app.autenticar(p_email email_ci)
RETURNS TABLE (
  escritorio_id    bigint,
  usuario_id       bigint,
  senha_hash       text,
  papel            papel_usuario,
  usuario_status   status_usuario,
  bloqueado_ate    timestamptz,
  escritorio_status status_escritorio
)
LANGUAGE sql SECURITY DEFINER STABLE
SET search_path = public, app AS $$
  SELECT u.escritorio_id, u.id, u.senha_hash, u.papel, u.status, u.bloqueado_ate, e.status
  FROM usuarios u
  JOIN escritorios e ON e.id = u.escritorio_id
  WHERE u.email = p_email
    AND u.deleted_at IS NULL
$$;
COMMENT ON FUNCTION app.autenticar(email_ci) IS 'Lookup de login pré-tenant. SECURITY DEFINER dona de kora_migrator + owner-exemption (usuarios/escritorios sem FORCE). App faz verify Argon2id + checa lockout/status.';

-- Só a app executa o login; readonly/plataforma não precisam.
REVOKE ALL ON FUNCTION app.autenticar(email_ci) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.autenticar(email_ci) TO kora_app;

RESET ROLE;
