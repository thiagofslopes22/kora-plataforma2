-- =============================================================================
-- KORA-PLATAFORMA — 07: ROW LEVEL SECURITY (camada primária de isolamento)
--
-- Modelo:
--   * Política PERMISSIVE "FOR ALL"  => isolamento por tenant (+ escopo de
--     município do funcionário). Governa VISIBILIDADE e o WITH CHECK de escrita.
--   * Políticas RESTRICTIVE por comando => "gating" de PAPEL (ex.: só admin
--     escreve usuários). RESTRICTIVE faz AND com a permissive.
--   * FORCE ROW LEVEL SECURITY na maioria: nem o dono escapa. EXCEÇÃO: usuarios,
--     usuarios_municipios e escritorios ficam só com ENABLE (sem FORCE), para
--     owner-exemption dos helpers SECURITY DEFINER (portável sem BYPASSRLS). O app
--     (kora_app) NUNCA é dono => segue 100% sujeito à RLS nessas 3 tabelas também.
--   * Fail-closed: sem GUC de tenant, app.tenant_atual() = NULL e nada casa.
--
-- Exceções DELIBERADAS (sem RLS de tenant): tabelas de REFERÊNCIA global
-- (municipios, exercicios, competencias, regras_validacao) e tentativas_login
-- (telemetria PRÉ-tenant de login). Justificadas no README.
-- =============================================================================
SET ROLE kora_migrator;

-- -----------------------------------------------------------------------------
-- Helpers que LEEM as tabelas de autoridade (usuarios, usuarios_municipios) para
-- calcular o contexto. São SECURITY DEFINER, DONOS de kora_migrator (dono das
-- tabelas). Como usuarios/usuarios_municipios NÃO têm FORCE RLS, o dono é isento
-- de RLS nelas (owner-exemption) — assim o funcionário lê a própria atribuição e
-- o escopo não colapsa. Portável (não exige BYPASSRLS, roda em Supabase/gerenciado).
-- SET search_path fixo evita ataque de search_path em SECURITY DEFINER.
-- -----------------------------------------------------------------------------

-- Autoridade DENTRO do tenant derivada do BANCO (não de GUC): consulta usuarios.
CREATE OR REPLACE FUNCTION app.eh_admin_escritorio() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, app AS $$
  SELECT EXISTS (
    SELECT 1 FROM usuarios u
    WHERE u.escritorio_id = app.tenant_atual()
      AND u.id = app.usuario_atual()
      AND u.papel = 'admin_escritorio'
      AND u.deleted_at IS NULL
  )
$$;
COMMENT ON FUNCTION app.eh_admin_escritorio() IS 'TRUE se o usuário do contexto é admin do escritório. SECURITY DEFINER dona de kora_migrator: lê usuarios via owner-exemption.';

-- Municípios atribuídos ao FUNCIONÁRIO (base do 3º nível de acesso).
CREATE OR REPLACE FUNCTION app.municipios_do_usuario() RETURNS bigint[]
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, app AS $$
  SELECT coalesce(array_agg(municipio_id), '{}')
  FROM usuarios_municipios
  WHERE escritorio_id = app.tenant_atual() AND usuario_id = app.usuario_atual()
$$;
COMMENT ON FUNCTION app.municipios_do_usuario() IS 'Municípios do funcionário. SECURITY DEFINER dona de kora_migrator: lê usuarios_municipios via owner-exemption.';

-- Acesso com escopo de município (prefeitura/entidade/prestação/…):
CREATE OR REPLACE FUNCTION app.pode_acessar(p_escritorio bigint, p_municipio bigint) RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE AS $$
  SELECT app.eh_plataforma()
      OR ( p_escritorio = app.tenant_atual()
           AND ( app.eh_admin_escritorio()
                 OR p_municipio = ANY (app.municipios_do_usuario()) ) )
$$;
COMMENT ON FUNCTION app.pode_acessar(bigint,bigint) IS 'Isolamento tenant + escopo de município do funcionário, em um só predicado.';

