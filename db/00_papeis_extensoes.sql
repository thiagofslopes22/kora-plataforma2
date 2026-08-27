-- =============================================================================
-- KORA-PLATAFORMA — 00: EXTENSÕES E PAPÉIS (ROLES)
-- PostgreSQL 16+
-- Execute como superusuário UMA vez, na criação do cluster/database.
-- Ordem de execução: 00 -> 01 -> 02 -> 03 -> 04 -> 05 -> 06 -> 07 -> 08 -> 09
-- =============================================================================

-- -----------------------------------------------------------------------------
-- EXTENSÕES
-- -----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pg_trgm;        -- busca textual (nomes de municípios/entidades/docs)
CREATE EXTENSION IF NOT EXISTS btree_gin;      -- GIN composto (escritorio_id + trigram) => poda por tenant no índice GIN
CREATE EXTENSION IF NOT EXISTS pgcrypto;       -- digest()/gen_random_bytes() para hashes e tokens
-- Observabilidade: opcional. Em Postgres gerenciado que nao pre-carrega a lib
-- (shared_preload_libraries), o CREATE falha — nao pode derrubar a migracao.
DO $$ BEGIN
  CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
EXCEPTION WHEN OTHERS THEN
  RAISE NOTICE 'pg_stat_statements indisponivel (%): seguindo sem observabilidade de queries', SQLERRM;
END $$;
-- Opcionais de produção (recomendados; exigem shared_preload_libraries):
--   CREATE EXTENSION IF NOT EXISTS pg_cron;    -- agendamento de REFRESH MV / manutenção de partições
--   CREATE EXTENSION IF NOT EXISTS pg_partman; -- manutenção automática de partições (preferível ao script manual)
--   CREATE EXTENSION IF NOT EXISTS pgaudit;    -- auditoria de sessão/DDL (complementa a tabela de auditoria de dados)
-- PG18+: uuidv7() é nativo; em PG16/17 usamos a função app.gerar_uuidv7() (arquivo 01).

-- -----------------------------------------------------------------------------
-- SCHEMA de funções de plataforma (namespace para helpers de RLS)
-- -----------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS app;
COMMENT ON SCHEMA app IS 'Funções auxiliares de contexto/RLS. Nunca contém tabelas de dados.';

-- =============================================================================
-- PAPÉIS (privilégio mínimo). NENHUM deles tem BYPASSRLS, exceto observação.
-- =============================================================================

-- Papel de GRUPO dono do schema/objetos. Sem LOGIN. Executa DDL/migrações.
-- NÃO recebe BYPASSRLS: com FORCE RLS, nem o dono lê dados fora de política.
-- Backfills massivos em migração usam janela de manutenção sob superusuário
-- OU a função de manutenção que seta o GUC de plataforma (ver 07_rls.sql).
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kora_migrator') THEN
    CREATE ROLE kora_migrator NOLOGIN;
  END IF;
END $$;
COMMENT ON ROLE kora_migrator IS 'Dono dos objetos; executa DDL e migrações. Sem BYPASSRLS.';

-- Papel da APLICAÇÃO (backends auditor/conciliador). LOGIN via PgBouncer.
-- É o único papel usado no caminho de request do tenant. Sem BYPASSRLS.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kora_app') THEN
    CREATE ROLE kora_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT CONNECTION LIMIT 250;
  END IF;
END $$;
-- Senha injetada pelo runner (db/migrate.py) a partir da variavel de ambiente
-- KORA_APP_PASSWORD. Reaplicada a cada migracao => rotacao de senha e so trocar a env.
ALTER ROLE kora_app LOGIN PASSWORD '${KORA_APP_PASSWORD}';
COMMENT ON ROLE kora_app IS 'Aplicação multi-tenant. RLS obrigatória. Define app.current_tenant/current_user por transação.';

-- Papel da PLATAFORMA (SUPER_ADMIN): operações cross-tenant controladas
-- (criar/liberar/suspender escritórios, analytics globais). LOGIN em POOL
-- SEPARADO do kora_app. Continua SEM BYPASSRLS — o acesso cross-tenant é
-- concedido explicitamente pelas POLÍTICAS RLS via app.eh_plataforma().
-- Isolar isso em um papel distinto (e não em um GUC do kora_app) impede que
-- um bug na aplicação de tenant escale para acesso global.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kora_platform') THEN
    CREATE ROLE kora_platform LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT CONNECTION LIMIT 20;
  END IF;
END $$;
-- Senha injetada pelo runner (db/migrate.py) a partir da variavel de ambiente
-- KORA_PLATFORM_PASSWORD. Reaplicada a cada migracao => rotacao de senha e so trocar a env.
ALTER ROLE kora_platform LOGIN PASSWORD '${KORA_PLATFORM_PASSWORD}';
COMMENT ON ROLE kora_platform IS 'Backoffice da plataforma (SUPER_ADMIN). Acesso cross-tenant concedido por política RLS, não por BYPASSRLS.';

-- Papel SOMENTE-LEITURA (BI, replicas de leitura, suporte). Sem BYPASSRLS.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kora_readonly') THEN
    CREATE ROLE kora_readonly LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT CONNECTION LIMIT 20;
  END IF;
