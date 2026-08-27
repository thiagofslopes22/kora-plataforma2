"""
Carregador minimo de arquivo .env (sem dependencia externa).

Existe para que segredos (senha do banco, JWT) fiquem num arquivo local e nunca
precisem ser digitados na linha de comando — onde acabariam no historico do
shell — nem colados em conversa.

Procura, na raiz do repositorio e nesta pasta, por: .env.supabase, .env
Variaveis JA definidas no ambiente tem PRECEDENCIA sobre o arquivo (assim o
Railway, que injeta env de verdade, nunca e sobrescrito por um .env esquecido).
"""
from __future__ import annotations

import os
from pathlib import Path

_CANDIDATOS = (".env.supabase", ".env")


def _injetar_senha() -> None:
    """Se KORA_DB_SENHA existir, monta a senha na DATABASE_URL com percent-encode.

    Evita a pegadinha que o proprio Supabase avisa: senha com '@', '/', '#' ou
    ':' quebra a URL — o '@' faz o parser cortar o host no lugar errado e o erro
    que aparece e "could not translate host name", que nao lembra em nada uma
    senha mal escapada. Assim voce cola a senha crua e nao precisa codificar."""
    senha = os.environ.get("KORA_DB_SENHA", "")
    url = os.environ.get("DATABASE_URL", "")
    if not senha or not url:
        return
    from urllib.parse import quote, urlsplit, urlunsplit

    partes = urlsplit(url)
    usuario = (partes.username or "")
    hostporta = partes.hostname or ""
    if partes.port:
        hostporta += f":{partes.port}"
    netloc = f"{quote(usuario, safe='')}:{quote(senha, safe='')}@{hostporta}"
    os.environ["DATABASE_URL"] = urlunsplit(
        (partes.scheme, netloc, partes.path, partes.query, partes.fragment)
    )


def carregar_env(verboso: bool = True) -> Path | None:
    raiz = Path(__file__).resolve().parent.parent
    for pasta in (raiz, raiz / "db"):
        for nome in _CANDIDATOS:
            caminho = pasta / nome
            if not caminho.is_file():
                continue
            n = 0
            for linha in caminho.read_text(encoding="utf-8").splitlines():
                linha = linha.strip()
                if not linha or linha.startswith("#") or "=" not in linha:
                    continue
                chave, _, valor = linha.partition("=")
                chave = chave.strip()
                valor = valor.strip().strip('"').strip("'")
                if chave and chave not in os.environ:
                    os.environ[chave] = valor
                    n += 1
            _injetar_senha()
            if verboso:
                print(f"Credenciais carregadas de {caminho.name} ({n} variaveis)")
            return caminho
    _injetar_senha()
    return None
