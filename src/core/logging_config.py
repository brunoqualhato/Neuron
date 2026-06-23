"""
Configuração centralizada de logging para o Neuron.

Uso:
    from src.core.logging_config import setup_logging
    setup_logging()  # Chamar uma vez no main.py

Modos:
    - CLI interativo: Rich handler com output colorido
    - Batch/API: handler simples para stderr
    - DEBUG: Ativado via NEURON_DEBUG=true no .env
"""

import logging
import os
import sys


def setup_logging(force_level: str | None = None):
    """
    Configura logging global do Neuron.

    Args:
        force_level: Se fornecido, força o nível (DEBUG, INFO, WARNING, ERROR).
    """
    # Determina nível via env ou parâmetro
    if force_level:
        level_str = force_level.upper()
    else:
        level_str = os.environ.get("NEURON_LOG_LEVEL", "WARNING").upper()

    # NEURON_DEBUG=true é atalho para DEBUG
    if os.environ.get("NEURON_DEBUG", "").lower() in ("true", "1", "yes"):
        level_str = "DEBUG"

    level = getattr(logging, level_str, logging.WARNING)

    # Formato
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%H:%M:%S"

    # Handler para stderr (não polui stdout em modo batch)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))

    # Configura root logger do namespace neuron
    root_logger = logging.getLogger("src")
    root_logger.setLevel(level)
    root_logger.addHandler(handler)

    # Silencia loggers verbosos de libs externas
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
