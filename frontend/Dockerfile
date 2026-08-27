# Frontend (Vite + React) servido por nginx, que tambem faz proxy dos backends.
#
# Contexto de build = RAIZ DO REPOSITORIO, igual aos dois backends. O frontend
# nao precisa de nada de fora da sua pasta, mas manter os TRES servicos com o
# mesmo Root Directory ('/') elimina a principal fonte de erro no Railway:
# basta trocar RAILWAY_DOCKERFILE_PATH entre eles.
#
# No Railway:
#     Root Directory:          /
#     RAILWAY_DOCKERFILE_PATH: frontend/Dockerfile

FROM node:20-alpine AS builder
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci --ignore-scripts || npm install --ignore-scripts
COPY frontend/ ./
# As chamadas vao para /api e /conc na PROPRIA origem (o nginx faz o proxy),
# entao nao ha URL de backend embutida no bundle — o mesmo build serve
# qualquer ambiente e nao existe CORS em producao.
RUN node node_modules/vite/bin/vite.js build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
# nginx:alpine roda envsubst nos arquivos de /etc/nginx/templates no boot,
# gerando /etc/nginx/conf.d/default.conf com PORT/AUDITOR_URL/CONCILIADOR_URL.
# Garante um resolver DNS valido antes do envsubst (ver o proprio script).
COPY frontend/16-kora-resolver.envsh /docker-entrypoint.d/16-kora-resolver.envsh
COPY frontend/nginx.conf.template /etc/nginx/templates/default.conf.template
ENV PORT=80
EXPOSE 80
