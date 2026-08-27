-- =============================================================================
-- KORA-PLATAFORMA — 01: TIPOS (ENUMs/DOMÍNIOS) E FUNÇÕES AUXILIARES
-- =============================================================================
SET ROLE kora_migrator;

-- Alguns helpers de RLS referenciam tabelas criadas só em 03 (usuarios,
-- usuarios_municipios). Desligamos a validação do corpo na CRIAÇÃO (só nesta
-- sessão); em runtime as tabelas já existem. Padrão para funções "forward-ref".
SET check_function_bodies = off;

-- -----------------------------------------------------------------------------
-- ENUMs NATIVOS
-- Decisão: ENUM nativo (4 bytes, ordenável, legível) para conjuntos ESTÁVEIS e
-- pequenos (papéis, severidade, tipos fiscais). Para "status" que muda por regra
-- de negócio com frequência, prefira tabela de lookup. Aqui os status abaixo são
-- de ciclo de vida bem definido -> ENUM. Caveat operacional: ALTER TYPE ... ADD
-- VALUE não pode rodar dentro de um bloco de transação junto com uso do valor;
-- adicionar valor é barato, REMOVER/REORDENAR não é -> só use ENUM onde o domínio
-- é aditivo e raro de mudar.
-- -----------------------------------------------------------------------------
CREATE TYPE status_escritorio      AS ENUM ('pendente','ativo','suspenso','cancelado');
CREATE TYPE plano_escritorio       AS ENUM ('trial','essencial','profissional','enterprise');
CREATE TYPE papel_usuario          AS ENUM ('admin_escritorio','funcionario');
CREATE TYPE status_usuario         AS ENUM ('convidado','ativo','suspenso');
CREATE TYPE tipo_entidade          AS ENUM ('prefeitura','camara','saae','fundo','autarquia','consorcio','fundacao');
CREATE TYPE tipo_prestacao         AS ENUM ('rreo','rgf','balancete','pca','remessa_mensal','loa');
CREATE TYPE status_prestacao       AS ENUM ('rascunho','em_validacao','com_inconsistencias','pronta','transmitida','homologada','rejeitada','retificada');
CREATE TYPE status_envio           AS ENUM ('enfileirado','transmitindo','transmitido','aceito','rejeitado','erro');
CREATE TYPE severidade             AS ENUM ('critica','alta','media','baixa','informativa');
CREATE TYPE status_inconsistencia  AS ENUM ('aberta','justificada','corrigida','ignorada','falso_positivo');
CREATE TYPE tipo_ator              AS ENUM ('usuario','plataforma_admin','sistema');
CREATE TYPE tipo_periodo           AS ENUM ('mensal','bimestral','trimestral','quadrimestral','semestral','anual');

