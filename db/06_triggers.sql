-- =============================================================================
-- KORA-PLATAFORMA — 06: TRIGGERS
--   (a) atualizado_em automático
--   (b) imutabilidade de escritorio_id (tenant não pode migrar de dono)
--   (c) imutabilidade da auditoria (bloqueio de UPDATE/DELETE — defesa dupla)
--   (d) trilha de auditoria (antes/depois, quem, quando, IP, UA)
--   (e) contadores pré-computados (evita COUNT(*) em runtime)
-- =============================================================================
SET ROLE kora_migrator;

-- -----------------------------------------------------------------------------
-- (a) atualizado_em
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.trg_atualizado_em() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.atualizado_em := now();
  RETURN NEW;
END;
$$;

-- -----------------------------------------------------------------------------
-- (b) escritorio_id imutável — impede que um bug/ataque "mova" uma linha de tenant
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.trg_escritorio_imutavel() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.escritorio_id IS DISTINCT FROM OLD.escritorio_id THEN
    RAISE EXCEPTION 'escritorio_id é imutável (tentativa % -> %)', OLD.escritorio_id, NEW.escritorio_id
      USING ERRCODE = 'raise_exception';
  END IF;
  RETURN NEW;
END;
$$;

-- -----------------------------------------------------------------------------
-- (c) auditoria imutável — bloqueia UPDATE/DELETE mesmo p/ dono/SECURITY DEFINER
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.trg_bloquear_mutacao() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Tabela % é append-only (% negado)', TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'insufficient_privilege';
END;
$$;

-- -----------------------------------------------------------------------------
-- (d) trilha de auditoria. Lê o ator/contexto de GUCs (SET LOCAL feitos pela app).
--     Grava valores antes/depois como JSONB.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.trg_auditar() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_tenant  bigint;
  v_reg_id  bigint;
  v_row     jsonb;     -- linha "corrente" (NEW no insert/update, OLD no delete)
  v_antes   jsonb;
  v_depois  jsonb;
BEGIN
  IF TG_OP = 'DELETE' THEN
    v_row := to_jsonb(OLD); v_antes := v_row; v_depois := NULL;
  ELSIF TG_OP = 'UPDATE' THEN
    v_row := to_jsonb(NEW); v_antes := to_jsonb(OLD); v_depois := v_row;
  ELSE -- INSERT
    v_row := to_jsonb(NEW); v_antes := NULL; v_depois := v_row;
  END IF;

  -- Derivar de JSONB torna o trigger genérico robusto a tabelas sem 'id'
  -- (usuarios_municipios) e sem 'escritorio_id' (escritorios, cujo tenant é 'id').
  v_reg_id := (v_row->>'id')::bigint;                                   -- NULL se não houver coluna id
  v_tenant := coalesce(
                (v_row->>'escritorio_id')::bigint,
                CASE WHEN TG_TABLE_NAME = 'escritorios' THEN (v_row->>'id')::bigint END,
                app.tenant_atual(), 0);

  INSERT INTO auditoria (escritorio_id, ator_tipo, ator_id, ator_email, acao, tabela,
                         registro_id, ip, user_agent, request_id, dados_antes, dados_depois)
  VALUES (
    v_tenant,
    CASE WHEN app.eh_plataforma() THEN 'plataforma_admin'::tipo_ator ELSE 'usuario'::tipo_ator END,
    app.usuario_atual(),
    nullif(current_setting('app.ator_email', true), ''),
    format('%s.%s', TG_TABLE_NAME, lower(TG_OP)),
    TG_TABLE_NAME,
    v_reg_id,
    nullif(current_setting('app.request_ip', true), '')::inet,
    nullif(current_setting('app.user_agent', true), ''),
    nullif(current_setting('app.request_id', true), ''),
    v_antes, v_depois
  );
  RETURN NULL; -- AFTER trigger
END;
$$;
COMMENT ON FUNCTION app.trg_auditar() IS 'Escreve trilha imutável (antes/depois + ator/IP/UA de GUCs). Anexar via AFTER em tabelas sensíveis.';

-- -----------------------------------------------------------------------------
-- (e) contadores pré-computados por prestação (dashboard sem COUNT(*))
-- -----------------------------------------------------------------------------
CREATE TABLE prestacao_contadores (
  escritorio_id  bigint NOT NULL,
  prestacao_id   bigint NOT NULL,
  criticas       integer NOT NULL DEFAULT 0,
  altas          integer NOT NULL DEFAULT 0,
  medias         integer NOT NULL DEFAULT 0,
  baixas         integer NOT NULL DEFAULT 0,
  informativas   integer NOT NULL DEFAULT 0,
  abertas        integer NOT NULL DEFAULT 0,
  atualizado_em  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (escritorio_id, prestacao_id),
  FOREIGN KEY (escritorio_id, prestacao_id) REFERENCES prestacoes_contas(escritorio_id, id) ON DELETE CASCADE
);
COMMENT ON TABLE prestacao_contadores IS 'Contadores mantidos por trigger (por severidade + abertas). Substitui COUNT(*) no dashboard.';

