# KORA-PLATAFORMA — Esquema de Banco (PostgreSQL 16+)

SaaS multi-tenant de compliance fiscal municipal (TCE-MA). Este diretório contém
o **projeto completo do banco**: DDL, índices, RLS, papéis, triggers, particionamento,
agregados, queries críticas e configuração.

> **Um sistema, dois backends** (nasceram separados, mas são o mesmo produto):
> **conciliador** (`:8001`, `/conc`, com auth — usuários/municípios/conciliações
> RGF-RREO, com histórico persistido) e **auditor** (`:8000`, `/api`, sem auth e
> hoje *stateless* — 13 anexos → 27 quadros → Excel → RIT com IA). Os arquivos
> `02`–`09` modelam o núcleo (mais próximo do conciliador) e o `10` costura o
> auditor, unificando os achados dos dois na tabela `inconsistencias`.

Prioridade de projeto (nesta ordem): **isolamento correto > leitura > escrita > elegância.**

## Ordem de execução

| # | Arquivo | Conteúdo |
|---|---------|----------|
| 00 | `00_papeis_extensoes.sql` | Extensões, papéis (roles) e GRANTs base |
| 01 | `01_tipos_funcoes.sql` | ENUMs, domínios, funções de contexto/RLS, UUIDv7 |
| 02 | `02_referencia.sql` | Tabelas de referência globais (municípios, competências, regras) |
| 03 | `03_tenant_dominio.sql` | Escritórios, usuários, entidades, prestações, documentos, validações |
| 04 | `04_seguranca_auth.sql` | Sessões, convites, tentativas de login, credenciais TCE, login |
| 05 | `05_particionamento.sql` | Auditoria, envios, itens, inconsistências + manutenção de partições |
| 06 | `06_triggers.sql` | `atualizado_em`, tenant imutável, auditoria, contadores |
| 07 | `07_rls.sql` | Políticas RLS por tabela e papel |
| 08 | `08_agregados_views.sql` | View do tenant, MV da plataforma, expurgo/retenção |
| 09 | `09_queries_criticas.sql` | 10 queries com plano esperado |
| 10 | `10_auditor.sql` | Integração do backend-auditor (13 anexos, quadros Q1–Q27, RIT, inconformidades) |
| 11 | `11_municipios_personalizados.sql` | Jurisdições fora do IBGE (órgão estadual, consórcio) criadas pelo tenant em `municipios` |

Aplique com `kora_migrator` como dono (os arquivos já fazem `SET ROLE kora_migrator`).
`CREATE INDEX CONCURRENTLY` deve rodar FORA de transação em produção (ver Migração).

> **Validado end-to-end** contra PostgreSQL **16.4**: os arquivos `00`–`08` e `10`
> aplicam sem erro (39 tabelas, 18 com RLS, 27 políticas, 17 enums, 168 índices,
> 86 partições). Bateria de testes de isolamento passou **10/10**: isolamento
> entre tenants, escopo de município do funcionário, acesso da plataforma,
> ausência de vazamento cross-tenant, `escritorio_id` imutável (trigger),
> fail-closed sem contexto, e contador por trigger. (`09` são queries de exemplo,
> não schema — rodam com o contexto de tenant setado.)

---

## 1. Diagrama textual (entidades, relacionamentos, cardinalidade)

