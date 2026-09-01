-- =============================================================================
-- KORA-PLATAFORMA — 11: JURISDIÇÕES PERSONALIZADAS EM `municipios`
--
-- Nem toda entidade que presta contas fica num município do IBGE: órgãos
-- estaduais (Ministério Público, Defensoria, TCE), consórcios e autarquias
-- precisam ser cadastrados do mesmo jeito. Em vez de afrouxar
-- `entidades.municipio_id` — que é o eixo do escopo de município na RLS —
-- abrimos `municipios` para linhas PERSONALIZADAS, marcadas com o escritório
-- que as criou:
--
--   escritorio_id IS NULL     -> referência IBGE: global, somente-leitura
--   escritorio_id = <tenant>  -> jurisdição do tenant: só ele enxerga
--
-- Com isso `municipios` deixa de ser exceção sem RLS (ver cabeçalho do 07):
-- ganha política de leitura (global OU do próprio tenant) e de escrita (só
-- admin do escritório, e só linha do próprio escritório).
-- =============================================================================
SET ROLE kora_migrator;

ALTER TABLE municipios ADD COLUMN escritorio_id bigint REFERENCES escritorios(id);
COMMENT ON COLUMN municipios.escritorio_id IS 'NULL = referência IBGE global. Preenchido = jurisdição personalizada, visível apenas ao escritório que a criou.';

-- Jurisdição personalizada não tem código IBGE. O índice único de codigo_ibge
-- continua valendo para a referência (NULLs não colidem entre si no Postgres).
ALTER TABLE municipios ALTER COLUMN codigo_ibge DROP NOT NULL;

-- Uma jurisdição por nome/UF dentro do escritório: recadastrar o mesmo nome
-- reaproveita a linha em vez de duplicar.
CREATE UNIQUE INDEX ux_municipios_custom ON municipios (escritorio_id, nome_normalizado, uf)
       WHERE escritorio_id IS NOT NULL;
CREATE INDEX ix_municipios_fk_escritorio ON municipios (escritorio_id)
       WHERE escritorio_id IS NOT NULL;                       -- índice do lado filho da FK

-- ENABLE sem FORCE: o dono (kora_migrator) segue semeando a referência do IBGE
-- pelos seeds. kora_app nunca é dono => 100% sujeito às políticas abaixo.
ALTER TABLE municipios ENABLE ROW LEVEL SECURITY;

-- Leitura: referência global + o que é do próprio tenant.
CREATE POLICY p_leitura ON municipios FOR SELECT
  USING (escritorio_id IS NULL OR app.pode_acessar_tenant(escritorio_id));

-- Plataforma (backoffice) mantém o controle da referência global.
CREATE POLICY p_plataforma ON municipios FOR ALL
  USING      (app.eh_plataforma())
  WITH CHECK (app.eh_plataforma());

-- Tenant só cria jurisdição PRÓPRIA, e só admin do escritório. Sem política de
-- UPDATE/DELETE: o tenant não mexe na referência do IBGE nem depois de criada.
CREATE POLICY p_custom_insert ON municipios FOR INSERT
  WITH CHECK (escritorio_id = app.tenant_atual() AND app.eh_admin_escritorio());

GRANT INSERT ON municipios TO kora_app;   -- a política acima é quem de fato limita

RESET ROLE;
