"""Utilidades de texto compartilhadas pelos extratores."""
import unicodedata


def sem_acento(s: str) -> str:
    """Remove acentos/cedilha: 'DÉFICIT' -> 'DEFICIT', 'CONTINGÊNCIA' -> 'CONTINGENCIA'.

    Os termos de busca dos extratores sao escritos sem acento, mas cada sistema
    contabil gera o PDF de um jeito — comparar sempre sem acento nos dois lados.
    """
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
