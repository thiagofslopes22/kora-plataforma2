-- =============================================================================
-- SEED 02 - Exercicios e competencias (calendario fiscal, referencia global)
--
-- PRAZOS: aplicada a regra geral da LRF, nao um calendario proprio do TCE-MA:
--   - RREO  (LRF art. 52): ate 30 dias apos o fim de cada BIMESTRE
--   - RGF   (LRF art. 55 §2): ate 30 dias apos o fim de cada QUADRIMESTRE
--            (municipios < 50 mil hab. podem optar pelo SEMESTRE, art. 63)
--   - PCA/anual: prazo referencial 31/03 do exercicio seguinte
--
-- >>> CONFERIR com a resolucao vigente do TCE-MA antes de usar os prazos para
--     disparar alertas ao cliente. A data em `prazo_entrega` e facilmente
--     corrigivel com UPDATE sem mexer no schema.
--
-- Idempotente: ON CONFLICT sobre ux_competencias_periodo.
-- =============================================================================
SET ROLE kora_migrator;

-- Exercicios cobertos: 2023..2028 (retroativo p/ historico + futuro proximo).
INSERT INTO exercicios (ano, aberto)
SELECT ano, ano >= EXTRACT(YEAR FROM now())::smallint
FROM generate_series(2023, 2028) AS ano
ON CONFLICT (ano) DO NOTHING;

-- ---------------------------------------------------------------------------
-- BIMESTRAL (RREO) - 6 por exercicio
-- ---------------------------------------------------------------------------
INSERT INTO competencias (exercicio, tipo_periodo, numero, data_inicio, data_fim, prazo_entrega)
SELECT
  e.ano,
  'bimestral'::tipo_periodo,
  n::smallint,
  make_date(e.ano, (2 * n - 1), 1),
  (make_date(e.ano, (2 * n - 1), 1) + INTERVAL '2 months - 1 day')::date,
  (make_date(e.ano, (2 * n - 1), 1) + INTERVAL '2 months - 1 day' + INTERVAL '30 days')::date
FROM (SELECT ano::int FROM generate_series(2023, 2028) AS ano) e
CROSS JOIN generate_series(1, 6) AS n
ON CONFLICT (exercicio, tipo_periodo, numero) DO NOTHING;

-- ---------------------------------------------------------------------------
-- QUADRIMESTRAL (RGF) - 3 por exercicio
-- ---------------------------------------------------------------------------
INSERT INTO competencias (exercicio, tipo_periodo, numero, data_inicio, data_fim, prazo_entrega)
SELECT
  e.ano,
  'quadrimestral'::tipo_periodo,
  n::smallint,
  make_date(e.ano, (4 * n - 3), 1),
  (make_date(e.ano, (4 * n - 3), 1) + INTERVAL '4 months - 1 day')::date,
  (make_date(e.ano, (4 * n - 3), 1) + INTERVAL '4 months - 1 day' + INTERVAL '30 days')::date
FROM (SELECT ano::int FROM generate_series(2023, 2028) AS ano) e
CROSS JOIN generate_series(1, 3) AS n
ON CONFLICT (exercicio, tipo_periodo, numero) DO NOTHING;

-- ---------------------------------------------------------------------------
-- SEMESTRAL (RGF de municipio pequeno, LRF art. 63) - 2 por exercicio
-- ---------------------------------------------------------------------------
INSERT INTO competencias (exercicio, tipo_periodo, numero, data_inicio, data_fim, prazo_entrega)
SELECT
  e.ano,
  'semestral'::tipo_periodo,
  n::smallint,
  make_date(e.ano, (6 * n - 5), 1),
  (make_date(e.ano, (6 * n - 5), 1) + INTERVAL '6 months - 1 day')::date,
  (make_date(e.ano, (6 * n - 5), 1) + INTERVAL '6 months - 1 day' + INTERVAL '30 days')::date
FROM (SELECT ano::int FROM generate_series(2023, 2028) AS ano) e
CROSS JOIN generate_series(1, 2) AS n
ON CONFLICT (exercicio, tipo_periodo, numero) DO NOTHING;

-- ---------------------------------------------------------------------------
-- MENSAL (balancetes / remessa mensal) - 12 por exercicio
-- ---------------------------------------------------------------------------
INSERT INTO competencias (exercicio, tipo_periodo, numero, data_inicio, data_fim, prazo_entrega)
SELECT
  e.ano,
  'mensal'::tipo_periodo,
  n::smallint,
  make_date(e.ano, n, 1),
  (make_date(e.ano, n, 1) + INTERVAL '1 month - 1 day')::date,
  (make_date(e.ano, n, 1) + INTERVAL '1 month - 1 day' + INTERVAL '30 days')::date
FROM (SELECT ano::int FROM generate_series(2023, 2028) AS ano) e
CROSS JOIN generate_series(1, 12) AS n
ON CONFLICT (exercicio, tipo_periodo, numero) DO NOTHING;

-- ---------------------------------------------------------------------------
-- ANUAL (prestacao de contas anual) - 1 por exercicio, prazo 31/03 do seguinte
-- ---------------------------------------------------------------------------
INSERT INTO competencias (exercicio, tipo_periodo, numero, data_inicio, data_fim, prazo_entrega)
SELECT
  e.ano,
  'anual'::tipo_periodo,
  1::smallint,
  make_date(e.ano, 1, 1),
  make_date(e.ano, 12, 31),
  make_date(e.ano + 1, 3, 31)
FROM (SELECT ano::int FROM generate_series(2023, 2028) AS ano) e
ON CONFLICT (exercicio, tipo_periodo, numero) DO NOTHING;

RESET ROLE;
