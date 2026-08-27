"""
Senhas e tokens.

Senha: Argon2id (o que o schema documenta). O prototipo usava bcrypt, entao
`verificar_senha` ainda aceita hashes bcrypt e sinaliza rehash — assim os
usuarios migrados do SQLite continuam entrando e sao promovidos a Argon2id no
primeiro login bem-sucedido, sem reset de senha em massa.

Token: JWT curto carregando tenant + usuario + papel. O backend NUNCA confia no
papel do token para decidir o que o usuario pode ver — quem decide e a RLS, que
le a tabela `usuarios`. O token so diz QUEM e; o banco diz O QUE pode.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from jose import JWTError, jwt

_ph = PasswordHasher()  # perfil padrao do argon2-cffi (Argon2id)

ALGORITMO = "HS256"
EXPIRACAO_HORAS = int(os.getenv("KORA_TOKEN_HORAS", "12"))


def _segredo() -> str:
    s = os.getenv("KORA_JWT_SECRET", "")
    if not s:
        raise RuntimeError(
            "KORA_JWT_SECRET nao definida. Gere com: openssl rand -base64 48"
        )
    if len(s) < 32:
        raise RuntimeError("KORA_JWT_SECRET curta demais (minimo 32 caracteres).")
    return s


# ---------------------------------------------------------------------------
# Senhas
# ---------------------------------------------------------------------------
def hash_senha(senha: str) -> str:
    return _ph.hash(senha)


def verificar_senha(senha: str, hash_armazenado: str) -> tuple[bool, bool]:
    """Retorna (senha_confere, precisa_rehash).

    `precisa_rehash` fica True quando o hash e bcrypt legado ou quando os
    parametros do Argon2 mudaram — o chamador deve regravar o hash."""
    if not hash_armazenado:
        return False, False

    # Legado do prototipo: bcrypt ($2a$/$2b$/$2y$)
    if hash_armazenado.startswith("$2"):
        try:
            import bcrypt

            ok = bcrypt.checkpw(senha.encode("utf-8"), hash_armazenado.encode("utf-8"))
            return ok, ok  # se confere, promove p/ Argon2id
        except Exception:
            return False, False

    try:
        _ph.verify(hash_armazenado, senha)
    except (VerifyMismatchError, InvalidHashError):
        return False, False
    except Exception:
        return False, False
    return True, _ph.check_needs_rehash(hash_armazenado)


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
def criar_token_usuario(escritorio_id: int, usuario_id: int, papel: str, email: str) -> str:
    agora = datetime.now(timezone.utc)
    payload = {
        "tipo": "usuario",
        "esc": int(escritorio_id),
        "uid": int(usuario_id),
        "papel": papel,
        "sub": email,
        "iat": agora,
        "exp": agora + timedelta(hours=EXPIRACAO_HORAS),
    }
    return jwt.encode(payload, _segredo(), algorithm=ALGORITMO)


def criar_token_plataforma(admin_id: int, email: str) -> str:
    agora = datetime.now(timezone.utc)
    payload = {
        "tipo": "plataforma",
        "aid": int(admin_id),
        "sub": email,
        "iat": agora,
        "exp": agora + timedelta(hours=EXPIRACAO_HORAS),
    }
    return jwt.encode(payload, _segredo(), algorithm=ALGORITMO)


def decodificar_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, _segredo(), algorithms=[ALGORITMO])
    except JWTError:
        return None