-- Acesso só por tenant (tabelas sem município: usuários, convites, sessões…):
CREATE OR REPLACE FUNCTION app.pode_acessar_tenant(p_escritorio bigint) RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE AS $$
  SELECT app.eh_plataforma() OR p_escritorio = app.tenant_atual()
$$;

-- =============================================================================
-- ESCRITORIOS — tenant vê só a própria linha; ciclo de vida é da plataforma.
-- =============================================================================
ALTER TABLE escritorios ENABLE ROW LEVEL SECURITY;   -- sem FORCE: owner-exemption p/ app.autenticar (login pré-tenant)
CREATE POLICY p_iso ON escritorios FOR ALL
  USING      (app.eh_plataforma() OR (id = app.tenant_atual() AND (deleted_at IS NULL OR app.incluir_excluidos())))
  WITH CHECK (app.eh_plataforma());                                   -- só a plataforma escreve escritórios
-- (Criar/liberar/suspender é exclusivo da plataforma: garantido pelo WITH CHECK
--  acima + GRANT de INSERT/UPDATE/DELETE somente a kora_platform, abaixo.)
REVOKE INSERT, UPDATE, DELETE ON escritorios FROM kora_app;
GRANT  INSERT, UPDATE, DELETE ON escritorios TO kora_platform;

-- =============================================================================
-- PLATAFORMA_ADMINS — visível/gerenciável apenas pela plataforma.
-- =============================================================================
ALTER TABLE plataforma_admins ENABLE ROW LEVEL SECURITY;
ALTER TABLE plataforma_admins FORCE ROW LEVEL SECURITY;
CREATE POLICY p_iso ON plataforma_admins FOR ALL
  USING (app.eh_plataforma()) WITH CHECK (app.eh_plataforma());
REVOKE ALL ON plataforma_admins FROM kora_app, kora_readonly;
GRANT SELECT, INSERT, UPDATE, DELETE ON plataforma_admins TO kora_platform;

-- =============================================================================
-- USUARIOS — todos do tenant leem; escrita só admin/plataforma; self-update ok.
-- =============================================================================
ALTER TABLE usuarios ENABLE ROW LEVEL SECURITY;   -- sem FORCE: owner-exemption p/ app.eh_admin_escritorio()
CREATE POLICY p_iso ON usuarios FOR ALL
  USING      (app.pode_acessar_tenant(escritorio_id) AND (deleted_at IS NULL OR app.incluir_excluidos()))
  WITH CHECK (app.pode_acessar_tenant(escritorio_id));
-- RESTRICTIVE: INSERT/DELETE só admin ou plataforma
CREATE POLICY r_ins ON usuarios AS RESTRICTIVE FOR INSERT
  WITH CHECK (app.eh_plataforma() OR app.eh_admin_escritorio());
CREATE POLICY r_del ON usuarios AS RESTRICTIVE FOR DELETE
  USING (app.eh_plataforma() OR app.eh_admin_escritorio());
-- UPDATE: admin, plataforma OU o próprio usuário (troca senha/mfa)
CREATE POLICY r_upd ON usuarios AS RESTRICTIVE FOR UPDATE
  USING      (app.eh_plataforma() OR app.eh_admin_escritorio() OR id = app.usuario_atual())
  WITH CHECK (app.eh_plataforma() OR app.eh_admin_escritorio() OR id = app.usuario_atual());

-- =============================================================================
-- USUARIOS_MUNICIPIOS — atribuições: leitura tenant; escrita admin/plataforma.
-- =============================================================================
ALTER TABLE usuarios_municipios ENABLE ROW LEVEL SECURITY;   -- sem FORCE: owner-exemption p/ app.municipios_do_usuario()
CREATE POLICY p_iso ON usuarios_municipios FOR ALL
  USING      (app.pode_acessar_tenant(escritorio_id))
  WITH CHECK (app.pode_acessar_tenant(escritorio_id));
