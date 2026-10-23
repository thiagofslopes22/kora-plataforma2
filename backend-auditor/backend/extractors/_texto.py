"""Utilidades de texto compartilhadas pelos extratores."""
import re
import unicodedata


def sem_acento(s: str) -> str:
    """Remove acentos/cedilha: 'DÉFICIT' -> 'DEFICIT', 'CONTINGÊNCIA' -> 'CONTINGENCIA'.

    Os termos de busca dos extratores sao escritos sem acento, mas cada sistema
    contabil gera o PDF de um jeito — comparar sempre sem acento nos dois lados.
    """
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


_EXERCICIO_RE = re.compile(r"EXERC[IÍ]CIO\D{0,20}?((?:19|20)\d{2})\b")
_DATA_RE = re.compile(r"\b\d{2}/\d{2}/((?:19|20)\d{2})\b")


def busca_exercicio(texto: str):
    """Match com o ano do exercício em .group(1), ou None.

    Só aceita um ano (19xx/20xx) logo após "EXERCÍCIO" — sem isso o padrão antigo
    `EXERCÍCIO[^\\d]*(\\d{4})` atravessava linhas e pegava, por ex., o CPF do contador
    ("9938..."). Sem ano junto ao rótulo, usa o ano de uma data (ex.: 31/12/2025).
    """
    return _EXERCICIO_RE.search(texto) or _DATA_RE.search(texto)
