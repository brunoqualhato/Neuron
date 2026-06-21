"""
Utilitários compartilhados entre os módulos do sistema.
"""

import unicodedata


def normalizar(texto: str) -> str:
    """
    Converte para minúsculas e remove acentos.
    Permite comparar 'ultima versao' == 'última versão'.
    """
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return sem_acento.lower()