CREATE POLICY r_write ON usuarios_municipios AS RESTRICTIVE FOR ALL
  USING      (app.eh_plataforma() OR app.eh_admin_escritorio())
  WITH CHECK (app.eh_plataforma() OR app.eh_admin_escritorio());

-- =============================================================================
-- ENTIDADES — leitura com escopo de município; escrita admin/plataforma.
-- =============================================================================
ALTER TABLE entidades ENABLE ROW LEVEL SECURITY;
ALTER TABLE entidades FORCE ROW LEVEL SECURITY;
CREATE POLICY p_iso ON entidades FOR ALL
  USING      (app.pode_acessar(escritorio_id, municipio_id) AND (deleted_at IS NULL OR app.incluir_excluidos()))
  WITH CHECK (app.pode_acessar(escritorio_id, municipio_id));
CREATE POLICY r_write ON entidades AS RESTRICTIVE FOR ALL
  USING      (app.eh_plataforma() OR app.eh_admin_escritorio() OR municipio_id = ANY (app.municipios_do_usuario()))
  WITH CHECK (app.eh_plataforma() OR app.eh_admin_escritorio());     -- criar/editar entidade: admin/plataforma

-- =============================================================================
-- PRESTACOES_CONTAS / DOCUMENTOS / VALIDACOES / ITENS / INCONSISTENCIAS / ENVIOS
-- Escopo de município uniforme; funcionário atribuído pode operar.
-- =============================================================================
ALTER TABLE prestacoes_contas ENABLE ROW LEVEL SECURITY;  ALTER TABLE prestacoes_contas FORCE ROW LEVEL SECURITY;
CREATE POLICY p_iso ON prestacoes_contas FOR ALL
  USING      (app.pode_acessar(escritorio_id, municipio_id) AND (deleted_at IS NULL OR app.incluir_excluidos()))
  WITH CHECK (app.pode_acessar(escritorio_id, municipio_id));

ALTER TABLE documentos ENABLE ROW LEVEL SECURITY;         ALTER TABLE documentos FORCE ROW LEVEL SECURITY;
CREATE POLICY p_iso ON documentos FOR ALL
  USING      (app.pode_acessar(escritorio_id, municipio_id) AND (deleted_at IS NULL OR app.incluir_excluidos()))
  WITH CHECK (app.pode_acessar(escritorio_id, municipio_id));

ALTER TABLE validacoes ENABLE ROW LEVEL SECURITY;         ALTER TABLE validacoes FORCE ROW LEVEL SECURITY;
CREATE POLICY p_iso ON validacoes FOR ALL
  USING      (app.pode_acessar(escritorio_id, municipio_id))
  WITH CHECK (app.pode_acessar(escritorio_id, municipio_id));

ALTER TABLE itens_prestacao ENABLE ROW LEVEL SECURITY;    ALTER TABLE itens_prestacao FORCE ROW LEVEL SECURITY;
CREATE POLICY p_iso ON itens_prestacao FOR ALL
  USING      (app.pode_acessar(escritorio_id, municipio_id))
  WITH CHECK (app.pode_acessar(escritorio_id, municipio_id));

ALTER TABLE inconsistencias ENABLE ROW LEVEL SECURITY;    ALTER TABLE inconsistencias FORCE ROW LEVEL SECURITY;
CREATE POLICY p_iso ON inconsistencias FOR ALL
  USING      (app.pode_acessar(escritorio_id, municipio_id))
  WITH CHECK (app.pode_acessar(escritorio_id, municipio_id));

ALTER TABLE envios ENABLE ROW LEVEL SECURITY;             ALTER TABLE envios FORCE ROW LEVEL SECURITY;
CREATE POLICY p_iso ON envios FOR ALL
  USING      (app.pode_acessar(escritorio_id, municipio_id))
  WITH CHECK (app.pode_acessar(escritorio_id, municipio_id));