-- Domínios enxutos reutilizáveis
CREATE DOMAIN cnpj    AS char(14)  CHECK (VALUE ~ '^[0-9]{14}$');
CREATE DOMAIN uf      AS char(2)   CHECK (VALUE ~ '^[A-Z]{2}$');
CREATE DOMAIN ibge7   AS char(7)   CHECK (VALUE ~ '^[0-9]{7}$');
CREATE DOMAIN email_ci AS text     CHECK (VALUE = lower(VALUE) AND VALUE ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$');
COMMENT ON DOMAIN email_ci IS 'E-mail já normalizado (minúsculas). Normalização é responsabilidade da app antes do INSERT.';

-- =============================================================================
-- FUNÇÕES DE CONTEXTO (base da RLS)
-- Lêem GUCs setados por transação via SET LOCAL (compatível com PgBouncer
-- transaction mode). `missing_ok=true` => retorna NULL se o GUC não foi setado,
-- fazendo a RLS FALHAR FECHADO (nenhuma linha visível) em vez de vazar.
-- STABLE + PARALLEL SAFE: avaliadas uma vez por statement.
-- =============================================================================
CREATE OR REPLACE FUNCTION app.tenant_atual() RETURNS bigint
LANGUAGE sql STABLE PARALLEL SAFE AS $$
  SELECT NULLIF(current_setting('app.current_tenant', true), '')::bigint
$$;
COMMENT ON FUNCTION app.tenant_atual() IS 'escritorio_id do contexto (SET LOCAL app.current_tenant). NULL => sem acesso.';

CREATE OR REPLACE FUNCTION app.usuario_atual() RETURNS bigint
LANGUAGE sql STABLE PARALLEL SAFE AS $$
  SELECT NULLIF(current_setting('app.current_user_id', true), '')::bigint
$$;
COMMENT ON FUNCTION app.usuario_atual() IS 'usuario_id do contexto (SET LOCAL app.current_user_id).';

-- Plataforma (SUPER_ADMIN): determinado pelo PAPEL DE CONEXÃO, não por GUC.
-- Assim, um bug no backend de tenant (kora_app) NÃO consegue se declarar
-- plataforma; seria necessário conectar como kora_platform.
CREATE OR REPLACE FUNCTION app.eh_plataforma() RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE AS $$
  SELECT pg_has_role(current_user, 'kora_platform', 'MEMBER')
$$;
COMMENT ON FUNCTION app.eh_plataforma() IS 'TRUE apenas em conexões do papel kora_platform (backoffice SUPER_ADMIN).';

-- NOTA: os helpers que LEEM as tabelas de autoridade (eh_admin_escritorio,
-- municipios_do_usuario) são definidos em 07 como SECURITY DEFINER (donos
-- kora_auth), pois precisam IGNORAR a RLS dessas tabelas — senão um funcionário
-- não conseguiria ler a própria atribuição para calcular o próprio escopo.

-- Flag para incluir soft-deleted (restore/auditoria). Padrão: excluir.
CREATE OR REPLACE FUNCTION app.incluir_excluidos() RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE AS $$
  SELECT coalesce(current_setting('app.incluir_excluidos', true) = 'on', false)
$$;

-- =============================================================================
-- GERAÇÃO DE IDENTIFICADORES PÚBLICOS (UUIDv7 — ordenável no tempo)
-- Motivo: PK interna é BIGINT (localidade de índice B-tree). O identificador
-- EXPOSTO na API é um UUIDv7/ULID: k-sortable (não fragmenta índice como o v4)
-- e impede enumeração de IDs sequenciais. Em PG18+ troque por uuidv7() nativo.
-- =============================================================================
CREATE OR REPLACE FUNCTION app.gerar_uuidv7() RETURNS uuid
LANGUAGE plpgsql PARALLEL SAFE AS $$
DECLARE
  v_ts_ms  bigint := (extract(epoch FROM clock_timestamp()) * 1000)::bigint;
  v_bytes  bytea  := gen_random_bytes(16);
BEGIN
  -- 48 bits de timestamp em ms (big-endian) nos 6 primeiros bytes
  -- (set_byte exige o 3º argumento como integer -> cast explícito de bigint)
  v_bytes := set_byte(v_bytes, 0, ((v_ts_ms >> 40) & 255)::int);
  v_bytes := set_byte(v_bytes, 1, ((v_ts_ms >> 32) & 255)::int);
  v_bytes := set_byte(v_bytes, 2, ((v_ts_ms >> 24) & 255)::int);
  v_bytes := set_byte(v_bytes, 3, ((v_ts_ms >> 16) & 255)::int);
  v_bytes := set_byte(v_bytes, 4, ((v_ts_ms >>  8) & 255)::int);
  v_bytes := set_byte(v_bytes, 5, ( v_ts_ms        & 255)::int);
  -- versão 7 (nibble alto do byte 6) e variante RFC 4122 (bits altos do byte 8)
  v_bytes := set_byte(v_bytes, 6, (get_byte(v_bytes, 6) & 15) | 112);
  v_bytes := set_byte(v_bytes, 8, (get_byte(v_bytes, 8) & 63) | 128);
  RETURN encode(v_bytes, 'hex')::uuid;
END;
$$;
COMMENT ON FUNCTION app.gerar_uuidv7() IS 'UUIDv7 k-sortable para chaves públicas. PG18+: prefira uuidv7() nativo.';

RESET ROLE;
