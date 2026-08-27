-- =============================================================================
-- KORA-PLATAFORMA — 05: TABELAS PARTICIONADAS + MANUTENÇÃO DE PARTIÇÕES
--
-- ESCOLHA DE ESTRATÉGIA (justificada por tabela):
--   * auditoria, envios, tentativas_login  -> RANGE por TEMPO (mês).
--   * itens_prestacao, inconsistencias      -> RANGE por EXERCÍCIO (ano).
--
-- POR QUE RANGE-POR-TEMPO E NÃO LIST/HASH-POR-TENANT (discordância explícita):
--   O prompt cogitou LIST/HASH por tenant. Desaconselho como chave primária de
--   partição:
--     (a) LIST-por-tenant exige criar partição a cada escritório onboardado e
--         gera partições MUITO desiguais (um escritório grande domina);
--     (b) o isolamento entre tenants JÁ é garantido pela RLS + índices com
--         escritorio_id na frente (localidade), então a partição não precisa
--         carregar essa responsabilidade;
--     (c) a maior alavanca operacional aqui é RETENÇÃO/ARQUIVAMENTO e poda
--         temporal — DROP/DETACH de uma partição de mês/ano antigos é O(1),
--         enquanto expurgar por tenant seria DELETE caro.
--   Portanto a partição segue o TEMPO/EXERCÍCIO (padrão de consulta e retenção)
--   e o escritorio_id fica como 1ª coluna dos ÍNDICES dentro de cada partição.
--   HASH-por-tenant só se justificaria para espalhar contenção de escrita
--   extrema num single hot table — não é o caso deste workload.
-- =============================================================================
SET ROLE kora_migrator;

-- -----------------------------------------------------------------------------
-- Sentinela de plataforma: escritorio_id = 0 representa "eventos da plataforma"
-- (ações de SUPER_ADMIN sem tenant), permitindo que auditoria.escritorio_id
-- seja NOT NULL e lidere a PK. FK real para escritorios(id).
-- -----------------------------------------------------------------------------
INSERT INTO escritorios (id, razao_social, nome_normalizado, cnpj, status, plano, liberado_em)
OVERRIDING SYSTEM VALUE
VALUES (0, 'PLATAFORMA KORA', 'plataforma kora', '00000000000000', 'ativo', 'enterprise', now())
ON CONFLICT DO NOTHING;

-- =============================================================================
-- AUDITORIA — append-only, IMUTÁVEL. RANGE por mês em ocorrido_em.
-- Registra: quem, o quê, quando, IP, user-agent, valores antes/depois.
-- =============================================================================
CREATE TABLE auditoria (
  escritorio_id  bigint NOT NULL DEFAULT 0 REFERENCES escritorios(id),
  id             bigint GENERATED ALWAYS AS IDENTITY,
  ocorrido_em    timestamptz NOT NULL DEFAULT now(),
  ator_tipo      tipo_ator NOT NULL,
  ator_id        bigint,
  ator_email     text,
  acao           text NOT NULL,                       -- ex.: 'prestacao.transmitida', 'usuario.criado'
  tabela         text,                                -- objeto afetado
  registro_id    bigint,
  ip            inet,
  user_agent     text,
  request_id     text,                                -- correlação com logs da app
  dados_antes    jsonb,
  dados_depois   jsonb,
  PRIMARY KEY (escritorio_id, ocorrido_em, id)        -- tenant 1º; inclui coluna de partição
) PARTITION BY RANGE (ocorrido_em);
COMMENT ON TABLE auditoria IS 'Trilha de auditoria imutável (append-only). Particionada por mês. Sem UPDATE/DELETE.';

-- BRIN em coluna temporal de tabela append-only gigante (índice minúsculo):
CREATE INDEX brin_auditoria_ocorrido ON auditoria USING brin (ocorrido_em) WITH (pages_per_range = 32); -- varredura por janela de tempo
CREATE INDEX ix_auditoria_tenant_ator ON auditoria (escritorio_id, ator_id, ocorrido_em DESC); -- "o que o usuário X fez"
CREATE INDEX ix_auditoria_registro   ON auditoria (escritorio_id, tabela, registro_id, ocorrido_em DESC); -- histórico de um registro
CREATE INDEX gin_auditoria_depois    ON auditoria USING gin (dados_depois jsonb_path_ops);   -- busca por conteúdo alterado (@>)

