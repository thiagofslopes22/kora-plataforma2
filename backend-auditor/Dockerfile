# Backend Auditor.
#
# Contexto de build = RAIZ DO REPOSITORIO (mesmo motivo do conciliador: o
# codigo compartilha `kora_db/`). No Railway:
#     Root Directory:  /
#     Dockerfile Path: backend-auditor/Dockerfile

FROM python:3.11-slim

WORKDIR /app

# Ghostscript e libs de imagem: dependencias nativas do camelot/opencv usados
# na extracao de tabelas dos PDFs dos anexos.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ghostscript \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY backend-auditor/requirements.txt .

# O extra [cv] do camelot puxa `pdftopng`, que nao tem wheel publicado e quebra
# a instalacao. Instalamos o camelot BASE e o opencv headless separadamente —
# `camelot/__init__` importa cv2 no load, entao o opencv e obrigatorio mesmo
# sem o extra. Os extractors usam flavor="stream", que nao precisa do lattice.
RUN sed -i 's/^camelot-py\[cv\]/camelot-py/' requirements.txt \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir opencv-python-headless

COPY serve.py /app/serve.py
COPY kora_db/ /app/kora_db/
COPY db/ /app/db/
COPY backend-auditor/ /app/

ENV PYTHONPATH=/app

EXPOSE 8000
# Sobe via serve.py: um socket dual-stack (IPv4 + IPv6 no mesmo listener).
# `uvicorn --host ::` NAO serve: o asyncio forca IPV6_V6ONLY=1 e o dominio
# publico (que chega por IPv4) passa a responder 502. Ver serve.py.
CMD ["python", "serve.py", "backend.main:app", "8000"]