END $$;
-- Senha injetada pelo runner (db/migrate.py) a partir da variavel de ambiente
-- KORA_READONLY_PASSWORD. Reaplicada a cada migracao => rotacao de senha e so trocar a env.
ALTER ROLE kora_readonly LOGIN PASSWORD '${KORA_READONLY_PASSWORD}';
COMMENT ON ROLE kora_readonly IS 'Somente leitura. Continua sujeito a RLS (enxerga apenas o tenant do contexto).';

-- -----------------------------------------------------------------------------
-- PORTABILIDADE (Postgres gerenciado sem superusuário, ex.: Supabase):
-- o papel de aplicação da migração (quem roda estes scripts — 'postgres' no
-- Supabase) precisa ser MEMBRO de kora_migrator e kora_platform para poder
-- `SET ROLE kora_migrator` (usado no DDL) e `ALTER ... OWNER TO kora_platform`
-- (MV do 08). Em cluster local com superusuário isto é inócuo.
-- -----------------------------------------------------------------------------
DO $$ BEGIN
  EXECUTE format('GRANT kora_migrator, kora_platform TO %I', current_user);
END $$;

-- -----------------------------------------------------------------------------
-- PRIVILÉGIOS DE BANCO/SCHEMA
-- Substitua kora_db pelo nome real do database.
-- -----------------------------------------------------------------------------
-- REVOKE geral: por padrão o schema public é aberto; fechamos.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

GRANT USAGE ON SCHEMA public, app TO kora_app, kora_platform, kora_readonly;
GRANT CREATE, USAGE ON SCHEMA public, app TO kora_migrator;

-- -----------------------------------------------------------------------------
-- ACESSO AO SCHEMA `extensions` (Postgres gerenciado)
-- O Supabase JA vem com pgcrypto/pg_stat_statements instalados no schema
-- `extensions` — nosso CREATE EXTENSION vira no-op e as funcoes ficam la.
-- Ter `extensions` no search_path NAO basta: sem USAGE no schema o papel nao
-- enxerga nada dentro dele, e `gen_random_bytes()` (usado no DEFAULT de
-- ulid_publico, via app.gerar_uuidv7) falha com "function does not exist".
-- Condicional: em cluster proprio esse schema nao existe.
-- -----------------------------------------------------------------------------
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'extensions') THEN
    GRANT USAGE ON SCHEMA extensions TO kora_migrator, kora_app, kora_platform, kora_readonly;
    RAISE NOTICE 'USAGE concedido no schema extensions aos papeis kora_*';
  END IF;
END $$;

-- -----------------------------------------------------------------------------
-- SEARCH_PATH POR PAPEL
-- Postgres gerenciado (Supabase) instala as extensoes no schema `extensions`,
-- nao no `public`. Sem ele no search_path, `gin_trgm_ops` (indices) e
-- `gen_random_bytes`/`digest` (pgcrypto) nao resolvem. Incluir o schema quando
-- ele nao existe e inofensivo — entradas inexistentes sao ignoradas.
-- -----------------------------------------------------------------------------
ALTER ROLE kora_app      SET search_path = public, app, extensions;
ALTER ROLE kora_platform SET search_path = public, app, extensions;
ALTER ROLE kora_readonly SET search_path = public, app, extensions;
ALTER ROLE kora_migrator SET search_path = public, app, extensions;

-- -----------------------------------------------------------------------------
-- SUPABASE: nao expor as tabelas pela API REST (PostgREST).
-- O Supabase publica o schema `public` via HTTP para os papeis `anon` e
-- `authenticated` (chave publica do projeto). Nossas tabelas vivem em `public`,
-- entao revogamos explicitamente — RLS ja barraria, mas nao queremos depender
-- de uma unica camada para algo exposto na internet. Bloco condicional: em
-- cluster comum esses papeis nao existem.
-- -----------------------------------------------------------------------------
DO $$
DECLARE v_papel text;
BEGIN
  FOREACH v_papel IN ARRAY ARRAY['anon','authenticated'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_papel) THEN
      EXECUTE format('REVOKE ALL ON SCHEMA public FROM %I', v_papel);
      EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', v_papel);
      EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', v_papel);
      EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE kora_migrator IN SCHEMA public REVOKE ALL ON TABLES FROM %I', v_papel);
      RAISE NOTICE 'Supabase: privilegios de % revogados no schema public', v_papel;
    END IF;
  END LOOP;
END $$;

-- Objetos serão criados pelo kora_migrator (SET ROLE kora_migrator antes do DDL).
-- Privilégios PADRÃO para objetos futuros criados por kora_migrator:
ALTER DEFAULT PRIVILEGES FOR ROLE kora_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO kora_app;
ALTER DEFAULT PRIVILEGES FOR ROLE kora_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO kora_platform;
ALTER DEFAULT PRIVILEGES FOR ROLE kora_migrator IN SCHEMA public
  GRANT SELECT ON TABLES TO kora_readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE kora_migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO kora_app, kora_platform;
ALTER DEFAULT PRIVILEGES FOR ROLE kora_migrator IN SCHEMA public
  GRANT EXECUTE ON FUNCTIONS TO kora_app, kora_platform, kora_readonly;

-- Observação: GRANTs finos por tabela (ex.: negar UPDATE/DELETE na auditoria)
-- são reaplicados nos arquivos das respectivas tabelas para deixar a intenção
-- explícita e sobreviver a ALTER DEFAULT PRIVILEGES.
