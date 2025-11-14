from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import date

import mysql.connector as mysql

from src.core.banco.clientes_schema import garantir_banco_cliente, conexao_banco_cliente
from src.core.configuracao_logs import registrar_log


def importar_dump_cdr(
    caminho_dump: Path,
    id_cliente: int,
    configuracao_mysql: Dict[str, object],
) -> Tuple[Optional[date], Optional[date], str, List[str], int]:
    """
    Importa um dump de CDR diretamente no banco dedicado do cliente.

    Retorna:
        periodo_inicial, periodo_final, tabela_utilizada, novas_tabelas, total_registros
    """
    if not configuracao_mysql.get("database"):
        raise RuntimeError("Banco de dados não configurado para importação CDR.")

    nome_banco_cliente = garantir_banco_cliente(id_cliente)
    registrar_log(
        "cdr_importacao_inicio",
        arquivo=str(caminho_dump),
        id_cliente=id_cliente,
        tamanho_bytes=caminho_dump.stat().st_size if caminho_dump.exists() else None,
        banco=nome_banco_cliente,
    )

    comando = ["mysql"]
    if configuracao_mysql.get("host"):
        comando.extend(["-h", str(configuracao_mysql["host"])])
    if configuracao_mysql.get("port"):
        comando.extend(["-P", str(configuracao_mysql["port"])])
    if configuracao_mysql.get("user"):
        comando.extend(["-u", configuracao_mysql["user"]])

    ambiente = os.environ.copy()
    if configuracao_mysql.get("password"):
        ambiente["MYSQL_PWD"] = str(configuracao_mysql["password"])

    conexao_cli = conexao_banco_cliente(id_cliente)
    try:
        cursor_cli = conexao_cli.cursor()
        cursor_cli.execute("DROP TABLE IF EXISTS cdr")
        conexao_cli.commit()
    finally:
        conexao_cli.close()

    comando.extend(["-D", nome_banco_cliente])

    try:
        with open(caminho_dump, "rb") as conteudo_dump:
            subprocess.run(
                comando,
                stdin=conteudo_dump,
                check=True,
                env=ambiente,
            )
    except Exception as exc:
        registrar_log(
            "cdr_importacao_erro",
            arquivo=str(caminho_dump),
            id_cliente=id_cliente,
            comando=" ".join(comando),
            erro=str(exc),
        )
        raise

    periodo_inicial = None
    periodo_final = None
    total_registros = 0

    conexao_cli = conexao_banco_cliente(id_cliente)
    try:
        cursor_cli = conexao_cli.cursor()
        try:
            cursor_cli.execute("SELECT MIN(calldate), MAX(calldate) FROM cdr")
            resultado = cursor_cli.fetchone()
            if resultado:
                periodo_inicial, periodo_final = resultado
        except mysql.Error:
            periodo_inicial = None
            periodo_final = None
        try:
            cursor_cli.execute("SELECT COUNT(1) FROM cdr")
            total_registros = int(cursor_cli.fetchone()[0] or 0)
        except mysql.Error:
            total_registros = 0
    finally:
        conexao_cli.close()

    tabela_utilizada = f"{nome_banco_cliente}.cdr"
    tabelas_finais = [tabela_utilizada]

    registrar_log(
        "cdr_importacao_concluida",
        arquivo=str(caminho_dump),
        id_cliente=id_cliente,
        banco=nome_banco_cliente,
        total_registros=total_registros,
        periodo_inicial=periodo_inicial,
        periodo_final=periodo_final,
    )
    return periodo_inicial, periodo_final, tabela_utilizada, tabelas_finais, total_registros