```
                        ┌─────────────────────┐
                        │  plataforma_admins  │  (SUPER_ADMIN — fora do tenant)
                        └──────────┬──────────┘
                        libera/suspende │ 1..N
                                   ▼
  REFERÊNCIA GLOBAL          ┌──────────────┐
  (sem tenant, sem RLS)      │ escritorios  │  1  (TENANT raiz; id = escritorio_id)
  ┌────────────┐             └──────┬───────┘
  │ municipios │◄───────┐           │ 1
  └────────────┘        │           ├───────────────┬────────────────┬───────────────┐
  ┌────────────┐        │           │ N             │ N              │ N             │ N
  │ exercicios │        │           ▼               ▼                ▼               ▼
  └─────┬──────┘        │      ┌──────────┐   ┌────────────┐   ┌───────────┐   ┌──────────┐
        │ 1..N          │      │ usuarios │   │ entidades  │   │ convites  │   │ sessoes  │
        ▼               │      └────┬─────┘   └─────┬──────┘   └───────────┘   └──────────┘
  ┌──────────────┐      │        N │ │ N            │ 1
  │ competencias │      │          │ └──────┐       │
  └──────┬───────┘      │          ▼        │       │ 1..N
         │ 1..N         │  ┌──────────────────┐     ▼
         │              └──┤usuarios_municipios│  ┌────────────────────┐
         ▼                 │ (funcionário↔mun) │  │ prestacoes_contas  │◄── competencias
  ┌───────────────┐        └──────────────────┘  └─────────┬──────────┘
  │regras_validacao│  (aplica-se em)                        │ 1
  └───────────────┘                          ┌──────────────┼───────────────┬──────────────┐
                                              │ N            │ N             │ N            │ N
                                              ▼              ▼               ▼              ▼
                                        ┌───────────┐  ┌──────────┐   ┌────────────┐  ┌──────────────┐
                                        │documentos │  │validacoes│   │itens_prest.│  │    envios    │
                                        └───────────┘  └────┬─────┘   └─────┬──────┘  └──────────────┘
                                                            │ 1            │ (item_id)
                                                            ▼              │
                                                     ┌──────────────┐◄─────┘
                                                     │inconsistencias│
                                                     └──────────────┘

  TRANSVERSAIS (tenant-scoped): credenciais_tce, prestacao_contadores, auditoria
  PRE-TENANT (sem RLS de tenant): tentativas_login
  PARTICIONADAS: auditoria/envios/tentativas_login (mês) · itens/inconsistencias (ano)
```

**Cardinalidades-chave**
- `escritorios (1) → (N) usuarios | entidades | prestacoes_contas | …` — tudo pendura no tenant.
- `municipios (1) → (N) entidades` (referência global 1:N tenant-scoped).
- `usuarios (N) ↔ (N) municipios` via `usuarios_municipios` (3º nível de acesso do funcionário).
- `entidades (1) → (N) prestacoes_contas → (N) {documentos, itens, validacoes, envios}`.
- `validacoes (1) → (N) inconsistencias`.
- `plataforma_admins (1) → (N) escritorios` (liberou/suspendeu).

---

## 2. Hierarquia de acesso e como a RLS a garante

| Nível | Papel de conexão | Enxerga | Mecanismo |
|-------|------------------|---------|-----------|
| SUPER_ADMIN | `kora_platform` | tudo (cross-tenant) | `app.eh_plataforma()` = `pg_has_role(current_user,'kora_platform')` nas políticas |
| ADMIN_ESCRITORIO | `kora_app` + GUCs | só o **seu** escritório | `escritorio_id = app.tenant_atual()` + `app.eh_admin_escritorio()` |
| FUNCIONARIO | `kora_app` + GUCs | só **municípios atribuídos** | `municipio_id = ANY(app.municipios_do_usuario())` |

Pontos que impedem vazamento **mesmo com bug na aplicação**:
1. **RLS + FORCE RLS** na maioria das tabelas de tenant — nem o dono escapa.
   Exceção: `usuarios`, `usuarios_municipios` e `escritorios` ficam só com `ENABLE`
   (sem `FORCE`), para *owner-exemption* dos helpers `SECURITY DEFINER` sem precisar
   de `BYPASSRLS` (portável a Postgres gerenciado como Supabase). O app (`kora_app`)
   nunca é dono → segue 100% isolado por RLS também nessas 3 tabelas.
2. A app conecta com **`kora_app` sem BYPASSRLS**. O acesso cross-tenant exige
   conectar como **`kora_platform`** (pool separado) — não é um GUC que a app de
   tenant possa setar. Um bug no backend de tenant não vira acesso global.
3. **Autoridade derivada do banco**, não de GUC: `app.eh_admin_escritorio()` lê a
   tabela `usuarios`. A app só informa *quem é* (`app.current_user_id`), não *o que
   pode*. Assim um GUC forjado não escala privilégio.
4. **Fail-closed**: sem `app.current_tenant`, `app.tenant_atual()` = NULL e nenhuma
   linha casa.
5. `escritorio_id` **NOT NULL e imutável** (trigger) — linha não migra de tenant.
6. `municipios` deixou de ser referência 100% somente-leitura (ver `11`): o tenant
   pode criar **jurisdições próprias** (órgão estadual, consórcio — o que não está
   no IBGE). Elas nascem com `escritorio_id` preenchido e a RLS da tabela só as
   mostra ao escritório que as criou; as linhas do IBGE (`escritorio_id IS NULL`)
   seguem globais e sem escrita pelo tenant.

