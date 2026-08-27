-- =============================================================================
-- KORA-PLATAFORMA — 08: AGREGADOS, VIEWS E MANUTENÇÃO
--
-- DISCORDÂNCIA/ESCLARECIMENTO sobre "materialized views para dashboards":
--   Materialized views NÃO suportam RLS. Se o dashboard do TENANT saísse de uma
--   MV compartilhada, um bug de filtro vazaria dados entre escritórios — exatamente
--   o que não pode acontecer. Portanto:
--     * Dashboard do TENANT  -> VIEW comum (security_barrier) sobre tabelas com
--       RLS + os contadores mantidos por trigger (prestacao_contadores). É
--       tempo-real e herda o isolamento. Sem COUNT(*) pesado.
--     * Analytics CROSS-TENANT do SUPER_ADMIN -> MATERIALIZED VIEW (sem RLS),
--       com GRANT exclusivo a kora_platform e REFRESH CONCURRENTLY agendado.
-- =============================================================================
SET ROLE kora_migrator;

-- -----------------------------------------------------------------------------
-- Dashboard do TENANT (RLS-safe). security_barrier impede que predicados do
-- usuário "vazem" para dentro da view antes dos filtros de RLS.
-- -----------------------------------------------------------------------------
-- security_invoker=true (PG15+): a RLS é avaliada com o contexto do USUÁRIO que
-- consulta (kora_app + GUCs), não do dono da view. SEM isto, a RLS usaria o
-- contexto de kora_migrator (sem tenant) e a view voltaria VAZIA para todos.
CREATE VIEW vw_dashboard_escritorio
WITH (security_barrier = true, security_invoker = true) AS
SELECT p.escritorio_id,
       p.id            AS prestacao_id,
       p.ulid_publico,
       p.entidade_id,
       p.municipio_id,
       p.tipo,
       p.status,
       p.prazo,
       coalesce(pc.criticas, 0)     AS inconsistencias_criticas,
       coalesce(pc.altas, 0)        AS inconsistencias_altas,
       coalesce(pc.abertas, 0)      AS inconsistencias_abertas
FROM prestacoes_contas p
LEFT JOIN prestacao_contadores pc
       ON pc.escritorio_id = p.escritorio_id AND pc.prestacao_id = p.id
WHERE p.deleted_at IS NULL;
COMMENT ON VIEW vw_dashboard_escritorio IS 'Dashboard do tenant. RLS das tabelas-base aplica-se; contadores por trigger evitam COUNT(*).';
GRANT SELECT ON vw_dashboard_escritorio TO kora_app, kora_readonly;

-- -----------------------------------------------------------------------------
-- Visão CROSS-TENANT do SUPER_ADMIN (MATERIALIZED VIEW, sem RLS).
-- ATENÇÃO: com FORCE RLS nas tabelas-base, quem POPULA a MV precisa enxergar
-- todos os tenants. Solução SEM BYPASSRLS: a MV pertence a kora_platform e o
-- refresh roda COMO kora_platform — as políticas concedem acesso via
-- eh_plataforma(). Criamos WITH NO DATA (populada empty seria enganoso) e a
-- primeira carga é um REFRESH não-concorrente rodando como kora_platform.
-- -----------------------------------------------------------------------------
CREATE MATERIALIZED VIEW mv_plataforma_visao AS
SELECT e.id                                   AS escritorio_id,
       e.razao_social,
       e.status,
       e.plano,
       count(DISTINCT en.id)                  AS total_entidades,
       count(DISTINCT p.id)                   AS total_prestacoes,
       count(DISTINCT p.id) FILTER (WHERE p.status = 'com_inconsistencias') AS prestacoes_com_inconsist,
       coalesce(sum(pc.criticas), 0)          AS inconsist_criticas_abertas
FROM escritorios e
LEFT JOIN entidades en          ON en.escritorio_id = e.id AND en.deleted_at IS NULL
LEFT JOIN prestacoes_contas p   ON p.escritorio_id = e.id AND p.deleted_at IS NULL
LEFT JOIN prestacao_contadores pc ON pc.escritorio_id = p.escritorio_id AND pc.prestacao_id = p.id
WHERE e.id <> 0
GROUP BY e.id, e.razao_social, e.status, e.plano
WITH NO DATA;
COMMENT ON MATERIALIZED VIEW mv_plataforma_visao IS 'Analytics cross-tenant do backoffice. Sem RLS; pertence a kora_platform; refresh como kora_platform.';
-- REFRESH CONCURRENTLY EXIGE um índice ÚNICO:
CREATE UNIQUE INDEX ux_mv_plataforma ON mv_plataforma_visao (escritorio_id);
CREATE INDEX ix_mv_plataforma_status ON mv_plataforma_visao (status);

