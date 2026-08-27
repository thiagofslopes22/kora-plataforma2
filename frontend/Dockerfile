# Frontend (Vite + React) servido por nginx, que tambem faz proxy dos backends.
#
# Contexto de build = esta pasta (frontend/). No Railway:
#     Root Directory:  frontend
#     Dockerfile Path: Dockerfile
#
# Diferente dos backends, aqui NAO precisa da raiz do repo — o frontend nao
# importa kora_db.

FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --ignore-scripts || npm install --ignore-scripts
COPY . .
# As chamadas vao para /api e /conc na PROPRIA origem (o nginx faz o proxy),
# entao nao ha URL de backend embutida no bundle — o mesmo build serve
# qualquer ambiente.
RUN node node_modules/vite/bin/vite.js build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
# nginx:alpine roda envsubst nos arquivos de /etc/nginx/templates no boot,
# gerando /etc/nginx/conf.d/default.conf com PORT/AUDITOR_URL/CONCILIADOR_URL.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
ENV PORT=80
EXPOSE 80
