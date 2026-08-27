import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from backend.api.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="Kora API",
    description="Sistema de geração automática de tabelas RIT para prefeituras",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/")
def root():
    return {"message": "Kora API rodando. Acesse /docs para a documentação."}


@app.get("/teste", response_class=HTMLResponse)
def teste():
    html = (Path(__file__).parent.parent / "teste.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)