CREATE OR REPLACE FUNCTION app.trg_contar_inconsistencias() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  d_crit int := 0; d_alta int := 0; d_media int := 0; d_baixa int := 0; d_info int := 0; d_abertas int := 0;
  v_tenant bigint; v_prest bigint;
BEGIN
  -- Deltas por severidade e por "aberta"
  IF TG_OP IN ('DELETE','UPDATE') THEN
    v_tenant := OLD.escritorio_id; v_prest := OLD.prestacao_id;
    d_crit := d_crit - (OLD.severidade='critica')::int;      d_alta := d_alta - (OLD.severidade='alta')::int;
    d_media := d_media - (OLD.severidade='media')::int;       d_baixa := d_baixa - (OLD.severidade='baixa')::int;
    d_info := d_info - (OLD.severidade='informativa')::int;   d_abertas := d_abertas - (OLD.status='aberta')::int;
  END IF;
  IF TG_OP IN ('INSERT','UPDATE') THEN
    v_tenant := NEW.escritorio_id; v_prest := NEW.prestacao_id;
    d_crit := d_crit + (NEW.severidade='critica')::int;      d_alta := d_alta + (NEW.severidade='alta')::int;
    d_media := d_media + (NEW.severidade='media')::int;       d_baixa := d_baixa + (NEW.severidade='baixa')::int;
    d_info := d_info + (NEW.severidade='informativa')::int;   d_abertas := d_abertas + (NEW.status='aberta')::int;
  END IF;

  INSERT INTO prestacao_contadores AS pc (escritorio_id, prestacao_id, criticas, altas, medias, baixas, informativas, abertas)
  VALUES (v_tenant, v_prest, d_crit, d_alta, d_media, d_baixa, d_info, d_abertas)
  ON CONFLICT (escritorio_id, prestacao_id) DO UPDATE SET
    criticas = pc.criticas + EXCLUDED.criticas,
    altas    = pc.altas    + EXCLUDED.altas,
    medias   = pc.medias   + EXCLUDED.medias,
    baixas   = pc.baixas   + EXCLUDED.baixas,
    informativas = pc.informativas + EXCLUDED.informativas,
    abertas  = pc.abertas  + EXCLUDED.abertas,
    atualizado_em = now();
  RETURN NULL;
END;
$$;
COMMENT ON FUNCTION app.trg_contar_inconsistencias() IS 'Mantém prestacao_contadores incrementalmente (por severidade + abertas).';

-- =============================================================================
-- ANEXAÇÃO DOS TRIGGERS
-- =============================================================================
-- atualizado_em (todas as tabelas que têm a coluna)
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['escritorios','plataforma_admins','usuarios','entidades',
                           'prestacoes_contas','credenciais_tce','inconsistencias'] LOOP
    EXECUTE format('CREATE TRIGGER z_atualizado_em BEFORE UPDATE ON %I
                    FOR EACH ROW EXECUTE FUNCTION app.trg_atualizado_em()', t);
  END LOOP;
END $$;

-- escritorio_id imutável (todas as tabelas tenant-scoped que sofrem UPDATE)
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['usuarios','entidades','prestacoes_contas','documentos',
                           'validacoes','credenciais_tce','sessoes','convites',
                           'inconsistencias','itens_prestacao','envios'] LOOP
    EXECUTE format('CREATE TRIGGER a_tenant_imutavel BEFORE UPDATE ON %I
                    FOR EACH ROW EXECUTE FUNCTION app.trg_escritorio_imutavel()', t);
  END LOOP;
END $$;

-- auditoria imutável (bloqueia UPDATE e DELETE)
CREATE TRIGGER a_bloquear_update BEFORE UPDATE ON auditoria
  FOR EACH ROW EXECUTE FUNCTION app.trg_bloquear_mutacao();
CREATE TRIGGER a_bloquear_delete BEFORE DELETE ON auditoria
  FOR EACH ROW EXECUTE FUNCTION app.trg_bloquear_mutacao();

-- trilha de auditoria nas tabelas sensíveis
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['escritorios','usuarios','entidades','prestacoes_contas',
                           'credenciais_tce','convites','usuarios_municipios'] LOOP
    EXECUTE format('CREATE TRIGGER zz_auditar AFTER INSERT OR UPDATE OR DELETE ON %I
                    FOR EACH ROW EXECUTE FUNCTION app.trg_auditar()', t);
  END LOOP;
END $$;

-- contadores
CREATE TRIGGER zz_contadores AFTER INSERT OR UPDATE OR DELETE ON inconsistencias
  FOR EACH ROW EXECUTE FUNCTION app.trg_contar_inconsistencias();

RESET ROLE;
