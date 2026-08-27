-- =============================================================================
-- KORA-PLATAFORMA — 10: INTEGRAÇÃO DO BACKEND-AUDITOR
--
-- Contexto: o sistema é ÚNICO, com dois backends que nasceram separados:
--   * CONCILIADOR (:8001, /conc, COM auth): usuarios/prefeituras/conciliacoes
--     RGF-RREO. Já refletido em 03 (usuarios/entidades/prestacoes/validacoes/
--     inconsistencias).
--   * AUDITOR (:8000, /api, SEM auth, HOJE STATELESS): 13 anexos PDF -> 27
--     quadros (Q1..Q27) -> Excel de trabalho -> inconformidades IRREGULAR/ALERTA
--     (motor de regras + IA) -> RIT (HTML). Nada é persistido hoje.
--
-- Este arquivo dá PERSISTÊNCIA ao auditor e unifica os achados dos dois backends
-- na mesma tabela `inconsistencias`. Roda DEPOIS de 03..07 (usa RLS/helpers).
-- Como nada foi implantado ainda, usamos ALTER para deixar explícita a costura.
-- =============================================================================
SET ROLE kora_migrator;

-- -----------------------------------------------------------------------------
-- ENUMs do domínio do auditor
-- -----------------------------------------------------------------------------
-- Os 13 tipos de upload reais (frontend AuditoriaPage.DOCS / routes.py _uploads_form)
CREATE TYPE tipo_documento AS ENUM (
  'ANX_10_ATUAL','ANX_10_ANTERIOR','ANX_12','ANX_06','ANX_02','ANX_13','ANX_14',
  'DFC','LOA','RGF_2SEM','RGF_1SEM','BO_FUNDEB','FF_SAUDE'
);
-- Papel do arquivo no fluxo (vale para conciliador e auditor)
CREATE TYPE papel_documento AS ENUM (
  'anexo_fonte','planilha_trabalho','relatorio_rit','rascunho','homologado','comprovante','outro'
);
-- Que processo a análise representa
CREATE TYPE tipo_analise AS ENUM ('conciliacao_rgf','conciliacao_rreo','auditoria_rit');
CREATE TYPE status_analise AS ENUM ('em_processamento','concluida','erro');
-- Classificação do achado do auditor (a UI usa IRREGULAR/ALERTA)
CREATE TYPE classificacao_achado AS ENUM ('irregular','alerta','regular');

-- -----------------------------------------------------------------------------
-- DOCUMENTOS: aplicar a taxonomia real (13 tipos) + papel no fluxo.
-- (coluna estava como text; tabela vazia -> cast direto é seguro)
-- -----------------------------------------------------------------------------
ALTER TABLE documentos
  ALTER COLUMN tipo_documento TYPE tipo_documento USING NULLIF(tipo_documento,'')::tipo_documento,
  ADD COLUMN papel_documento papel_documento NOT NULL DEFAULT 'anexo_fonte';
CREATE INDEX ix_documentos_tipo ON documentos (escritorio_id, tipo_documento)
       WHERE deleted_at IS NULL;                       -- "quais anexos deste tipo já subiram?"

-- -----------------------------------------------------------------------------
-- VALIDACOES vira "execução de análise" (conciliação OU auditoria RIT).
-- Uma análise pode existir sem prestação formal (auditoria a partir de PDFs
-- avulsos) -> prestacao_id passa a ser opcional; ganha entidade/competência.
-- -----------------------------------------------------------------------------
ALTER TABLE validacoes
  ADD COLUMN tipo_analise    tipo_analise   NOT NULL DEFAULT 'auditoria_rit',
  ADD COLUMN status_analise  status_analise NOT NULL DEFAULT 'concluida',
  ADD COLUMN entidade_id     bigint,
  ADD COLUMN competencia_id  bigint REFERENCES competencias(id),
  ADD COLUMN dados_manuais   jsonb,          -- aba "Dados Manuais" do Excel do auditor
  ADD COLUMN resumo          jsonb,          -- {irregulares, alertas, quadros_analisados, quadros_ausentes}
  ALTER COLUMN prestacao_id  DROP NOT NULL;