O login pré-tenant e os helpers de contexto são `SECURITY DEFINER` **donos de
`kora_migrator`** e usam *owner-exemption* (as 3 tabelas de autoridade sem `FORCE`).
**Nenhum papel usa `BYPASSRLS`** — o schema roda em Postgres gerenciado (Supabase)
sem superusuário. `EXECUTE` de `app.autenticar()` é só para `kora_app`.

---

## 3. Onde eu DISCORDO do enunciado (e por quê)

1. **"LIST/HASH por tenant" para tabelas grandes → prefira RANGE por tempo/exercício.**
   Partição por tenant gera partições desiguais, exige DDL a cada onboarding e não
   agrega isolamento (a RLS já isola). A alavanca real é retenção/arquivamento, que
   é temporal. Uso RANGE por mês (auditoria/envios) e por ano (itens/inconsistências),
   com `escritorio_id` liderando os **índices** dentro da partição. Detalhes em `05`.

2. **"tenant_id como 1ª coluna de TODO índice" — verdadeiro para índices tenant-scoped,
   com exceções necessárias.** Login por e-mail (`ux_usuarios_email`), resolução de
   ULID público, dedup por hash *podem* liderar por tenant, mas **login é pré-tenant**
   e precisa ser global; idem tabelas de **referência** (município/regra) e
   `tentativas_login`. Essas exceções estão marcadas e justificadas.

3. **Materialized view para dashboard do tenant → não.** MV não suporta RLS; seria um
   vetor de vazamento. Dashboard do tenant sai de **view `security_barrier` + contadores
   por trigger** (tempo-real, RLS aplicada). MV fica só para analytics **cross-tenant do
   SUPER_ADMIN** (sem RLS, GRANT exclusivo). Ver `08`.

4. **Argon2id para tokens de sessão/refresh/convite → desnecessário.** Argon2id é para
   **senhas** (baixa entropia). Tokens são aleatórios de ≥256 bits: **SHA-256** é
   correto e evita a latência do Argon2 no caminho quente. Senhas: Argon2id. Tokens: SHA-256.

5. **Credenciais do TCE: envelope encryption (KMS), não pgcrypto.** pgcrypto coloca a
   gestão de chave dentro do SQL (chave vaza em parâmetros/logs/planos). Uso **DEK por
   segredo + AES-256-GCM na app + DEK embrulhado por KMS**; o Postgres nunca vê a
   chave-mestra. TDE/disco protege mídia roubada, não um papel de banco comprometido.

6. **Rate limiting de caminho quente é melhor no Redis.** Mantive `tentativas_login`
   para **lockout persistente e auditoria de segurança**, mas a contagem por
   janela/segundo em produção deve ser feita em cache, não em cada login batendo no OLTP.

7. **ENUM nativo com parcimônia.** Ótimo para domínios estáveis e aditivos (severidade,
   papel, tipos fiscais). Para "status" que muda por regra de negócio frequente, uma
   tabela de lookup é mais flexível (ENUM não remove/reordena valor sem dor). Os status
   aqui são de ciclo de vida bem definido → ENUM.

---

## 4. Técnicas de performance aplicadas (mapa)

| Técnica | Onde |
|---------|------|
| Índice composto igualdade→range→sort, `escritorio_id` na frente | `ix_prestacoes_pendentes (escritorio_id,status,prazo)` |
| Índice **parcial** (ativos/pendentes) | `ix_prestacoes_pendentes … WHERE status IN(...) AND deleted_at IS NULL`, `ix_incons_prestacao_abertas … WHERE status='aberta'` |
| Índice de **cobertura** (INCLUDE) | `ix_usuarios_tenant_ativos`, `ix_prestacoes_pendentes`, `ix_entidades_tenant_municipio` |
| **Particionamento** RANGE tempo/ano | `auditoria`,`envios`,`tentativas_login` (mês); `itens_prestacao`,`inconsistencias` (ano) |
| **BRIN** em append-only temporal | `brin_auditoria_ocorrido` |
| **GIN + pg_trgm** (busca textual) | `gin_entidades_nome`, `gin_documentos_nome`, `gin_municipios_nome` (btree_gin p/ poda por tenant) |
| **JSONB + GIN jsonb_path_ops** | `payload_tce`/`resposta_tce`, `dados_extras`, `dados_depois` |
| **Materialized view** (REFRESH CONCURRENTLY) | `mv_plataforma_visao` (só SUPER_ADMIN) |
| **Contador por trigger** (sem COUNT(*)) | `prestacao_contadores` via `trg_contar_inconsistencias` |
| Tipos enxutos | `BIGINT` PK, `SMALLINT` exercício, `TIMESTAMPTZ`, ENUMs 4B, `UUIDv7` público |
| FK sempre indexada do lado filho | `ix_*_fk_*` em todas as FKs |