-- =============================================================================
-- CREDENCIAIS_TCE — segredo sensível: ACESSO TOTAL (leitura+escrita) restrito a
-- admin/plataforma. O funcionário NUNCA lê a linha; a transmissão ao TCE decifra
-- server-side via KMS sob contexto de serviço, sem expor o segredo ao usuário.
-- (A RESTRICTIVE FOR ALL abaixo bloqueia inclusive SELECT do funcionário.)
-- =============================================================================
ALTER TABLE credenciais_tce ENABLE ROW LEVEL SECURITY;    ALTER TABLE credenciais_tce FORCE ROW LEVEL SECURITY;
CREATE POLICY p_iso ON credenciais_tce FOR ALL
  USING      (app.pode_acessar(escritorio_id, municipio_id) AND (deleted_at IS NULL OR app.incluir_excluidos()))
  WITH CHECK (app.pode_acessar(escritorio_id, municipio_id));
CREATE POLICY r_admin ON credenciais_tce AS RESTRICTIVE FOR ALL
  USING      (app.eh_plataforma() OR app.eh_admin_escritorio())
  WITH CHECK (app.eh_plataforma() OR app.eh_admin_escritorio());

-- =============================================================================
-- CONVITES — leitura/escrita admin/plataforma.
-- =============================================================================
ALTER TABLE convites ENABLE ROW LEVEL SECURITY;           ALTER TABLE convites FORCE ROW LEVEL SECURITY;
CREATE POLICY p_iso ON convites FOR ALL
  USING      (app.pode_acessar_tenant(escritorio_id))
  WITH CHECK (app.pode_acessar_tenant(escritorio_id));
CREATE POLICY r_write ON convites AS RESTRICTIVE FOR ALL
  USING      (app.eh_plataforma() OR app.eh_admin_escritorio())
  WITH CHECK (app.eh_plataforma() OR app.eh_admin_escritorio());

-- =============================================================================
-- SESSOES — cada usuário gerencia as próprias; admin pode revogar do tenant.
-- =============================================================================
ALTER TABLE sessoes ENABLE ROW LEVEL SECURITY;            ALTER TABLE sessoes FORCE ROW LEVEL SECURITY;
CREATE POLICY p_iso ON sessoes FOR ALL
  USING      (app.pode_acessar_tenant(escritorio_id))
  WITH CHECK (app.pode_acessar_tenant(escritorio_id));
CREATE POLICY r_write ON sessoes AS RESTRICTIVE FOR ALL
  USING      (app.eh_plataforma() OR app.eh_admin_escritorio() OR usuario_id = app.usuario_atual())
  WITH CHECK (app.eh_plataforma() OR app.eh_admin_escritorio() OR usuario_id = app.usuario_atual());

-- =============================================================================
-- PRESTACAO_CONTADORES — isolamento por tenant (mantido por trigger).
-- =============================================================================
ALTER TABLE prestacao_contadores ENABLE ROW LEVEL SECURITY; ALTER TABLE prestacao_contadores FORCE ROW LEVEL SECURITY;
CREATE POLICY p_iso ON prestacao_contadores FOR ALL
  USING      (app.pode_acessar_tenant(escritorio_id))
  WITH CHECK (app.pode_acessar_tenant(escritorio_id));

-- =============================================================================
-- AUDITORIA — tenant lê só a própria trilha; INSERT permitido; sem UPDATE/DELETE.
-- (grants de imutabilidade e trigger de bloqueio já no 05/06)
-- =============================================================================
ALTER TABLE auditoria ENABLE ROW LEVEL SECURITY;          ALTER TABLE auditoria FORCE ROW LEVEL SECURITY;
CREATE POLICY p_sel ON auditoria FOR SELECT
  USING (app.eh_plataforma() OR escritorio_id = app.tenant_atual());
CREATE POLICY p_ins ON auditoria FOR INSERT
  WITH CHECK (app.eh_plataforma() OR escritorio_id = app.tenant_atual() OR escritorio_id = 0);

RESET ROLE;