-- IMUTABILIDADE por GRANT: só INSERT e SELECT. (Trigger de bloqueio no 06 reforça
-- mesmo contra o dono / SECURITY DEFINER.)
REVOKE ALL ON auditoria FROM kora_app, kora_platform, kora_readonly;
GRANT INSERT ON auditoria TO kora_app, kora_platform;
GRANT SELECT ON auditoria TO kora_app, kora_platform, kora_readonly;

-- =============================================================================
-- ENVIOS — cada transmissão/tentativa de remessa ao TCE-MA. RANGE por mês.
-- Volume alto (retries, múltiplos anexos). Payload/resposta do TCE => JSONB.
-- =============================================================================
CREATE TABLE envios (
  escritorio_id  bigint NOT NULL REFERENCES escritorios(id),
  id             bigint GENERATED ALWAYS AS IDENTITY,
  criado_em      timestamptz NOT NULL DEFAULT now(),
  prestacao_id   bigint NOT NULL,
  entidade_id    bigint NOT NULL,
  municipio_id   bigint NOT NULL,
  status         status_envio NOT NULL DEFAULT 'enfileirado',
  protocolo_tce  text,
  payload_tce    jsonb,                               -- schema variável do TCE-MA => JSONB
  resposta_tce   jsonb,
  erro           text,
  concluido_em   timestamptz,
  PRIMARY KEY (escritorio_id, criado_em, id),
  FOREIGN KEY (escritorio_id, prestacao_id) REFERENCES prestacoes_contas(escritorio_id, id)
) PARTITION BY RANGE (criado_em);
COMMENT ON TABLE envios IS 'Transmissões ao TCE-MA (append, alto volume). Particionada por mês.';
CREATE INDEX ix_envios_por_prestacao ON envios (escritorio_id, prestacao_id, criado_em DESC); -- timeline de envios de uma prestação
CREATE INDEX ix_envios_por_entidade  ON envios (escritorio_id, entidade_id, criado_em DESC);  -- timeline por entidade
CREATE INDEX ix_envios_pendentes     ON envios (escritorio_id, status, criado_em)
       WHERE status IN ('enfileirado','transmitindo','erro');                                 -- fila de reprocessamento (parcial)
CREATE INDEX gin_envios_resposta ON envios USING gin (resposta_tce jsonb_path_ops);           -- busca em resposta do TCE

-- =============================================================================
-- ITENS_PRESTACAO — linhas extraídas dos anexos (a MAIOR tabela). RANGE/ano.
-- Colunas típicas TIPADAS (numéricas/consulta) + JSONB para campos por-anexo.
-- =============================================================================
CREATE TABLE itens_prestacao (
  escritorio_id   bigint NOT NULL REFERENCES escritorios(id),
  exercicio       smallint NOT NULL,
  id              bigint GENERATED ALWAYS AS IDENTITY,
  prestacao_id    bigint NOT NULL,
  municipio_id    bigint NOT NULL,
  anexo           text NOT NULL,                      -- 'ANX02','ANX05',... (alinha com extractors)
  codigo_conta    text,
  descricao       text,
  natureza        text,
  valor_previsto  numeric(18,2),
  valor_realizado numeric(18,2),
  dados_extras    jsonb,                              -- campos específicos do anexo (schema variável)
  criado_em       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (escritorio_id, exercicio, id),
  FOREIGN KEY (escritorio_id, prestacao_id) REFERENCES prestacoes_contas(escritorio_id, id)
) PARTITION BY RANGE (exercicio);
COMMENT ON TABLE itens_prestacao IS 'Linhas extraídas dos anexos. Maior tabela; particionada por exercício (ano).';
CREATE INDEX ix_itens_por_prestacao ON itens_prestacao (escritorio_id, prestacao_id, anexo); -- itens de uma prestação por anexo
CREATE INDEX ix_itens_conta ON itens_prestacao (escritorio_id, prestacao_id, codigo_conta);  -- conciliação por conta contábil
CREATE INDEX gin_itens_extras ON itens_prestacao USING gin (dados_extras jsonb_path_ops);    -- consulta em campos por-anexo