> `btree_gin` permite `USING gin (escritorio_id, nome_normalizado gin_trgm_ops)`: o
> `escritorio_id` entra **no índice GIN**, podando por tenant antes do trigram — em vez
> de um Bitmap AND separado. `jsonb_path_ops` é menor/mais rápido para `@>` (containment);
> se precisar de existência de chave (`?`), use `jsonb_ops` (padrão) naquela coluna.

---

## 5. Connection pooling (PgBouncer transaction mode)

- **Modo `transaction`**: a conexão de servidor é devolvida ao pool **ao fim de cada
  transação**. Por isso o isolamento usa **`SET LOCAL` / `set_config(...,true)`** (escopo
  de transação) — nunca `SET` de sessão, que vazaria contexto entre tenants na mesma
  conexão física.
- Setar `app.current_tenant`/`app.current_user_id` como **primeiras instruções de cada
  transação**. Toda unidade de trabalho deve ser uma transação explícita (mesmo leituras).
- **Prepared statements**: em transaction mode exigem PgBouncer **≥ 1.21** com
  `max_prepared_statements > 0`; caso contrário, desabilite server-side prepared no driver
  (ex.: asyncpg `statement_cache_size=0`, ou usar prepared em nível de protocolo suportado).
- Não usar `SET SESSION AUTHORIZATION`, `LISTEN/NOTIFY`, cursores WITH HOLD, temp tables
  de sessão, advisory locks de sessão — nada que dependa de estado além da transação.
- Pools **separados por papel**: `kora_app` (tenant) e `kora_platform` (backoffice), para
  que `current_user` de fato distinga plataforma nas políticas RLS.

---

## 6. Checklist `postgresql.conf` (OLTP multi-tenant, muitas partições)

```conf
# --- Memória
shared_buffers = 25% da RAM                 # ex.: 8GB em host de 32GB
effective_cache_size = 60-75% da RAM        # dica ao planner
work_mem = 16MB                             # POR nó de ordenação/hash; conservador (PgBouncer multiplica backends)
maintenance_work_mem = 1GB                  # CREATE INDEX / VACUUM mais rápidos
hash_mem_multiplier = 2.0

# --- Conexões (PgBouncer faz o fan-out)
max_connections = 150                       # baixo; o pool absorve o resto
superuser_reserved_connections = 5

# --- Disco/SSD
random_page_cost = 1.1
effective_io_concurrency = 200
maintenance_io_concurrency = 200

# --- WAL / checkpoint
wal_compression = zstd
wal_buffers = 64MB
max_wal_size = 16GB
min_wal_size = 2GB
checkpoint_completion_target = 0.9
checkpoint_timeout = 15min

# --- Planejamento com partições
enable_partitionwise_join = on
enable_partitionwise_aggregate = on
max_locks_per_transaction = 256             # muitas partições => mais locks por txn
default_statistics_target = 200             # colunas assimétricas: suba p/ 500 em status/severidade
jit = off                                   # OLTP de baixa latência: JIT costuma atrapalhar

# --- Autovacuum (mais agressivo nas tabelas quentes)
autovacuum = on
autovacuum_max_workers = 6
autovacuum_naptime = 15s
autovacuum_vacuum_scale_factor = 0.05       # global; e por-tabela abaixo
autovacuum_vacuum_insert_scale_factor = 0.02
# Por tabela quente (aplicado no DDL via ALTER TABLE ... SET):
#   inconsistencias, prestacoes_contas, prestacao_contadores, sessoes:
#   autovacuum_vacuum_scale_factor=0.02, autovacuum_analyze_scale_factor=0.02
#   auditoria/envios/itens (append): autovacuum_vacuum_insert_scale_factor=0.01

# --- Observabilidade / segurança
shared_preload_libraries = 'pg_stat_statements,pg_cron,pgaudit'
track_io_timing = on
log_min_duration_statement = 500ms
log_lock_waits = on
pgaudit.log = 'ddl, role, write'            # complementa a tabela de auditoria de dados
password_encryption = scram-sha-256
huge_pages = try
```

