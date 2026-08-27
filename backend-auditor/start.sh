#!/bin/bash
set -e
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi
if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "❌ ANTHROPIC_API_KEY não definida. Crie um arquivo .env"
  exit 1
fi
echo "🚀 Kora API em http://localhost:8000"
python -m uvicorn backend.main:app --reload --port 8000
