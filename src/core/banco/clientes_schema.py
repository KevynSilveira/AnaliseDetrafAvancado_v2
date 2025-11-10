"""Rotinas utilitárias para gerenciamento de bancos específicos por cliente."""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from typing import Dict, Optional

import mysql.connector as mysql
from dotenv import load_dotenv

from .conexao_banco import obter_conexao

# ---------------------------------------------------------------------------
# Carrega configurações do ambiente
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parents[3]
ENV_PATH = BASE_DIR / "configs" / ".env"

if ENV_PATH.exists():
    load_dotenv(ENV_PATH)

_DB_NAME = os.getenv("DB_NAME")
_CLIENTE_PREFIXO_DEFAULT = os.getenv("CLIENT_DB_PREFIX") or (_DB_NAME or "cliente")

_DBCFG = {
    "host": os.getenv("DB_HOST") or None,
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER") or None,
    "password": os.getenv("DB_PASS") or None,
}


def _compactar(cfg: Dict[str, Optional[object]]) -> Dict[str, object]:
    """Remove chaves com valor None antes de abrir uma conexão."""
    return {chave: valor for chave, valor in cfg.items() if valor is not None}


def _config_conexao_bruta(database: Optional[str] = None) -> Dict[str, object]:
    """Retorna as credenciais básicas para nova conexão direta."""
    cfg = dict(_DBCFG)
    if database:
        cfg["database"] = database
    elif _DB_NAME:
        cfg["database"] = _DB_NAME
    return _compactar(cfg)


SQL_TABELA_DETRAF_CLIENTE = """
CREATE TABLE IF NOT EXISTS detraf_operadora_batimento (
    id INT AUTO_INCREMENT PRIMARY KEY,
    id_importacao INT,
    sequencial CHAR(10),
    assinante_a VARCHAR(21),
    eqt_a CHAR(3),
    cnl_a CHAR(5),
    area_local_a CHAR(4),
    data_chamada DATE,
    hora_atendimento TIME,
    assinante_b VARCHAR(20),
    eqt_b CHAR(3),
    cnl_b CHAR(5),
    area_local_b CHAR(4),
    duracao_real_segundos INT,
    poi CHAR(10),
    descritor_cdr CHAR(5),
    duracao_calculada DECIMAL(10,1),
    categoria_assinante_a CHAR(2),
    fds CHAR(2),
    causa_saida CHAR(1),
    contador_saidas_parciais CHAR(2),
    valor_remuneracao DECIMAL(18,5),
    gh CHAR(1),
    eqt_credora CHAR(3),
    eqt_devedora CHAR(3),
    importado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
    classificacao VARCHAR(20) NULL,
    tipo_chamada VARCHAR(30) NULL,
    INDEX idx_descritor (descritor_cdr),
    INDEX idx_data (data_chamada),
    INDEX idx_gh (gh)
)
"""


def _normalizar_nome_banco(nome: str) -> str:
    """Normaliza o nome do cliente para usar como nome de banco MySQL."""
    texto = unicodedata.normalize("NFKD", (nome or "").strip())
    texto = texto.encode("ascii", "ignore").decode("ascii")
    texto = texto.lower()
    texto = re.sub(r"[^a-z0-9]+", "_", texto)
    texto = texto.strip("_")
    if not texto:
        texto = re.sub(r"[^a-z0-9]+", "_", _CLIENTE_PREFIXO_DEFAULT.lower()).strip("_") or "cliente"
    # Reserva espaço para possíveis sufixos numéricos
    return texto[:52]


def _banco_disponivel(cursor, candidato: str, id_cliente: int) -> bool:
    """Verifica se o nome de banco está disponível."""
    cursor.execute(
        """
        SELECT id_cliente
        FROM clientes
        WHERE schema_cliente = %s AND id_cliente <> %s
        LIMIT 1
        """,
        (candidato, id_cliente),
    )
    if cursor.fetchone():
        return False

    cursor.execute(
        "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s",
        (candidato,),
    )
    return cursor.fetchone() is None


def _resolver_banco_cliente(id_cliente: int, nome_cliente: str, banco_atual: Optional[str]) -> str:
    """Determina (ou retorna) o banco associado ao cliente."""
    if banco_atual:
        return banco_atual

    conexao = obter_conexao()
    try:
        cursor = conexao.cursor()
        base = _normalizar_nome_banco(nome_cliente)
        candidato = base
        sufixo = 2

        while not _banco_disponivel(cursor, candidato, id_cliente):
            candidato = f"{base}_{sufixo}"
            if len(candidato) > 60:
                limite = max(10, 60 - len(str(sufixo)) - 1)
                candidato = f"{base[:limite]}_{sufixo}"
            sufixo += 1

        cursor.execute(
            "UPDATE clientes SET schema_cliente = %s WHERE id_cliente = %s",
            (candidato, id_cliente),
        )
        conexao.commit()
        return candidato
    finally:
        conexao.close()


def _garantir_banco_existente(nome_banco: str) -> None:
    """Cria (se necessário) o banco do cliente e sua tabela DETRAF."""
    cfg_servidor = _config_conexao_bruta()
    conexao = mysql.connect(**cfg_servidor)
    try:
        cursor = conexao.cursor()
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{nome_banco}` "
            "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        conexao.commit()
    finally:
        conexao.close()

    cfg_banco = _config_conexao_bruta(nome_banco)
    conexao = mysql.connect(**cfg_banco)
    try:
        cursor = conexao.cursor()
        cursor.execute(SQL_TABELA_DETRAF_CLIENTE)
        conexao.commit()
    finally:
        conexao.close()


def garantir_banco_cliente(id_cliente: int) -> str:
    """Garante que o cliente possua um banco próprio configurado."""
    conexao = obter_conexao()
    try:
        cursor = conexao.cursor(dictionary=True)
        cursor.execute(
            "SELECT nome_cliente, schema_cliente FROM clientes WHERE id_cliente = %s",
            (id_cliente,),
        )
        info = cursor.fetchone()
        if not info:
            raise ValueError(f"Cliente {id_cliente} não encontrado.")
        nome_banco = info.get("schema_cliente")
        nome_cliente = info.get("nome_cliente") or f"cliente_{id_cliente}"
    finally:
        conexao.close()

    nome_banco = _resolver_banco_cliente(id_cliente, nome_cliente, nome_banco)
    _garantir_banco_existente(nome_banco)
    return nome_banco


def obter_banco_cliente(id_cliente: int) -> Optional[str]:
    """Retorna o banco associado ao cliente (não garante criação)."""
    conexao = obter_conexao()
    try:
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT schema_cliente FROM clientes WHERE id_cliente = %s",
            (id_cliente,),
        )
        resultado = cursor.fetchone()
        return resultado[0] if resultado and resultado[0] else None
    finally:
        conexao.close()


def conexao_banco(nome_banco: str):
    """Retorna uma conexão direta para o banco informado."""
    cfg = _config_conexao_bruta(nome_banco)
    return mysql.connect(**cfg)


def conexao_banco_cliente(id_cliente: int):
    """Retorna uma conexão para o banco específico do cliente."""
    nome_banco = garantir_banco_cliente(id_cliente)
    return conexao_banco(nome_banco)