-- Transferência de dono exige superusuário (kora_migrator não é membro de
-- kora_platform). Este script roda sob um superusuário que fez SET ROLE.
RESET ROLE;
-- ALTER ... OWNER TO exige que o NOVO DONO tenha CREATE no schema do objeto
-- (regra do Postgres). Em cluster proprio isso passa despercebido porque o
-- script roda como superusuario, que pula a checagem; em Postgres gerenciado
-- (Supabase) o papel da migracao NAO e superusuario e o ALTER falha com
-- "permission denied for schema public".
-- Mantemos o CREATE (nao revogamos depois) porque o REFRESH da MV materializa
-- uma nova heap no mesmo schema — revogar deixaria a MV impossivel de atualizar.
GRANT CREATE ON SCHEMA public TO kora_platform;
ALTER MATERIALIZED VIEW mv_plataforma_visao OWNER TO kora_platform;
REVOKE ALL ON mv_plataforma_visao FROM PUBLIC, kora_app, kora_readonly;
GRANT SELECT ON mv_plataforma_visao TO kora_platform;
SET ROLE kora_migrator;

-- Primeira carga + agendamento DEVEM rodar como kora_platform (enxerga cross-tenant):
--   -- conectado como kora_platform:
--   REFRESH MATERIALIZED VIEW mv_plataforma_visao;                 -- 1ª vez (NO DATA -> sem CONCURRENTLY)
--   SELECT cron.schedule_in_database('refresh-mv-plataforma','*/10 * * * *',
--     $$REFRESH MATERIALIZED VIEW CONCURRENTLY mv_plataforma_visao$$, 'kora_db', 'kora_platform');

-- =============================================================================
-- MANUTENÇÃO: expurgo de sessões e retenção de partições
-- =============================================================================
-- Expurgo de sessões expiradas/revogadas antigas (sessoes não é particionada).
CREATE OR REPLACE FUNCTION app.expurgar_sessoes() RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE v_n bigint;
BEGIN
  DELETE FROM sessoes
   WHERE (expira_em < now() - interval '7 days')
      OR (revogada_em IS NOT NULL AND revogada_em < now() - interval '7 days');
  GET DIAGNOSTICS v_n = ROW_COUNT;
  RETURN v_n;
END;
$$;
-- SELECT cron.schedule('expurgo-sessoes','0 4 * * *', $$SELECT app.expurgar_sessoes()$$);

-- Retenção: DETACH + DROP de partições antigas (O(1)). Ajuste a janela legal
-- (auditoria fiscal costuma exigir 5+ anos -> NÃO dropar auditoria cedo).
CREATE OR REPLACE FUNCTION app.aplicar_retencao_mensal(p_tabela regclass, p_meses_reter int)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
  r record; v_limite date := date_trunc('month', now() - (p_meses_reter || ' month')::interval)::date;
BEGIN
  FOR r IN
    SELECT c.oid::regclass AS parti, pg_get_expr(c.relpartbound, c.oid) AS bound
    FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
    WHERE i.inhparent = p_tabela
  LOOP
    -- Extrai o limite superior "TO ('YYYY-MM-DD')" e compara com a janela.
    IF (substring(r.bound FROM 'TO \(''([0-9-]+)''\)'))::date <= v_limite THEN
      EXECUTE format('ALTER TABLE %s DETACH PARTITION %s', p_tabela, r.parti);
      EXECUTE format('DROP TABLE %s', r.parti);
    END IF;
  END LOOP;
END;
$$;
COMMENT ON FUNCTION app.aplicar_retencao_mensal(regclass,int) IS 'DETACH+DROP de partições mensais além da janela de retenção. NÃO usar em auditoria fiscal sem base legal.';
-- Exemplo (tentativas_login: 12 meses bastam):
-- SELECT cron.schedule('retencao-tentativas','30 4 1 * *',
--   $$SELECT app.aplicar_retencao_mensal('tentativas_login', 12)$$);

RESET ROLE;