ALTER TABLE validacoes
  ADD CONSTRAINT fk_validacoes_entidade FOREIGN KEY (escritorio_id, entidade_id)
      REFERENCES entidades(escritorio_id, id);
CREATE INDEX ix_validacoes_entidade ON validacoes (escritorio_id, entidade_id, iniciada_em DESC); -- histórico de análises por entidade
CREATE INDEX ix_validacoes_tipo     ON validacoes (escritorio_id, tipo_analise, status_analise);  -- filtrar por processo/status
CREATE INDEX ix_validacoes_fk_competencia ON validacoes (competencia_id);                          -- lado filho da FK global

COMMENT ON COLUMN validacoes.tipo_analise IS 'conciliacao_rgf | conciliacao_rreo | auditoria_rit — unifica os dois backends.';

-- -----------------------------------------------------------------------------
-- QUADROS — os 27 quadros contábeis extraídos numa execução do auditor.
-- Estrutura HETEROGÊNEA por quadro -> payload em JSONB (espelha `data.dados`).
-- Tenant-scoped, com municipio_id denormalizado para RLS/poda.
-- -----------------------------------------------------------------------------
CREATE TABLE quadros (
  escritorio_id  bigint NOT NULL REFERENCES escritorios(id),
  id             bigint GENERATED ALWAYS AS IDENTITY,
  validacao_id   bigint NOT NULL,
  municipio_id   bigint NOT NULL,
  exercicio      smallint NOT NULL,
  chave          text NOT NULL,               -- 'quadro_01' .. 'quadro_27'
  descricao      text,
  payload        jsonb,                        -- dados calculados do quadro (schema variável)
  gerado         boolean NOT NULL DEFAULT true,
  docs_faltando  text[] NOT NULL DEFAULT '{}',
  criado_em      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (escritorio_id, id),
  FOREIGN KEY (escritorio_id, validacao_id) REFERENCES validacoes(escritorio_id, id) ON DELETE CASCADE
);
COMMENT ON TABLE quadros IS 'Quadros Q1..Q27 extraídos por execução de auditoria. payload heterogêneo em JSONB.';
CREATE UNIQUE INDEX ux_quadros_exec_chave ON quadros (escritorio_id, validacao_id, chave); -- 1 quadro por chave por execução
CREATE INDEX ix_quadros_fk_validacao ON quadros (escritorio_id, validacao_id);             -- lado filho da FK
CREATE INDEX gin_quadros_payload ON quadros USING gin (payload jsonb_path_ops);             -- consultar valores dentro do quadro

-- -----------------------------------------------------------------------------
-- RELATORIOS_RIT — o RIT gerado (HTML/PDF em storage externo) por execução.
-- -----------------------------------------------------------------------------
CREATE TABLE relatorios_rit (
  escritorio_id     bigint NOT NULL REFERENCES escritorios(id),
  id                bigint GENERATED ALWAYS AS IDENTITY,
  ulid_publico      uuid NOT NULL DEFAULT app.gerar_uuidv7(),
  validacao_id      bigint NOT NULL,
  entidade_id       bigint NOT NULL,
  municipio_id      bigint NOT NULL,
  exercicio         smallint NOT NULL,
  formato           text NOT NULL DEFAULT 'html',   -- 'html' | 'pdf'
  storage_bucket    text,
  storage_key       text,
  hash_sha256       bytea,
  total_irregulares integer NOT NULL DEFAULT 0,
  total_alertas     integer NOT NULL DEFAULT 0,
  quadros_analisados integer NOT NULL DEFAULT 0,
  quadros_ausentes  text[] NOT NULL DEFAULT '{}',
  gerado_por        bigint,
  criado_em         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (escritorio_id, id),
  FOREIGN KEY (escritorio_id, validacao_id) REFERENCES validacoes(escritorio_id, id),
  FOREIGN KEY (escritorio_id, entidade_id)  REFERENCES entidades(escritorio_id, id)
);
COMMENT ON TABLE relatorios_rit IS 'RIT gerado (HTML/PDF em S3) por execução de auditoria, com resumo dos achados.';
CREATE UNIQUE INDEX ux_rit_ulid ON relatorios_rit (ulid_publico);
CREATE INDEX ix_rit_por_entidade ON relatorios_rit (escritorio_id, entidade_id, criado_em DESC); -- RITs de uma entidade
CREATE INDEX ix_rit_fk_validacao ON relatorios_rit (escritorio_id, validacao_id);                -- lado filho da FK

