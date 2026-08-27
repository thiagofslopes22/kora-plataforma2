# Deploy no Railway — banco multi-tenant

Passo a passo do que precisa existir para o sistema rodar com **vários escritórios
de contabilidade** no Railway. O schema já foi validado localmente contra
PostgreSQL 16.4 (aplica limpo, 26/26 nos testes de isolamento pela API).

---

## 1. Antes de tudo: duas ressalvas sobre o Railway

**Região.** O Railway não tem região no Brasil (as mais próximas são US-East/US-West).
O projeto do banco tinha sido pensado para **Supabase São Paulo** justamente por
LGPD e latência. Nada disso impede o deploy — o schema ficou portável e roda nos
dois —, mas vale decidir conscientemente:

- *Latência*: cada request do escritório vai e volta para os EUA (~120–180 ms a mais).
- *LGPD*: dados de prestação de contas municipal saindo do país exigem base legal e
  transparência no contrato com os escritórios. É uma decisão de negócio, não técnica.

**Armazenamento de arquivos.** O Railway não tem storage de objetos. Hoje os PDFs
e planilhas ficam em `tempfile.mkdtemp()` e são servidos via `/download/{job_id}`
a partir de um dicionário em memória. Isso **não sobrevive a um restart nem escala
para 2 instâncias**, e no Railway restarts são rotina (todo deploy é um). Antes de
faturar isso como produto, ligue um bucket S3-compatível (Cloudflare R2, Backblaze
B2 ou o próprio Supabase Storage) — a tabela `documentos` já foi modelada para
guardar `storage_bucket` + `storage_key` + `hash_sha256`.

---

## 2. Serviços no projeto Railway

| Serviço | O que é | Observação |
|---|---|---|
| `Postgres` | plugin oficial do Railway | PG 16+; dá superusuário, então o `00` roda inteiro |
| `conciliador` | `backend-conciliador/Dockerfile` | **Root Directory `/`** (contexto = raiz do repo) |
| `auditor` | `backend-auditor/Dockerfile` | idem, quando for ligado ao banco |
| `frontend` | build estático do Vite | aponta para as URLs públicas dos backends |

> O Root Directory precisa ser a raiz porque os backends importam `kora_db/`,
> que é compartilhado entre eles.

---

## 3. Variáveis de ambiente

### Gerar os segredos (uma vez)

```bash
openssl rand -base64 24   # KORA_APP_PASSWORD
openssl rand -base64 24   # KORA_PLATFORM_PASSWORD
openssl rand -base64 24   # KORA_READONLY_PASSWORD
openssl rand -base64 48   # KORA_JWT_SECRET
```

### No serviço `conciliador` (e depois no `auditor`)

```
DATABASE_URL           = ${{Postgres.DATABASE_URL}}
KORA_APP_PASSWORD      = <o gerado>
KORA_PLATFORM_PASSWORD = <o gerado>
KORA_READONLY_PASSWORD = <o gerado>
KORA_JWT_SECRET        = <o gerado>
KORA_CORS_ORIGINS      = https://seu-frontend.up.railway.app
KORA_TOKEN_HORAS       = 12
```

`DATABASE_URL` é usada **só para descobrir host/porta/banco**. No caminho de
request os backends reconectam como `kora_app` (ou `kora_platform`), que não têm
BYPASSRLS — é isso que garante o isolamento mesmo com bug na aplicação.

---

## 4. Migração e bootstrap

Rode uma vez, do seu terminal, com a `DATABASE_URL` **pública** do Postgres do
Railway (Settings → Networking → Public Network):

```bash
export DATABASE_URL='postgresql://postgres:...@...proxy.rlwy.net:PORTA/railway'
export KORA_APP_PASSWORD=...  KORA_PLATFORM_PASSWORD=...  KORA_READONLY_PASSWORD=...

python db/migrate.py --seed        # schema + 217 municípios do MA + calendário fiscal
python db/migrate.py --status      # confere o que foi aplicado
```

O runner é idempotente: registra cada arquivo em `kora_schema_migrations` e não
reaplica. As senhas dos papéis são ressincronizadas a cada execução, então
**rotacionar senha = trocar a env e rodar de novo**.

Depois, o primeiro super-admin:

```bash
export KORA_ADMIN_EMAIL='voce@dominio.com'
export KORA_ADMIN_SENHA='...'          # mínimo 12 caracteres
export KORA_ADMIN_NOME='Seu Nome'
python db/bootstrap.py
```

---

## 5. Cadastrando um escritório de contabilidade

```bash
# 1) autentica como super-admin
TOKEN=$(curl -s -X POST https://SEU-CONCILIADOR/plataforma/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"voce@dominio.com","senha":"..."}' | jq -r .access_token)

# 2) cria o escritório JÁ com o admin dele (os dois nascem juntos:
#    escritório sem admin é um tenant órfão, ninguém consegue entrar)
curl -X POST https://SEU-CONCILIADOR/plataforma/escritorios \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
        "razao_social": "Contabilidade Exemplo LTDA",
        "cnpj": "12345678000190",
        "plano": "essencial",
        "max_usuarios": 10,
        "max_municipios": 15,
        "admin_nome": "Fulano de Tal",
        "admin_email": "fulano@exemplo.com.br",
        "admin_senha": "uma-senha-forte"
      }'
```

A partir daí o admin do escritório loga em `/auth/login` e gerencia sozinho os
próprios usuários, entidades e municípios — sem nunca enxergar outro escritório.

Outras rotas do backoffice: `GET /plataforma/escritorios`,
`PATCH /plataforma/escritorios/{id}/suspender`, `.../reativar`.

---

## 6. Como o isolamento é garantido

Três camadas independentes, em ordem de importância:

1. **RLS no Postgres** — toda tabela de tenant tem política ligada e, na maioria,
   `FORCE RLS` (nem o dono escapa). Sem `app.current_tenant` no contexto, nenhuma
   linha casa: falha fechado.
2. **Papel de conexão separado** — acesso cross-tenant exige conectar como
   `kora_platform`. Não é um GUC que o backend de tenant possa setar; ele nem
   conecta com esse papel.
3. **Autoridade lida do banco** — `app.eh_admin_escritorio()` consulta a tabela
   `usuarios`. O token diz apenas *quem* é o usuário, nunca *o que* ele pode.
   Token forjado com papel elevado não amplia o que a RLS entrega.

Nenhum papel (`kora_app`, `kora_platform`, `kora_readonly`, `kora_migrator`)
tem `BYPASSRLS`.

---

## 7. Manutenção recorrente

As partições (auditoria/envios/tentativas_login por mês; itens/inconsistências
por ano) **não se criam sozinhas** — sem `pg_cron` no Railway, agende fora:

```sql
-- as funções recebem a TABELA particionada e quantos períodos criar à frente
SELECT app.criar_particoes_mensais('auditoria',        3);
SELECT app.criar_particoes_mensais('envios',           3);
SELECT app.criar_particoes_mensais('tentativas_login', 3);
SELECT app.criar_particoes_anuais ('itens_prestacao',  1);
SELECT app.criar_particoes_anuais ('inconsistencias',  1);
```

Um cron mensal (Railway Cron ou GitHub Actions) resolve. Se faltar partição, o
INSERT falha — vale monitorar.
