from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[2]
VAR_DIR = BASE_DIR / os.getenv("VAR_DIR", "var")
PASTA_LOGS = VAR_DIR / "logs"
PASTA_LOGS.mkdir(parents=True, exist_ok=True)
ARQUIVO_LOG = PASTA_LOGS / "api_conferencia.log"

NOME_LOGGER = "api_conferencia"
_LOGGER: logging.Logger | None = None


def obter_logger_aplicacao() -> logging.Logger:
    """Garante que exista um logger configurado para toda a aplicação."""
    global _LOGGER
    if _LOGGER:
        return _LOGGER
    logger = logging.getLogger(NOME_LOGGER)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(ARQUIVO_LOG, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    _LOGGER = logger
    return logger


def _serializar_valor(valor: Any):
    if isinstance(valor, (datetime, date, time)):
        return valor.isoformat()
    if isinstance(valor, (list, tuple)):
        return [_serializar_valor(item) for item in valor]
    if isinstance(valor, dict):
        return {chave: _serializar_valor(item) for chave, item in valor.items()}
    try:
        json.dumps(valor)
        return valor
    except (TypeError, ValueError):
        return str(valor)


def registrar_log(evento: str, **contexto):
    dados = {chave: _serializar_valor(valor) for chave, valor in contexto.items()}
    logger = obter_logger_aplicacao()
    try:
        logger.info("%s | %s", evento, json.dumps(dados, ensure_ascii=False))
    except Exception as erro:  # pragma: no cover
        logger.warning("Falha ao registrar log (%s): %s", evento, erro)


def serializar_para_log(valor: Any):
    return _serializar_valor(valor)