-- -----------------------------------------------------------------------------
-- INCONSISTENCIAS: unificar com as inconformidades do auditor.
-- Já guarda divergências do conciliador (severidade/anexo/regra). Adicionamos
-- os campos que a UI do auditor consome (AuditResult.jsx).
-- prestacao_id passa a ser opcional (achado pode vir de auditoria avulsa).
-- -----------------------------------------------------------------------------
ALTER TABLE inconsistencias
  ADD COLUMN classificacao classificacao_achado,   -- irregular/alerta (mapeia IRREGULAR/ALERTA)
  ADD COLUMN dimensao      text,                    -- ex.: 'Pessoal', 'Educação', 'FUNDEB'
  ADD COLUMN quadro        text,                    -- 'quadro_06' etc.
  ADD COLUMN titulo        text,
  ADD COLUMN valor_apurado numeric(18,2),
  ADD COLUMN limite_legal  text,
  ADD COLUMN base_legal    text,
  ALTER COLUMN prestacao_id DROP NOT NULL;
COMMENT ON COLUMN inconsistencias.classificacao IS 'Achado do auditor: irregular/alerta. severidade continua preenchida (irregular->critica, alerta->media) p/ os contadores.';
-- Achados de auditoria por execução e classificação (parcial em abertos):
CREATE INDEX ix_incons_auditoria ON inconsistencias (escritorio_id, validacao_id, classificacao)
       WHERE status = 'aberta';                     -- painel do RIT: irregulares/alertas abertos por execução

-- =============================================================================
-- RLS + GRANTS + TRIGGERS para as tabelas NOVAS (quadros, relatorios_rit)
-- Mesmo padrão do 07: isolamento por tenant + escopo de município.
-- =============================================================================
ALTER TABLE quadros ENABLE ROW LEVEL SECURITY;         ALTER TABLE quadros FORCE ROW LEVEL SECURITY;
CREATE POLICY p_iso ON quadros FOR ALL
  USING      (app.pode_acessar(escritorio_id, municipio_id))
  WITH CHECK (app.pode_acessar(escritorio_id, municipio_id));

ALTER TABLE relatorios_rit ENABLE ROW LEVEL SECURITY;  ALTER TABLE relatorios_rit FORCE ROW LEVEL SECURITY;
CREATE POLICY p_iso ON relatorios_rit FOR ALL
  USING      (app.pode_acessar(escritorio_id, municipio_id))
  WITH CHECK (app.pode_acessar(escritorio_id, municipio_id));

-- escritorio_id imutável nas novas tabelas
CREATE TRIGGER a_tenant_imutavel BEFORE UPDATE ON quadros
  FOR EACH ROW EXECUTE FUNCTION app.trg_escritorio_imutavel();
CREATE TRIGGER a_tenant_imutavel BEFORE UPDATE ON relatorios_rit
  FOR EACH ROW EXECUTE FUNCTION app.trg_escritorio_imutavel();

-- Gerar um RIT é evento relevante -> auditar (quadros são volumosos: não auditar)
CREATE TRIGGER zz_auditar AFTER INSERT OR UPDATE OR DELETE ON relatorios_rit
  FOR EACH ROW EXECUTE FUNCTION app.trg_auditar();

RESET ROLE;