-- =============================================================================
-- INCONSISTENCIAS — achados individuais das validações. RANGE/ano (co-locado
-- com itens). Recebem UPDATE (status muda) -> não é append puro; sem BRIN.
-- =============================================================================
CREATE TABLE inconsistencias (
  escritorio_id   bigint NOT NULL REFERENCES escritorios(id),
  exercicio       smallint NOT NULL,
  id              bigint GENERATED ALWAYS AS IDENTITY,
  validacao_id    bigint NOT NULL,
  prestacao_id    bigint NOT NULL,
  municipio_id    bigint NOT NULL,
  item_id         bigint,
  regra_codigo    text NOT NULL,
  anexo           text,
  severidade      severidade NOT NULL,
  status          status_inconsistencia NOT NULL DEFAULT 'aberta',
  campo           text,
  valor_esperado  text,
  valor_encontrado text,
  mensagem        text NOT NULL,
  justificativa   text,
  resolvido_por   bigint,
  resolvido_em    timestamptz,
  criado_em       timestamptz NOT NULL DEFAULT now(),
  atualizado_em   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (escritorio_id, exercicio, id),
  FOREIGN KEY (escritorio_id, prestacao_id) REFERENCES prestacoes_contas(escritorio_id, id),
  FOREIGN KEY (escritorio_id, validacao_id) REFERENCES validacoes(escritorio_id, id)
) PARTITION BY RANGE (exercicio);
COMMENT ON TABLE inconsistencias IS 'Divergências detectadas (por severidade/anexo). Particionada por exercício.';
-- Painel "abertas críticas de uma prestação" (igualdade -> parcial):
CREATE INDEX ix_incons_prestacao_abertas ON inconsistencias (escritorio_id, prestacao_id, severidade)
       WHERE status = 'aberta';                                                                -- inconsistências abertas por prestação
CREATE INDEX ix_incons_por_validacao ON inconsistencias (escritorio_id, validacao_id);        -- achados de uma validação
CREATE INDEX ix_incons_regra ON inconsistencias (escritorio_id, regra_codigo, severidade);    -- estatística por regra

-- =============================================================================
-- FUNÇÃO DE MANUTENÇÃO DE PARTIÇÕES
-- Cria antecipadamente as partições dos próximos meses/anos. Idempotente.
-- Em produção, prefira pg_partman; esta função é o fallback autocontido.
-- =============================================================================
CREATE OR REPLACE FUNCTION app.criar_particoes_mensais(p_tabela regclass, p_meses_a_frente int DEFAULT 3)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
  v_inicio date := date_trunc('month', now())::date;
  v_i int;
  v_de date; v_ate date; v_nome text; v_base text := split_part(p_tabela::text, '.', -1);
BEGIN
  FOR v_i IN 0..p_meses_a_frente LOOP
    v_de  := (v_inicio + (v_i || ' month')::interval)::date;
    v_ate := (v_de + interval '1 month')::date;
    v_nome := format('%s_%s', v_base, to_char(v_de, 'YYYYMM'));
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I PARTITION OF %s FOR VALUES FROM (%L) TO (%L)',
                   v_nome, p_tabela, v_de, v_ate);
  END LOOP;
END;
$$;
COMMENT ON FUNCTION app.criar_particoes_mensais(regclass,int) IS 'Cria partições mensais futuras (auditoria/envios/tentativas_login).';

CREATE OR REPLACE FUNCTION app.criar_particoes_anuais(p_tabela regclass, p_anos_a_frente int DEFAULT 1)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
  v_ano int := extract(year FROM now())::int;
  v_i int; v_nome text; v_base text := split_part(p_tabela::text, '.', -1);
BEGIN
  FOR v_i IN 0..p_anos_a_frente LOOP
    v_nome := format('%s_%s', v_base, v_ano + v_i);
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I PARTITION OF %s FOR VALUES FROM (%L) TO (%L)',
                   v_nome, p_tabela, v_ano + v_i, v_ano + v_i + 1);
  END LOOP;
END;
$$;
COMMENT ON FUNCTION app.criar_particoes_anuais(regclass,int) IS 'Cria partições anuais futuras (itens_prestacao/inconsistencias).';

-- Bootstrap: cria as partições correntes (senão o primeiro INSERT falha).
SELECT app.criar_particoes_mensais('auditoria');
SELECT app.criar_particoes_mensais('envios');
SELECT app.criar_particoes_mensais('tentativas_login');
SELECT app.criar_particoes_anuais('itens_prestacao');
SELECT app.criar_particoes_anuais('inconsistencias');

-- Agendamento (requer pg_cron). Roda todo dia 25 às 03:00, garantindo o mês/ano seguinte.
-- SELECT cron.schedule('particoes-mensais','0 3 25 * *', $$
--   SELECT app.criar_particoes_mensais('auditoria');
--   SELECT app.criar_particoes_mensais('envios');
--   SELECT app.criar_particoes_mensais('tentativas_login');
-- $$);
-- SELECT cron.schedule('particoes-anuais','0 3 1 12 *', $$
--   SELECT app.criar_particoes_anuais('itens_prestacao');
--   SELECT app.criar_particoes_anuais('inconsistencias');
-- $$);

RESET ROLE;