Sugestão de `ALTER TABLE` para autovacuum por tabela (aplicar após o `03`/`05`):
```sql
ALTER TABLE inconsistencias      SET (autovacuum_vacuum_scale_factor=0.02, autovacuum_analyze_scale_factor=0.02);
ALTER TABLE prestacoes_contas    SET (autovacuum_vacuum_scale_factor=0.02, autovacuum_analyze_scale_factor=0.02);
ALTER TABLE prestacao_contadores SET (autovacuum_vacuum_scale_factor=0.02);
ALTER TABLE sessoes              SET (autovacuum_vacuum_scale_factor=0.02);
ALTER TABLE auditoria            SET (autovacuum_vacuum_insert_scale_factor=0.01);
ALTER TABLE envios               SET (autovacuum_vacuum_insert_scale_factor=0.01);
ALTER TABLE itens_prestacao      SET (autovacuum_vacuum_insert_scale_factor=0.01);
```

---

## 7. Estratégia de migração / versionamento

- **Ferramenta**: manter **Alembic** (já usado no `backend-conciliador`), porém em Postgres
  e com estes arquivos SQL versionados como a fonte de verdade do schema base. Cada mudança
  vira uma revisão idempotente e reversível quando possível.
- **Papéis de migração**: DDL roda como **`kora_migrator`** (dono). `kora_app` nunca executa DDL.
  Com `FORCE RLS`, backfills massivos usam janela de manutenção (superusuário) ou uma função
  de manutenção que assume `kora_platform`.
- **Zero-downtime (expand/contract)**:
  1. *Expand* — adicionar coluna/tabela/índice novo (compatível), `NOT NULL` só com `DEFAULT`
     ou em duas fases; `CREATE INDEX CONCURRENTLY` **fora de transação**.
  2. *Migrate* — backfill em lotes; a app passa a escrever nos dois formatos.
  3. *Contract* — remover o antigo depois que nada mais o usa.
- **RLS em migração**: ao criar tabela tenant-scoped, **sempre** no mesmo release: `ENABLE`+`FORCE
  RLS`, políticas e GRANTs. Um teste de CI deve **falhar** se existir tabela com `escritorio_id`
  sem RLS habilitada (query em `pg_class.relrowsecurity`).
- **Partições**: criadas à frente por `pg_cron` (ou `pg_partman`); a migração inclui o
  bootstrap (`app.criar_particoes_*`). Retenção por `DETACH`+`DROP` (respeitando prazo legal
  fiscal — não dropar auditoria cedo).
- **Do protótipo atual** (`backend-conciliador`): `prefeituras → entidades`, `usuarios` ganha
  `escritorio_id`/`papel`, `conciliacoes → prestacoes_contas` (+ `validacoes`), tudo sob um
  `escritorio_id` de backfill. Migração de dados feita sob `kora_platform`.

---

## 8. Papéis e resumo de privilégios

| Papel | LOGIN | BYPASSRLS | Uso |
|-------|-------|-----------|-----|
| `kora_migrator` | não | não | Dono dos objetos, DDL, migrações; owner das funções SECURITY DEFINER de contexto/login |
| `kora_app` | sim | não | Aplicação de tenant (RLS + GUCs) |
| `kora_platform` | sim | não | Backoffice SUPER_ADMIN (cross-tenant via política) |
| `kora_readonly` | sim | não | BI/suporte (RLS aplica; sem credenciais_tce) |

Nenhum papel usa `BYPASSRLS` (portável a Supabase). No Supabase, conceda ao papel
que roda a migração (`postgres`) membership em `kora_migrator`/`kora_platform` —
o `00` já faz isso via `GRANT ... TO current_user`.

Troque todas as senhas `TROQUE_EM_PRODUCAO_*` e prefira `scram-sha-256` + certificados/mTLS
entre app e banco.
