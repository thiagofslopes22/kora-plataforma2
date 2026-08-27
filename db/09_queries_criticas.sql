-- =============================================================================
-- KORA-PLATAFORMA — 09: 10 QUERIES CRÍTICAS + PLANO ESPERADO + ÍNDICE USADO
--
-- PADRÃO DE CONTEXTO POR TRANSAÇÃO (compatível com PgBouncer transaction mode):
--   BEGIN;
--     SELECT set_config('app.current_tenant',  '<escritorio_id>', true);  -- true = LOCAL
--     SELECT set_config('app.current_user_id', '<usuario_id>',    true);
--     -- (opcional p/ auditoria): app.request_ip, app.user_agent, app.ator_email, app.request_id
--     ...queries...
--   COMMIT;
-- Use set_config(...,true) OU "SET LOCAL": ambos morrem no fim da transação, então
-- a conexão devolvida ao pool não carrega contexto de um tenant para outro.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Q1. LOGIN (pré-tenant) — resolve tenant + hash por e-mail.
--     Índice: ux_usuarios_email (parcial, deleted_at IS NULL).
--     Plano:  Index Scan using ux_usuarios_email  (1 linha). Sem RLS (SECURITY DEFINER).
-- -----------------------------------------------------------------------------
SELECT * FROM app.autenticar('fulano@escritorio.com');

-- -----------------------------------------------------------------------------
-- Q2. DASHBOARD — prestações pendentes do escritório, ordenadas por prazo.
--     Índice: ix_prestacoes_pendentes (escritorio_id, status, prazo) INCLUDE(...)
--             parcial WHERE status IN (...) AND deleted_at IS NULL.
--     Plano:  Index Only Scan  (covering => sem heap fetch). RLS casada no 1º termo.
-- -----------------------------------------------------------------------------
SELECT entidade_id, municipio_id, tipo, competencia_id, status, prazo
FROM prestacoes_contas
WHERE status IN ('rascunho','em_validacao','com_inconsistencias','pronta')
ORDER BY prazo
LIMIT 50;

-- -----------------------------------------------------------------------------
-- Q3. FUNCIONÁRIO — entidades dos municípios atribuídos (3º nível de acesso).
--     A RLS já restringe via app.municipios_do_usuario(); a query só pagina.
--     Índice: ix_entidades_tenant_municipio (escritorio_id, municipio_id) INCLUDE(tipo,nome).
--     Plano:  Bitmap/Index Scan por município + filtro RLS = ANY(array). Index Only Scan.
-- -----------------------------------------------------------------------------
SELECT id, municipio_id, tipo, nome
FROM entidades
WHERE municipio_id = ANY (app.municipios_do_usuario())
ORDER BY nome;

-- -----------------------------------------------------------------------------
-- Q4. BUSCA TEXTUAL — entidade por trecho do nome (com poda por tenant).
--     Índice: gin_entidades_nome  USING gin (escritorio_id, nome_normalizado gin_trgm_ops)  [btree_gin].
--     Plano:  Bitmap Index Scan (GIN) => Bitmap Heap Scan. O escritorio_id entra
--             NO índice GIN (btree_gin), então poda por tenant ANTES do trigram.
-- -----------------------------------------------------------------------------
SELECT id, municipio_id, nome
FROM entidades
WHERE escritorio_id = current_setting('app.current_tenant')::bigint
  AND nome_normalizado LIKE '%imperatriz%'
LIMIT 20;

-- -----------------------------------------------------------------------------
-- Q5. INCONSISTÊNCIAS abertas de uma prestação, por severidade.
--     Índice: ix_incons_prestacao_abertas (escritorio_id, prestacao_id, severidade) WHERE status='aberta'.
--     Plano:  Partition Pruning por exercício -> Index Scan na partição do ano.
-- -----------------------------------------------------------------------------
SELECT severidade, count(*)
FROM inconsistencias
WHERE exercicio = 2026 AND prestacao_id = $1 AND status = 'aberta'
GROUP BY severidade;

-- -----------------------------------------------------------------------------
-- Q6. CONTADORES do dashboard (SEM COUNT(*)) — lê agregado mantido por trigger.
--     Índice: PK prestacao_contadores (escritorio_id, prestacao_id).
--     Plano:  Index Only Scan (1 linha). Substitui um COUNT(*) em inconsistencias.
-- -----------------------------------------------------------------------------
SELECT criticas, altas, medias, baixas, abertas
FROM prestacao_contadores
WHERE prestacao_id = $1;

-- -----------------------------------------------------------------------------
-- Q7. TIMELINE de envios de uma entidade numa janela de tempo.
--     Índice: ix_envios_por_entidade (escritorio_id, entidade_id, criado_em DESC).
--     Plano:  Partition Pruning por mês (criado_em) -> Index Scan Backward.
-- -----------------------------------------------------------------------------
SELECT id, criado_em, status, protocolo_tce
FROM envios
WHERE entidade_id = $1
  AND criado_em >= now() - interval '90 days'
ORDER BY criado_em DESC
LIMIT 100;

-- -----------------------------------------------------------------------------
-- Q8. DEDUP de documento por hash (evita reupload do mesmo arquivo).
--     Índice: ux_documentos_hash (escritorio_id, hash_sha256) WHERE deleted_at IS NULL.
--     Plano:  Index Scan (0/1 linha).
-- -----------------------------------------------------------------------------
SELECT id, storage_key
FROM documentos
WHERE hash_sha256 = $1;

-- -----------------------------------------------------------------------------
-- Q9. AUDITORIA — o que um usuário fez nos últimos 30 dias.
--     Índice: ix_auditoria_tenant_ator (escritorio_id, ator_id, ocorrido_em DESC)
--             + BRIN brin_auditoria_ocorrido para a janela temporal.
--     Plano:  Partition Pruning por mês -> Index Scan; BRIN ajuda varreduras largas.
-- -----------------------------------------------------------------------------
SELECT ocorrido_em, acao, tabela, registro_id
FROM auditoria
WHERE ator_id = $1
  AND ocorrido_em >= now() - interval '30 days'
ORDER BY ocorrido_em DESC;

-- -----------------------------------------------------------------------------
-- Q10. SUPER_ADMIN — escritórios por status com contadores (backoffice).
--      Fonte: mv_plataforma_visao (cross-tenant, sem RLS, só kora_platform).
--      Índice: ix_mv_plataforma_status. Plano: Index Scan na MV (pré-agregada).
--      Alternativa tempo-real (sem MV): ix_escritorios_status (Index Only Scan).
-- -----------------------------------------------------------------------------
SELECT escritorio_id, razao_social, plano, total_entidades, prestacoes_com_inconsist, inconsist_criticas_abertas
FROM mv_plataforma_visao
WHERE status = 'ativo'
ORDER BY inconsist_criticas_abertas DESC;

-- =============================================================================
-- COMO VALIDAR OS PLANOS (execute com contexto setado):
--   EXPLAIN (ANALYZE, BUFFERS, VERBOSE) <query>;
-- Verifique: (1) "Index Only Scan" onde há INCLUDE; (2) "never executed"/pruning
-- nas partições fora da janela; (3) o filtro de RLS aparece como Filter com as
-- funções app.* — se aparecer Seq Scan em tabela grande, revise o índice.
-- =============================================================================
