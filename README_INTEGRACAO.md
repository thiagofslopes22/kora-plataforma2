# Kora — Plataforma Unificada

Este repositório junta, **lado a lado e sem alterar nenhuma lógica**, os dois sistemas:

| Parte | Origem | O que faz |
|-------|--------|-----------|
| `frontend/` | `rgf-conciliador/frontend` | Interface React (Vite) — login, home, conciliação RGF e RREO, admin. **É a UI unificada** (vamos adicionar aqui as telas do auditor). |
| `backend-conciliador/` | `rgf-conciliador/backend` | Conciliação RGF/MSC e RREO (rascunho × homologado) + login (JWT) + banco de dados + prefeituras/usuários. Já roda no Railway. |
| `backend-auditor/` | `auditor_tce6/kora` | Motor de auditoria: extrai anexos de balanço (PDF) → gera Excel nos templates → lê o Excel preenchido → gera o relatório **RIT**. |

> As pastas originais (`auditor_tce6`, `rgf-conciliador`) **não foram tocadas** — continuam como backup intacto.
> Foram excluídas da cópia apenas pastas regeneráveis: `venv`, `.venv`, `node_modules`, `__pycache__`, `.pytest_cache`, `dist`, `.git`. Elas voltam com `pip install` / `npm install`.

---

## Como rodar tudo localmente (3 terminais)

### Terminal 1 — Backend Conciliador (porta 8001)
```powershell
cd backend-conciliador
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8001
```
Sobe em http://localhost:8001 . Usa SQLite local (`kora.db`) por padrão.

### Terminal 2 — Backend Auditor (porta 8000)
```powershell
cd backend-auditor
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Precisa da chave da Anthropic no arquivo .env (já veio copiado; confira se está válida)
python -m uvicorn backend.main:app --reload --port 8000
```
Sobe em http://localhost:8000 (docs em http://localhost:8000/docs).
> Observação: o auditor usa `camelot-py` + `ghostscript` (dependência de sistema). Se falhar leitura de PDF, instale o Ghostscript no Windows.

### Terminal 3 — Frontend (porta 5173)
```powershell
cd frontend
npm install
npm run dev
```
Abre em http://localhost:5173 .

---

## Mapa de portas

| Serviço | Porta local |
|---------|-------------|
| Frontend (Vite) | 5173 |
| Backend Auditor | 8000 |
| Backend Conciliador | 8001 |

Os dois backends vinham configurados para a porta **8000** — por isso o conciliador roda em **8001** aqui. Isso é só o parâmetro `--port` do comando; nenhum código foi alterado.

---

## Como os dois se conectam (o que falta wire — trabalho de frontend)

Hoje o frontend fala com **um** backend só. Em `frontend/src/lib/api.js` existe:
```js
const BASE = 'https://rgf-production.up.railway.app'   // aponta para o conciliador
```

Para a plataforma unificada, o frontend precisa falar com **os dois** backends. Sugestão (a fazer, sem mexer na lógica existente):

1. Criar um segundo cliente de API para o auditor, ex. `frontend/src/lib/apiAuditor.js`, com `BASE = 'http://localhost:8000'` (e a URL de produção do auditor quando existir).
2. Manter `api.js` como está (conciliador).
3. Adicionar as **novas páginas do auditor** em `frontend/src/pages/` (ex.: `AuditorUploadPage.jsx`, `AuditorRitPage.jsx`) seguindo o mesmo padrão das páginas de conciliação.
4. Registrar as rotas novas em `frontend/src/App.jsx` (ex.: `/auditor`, `/auditor/rit`) dentro de `<ProtectedRoute>`, e adicionar os links no `Sidebar.jsx`.

### Endpoints do auditor (backend-auditor) para o frontend consumir
- `GET  /api/health` — status
- `GET  /api/quadros` — lista os quadros/tabelas e o que cada um precisa
- (demais rotas de upload de anexos → geração de Excel → leitura do Excel → geração do RIT estão em `backend-auditor/backend/api/routes.py`)

### Endpoints do conciliador (backend-conciliador)
- Login/JWT, prefeituras, usuários e as rotas de conciliação RGF e RREO estão em `backend-conciliador/main.py`.

---

## Próximos passos sugeridos
1. Subir os 3 serviços e confirmar que cada um responde (health checks).
2. Desenhar as telas do auditor no frontend, reusando `UploadStep`, `ProcessingStep`, `ResultStep` que já existem para conciliação.
3. Decidir a autenticação do auditor: hoje ele **não tem login**. Opções: (a) proteger via o mesmo JWT do conciliador (colar depois), ou (b) deixar aberto no MVP.
4. Quando estiver estável, avaliar a **fusão real** num backend único (um login, um banco, um deploy) — hoje está lado a lado de propósito, para não mexer em código.
