"""Rotinas centralizadas de limpeza de dados, arquivos temporários e logs."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional
import mysql.connector as mysql

from src.core.banco.conexao_banco import obter_conexao
from src.core.banco.clientes_schema import conexao_banco, garantir_banco_cliente


@dataclass
class ResultadoLimpeza:
    tipo: str
    detalhes: Dict[str, int]


def _mapear_importacoes_por_cliente(ids_importacao: List[int]) -> Dict[int, Dict[str, object]]:
    if not ids_importacao:
        return {}

    placeholders = ",".join(["%s"] * len(ids_importacao))
    conexao = obter_conexao()
    associados: Dict[int, Dict[str, object]] = {}
    try:
        cursor = conexao.cursor(dictionary=True)
        cursor.execute(
            f"""
            SELECT ci.id,
                   ci.id_cliente,
                   cli.schema_cliente
            FROM controle_importacoes ci
            JOIN clientes cli ON cli.id_cliente = ci.id_cliente
            WHERE ci.id IN ({placeholders})
            """,
            tuple(ids_importacao),
        )
        for linha in cursor.fetchall():
            id_cliente = linha.get("id_cliente")
            if id_cliente is None:
                continue
            identificador = linha.get("id")
            if identificador is None:
                continue
            registro = associados.setdefault(
                int(id_cliente),
                {"ids": [], "banco": linha.get("schema_cliente")},
            )
            registro["ids"].append(int(identificador))
    finally:
        conexao.close()

    for id_cliente, registro in associados.items():
        if not registro.get("banco"):
            try:
                registro["banco"] = garantir_banco_cliente(id_cliente)
            except Exception:
                registro["banco"] = None

    return associados


def _executar_sql(query: str, parametros: Optional[Iterable] = None) -> int:
    conexao = obter_conexao()
    try:
        cursor = conexao.cursor()
        cursor.execute(query, parametros or ())
        afetados = cursor.rowcount
        conexao.commit()
        return afetados
    finally:
        conexao.close()


def limpar_logs(var_dir: Path, older_than_days: Optional[int], keep_last: Optional[int]) -> ResultadoLimpeza:
    logs_dir = var_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    arquivos = []
    for arquivo in logs_dir.glob("*.log"):
        try:
            stat = arquivo.stat()
        except OSError:
            continue
        arquivos.append((arquivo, stat.st_mtime))

    arquivos.sort(key=lambda item: item[1], reverse=True)
    agora = datetime.now()

    removidos = 0
    mantidos = 0

    for indice, (arquivo, mtime) in enumerate(arquivos):
        apagar = False
        if older_than_days is not None:
            idade = agora - datetime.fromtimestamp(mtime)
            if idade > timedelta(days=older_than_days):
                apagar = True
        if keep_last is not None and indice >= keep_last:
            apagar = True

        if apagar:
            try:
                arquivo.unlink()
                removidos += 1
            except OSError:
                mantidos += 1
        else:
            mantidos += 1

    return ResultadoLimpeza("LOGS", {"removidos": removidos, "mantidos": mantidos})


def limpar_arquivos_tmp(var_dir: Path, ids_importacao: List[int], older_than_days: Optional[int]) -> ResultadoLimpeza:
    total = 0
    removidos = 0

    if not ids_importacao:
        return ResultadoLimpeza("TMP", {"removidos": 0, "total": 0})

    conexao = obter_conexao()
    try:
        cursor = conexao.cursor(dictionary=True)
        formato_ids = ",".join(["%s"] * len(ids_importacao))
        cursor.execute(
            f"""
            SELECT id, caminho_arquivo, removido_em
            FROM arquivos_importacao
            WHERE id_importacao IN ({formato_ids})
            """,
            tuple(ids_importacao),
        )
        registros = cursor.fetchall()
    finally:
        conexao.close()

    limite_tempo = None
    if older_than_days is not None:
        limite_tempo = datetime.now() - timedelta(days=older_than_days)

    for registro in registros:
        caminho = Path(registro["caminho_arquivo"])
        total += 1
        if registro.get("removido_em"):
            continue

        if limite_tempo and caminho.exists():
            try:
                if datetime.fromtimestamp(caminho.stat().st_mtime) > limite_tempo:
                    continue
            except OSError:
                pass

        if caminho.exists():
            try:
                caminho.unlink()
                removidos += 1
            except OSError:
                continue
        else:
            removidos += 1

        _executar_sql(
            "UPDATE arquivos_importacao SET removido_em = NOW() WHERE id = %s",
            (registro["id"],),
        )

    return ResultadoLimpeza("TMP", {"removidos": removidos, "total": total})


def marcar_importacoes_removidas(ids_importacao: List[int], mensagem: str) -> None:
    if not ids_importacao:
        return
    placeholders = ",".join(["%s"] * len(ids_importacao))
    parametros: List[object] = ["REMOVIDO", mensagem]
    parametros.extend(ids_importacao)
    _executar_sql(
        f"""
        UPDATE controle_importacoes
        SET status = %s,
            mensagem = %s
        WHERE id IN ({placeholders})
        """,
        tuple(parametros),
    )


def limpar_detraf(ids_importacao: List[int], remover_controle: bool) -> ResultadoLimpeza:
    if not ids_importacao:
        return ResultadoLimpeza("DETRAF", {"removidos": 0})

    placeholders = ",".join(["%s"] * len(ids_importacao))
    afetados = _executar_sql(
        f"DELETE FROM detraf_operadora_batimento WHERE id_importacao IN ({placeholders})",
        tuple(ids_importacao),
    )

    associados = _mapear_importacoes_por_cliente(ids_importacao)
    removidos_clientes = 0
    clientes_processados = 0

    for id_cliente, info in associados.items():
        ids_cli = info.get("ids") or []
        nome_banco = info.get("banco")
        if not ids_cli or not nome_banco:
            continue
        placeholders_cli = ",".join(["%s"] * len(ids_cli))
        conexao_cli = None
        cursor_cli = None
        try:
            conexao_cli = conexao_banco(nome_banco)
            cursor_cli = conexao_cli.cursor()
            cursor_cli.execute(
                f"DELETE FROM detraf_operadora_batimento WHERE id_importacao IN ({placeholders_cli})",
                tuple(ids_cli),
            )
            removidos_clientes += cursor_cli.rowcount or 0
            conexao_cli.commit()
            clientes_processados += 1
        except mysql.Error:
            if conexao_cli:
                conexao_cli.rollback()
        finally:
            try:
                if cursor_cli:
                    cursor_cli.close()
            except Exception:
                pass
            if conexao_cli:
                conexao_cli.close()

    if remover_controle:
        _executar_sql(
            f"DELETE FROM controle_importacoes WHERE id IN ({placeholders})",
            tuple(ids_importacao),
        )

    detalhes = {
        "registros_base": afetados,
        "clientes": len(associados),
    }
    if removidos_clientes:
        detalhes["registros_clientes"] = removidos_clientes
    detalhes["limpezas_sucesso"] = clientes_processados

    return ResultadoLimpeza("DETRAF", detalhes)


def limpar_cdr(ids_importacao: List[int], remover_controle: bool) -> ResultadoLimpeza:
    if not ids_importacao:
        return ResultadoLimpeza("CDR", {"tabelas_dropadas": 0})

    placeholders = ",".join(["%s"] * len(ids_importacao))
    associados = _mapear_importacoes_por_cliente(ids_importacao)

    conexao = obter_conexao()
    try:
        cursor = conexao.cursor(dictionary=True)
        cursor.execute(
            f"""
            SELECT cti.nome_tabela
            FROM cdr_tabelas_importadas cti
            WHERE id_importacao IN ({placeholders})
            """,
            tuple(ids_importacao),
        )
        registros = cursor.fetchall()
    finally:
        conexao.close()

    tabelas = {linha["nome_tabela"] for linha in registros if linha.get("nome_tabela")}

    dropadas = 0
    for nome in tabelas:
        if not _nome_tabela_valido(nome):
            continue
        try:
            _executar_sql(f"DROP TABLE IF EXISTS {_formatar_identificador(nome)}")
            dropadas += 1
        except Exception:
            continue

    clientes_processados = 0
    for id_cliente, info in associados.items():
        nome_banco = info.get("banco")
        if not nome_banco:
            continue
        conexao_cli = None
        cursor_cli = None
        try:
            conexao_cli = conexao_banco(nome_banco)
            cursor_cli = conexao_cli.cursor()
            cursor_cli.execute("DROP TABLE IF EXISTS cdr")
            conexao_cli.commit()
            clientes_processados += 1
        except mysql.Error:
            if conexao_cli:
                conexao_cli.rollback()
        finally:
            try:
                if cursor_cli:
                    cursor_cli.close()
            except Exception:
                pass
            if conexao_cli:
                conexao_cli.close()

    _executar_sql(
        f"DELETE FROM cdr_tabelas_importadas WHERE id_importacao IN ({placeholders})",
        tuple(ids_importacao),
    )

    if remover_controle:
        _executar_sql(
            f"DELETE FROM controle_importacoes WHERE id IN ({placeholders})",
            tuple(ids_importacao),
        )

    return ResultadoLimpeza(
        "CDR",
        {
            "tabelas_registradas": dropadas,
            "clientes": len(associados),
            "limpezas_sucesso": clientes_processados,
        },
    )


def registrar_execucao(parametros: dict, resultados: List, id_agendamento: Optional[int] = None) -> None:
    """Mantido por compatibilidade; atualmente sem efeito."""
    return


def _dividir(lista: List[int], tamanho: int) -> Iterable[List[int]]:
    for i in range(0, len(lista), tamanho):
        yield lista[i : i + tamanho]


def buscar_importacoes(
    clientes: List[int],
    tipos: Optional[List[str]] = None,
    periodo_inicio: Optional[str] = None,
    periodo_fim: Optional[str] = None,
    ids: Optional[List[int]] = None,
) -> List[int]:
    ids = ids or []
    condicoes = []
    parametros: List = []

    if clientes:
        condicoes.append(
            f"id_cliente IN ({','.join(['%s'] * len(clientes))})"
        )
        parametros.extend(clientes)

    if tipos:
        condicoes.append(
            f"tipo_arquivo IN ({','.join(['%s'] * len(tipos))})"
        )
        parametros.extend(tipos)

    if periodo_inicio:
        condicoes.append("data_importacao >= %s")
        parametros.append(periodo_inicio)

    if periodo_fim:
        condicoes.append("data_importacao <= %s")
        parametros.append(periodo_fim)

    if ids:
        condicoes.append(
            f"id IN ({','.join(['%s'] * len(ids))})"
        )
        parametros.extend(ids)

    if not condicoes:
        condicoes.append("1=1")

    where_sql = " AND ".join(condicoes)

    conexao = obter_conexao()
    try:
        cursor = conexao.cursor()
        cursor.execute(
            f"SELECT id FROM controle_importacoes WHERE {where_sql}",
            tuple(parametros),
        )
        return [linha[0] for linha in cursor.fetchall()]
    finally:
        conexao.close()


_PADRAO_TABELA = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)?$")


def _nome_tabela_valido(nome: str) -> bool:
    return bool(nome and _PADRAO_TABELA.fullmatch(nome))


def _formatar_identificador(nome: str) -> str:
    partes = nome.split(".")
    return ".".join(f"`{parte}`" for parte in partes if parte)
