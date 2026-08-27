# Backend Conciliador.
#
# IMPORTANTE: o contexto de build e a RAIZ DO REPOSITORIO, nao esta pasta —
# o backend importa `kora_db/`, que fica na raiz e e compartilhado com o
# backend-auditor. No Railway configure o servico assim:
#     Root Directory:  /            (a raiz do repo)
#     Dockerfile Path: backend-conciliador/Dockerfile
# Build local equivalente:
#     docker build -f backend-conciliador/Dockerfile -t kora-conciliador .

FROM python:3.11-slim

WORKDIR /app

# LibreOffice headless — necessário para converter .xls → .xlsx no Conciliador RREO
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-calc \
    && rm -rf /var/lib/apt/lists/*

COPY backend-conciliador/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# camada de dados compartilhada (pool kora_app + contexto de tenant p/ a RLS)
COPY kora_db/ /app/kora_db/
# schema + runner de migracao (permite rodar a migracao a partir do container)
COPY db/ /app/db/
COPY backend-conciliador/ /app/

# O codigo faz `sys.path.insert(parent)` para achar kora_db; no container o
# proprio /app ja e a raiz, entao kora_db resolve direto.
ENV PYTHONPATH=/app

EXPOSE 8000
# Railway injeta $PORT; localmente cai em 8000.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
