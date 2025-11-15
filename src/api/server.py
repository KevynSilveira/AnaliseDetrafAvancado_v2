# ======================================
# API DETRAF CONFERÊNCIA V2
# ======================================
# Responsável por:
# - Servir dados para a interface web
# - Fazer upload e controle de importações
# - Calcular KPIs e métricas DETRAF
# ======================================

import csv
import io
import json
import os
import re
import threading
import subprocess
from collections import Counter
from functools import lru_cache
from pathlib import Path
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from dotenv import load_dotenv
import mysql.connector as mysql
from mysql.connector.pooling import MySQLConnectionPool
from pydantic import BaseModel, Field
from src.core.banco.clientes_schema import (
    conexao_banco_cliente,
    garantir_banco_cliente,
)
from src.core.banco.verifica_tabelas import (
    criar_tabela_clientes,
    criar_tabela_controle_importacoes,
    criar_tabela_detraf_operadora_batimento,
    criar_tabela_arquivos_importacao,
    criar_tabela_cdr_tabelas_importadas,
    criar_tabela_conferencia_execucoes,
    criar_tabela_detraf_normalizado,
    criar_tabela_cdr_normalizado,
    criar_tabela_conferencia_resultados,
)
from src.core.limpeza import (
    limpar_logs,
    limpar_arquivos_tmp,
    limpar_detraf,
    limpar_cdr,
    marcar_importacoes_removidas,
    registrar_execucao,
    buscar_importacoes,
)
from src.core.faz_batimento import executar_batimento, TOLERANCIA_DURACAO_SEG
from src.core.importadores.importador_cdr import importar_dump_cdr
from src.core.importadores.importador_detraf import processar_arquivo_detraf
from src.core.configuracao_logs import registrar_log, serializar_para_log

# ======================================
# Carrega o .env do caminho correto
# ======================================
BASE_DIR = Path(__file__).resolve().parents[2]  # sobe até a raiz do projeto
ENV_PATH = BASE_DIR / "configs" / ".env"

if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:
    print(f"[AVISO] Arquivo .env não encontrado em {ENV_PATH}")

# ======================================
# Configurações do Banco
# ======================================
DBCFG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "database": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
   "password": os.getenv("DB_PASS"),
}

# Caminho da pasta var (para uploads, logs, etc)
VAR_DIR = BASE_DIR / os.getenv("VAR_DIR", "var")
(VAR_DIR / "tmp").mkdir(parents=True, exist_ok=True)
LOG_DIR = VAR_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

TABELAS_AUXILIARES = {
    "eot": "eot",
    "numeros_portados": "numeros_portados",
    "cadup": "cadup",
}

# ======================================
# Logging centralizado
# ======================================


def _registrar_sql_erro(evento: str, sql: str, parametros, erro: Exception):
    registrar_log(
        evento,
        sql=sql,
        placeholders=sql.count("%s"),
        parametros=serializar_para_log(parametros),
        erro=str(erro),
    )

# Cria pool de conexões
pool = MySQLConnectionPool(pool_name="detraf_pool", pool_size=5, **DBCFG)

# Função simples para pegar conexão
def db():
    return pool.get_connection()


@lru_cache(maxsize=64)
def _coluna_existe(tabela: str, coluna: str) -> bool:
    conexao = db()
    try:
        cursor = conexao.cursor()
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = %s
              AND COLUMN_NAME = %s
            LIMIT 1
            """,
            (tabela, coluna),
        )
        return cursor.fetchone() is not None
    finally:
        conexao.close()


def criar_tabela_importacoes_auxiliares():
    """Cria histórico para dumps auxiliares (EOT, números portados, CADUP)."""
    conexao = db()
    try:
        cursor = conexao.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS importacoes_auxiliares (
                id INT AUTO_INCREMENT PRIMARY KEY,
                tabela_alvo ENUM('eot','numeros_portados','cadup') NOT NULL,
                nome_arquivo VARCHAR(255) NOT NULL,
                tamanho_bytes BIGINT NULL,
                total_registros INT NULL,
                status ENUM('PROCESSANDO','CONCLUIDO','ERRO') DEFAULT 'PROCESSANDO',
                mensagem TEXT NULL,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
            """
        )
        conexao.commit()
    finally:
        conexao.close()


def registrar_importacao_auxiliar_inicio(tabela: str, nome_arquivo: str, tamanho_bytes: Optional[int]) -> int:
    """Grava início da importação auxiliar para exibir no histórico."""
    conexao = db()
    try:
        cursor = conexao.cursor()
        cursor.execute(
            """
            INSERT INTO importacoes_auxiliares (tabela_alvo, nome_arquivo, tamanho_bytes)
            VALUES (%s, %s, %s)
            """,
            (tabela, nome_arquivo, tamanho_bytes),
        )
        conexao.commit()
        return cursor.lastrowid
    finally:
        conexao.close()


def atualizar_importacao_auxiliar(id_registro: int, **campos):
    """Atualiza status/mensagem da importação auxiliar."""
    if not campos:
        return
    colunas = []
    valores = []
    for chave, valor in campos.items():
        colunas.append(f"{chave} = %s")
        valores.append(valor)
    valores.append(id_registro)
    conexao = db()
    try:
        cursor = conexao.cursor()
        cursor.execute(
            f"UPDATE importacoes_auxiliares SET {', '.join(colunas)} WHERE id = %s",
            tuple(valores),
        )
        conexao.commit()
    finally:
        conexao.close()

# ======================================
# Inicialização do Banco
# ======================================
def ensure_tables():
    criar_tabela_clientes()
    criar_tabela_controle_importacoes()
    criar_tabela_detraf_operadora_batimento()
    criar_tabela_arquivos_importacao()
    criar_tabela_cdr_tabelas_importadas()
    criar_tabela_conferencia_execucoes()
    criar_tabela_detraf_normalizado()
    criar_tabela_cdr_normalizado()
    criar_tabela_conferencia_resultados()
    criar_tabela_importacoes_auxiliares()
    _coluna_existe.cache_clear()

ensure_tables()

# ======================================
# Inicia a API
# ======================================
app = FastAPI(title="DETRAF Conferência API")

# Libera CORS para a Web rodar localmente
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ======================================
# Modelos de retorno
# ======================================
class Kpis(BaseModel):
    total: int
    percent_conferido: float
    percent_divergente: float
    percent_perdido: float


class ClienteEntrada(BaseModel):
    nome_cliente: str


class LogsCleanup(BaseModel):
    older_than_days: Optional[int] = None
    keep_last: Optional[int] = None


class LimpezaManualEntrada(BaseModel):
    clientes: List[int] = Field(default_factory=list)
    alvos: List[str]
    opcoes: Dict[str, Dict] = Field(default_factory=dict)
    remover_controle: bool = False
    periodo_inicio: Optional[str] = None
    periodo_fim: Optional[str] = None
    ids_importacoes: List[int] = Field(default_factory=list)


class ConferenciaProcessarEntrada(BaseModel):
    id_importacao_detraf: int
    id_importacao_cdr: Optional[int] = None
    forcar_normalizacao: bool = False
    mes_referencia: Optional[str] = None
    operadoras: Optional[List[str]] = None


def atualizar_controle_importacao(id_importacao: int, **campos):
    """Atualiza colunas específicas da tabela de controle."""
    if not campos:
        return
    colunas = ", ".join(f"{chave}=%s" for chave in campos.keys())
    valores = list(campos.values())
    valores.append(id_importacao)

    conexao = db()
    try:
        cursor = conexao.cursor()
        cursor.execute(
            f"UPDATE controle_importacoes SET {colunas} WHERE id=%s",
            valores,
        )
        conexao.commit()
    finally:
        conexao.close()


def registrar_arquivo_importado(id_importacao: int, caminho: Path, tipo: str) -> None:
    conexao = db()
    try:
        cursor = conexao.cursor()
        cursor.execute(
            """
            INSERT INTO arquivos_importacao (id_importacao, caminho_arquivo, tipo_arquivo)
            VALUES (%s, %s, %s)
            """,
            (id_importacao, str(caminho), tipo),
        )
        conexao.commit()
    finally:
        conexao.close()


def registrar_tabelas_cdr(id_importacao: int, tabelas: List[str]) -> None:
    if not tabelas:
        return

    conexao = db()
    try:
        cursor = conexao.cursor()
        valores = [(id_importacao, tabela) for tabela in tabelas if tabela]
        if not valores:
            return
        cursor.executemany(
            "INSERT INTO cdr_tabelas_importadas (id_importacao, nome_tabela) VALUES (%s, %s)",
            valores,
        )
        conexao.commit()
    finally:
        conexao.close()


def registrar_execucao_conferencia(
    id_cliente: int,
    id_importacao_detraf: int,
    id_importacao_cdr: Optional[int],
    mes_referencia: Optional[str] = None,
    operadoras: Optional[List[str]] = None,
) -> int:
    operadoras_json = json.dumps(operadoras, ensure_ascii=False) if operadoras else None
    conexao = db()
    try:
        cursor = conexao.cursor()
        cursor.execute(
            """
            INSERT INTO conferencia_execucoes (id_cliente, id_importacao_detraf, id_importacao_cdr, mes_referencia, operadoras_json)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (id_cliente, id_importacao_detraf, id_importacao_cdr, mes_referencia, operadoras_json),
        )
        conexao.commit()
        return cursor.lastrowid
    finally:
        conexao.close()


def atualizar_execucao_conferencia(exec_id: int, **campos) -> None:
    if not campos:
        return
    colunas = ", ".join(f"{campo}=%s" for campo in campos.keys())
    parametros = list(campos.values()) + [exec_id]

    conexao = db()
    try:
        cursor = conexao.cursor()
        cursor.execute(
            f"UPDATE conferencia_execucoes SET {colunas} WHERE id=%s",
            parametros,
        )
        conexao.commit()
    finally:
        conexao.close()


def obter_execucao_conferencia(exec_id: int) -> Optional[dict]:
    conexao = db()
    try:
        cursor = conexao.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM conferencia_execucoes WHERE id=%s",
            (exec_id,),
        )
        return cursor.fetchone()
    finally:
        conexao.close()


def _callback_execucao(exec_id: Optional[int]):
    if not exec_id:
        return None

    def atualizar(status: str, etapa: str, progresso: int, processados: int, total: int, mensagem: Optional[str] = None):
        campos = {
            "status_execucao": status,
            "etapa_atual": etapa,
            "progresso_percentual": min(max(progresso, 0), 99),
            "processados": processados,
            "total_registros": total,
        }
        if mensagem:
            campos["mensagem"] = mensagem
        atualizar_execucao_conferencia(exec_id, **campos)

    return atualizar


def _obter_importacao(id_importacao: int) -> Optional[dict]:
    conexao = db()
    try:
        cursor = conexao.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT ci.*, cli.nome_cliente
            FROM controle_importacoes ci
            LEFT JOIN clientes cli ON cli.id_cliente = ci.id_cliente
            WHERE ci.id = %s
            LIMIT 1
            """,
            (id_importacao,),
        )
        return cursor.fetchone()
    finally:
        conexao.close()


def _buscar_importacao_recente(id_cliente: int, tipo: str) -> Optional[dict]:
    conexao = db()
    try:
        cursor = conexao.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, nome_arquivo, periodo_inicial, periodo_final
            FROM controle_importacoes
            WHERE id_cliente = %s AND tipo_arquivo = %s AND status = 'CONCLUIDO'
            ORDER BY data_importacao DESC, id DESC
            LIMIT 1
            """,
            (id_cliente, tipo),
        )
        return cursor.fetchone()
    finally:
        conexao.close()


def _executar_conferencia_automatica(
    id_cliente: int,
    id_importacao_detraf: int,
    periodo_detraf_inicio: Optional[date],
    periodo_detraf_fim: Optional[date],
    id_importacao_cdr: Optional[int] = None,
    periodo_cdr_inicio: Optional[date] = None,
    periodo_cdr_fim: Optional[date] = None,
) -> Optional[dict]:
    cdr_info = None
    if id_importacao_cdr:
        cdr_info = {
            "id": id_importacao_cdr,
            "periodo_inicial": periodo_cdr_inicio,
            "periodo_final": periodo_cdr_fim,
        }
    else:
        cdr_info = _buscar_importacao_recente(id_cliente, "CDR")

    if not cdr_info or not cdr_info.get("id"):
        return None

    periodo_inicio = periodo_detraf_inicio or cdr_info.get("periodo_inicial")
    periodo_fim = periodo_detraf_fim or cdr_info.get("periodo_final")

    exec_id = registrar_execucao_conferencia(id_cliente, id_importacao_detraf, cdr_info["id"])
    resumo = executar_batimento(
        id_cliente=id_cliente,
        id_importacao_detraf=id_importacao_detraf,
        id_importacao_cdr=cdr_info["id"],
        periodo_inicio=periodo_inicio,
        periodo_fim=periodo_fim,
        notificar_execucao=_callback_execucao(exec_id),
    )
    return {
        "resumo": resumo,
        "id_importacao_cdr": cdr_info["id"],
        "id_execucao": exec_id,
    }


STATUS_VALIDOS = {"CONFERIDO", "DIVERGENTE", "PERDIDO"}


def _filtrar_status_param(valores: Optional[List[str]]) -> List[str]:
    if not valores:
        return []
    resultado: List[str] = []
    for valor in valores:
        chave = (valor or "").strip().upper()
        if chave in STATUS_VALIDOS and chave not in resultado:
            resultado.append(chave)
    return resultado


def _formatar_segundos(valor: Optional[int]) -> str:
    if valor is None:
        return "--"
    total = max(0, int(valor))
    horas, resto = divmod(total, 3600)
    minutos, segundos = divmod(resto, 60)
    return f"{horas:02d}:{minutos:02d}:{segundos:02d}"


def _formatar_data_display(dt: Optional[datetime]) -> tuple[str, str]:
    if not dt:
        return "--", "--"
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S")


def _formatar_janela(inicio: Optional[date], fim: Optional[date]) -> str:
    if not inicio and not fim:
        return "--"
    if inicio and fim:
        return f"{inicio:%Y%m} – {fim:%Y%m}"
    ref = inicio or fim
    return ref.strftime("%Y%m") if ref else "--"


def _parse_data_param(valor: Optional[str]) -> Optional[datetime]:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor)
    except ValueError:
        try:
            return datetime.strptime(valor, "%Y-%m-%d")
        except ValueError:
            return None


def _montar_filtros_conferencia(
    id_importacao: int,
    status: Optional[List[str]],
    busca: Optional[str],
    descritor: Optional[str],
    gh: Optional[str],
    apenas_sem_cdr: bool,
    diferenca_min: Optional[int],
    eot_divergente: bool = False,
    cruza_gh: bool = False,
    tarifa: Optional[str] = None,
    assinante_a: Optional[str] = None,
    assinante_b: Optional[str] = None,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
    multi_divergencias: bool = False,
    gh_inconsistente: bool = False,
    sigame: bool = False,
):
    tabela = "conferencia_resultados"

    def col(nome: str) -> str:
        return f"{tabela}.{nome}"

    condicoes = [f"{col('id_importacao_detraf')} = %s"]
    parametros: List = [id_importacao]

    status_filtrados = _filtrar_status_param(status)
    if status_filtrados:
        condicoes.append(f"{col('status')} IN (" + ",".join(["%s"] * len(status_filtrados)) + ")")
        parametros.extend(status_filtrados)

    if busca:
        termo = busca.strip()
        termo_digits = re.sub(r"\D", "", termo)
        alvo = termo_digits or termo
        if alvo:
            condicoes.append(f"({col('assinante_a')} LIKE %s OR {col('assinante_b')} LIKE %s)")
            like = f"%{alvo}%"
            parametros.extend([like, like])

    if descritor:
        condicoes.append(f"{col('descritor')} = %s")
        parametros.append(descritor.strip().upper())

    if gh:
        condicoes.append(f"{col('gh')} = %s")
        parametros.append(gh.strip().upper())

    if apenas_sem_cdr:
        condicoes.append(f"{col('id_registro_cdr')} IS NULL")

    if diferenca_min is not None:
        condicoes.append(f"{col('delta_duracao_seg')} > %s")
        parametros.append(int(diferenca_min))

    if eot_divergente:
        condicoes.append(
            f"""(
                {col('eot_detraf')} IS NOT NULL AND {col('eot_cdr')} IS NOT NULL
                AND UPPER(TRIM({col('eot_detraf')})) <> UPPER(TRIM({col('eot_cdr')}))
            )"""
        )

    if cruza_gh:
        condicoes.append(
            f"""
            EXISTS (
                SELECT 1
                FROM detraf_normalizado dn
                WHERE dn.id_importacao = {tabela}.id_importacao_detraf
                  AND dn.id_registro = {tabela}.id_registro_detraf
                  AND dn.segundos_gh_normal > 0
                  AND dn.segundos_gh_reduzido > 0
            )
            """
        )

    if gh_inconsistente:
        condicoes.append(
            f"""
            EXISTS (
                SELECT 1
                FROM detraf_normalizado dn
                WHERE dn.id_importacao = {tabela}.id_importacao_detraf
                  AND dn.id_registro = {tabela}.id_registro_detraf
                  AND (
                      (UPPER(COALESCE(dn.gh,'')) = 'N' AND dn.segundos_gh_reduzido > 0)
                      OR (UPPER(COALESCE(dn.gh,'')) = 'R' AND dn.segundos_gh_normal > 0)
                  )
            )
            """
        )

    if sigame:
        condicoes.append(
            f"""
            (
                COALESCE(JSON_VALID({col('snapshot_cdr')}), 0) = 1
                AND JSON_EXTRACT({col('snapshot_cdr')}, '$.sigame') IS NOT NULL
                AND COALESCE(
                    JSON_UNQUOTE(JSON_EXTRACT({col('snapshot_cdr')}, '$.sigame')),
                    ''
                ) <> ''
            )
            """
        )

    if tarifa:
        tarifa_limpa = tarifa.strip().upper()
        if tarifa_limpa == "CNG":
            condicoes.append(
                f"""
                EXISTS (
                    SELECT 1
                    FROM detraf_normalizado dn
                    WHERE dn.id_importacao = {tabela}.id_importacao_detraf
                      AND dn.id_registro = {tabela}.id_registro_detraf
                      AND (
                          UPPER(COALESCE(dn.poi,'')) = 'CNG'
                          OR dn.assinante_b_norm LIKE '0800%%'
                          OR dn.assinante_b_norm LIKE '800%%'
                      )
                )
                """
            )
        else:
            condicoes.append(
                f"""
                EXISTS (
                    SELECT 1
                    FROM detraf_normalizado dn
                    WHERE dn.id_importacao = {tabela}.id_importacao_detraf
                      AND dn.id_registro = {tabela}.id_registro_detraf
                      AND UPPER(COALESCE(dn.tarifa_aplicada,'')) = %s
                )
                """
            )
            parametros.append(tarifa_limpa)

    if assinante_a:
        condicoes.append(f"{col('assinante_a')} LIKE %s")
        parametros.append(f"%{assinante_a.strip()}%")

    if assinante_b:
        condicoes.append(f"{col('assinante_b')} LIKE %s")
        parametros.append(f"%{assinante_b.strip()}%")

    inicio_dt = _parse_data_param(data_inicio)
    fim_dt = _parse_data_param(data_fim)
    if inicio_dt:
        condicoes.append(f"{col('data_hora')} >= %s")
        parametros.append(inicio_dt)
    if fim_dt:
        condicoes.append(f"{col('data_hora')} <= %s")
        parametros.append(fim_dt)

    if multi_divergencias:
        condicoes.append(
            f"""
            (
                {col('detalhes_divergencia')} IS NOT NULL
                AND {col('detalhes_divergencia')} <> ''
                AND JSON_VALID({col('detalhes_divergencia')})
                AND JSON_LENGTH({col('detalhes_divergencia')}) > 1
            )
            """
        )

    where = " AND ".join(condicoes)
    where_alias = where.replace(f"{tabela}.", "cr.")
    return where, where_alias, parametros


def _consultar_conferencia_resultados(
    where: str,
    where_alias: str,  # mantido para compatibilidade futura
    parametros: List,
    limite: Optional[int],
    offset: int = 0,
):
    conexao = db()
    try:
        cursor = conexao.cursor(dictionary=True)
        sql_count = f"SELECT COUNT(1) AS total FROM conferencia_resultados WHERE {where}"
        try:
            cursor.execute(sql_count, tuple(parametros))
        except mysql.connector.Error as exc:
            _registrar_sql_erro("sql_count_erro", sql_count, parametros, exc)
            raise
        total = int(cursor.fetchone()["total"] or 0)

        consulta_sql = (
            f"""
            SELECT
                conferencia_resultados.id,
                conferencia_resultados.status,
                conferencia_resultados.observacao,
                conferencia_resultados.descricao_divergencia,
                conferencia_resultados.detalhes_divergencia,
                conferencia_resultados.snapshot_cdr,
                conferencia_resultados.assinante_a,
                conferencia_resultados.assinante_b,
                conferencia_resultados.descritor,
                conferencia_resultados.gh,
                conferencia_resultados.data_hora,
                conferencia_resultados.duracao_detraf_seg,
                conferencia_resultados.duracao_cdr_seg,
                conferencia_resultados.eot_detraf,
                conferencia_resultados.eot_cdr,
                conferencia_resultados.delta_duracao_seg,
                conferencia_resultados.delta_hora_seg,
                conferencia_resultados.id_registro_detraf,
                conferencia_resultados.id_registro_cdr
            FROM conferencia_resultados
            WHERE {where}
            ORDER BY FIELD(conferencia_resultados.status,'CONFERIDO','DIVERGENTE','PERDIDO'),
                     conferencia_resultados.data_hora ASC,
                     conferencia_resultados.id ASC
            """
        )
        consulta_parametros = list(parametros)
        if limite is not None:
            consulta_sql += " LIMIT %s OFFSET %s"
            consulta_parametros.extend([limite, offset])
        try:
            cursor.execute(consulta_sql, tuple(consulta_parametros))
        except mysql.connector.Error as exc:
            _registrar_sql_erro("sql_listagem_erro", consulta_sql, consulta_parametros, exc)
            raise
        registros = cursor.fetchall()
        return total, registros
    finally:
        conexao.close()


def _carregar_snapshot(payload):
    if not payload:
        return {}
    if isinstance(payload, (dict, list)):
        return payload
    try:
        return json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return {"raw": payload}


def _obter_disposition_cdr(snapshot_payload) -> str:
    if not snapshot_payload:
        return ""
    dados = snapshot_payload if isinstance(snapshot_payload, dict) else _carregar_snapshot(snapshot_payload)
    if not dados:
        return ""
    valor = (
        dados.get("disposition")
        or dados.get("Disposition")
        or dados.get("DISPOSITION")
        or dados.get("cdr_disposition")
    )
    return str(valor).strip().upper() if valor else ""


def _extrair_sigame_snapshot(snapshot_payload) -> Tuple[bool, Optional[str]]:
    if not snapshot_payload:
        return False, None
    dados = snapshot_payload if isinstance(snapshot_payload, dict) else _carregar_snapshot(snapshot_payload)
    if not isinstance(dados, dict) or not dados:
        return False, None
    sigame_bruto = dados.get("sigame")
    if not sigame_bruto:
        return False, None
    destino = dados.get("sigame_destino_norm") or dados.get("sigame_destino_raw")
    if destino is not None:
        destino = str(destino).strip() or None
    return True, destino


def _filtrar_detalhes_divergencia(
    detalhes_raw,
    disposition: str,
) -> Tuple[List[dict], List[str], bool]:
    if not detalhes_raw:
        return [], [], False
    if isinstance(detalhes_raw, str):
        try:
            detalhes = json.loads(detalhes_raw)
        except (json.JSONDecodeError, TypeError):
            detalhes = []
    else:
        detalhes = detalhes_raw
    if not isinstance(detalhes, list):
        return [], [], False
    ignorar_eot = disposition and disposition != "ANSWERED"
    detalhes_filtrados: List[dict] = []
    tipos_filtrados: List[str] = []
    possui_eot_considerado = False
    for item in detalhes:
        if not isinstance(item, dict):
            continue
        tipo = (item.get("tipo") or "divergência").strip() or "divergência"
        eh_eot = tipo.lower() == "eot"
        if eh_eot:
            if ignorar_eot:
                continue
            possui_eot_considerado = True
        detalhes_filtrados.append(item)
        tipos_filtrados.append(tipo)
        return detalhes_filtrados, tipos_filtrados, possui_eot_considerado


def _preencher_partes_detraf(partes: list):
    if not partes:
        return
    precisam_busca = [parte for parte in partes if parte.get("id") and not parte.get("assinante_a")]
    if not precisam_busca:
        return
    ids = [parte.get("id") for parte in precisam_busca if parte.get("id")]
    if not ids:
        return
    placeholders = ",".join(["%s"] * len(ids))
    conexao = db()
    try:
        cursor = conexao.cursor(dictionary=True)
        cursor.execute(
            f"""
            SELECT id, sequencial, assinante_a, assinante_b, data_chamada, hora_atendimento,
                   gh, duracao_real_segundos, duracao_calculada, eqt_credora, eqt_devedora,
                   poi, valor_remuneracao
            FROM detraf_operadora_batimento
            WHERE id IN ({placeholders})
            """,
            ids,
        )
        registros = {linha["id"]: linha for linha in cursor.fetchall()}
    finally:
        conexao.close()

    for parte in partes:
        origem = registros.get(parte.get("id"))
        if not origem:
            continue
        parte["sequencial"] = origem.get("sequencial") or parte.get("sequencial")
        parte["assinante_a"] = origem.get("assinante_a") or parte.get("assinante_a")
        parte["assinante_b"] = origem.get("assinante_b") or parte.get("assinante_b")
        parte["data_chamada"] = str(origem.get("data_chamada") or parte.get("data_chamada") or "")
        parte["hora_atendimento"] = str(origem.get("hora_atendimento") or parte.get("hora_atendimento") or "")
        parte["poi"] = origem.get("poi") or parte.get("poi")
        parte["eqt_credora"] = origem.get("eqt_credora") or parte.get("eqt_credora")
        parte["eqt_devedora"] = origem.get("eqt_devedora") or parte.get("eqt_devedora")
        parte["valor_remuneracao"] = origem.get("valor_remuneracao") if origem.get("valor_remuneracao") is not None else parte.get("valor_remuneracao")
        parte["duracao_real_segundos"] = int(origem.get("duracao_real_segundos") or parte.get("duracao_real_segundos") or 0)
        calc = origem.get("duracao_calculada")
        if calc is not None:
            parte["duracao_calculada_seg"] = int(round(float(calc) * 60))


def marcar_arquivo_removido(caminho: Path) -> None:
    conexao = db()
    try:
        cursor = conexao.cursor()
        cursor.execute(
            """
            UPDATE arquivos_importacao
            SET removido_em = NOW()
            WHERE caminho_arquivo = %s AND removido_em IS NULL
            """,
            (str(caminho),),
        )
        conexao.commit()
    finally:
        conexao.close()


def _caminho_log_seguro(nome: str) -> Path:
    """Evita escalonamentos de path; restringe aos arquivos conhecidos na pasta de logs."""
    nome_limpo = os.path.basename(nome)
    caminho = LOG_DIR / nome_limpo
    if not caminho.exists() or not caminho.is_file():
        raise HTTPException(status_code=404, detail="Log não encontrado.")
    return caminho


def _listar_logs() -> List[dict]:
    itens: List[tuple[float, dict]] = []
    for entrada in LOG_DIR.glob("*.log"):
        try:
            stat = entrada.stat()
        except OSError:
            continue
        itens.append(
            (
                stat.st_mtime,
                {
                    "nome": entrada.name,
                    "tamanho_bytes": stat.st_size,
                    "modificado_em": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "criado_em": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                },
            )
        )
    itens.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in itens]



# ======================================
# Endpoints principais
# ======================================

@app.get("/api/kpis", response_model=Kpis)
def get_kpis():
    """Retorna KPIs principais"""
    c = db()
    try:
        cur = c.cursor(dictionary=True)
        cur.execute("SELECT COUNT(1) AS total FROM detraf_operadora_batimento")
        total = cur.fetchone()["total"] or 0

        mapa = {}
        if _coluna_existe("detraf_operadora_batimento", "classificacao"):
            cur.execute(
                """
                SELECT classificacao, COUNT(1) AS q
                FROM detraf_operadora_batimento
                GROUP BY classificacao
                """
            )
            mapa = { (r["classificacao"] or "").lower(): int(r["q"]) for r in cur.fetchall() }

        conf = mapa.get("conferido", 0)
        divg = mapa.get("divergente", 0)
        perd = mapa.get("perdido", 0)

        def pct(x): 
            return round((x / total * 100.0), 1) if total else 0.0

        return Kpis(
            total=total,
            percent_conferido=pct(conf),
            percent_divergente=pct(divg),
            percent_perdido=pct(perd),
        )
    finally:
        c.close()


@app.get("/api/classificacao")
def get_classificacao():
    """Retorna dados para o gráfico de pizza"""
    if not _coluna_existe("detraf_operadora_batimento", "classificacao"):
        return []

    c = db()
    try:
        cur = c.cursor(dictionary=True)
        cur.execute("""
            SELECT classificacao AS name, COUNT(1) AS value
            FROM detraf_operadora_batimento
            GROUP BY classificacao
        """)
        return [{"name": r["name"], "value": int(r["value"])} for r in cur.fetchall()]
    finally:
        c.close()


@app.get("/api/volumes")
def get_volumes():
    """Retorna dados para o gráfico de barras"""
    if not _coluna_existe("detraf_operadora_batimento", "tipo_chamada"):
        return []

    c = db()
    try:
        cur = c.cursor(dictionary=True)
        cur.execute("""
            SELECT COALESCE(tipo_chamada, 'Outros') AS name, COUNT(1) AS value
            FROM detraf_operadora_batimento
            GROUP BY tipo_chamada
            ORDER BY value DESC LIMIT 8
        """)
        return [{"name": r["name"], "value": int(r["value"])} for r in cur.fetchall()]
    finally:
        c.close()

@app.get("/api/clientes")
def listar_clientes():
    """Lista clientes ativos."""
    conexao = db()
    try:
        cursor = conexao.cursor(dictionary=True)
        cursor.execute("""
            SELECT id_cliente, nome_cliente
            FROM clientes
            WHERE ativo = 1
            ORDER BY nome_cliente
        """)
        return cursor.fetchall()
    finally:
        conexao.close()


@app.post("/api/clientes")
def cadastrar_cliente(entrada: ClienteEntrada):
    """Cadastra um novo cliente ativo."""
    nome = (entrada.nome_cliente or "").strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Nome do cliente é obrigatório.")

    conexao = db()
    novo_id = None
    try:
        cursor = conexao.cursor()
        cursor.execute(
            "INSERT INTO clientes (nome_cliente) VALUES (%s)",
            (nome,),
        )
        conexao.commit()
        novo_id = cursor.lastrowid
    finally:
        conexao.close()

    banco = None
    if novo_id:
        try:
            banco = garantir_banco_cliente(novo_id)
        except ValueError:
            banco = None

    resposta = {"mensagem": "Cliente cadastrado com sucesso.", "id_cliente": novo_id}
    if banco:
        resposta["banco"] = banco
    return resposta


@app.get("/api/imports")
def list_imports():
    """Lista todas as importações"""
    conexao = db()
    try:
        cursor = conexao.cursor(dictionary=True)
        cursor.execute("""
            SELECT ci.id,
                   ci.id_cliente,
                   ci.nome_arquivo,
                   ci.tipo_arquivo,
                   ci.periodo_inicial,
                   ci.periodo_final,
                   ci.eqt_credora,
                   ci.eqt_devedora,
                   ci.linhas_processadas,
                    ci.data_importacao,
                    ci.status,
                    ci.mensagem,
                    cli.nome_cliente
            FROM controle_importacoes ci
            LEFT JOIN clientes cli ON cli.id_cliente = ci.id_cliente
            ORDER BY ci.data_importacao DESC, ci.id DESC
            LIMIT 100
        """)
        return cursor.fetchall()
    finally:
        conexao.close()


@app.get("/api/imports/{imp_id}")
def get_import(imp_id: int):
    """Retorna uma importação específica"""
    conexao = db()
    try:
        cursor = conexao.cursor(dictionary=True)
        cursor.execute("""
            SELECT ci.id,
                   ci.id_cliente,
                   ci.nome_arquivo,
                   ci.tipo_arquivo,
                   ci.periodo_inicial,
                   ci.periodo_final,
                   ci.eqt_credora,
                   ci.eqt_devedora,
                   ci.linhas_processadas,
                    ci.data_importacao,
                    ci.status,
                    ci.mensagem,
                    cli.nome_cliente
            FROM controle_importacoes ci
            LEFT JOIN clientes cli ON cli.id_cliente = ci.id_cliente
            WHERE ci.id = %s
        """, (imp_id,))
        registro = cursor.fetchone()
        return registro or {}
    finally:
        conexao.close()


@app.get("/api/operadoras")
def listar_operadoras():
    """Retorna a lista distinta de operadoras cadastradas na tabela EOT."""
    conexao = db()
    try:
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT DISTINCT nome_fantasia FROM eot WHERE nome_fantasia IS NOT NULL AND nome_fantasia <> '' ORDER BY nome_fantasia ASC"
        )
        registros = cursor.fetchall()
        return [linha[0] for linha in registros if linha and linha[0]]
    finally:
        conexao.close()


@app.post("/api/imports")
def upload_import(
    id_cliente: int = Form(...),
    tipo_arquivo: str = Form(...),
    arquivo: UploadFile = File(...),
):
    """Recebe e processa importações CDR ou DETRAF."""
    tipo = (tipo_arquivo or "").strip().upper()
    if tipo not in ("CDR", "DETRAF"):
        raise HTTPException(status_code=400, detail="Tipo de arquivo inválido.")

    nome_original = arquivo.filename or ""
    extensao = Path(nome_original).suffix.lower()
    if tipo == "CDR" and extensao != ".sql":
        raise HTTPException(status_code=400, detail="Arquivos CDR devem estar no formato .sql.")
    if tipo == "DETRAF" and extensao != ".txt":
        raise HTTPException(status_code=400, detail="Arquivos DETRAF devem estar no formato .txt.")

    destino = VAR_DIR / "tmp" / f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{nome_original}"
    with open(destino, "wb") as saida:
        while chunk := arquivo.file.read(1024 * 1024):
            saida.write(chunk)
    arquivo.file.close()

    conexao = db()
    try:
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT 1 FROM clientes WHERE id_cliente=%s AND ativo = 1",
            (id_cliente,),
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Cliente não encontrado.")

        cursor.execute(
            """
            INSERT INTO controle_importacoes (id_cliente, nome_arquivo, tipo_arquivo, status, mensagem)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (id_cliente, nome_original, tipo, "PROCESSANDO", "Arquivo recebido. Iniciando processamento."),
        )
        conexao.commit()
        id_importacao = cursor.lastrowid
    finally:
        conexao.close()

    registrar_arquivo_importado(id_importacao, destino, tipo)

    def processar_importacao(path: Path, tipo_importacao: str, id_registro: int, id_cliente_thread: int):
        try:
            if tipo_importacao == "CDR":
                atualizar_controle_importacao(
                    id_registro,
                    mensagem="Processando dump CDR (preparando importação)...",
                )
                (
                    periodo_inicial,
                    periodo_final,
                    tabela,
                    novas_tabelas,
                    total_cdr,
                ) = importar_dump_cdr(
                    caminho_dump=path,
                    id_cliente=id_cliente_thread,
                    configuracao_mysql=DBCFG,
                )
                mensagem_final = "Dump CDR importado com sucesso."
                if tabela:
                    mensagem_final += f" Tabela analisada: {tabela}."
                registrar_tabelas_cdr(id_registro, novas_tabelas)
                atualizar_controle_importacao(
                    id_registro,
                    mensagem="Processando dump CDR (finalizando análise)...",
                )
                atualizar_controle_importacao(
                    id_registro,
                    status="CONCLUIDO",
                    periodo_inicial=periodo_inicial,
                    periodo_final=periodo_final,
                    mensagem=mensagem_final,
                    tabela_referencia=tabela,
                    linhas_processadas=total_cdr,
                )

                detraf_alvo = None
                try:
                    detraf_alvo = _buscar_importacao_recente(id_cliente_thread, "DETRAF")
                    if detraf_alvo:
                        conferencia = _executar_conferencia_automatica(
                            id_cliente=id_cliente_thread,
                            id_importacao_detraf=detraf_alvo["id"],
                            periodo_detraf_inicio=detraf_alvo.get("periodo_inicial"),
                            periodo_detraf_fim=detraf_alvo.get("periodo_final"),
                            id_importacao_cdr=id_registro,
                            periodo_cdr_inicio=periodo_inicial,
                            periodo_cdr_fim=periodo_final,
                        )
                        if conferencia:
                            stats = conferencia.get("resumo", {})
                            texto = (
                                f"{mensagem_final} Conferência automática executada "
                                f"(Conferidos: {stats.get('conferidos', 0)}, "
                                f"Divergentes: {stats.get('divergentes', 0)}, "
                                f"Perdidos: {stats.get('perdidos', 0)})."
                            )
                            atualizar_controle_importacao(
                                detraf_alvo["id"],
                                mensagem=texto,
                            )
                except Exception as exc:
                    alvo = detraf_alvo["id"] if isinstance(detraf_alvo, dict) else id_registro
                    atualizar_controle_importacao(
                        alvo,
                        mensagem=f"Conferência automática (via CDR) falhou: {exc}",
                    )
            else:
                resumo_detraf = processar_arquivo_detraf(
                    caminho=path,
                    id_importacao=id_registro,
                    id_cliente=id_cliente_thread,
                    obter_conexao_base=db,
                    atualizar_controle=atualizar_controle_importacao,
                )
                resumo_detraf = resumo_detraf or {}
                mensagem_final = (
                    "Arquivo DETRAF importado com sucesso. "
                    f"{resumo_detraf.get('linhas_processadas', 0)} registros processados."
                )
                periodo_inicial = resumo_detraf.get("periodo_inicial")
                periodo_final = resumo_detraf.get("periodo_final")

                try:
                    conferencia = _executar_conferencia_automatica(
                        id_cliente=id_cliente_thread,
                        id_importacao_detraf=id_registro,
                        periodo_detraf_inicio=periodo_inicial,
                        periodo_detraf_fim=periodo_final,
                    )
                    if conferencia:
                        stats = conferencia.get("resumo", {})
                        texto = (
                            f"{mensagem_final} Conferência automática executada "
                            f"(Conferidos: {stats.get('conferidos', 0)}, "
                            f"Divergentes: {stats.get('divergentes', 0)}, "
                            f"Perdidos: {stats.get('perdidos', 0)})."
                        )
                        atualizar_controle_importacao(id_registro, mensagem=texto)
                except Exception as exc:
                    atualizar_controle_importacao(
                        id_registro,
                        mensagem=f"{mensagem_final} Conferência automática falhou: {exc}",
                    )
        except Exception as erro:
            atualizar_controle_importacao(
                id_registro,
                status="ERRO",
                mensagem=str(erro),
            )
        finally:
            try:
                if path.exists():
                    path.unlink()
                    marcar_arquivo_removido(path)
            except OSError:
                pass

    threading.Thread(
        target=processar_importacao,
        args=(destino, tipo, id_importacao, id_cliente),
        daemon=True,
    ).start()

    return {"id": id_importacao, "mensagem": "Importação registrada com sucesso."}


def _montar_comando_mysql():
    comando = ["mysql"]
    if DBCFG.get("host"):
        comando.extend(["-h", str(DBCFG["host"])])
    if DBCFG.get("port"):
        comando.extend(["-P", str(DBCFG["port"])])
    if DBCFG.get("user"):
        comando.extend(["-u", str(DBCFG["user"])])
    ambiente = os.environ.copy()
    if DBCFG.get("password"):
        ambiente["MYSQL_PWD"] = str(DBCFG["password"])
    if not DBCFG.get("database"):
        raise RuntimeError("Banco padrão não configurado para importação.")
    comando.extend(["-D", str(DBCFG["database"])])
    return comando, ambiente


def _contar_registros_tabela(nome_tabela: str) -> Optional[int]:
    conexao = db()
    try:
        cursor = conexao.cursor()
        cursor.execute(f"SELECT COUNT(1) FROM `{nome_tabela}`")
        resultado = cursor.fetchone()
        return int(resultado[0]) if resultado and resultado[0] is not None else None
    except mysql.Error:
        return None
    finally:
        conexao.close()


def _importar_tabela_auxiliar(nome_tabela: str, caminho: Path) -> dict:
    registrar_log(
        "auxiliar_importacao_inicio",
        tabela=nome_tabela,
        arquivo=str(caminho),
        tamanho_bytes=caminho.stat().st_size if caminho.exists() else None,
    )
    conexao = db()
    try:
        cursor = conexao.cursor()
        cursor.execute(f"DROP TABLE IF EXISTS `{nome_tabela}`")
        conexao.commit()
    finally:
        conexao.close()

    comando, ambiente = _montar_comando_mysql()
    try:
        with open(caminho, "rb") as conteudo:
            resultado = subprocess.run(
                comando,
                stdin=conteudo,
                check=False,
                env=ambiente,
                capture_output=True,
            )
    except OSError as exc:
        registrar_log(
            "auxiliar_importacao_erro",
            tabela=nome_tabela,
            arquivo=str(caminho),
            erro=str(exc),
        )
        raise RuntimeError("Falha ao executar comando mysql.") from exc

    if resultado.returncode != 0:
        registrar_log(
            "auxiliar_importacao_erro",
            tabela=nome_tabela,
            arquivo=str(caminho),
            returncode=resultado.returncode,
            stderr=resultado.stderr.decode(errors="ignore") if resultado.stderr else "",
        )
        raise RuntimeError(f"Comando mysql retornou código {resultado.returncode}.")

    total_registros = _contar_registros_tabela(nome_tabela)
    registrar_log(
        "auxiliar_importacao_concluida",
        tabela=nome_tabela,
        arquivo=str(caminho),
        total_registros=total_registros,
    )
    return {
        "tabela": nome_tabela,
        "total_registros": total_registros,
    }


@app.post("/api/importacoes/auxiliares/{tabela_id}")
def importar_tabela_auxiliar_endpoint(tabela_id: str, arquivo: UploadFile = File(...)):
    """Recebe dumps auxiliares (.sql), substitui a tabela alvo e registra histórico."""
    tabela = (tabela_id or "").strip().lower()
    if tabela not in TABELAS_AUXILIARES:
        raise HTTPException(status_code=400, detail="Tabela auxiliar inválida.")

    nome_original = arquivo.filename or "dump.sql"
    if not nome_original.lower().endswith(".sql"):
        raise HTTPException(status_code=400, detail="Envie arquivos no formato .sql.")

    destino = VAR_DIR / "tmp" / f"{datetime.now():%Y%m%d%H%M%S}_{tabela}_{Path(nome_original).name}"
    with open(destino, "wb") as saida:
        while chunk := arquivo.file.read(1024 * 1024):
            saida.write(chunk)
    arquivo.file.close()

    tamanho = destino.stat().st_size if destino.exists() else None
    registro_id = registrar_importacao_auxiliar_inicio(tabela, nome_original, tamanho)
    try:
        resultado = _importar_tabela_auxiliar(tabela, destino)
        total = resultado.get("total_registros")
        atualizar_importacao_auxiliar(
            registro_id,
            status="CONCLUIDO",
            total_registros=total,
            mensagem="Importação concluída com sucesso.",
        )
        resposta = {
            "tabela": tabela,
            "arquivo": nome_original,
            "tamanho_bytes": tamanho,
            "total_registros": total,
            "mensagem": "Importação concluída com sucesso.",
        }
        return resposta
    except Exception as exc:
        atualizar_importacao_auxiliar(
            registro_id,
            status="ERRO",
            mensagem=str(exc),
        )
        raise HTTPException(status_code=500, detail=f"Falha ao importar tabela {tabela.upper()}: {exc}")
    finally:
        try:
            if destino.exists():
                destino.unlink()
        except OSError:
            pass


@app.get("/api/importacoes/auxiliares")
def listar_importacoes_auxiliares():
    """Histórico completo dos uploads auxiliares, usado na aba da web."""
    conexao = db()
    try:
        cursor = conexao.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, tabela_alvo, nome_arquivo, tamanho_bytes, total_registros,
                   status, mensagem, criado_em, atualizado_em
            FROM importacoes_auxiliares
            ORDER BY criado_em DESC, id DESC
            LIMIT 100
            """
        )
        return cursor.fetchall()
    finally:
        conexao.close()


# ======================================
# Conferência - visão e filtros
# ======================================


@app.get("/api/conferencia/importacoes")
def listar_conferencia_importacoes():
    conexao = db()
    try:
        cursor = conexao.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT ci.id,
                   ci.id_cliente,
                   ci.nome_arquivo,
                   ci.periodo_inicial,
                   ci.periodo_final,
                   ci.eqt_credora,
                   ci.eqt_devedora,
                   ci.linhas_processadas,
                   cli.nome_cliente,
                   COALESCE(SUM(CASE WHEN cr.status = 'CONFERIDO' THEN 1 ELSE 0 END), 0) AS conferidos,
                   COALESCE(SUM(CASE WHEN cr.status = 'DIVERGENTE' THEN 1 ELSE 0 END), 0) AS divergentes,
                   COALESCE(SUM(CASE WHEN cr.status = 'PERDIDO' THEN 1 ELSE 0 END), 0) AS perdidos,
                   gh.seg_reduz_cob AS seg_reduzidos_cobrados,
                   gh.seg_reduz_val AS seg_reduzidos_validados
            FROM controle_importacoes ci
            INNER JOIN clientes cli ON cli.id_cliente = ci.id_cliente
            LEFT JOIN conferencia_resultados cr ON cr.id_importacao_detraf = ci.id
            LEFT JOIN (
                SELECT id_importacao,
                       SUM(CASE WHEN gh = 'R' THEN duracao_segundos ELSE 0 END) AS seg_reduz_cob,
                       SUM(segundos_gh_reduzido) AS seg_reduz_val
                FROM detraf_normalizado
                GROUP BY id_importacao
            ) gh ON gh.id_importacao = ci.id
            WHERE ci.tipo_arquivo = 'DETRAF'
              AND ci.status <> 'REMOVIDO'
            GROUP BY ci.id, ci.id_cliente, ci.nome_arquivo, ci.periodo_inicial, ci.periodo_final,
                     ci.eqt_credora, ci.eqt_devedora, ci.linhas_processadas, cli.nome_cliente,
                     gh.seg_reduz_cob, gh.seg_reduz_val
            ORDER BY ci.data_importacao DESC, ci.id DESC
            LIMIT 50
            """
        )
        resposta = []
        for linha in cursor.fetchall():
            conferidos = int(linha.get("conferidos") or 0)
            divergentes = int(linha.get("divergentes") or 0)
            perdidos = int(linha.get("perdidos") or 0)
            seg_reduz_cob = int(linha.get("seg_reduzidos_cobrados") or 0)
            seg_reduz_val = int(linha.get("seg_reduzidos_validados") or 0)
            total_resultados = conferidos + divergentes + perdidos
            processadas = int(linha.get("linhas_processadas") or total_resultados)
            percentual = round((conferidos / processadas * 100), 1) if processadas else 0.0
            resposta.append(
                {
                    "id": linha["id"],
                    "id_cliente": linha["id_cliente"],
                    "cliente": linha.get("nome_cliente"),
                    "arquivo": linha.get("nome_arquivo"),
                    "periodo_inicial": linha.get("periodo_inicial"),
                    "periodo_final": linha.get("periodo_final"),
                    "eqt_credora": linha.get("eqt_credora"),
                    "eqt_devedora": linha.get("eqt_devedora"),
                    "processadas": processadas,
                    "conferidos": conferidos,
                    "divergentes": divergentes,
                    "perdidos": perdidos,
                    "percentual_conferido": percentual,
                    "tem_resultados": total_resultados > 0,
                    "segundos_reduzidos_cobrados": seg_reduz_cob,
                    "segundos_reduzidos_validados": seg_reduz_val,
                }
            )
        return resposta
    finally:
        conexao.close()


@app.get("/api/conferencia/cdrs")
def listar_conferencia_cdrs(id_cliente: int):
    conexao = db()
    try:
        cursor = conexao.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, nome_arquivo, periodo_inicial, periodo_final, tabela_referencia, data_importacao
            FROM controle_importacoes
            WHERE id_cliente = %s AND tipo_arquivo = 'CDR' AND status = 'CONCLUIDO'
            ORDER BY data_importacao DESC, id DESC
            LIMIT 50
            """,
            (id_cliente,),
        )
        return cursor.fetchall()
    finally:
        conexao.close()


@app.get("/api/conferencia/resumo")
def obter_conferencia_resumo(id_importacao: int):
    conexao = db()
    try:
        cursor = conexao.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT ci.*, cli.nome_cliente
            FROM controle_importacoes ci
            INNER JOIN clientes cli ON cli.id_cliente = ci.id_cliente
            WHERE ci.id = %s AND ci.tipo_arquivo = 'DETRAF'
            LIMIT 1
            """,
            (id_importacao,),
        )
        info = cursor.fetchone()
        if not info:
            raise HTTPException(status_code=404, detail="Importação não encontrada para conferência.")

        cursor.execute(
            """
            SELECT status, COUNT(1) AS total
            FROM conferencia_resultados
            WHERE id_importacao_detraf = %s
            GROUP BY status
            """,
            (id_importacao,),
        )
        contagens = {linha["status"]: int(linha["total"] or 0) for linha in cursor.fetchall()}
        total_resultados = sum(contagens.values())
        processadas = total_resultados if total_resultados else 0
        validas = contagens.get("CONFERIDO", 0) if total_resultados else 0
        invalidas = total_resultados - validas if total_resultados else 0

        ordem_status = ["CONFERIDO", "DIVERGENTE", "PERDIDO"]
        resumo = []
        for chave in ordem_status:
            valor = contagens.get(chave, 0)
            percentual = round((valor / total_resultados * 100), 1) if total_resultados else 0.0
            resumo.append({"status": chave, "total": valor, "percentual": percentual})

        cursor.execute(
            """
            SELECT descritor, COUNT(1) AS total
            FROM conferencia_resultados
            WHERE id_importacao_detraf = %s AND descritor IS NOT NULL AND descritor <> ''
            GROUP BY descritor
            ORDER BY total DESC, descritor ASC
            LIMIT 8
            """,
            (id_importacao,),
        )
        descritores = [
            {"valor": linha["descritor"], "quantidade": int(linha["total"] or 0)}
            for linha in cursor.fetchall()
        ]

        cursor.execute(
            """
            SELECT gh, COUNT(1) AS total
            FROM conferencia_resultados
            WHERE id_importacao_detraf = %s AND gh IS NOT NULL AND gh <> ''
            GROUP BY gh
            ORDER BY total DESC, gh ASC
            LIMIT 8
            """,
            (id_importacao,),
        )
        ghs = [
            {"valor": linha["gh"], "quantidade": int(linha["total"] or 0)}
            for linha in cursor.fetchall()
        ]

        cursor.execute(
            """
            SELECT COUNT(1) AS total
            FROM conferencia_resultados
            WHERE id_importacao_detraf = %s AND id_registro_cdr IS NULL
            """,
            (id_importacao,),
        )
        sem_cdr = int(cursor.fetchone()["total"] or 0)

        dashboard_metricas = {}

        cursor.execute(
            """
            SELECT COUNT(*) AS total_registros,
                   COUNT(DISTINCT CONCAT_WS('|',
                       COALESCE(assinante_a,''),
                       COALESCE(assinante_b,''),
                       DATE_FORMAT(data_chamada,'%Y-%m-%d'),
                       COALESCE(hora_atendimento,'')
                   )) AS total_chamadas,
                   SUM(duracao_real_segundos) AS seg_arquivo
            FROM detraf_operadora_batimento
            WHERE id_importacao = %s
            """,
            (id_importacao,),
        )
        arquivo_info = cursor.fetchone() or {}
        dashboard_metricas["arquivo"] = {
            "registros": int(arquivo_info.get("total_registros") or 0),
            "chamadas": int(arquivo_info.get("total_chamadas") or 0),
            "segundos_totais": int(arquivo_info.get("seg_arquivo") or 0),
        }

        cursor.execute(
            """
            SELECT
                SUM(CASE WHEN gh = 'R' THEN duracao_segundos ELSE 0 END) AS seg_reduz_cob,
                SUM(CASE WHEN gh = 'N' THEN duracao_segundos ELSE 0 END) AS seg_normal_cob,
                SUM(segundos_gh_normal) AS seg_normal_val,
                SUM(segundos_gh_reduzido) AS seg_reduz_val
            FROM detraf_normalizado
            WHERE id_importacao = %s
            """,
            (id_importacao,),
        )
        metrica = cursor.fetchone() or {}
        gh_metricas = {
            "segundos_reduzidos_cobrados": int(metrica.get("seg_reduz_cob") or 0),
            "segundos_normais_cobrados": int(metrica.get("seg_normal_cob") or 0),
            "segundos_reduzidos_validados": int(metrica.get("seg_reduz_val") or 0),
            "segundos_normais_validados": int(metrica.get("seg_normal_val") or 0),
        }

        cursor.execute(
            """
            SELECT
                SUM(duracao_detraf_seg) AS seg_total,
                SUM(CASE WHEN status = 'CONFERIDO' THEN duracao_detraf_seg ELSE 0 END) AS seg_validos,
                SUM(CASE WHEN delta_duracao_seg > %s THEN 1 ELSE 0 END) AS qtd_acima_tolerancia
            FROM conferencia_resultados
            WHERE id_importacao_detraf = %s
            """,
            (TOLERANCIA_DURACAO_SEG, id_importacao),
        )
        duracao_metricas = cursor.fetchone() or {}
        seg_total = int(duracao_metricas.get("seg_total") or 0)
        seg_validos = int(duracao_metricas.get("seg_validos") or 0)
        seg_invalidos = max(0, seg_total - seg_validos)
        dashboard_metricas.update(
            {
            "segundos_totais": seg_total,
            "segundos_validos": seg_validos,
            "segundos_invalidos": seg_invalidos,
            "chamadas_delta_acima_tolerancia": int(duracao_metricas.get("qtd_acima_tolerancia") or 0),
            }
        )

        cursor.execute(
            """
            SELECT detalhes_divergencia, snapshot_cdr
            FROM conferencia_resultados
            WHERE id_importacao_detraf = %s
              AND detalhes_divergencia IS NOT NULL
              AND detalhes_divergencia <> ''
            """,
            (id_importacao,),
        )
        eot_divergente = 0
        gh_divergente = 0
        mult_divergencias = 0
        divergencias_por_tipo: Counter[str] = Counter()
        for linha in cursor.fetchall():
            disposition = _obter_disposition_cdr(linha.get("snapshot_cdr"))
            _, tipos_validos, possui_eot = _filtrar_detalhes_divergencia(linha.get("detalhes_divergencia"), disposition)
            if not tipos_validos:
                continue
            if len(tipos_validos) > 1:
                mult_divergencias += 1
            tipo_inconsistente = {tipo.lower() for tipo in tipos_validos}
            if "gh" in tipo_inconsistente:
                gh_divergente += 1
            for tipo in tipos_validos:
                tipo_norm = tipo.strip() or "outros"
                divergencias_por_tipo[tipo_norm] += 1
            if possui_eot:
                eot_divergente += 1
        dashboard_metricas["chamadas_eot_divergente"] = eot_divergente
        dashboard_metricas["chamadas_gh_divergente"] = gh_divergente
        dashboard_metricas["chamadas_multiplas_divergencias"] = mult_divergencias
        dashboard_metricas["divergencias_por_tipo"] = [
            {"tipo": tipo, "quantidade": quantidade}
            for tipo, quantidade in divergencias_por_tipo.most_common(8)
        ]

        cond_cng = "(UPPER(COALESCE(poi,'')) = 'CNG' OR assinante_b_norm LIKE '0800%%' OR assinante_b_norm LIKE '800%%')"
        cond_dest_movel = "(CHAR_LENGTH(assinante_b_norm) = 11 AND SUBSTRING(assinante_b_norm,3,1) = '9')"
        cond_dest_fixo = "(CHAR_LENGTH(assinante_b_norm) >= 10 AND SUBSTRING(assinante_b_norm,3,1) IN ('2','3','4','5'))"
        cursor.execute(
            f"""
            SELECT
                COUNT(1) AS total_chamadas,
                SUM(duracao_segundos) AS seg_total,
                SUM(CASE WHEN {cond_cng} THEN 1 ELSE 0 END) AS chamadas_cng,
                SUM(CASE WHEN {cond_cng} THEN duracao_segundos ELSE 0 END) AS seg_cng,
                SUM(CASE WHEN {cond_cng} AND UPPER(COALESCE(tarifa_aplicada,'')) = 'VU-M' THEN 1 ELSE 0 END) AS chamadas_cng_movel,
                SUM(CASE WHEN {cond_cng} AND UPPER(COALESCE(tarifa_aplicada,'')) = 'VU-M' THEN duracao_segundos ELSE 0 END) AS seg_cng_movel,
                SUM(CASE WHEN {cond_cng} AND UPPER(COALESCE(tarifa_aplicada,'')) = 'TU-RL' THEN 1 ELSE 0 END) AS chamadas_cng_fixo,
                SUM(CASE WHEN {cond_cng} AND UPPER(COALESCE(tarifa_aplicada,'')) = 'TU-RL' THEN duracao_segundos ELSE 0 END) AS seg_cng_fixo,
                SUM(CASE WHEN UPPER(COALESCE(tarifa_aplicada,'')) = 'VU-M' THEN 1 ELSE 0 END) AS chamadas_moveis,
                SUM(CASE WHEN UPPER(COALESCE(tarifa_aplicada,'')) = 'VU-M' THEN duracao_segundos ELSE 0 END) AS seg_moveis,
                SUM(CASE WHEN UPPER(COALESCE(tarifa_aplicada,'')) = 'TU-RL' THEN 1 ELSE 0 END) AS chamadas_fixas,
                SUM(CASE WHEN UPPER(COALESCE(tarifa_aplicada,'')) = 'TU-RL' THEN duracao_segundos ELSE 0 END) AS seg_fixas,
                SUM(
                    CASE
                        WHEN UPPER(COALESCE(tarifa_aplicada,'')) NOT IN ('VU-M','TU-RL')
                        THEN 1 ELSE 0 END
                ) AS chamadas_outros,
                SUM(
                    CASE
                        WHEN UPPER(COALESCE(tarifa_aplicada,'')) NOT IN ('VU-M','TU-RL')
                        THEN duracao_segundos ELSE 0 END
                ) AS seg_outros,
                SUM(CASE WHEN segundos_gh_normal > 0 AND segundos_gh_reduzido > 0 THEN 1 ELSE 0 END) AS chamadas_cruza_gh,
                SUM(CASE WHEN {cond_dest_movel} THEN 1 ELSE 0 END) AS chamadas_destino_movel,
                SUM(CASE WHEN {cond_dest_movel} THEN duracao_segundos ELSE 0 END) AS seg_destino_movel,
                SUM(CASE WHEN {cond_dest_fixo} THEN 1 ELSE 0 END) AS chamadas_destino_fixo,
                SUM(CASE WHEN {cond_dest_fixo} THEN duracao_segundos ELSE 0 END) AS seg_destino_fixo
            FROM detraf_normalizado
            WHERE id_importacao = %s
            """,
            (id_importacao,),
        )
        detraf_metricas = cursor.fetchone() or {}
        dashboard_metricas.update(
            {
                "detraf": {
                    "chamadas_totais": int(detraf_metricas.get("total_chamadas") or 0),
                    "segundos_totais": int(detraf_metricas.get("seg_total") or 0),
                    "chamadas_moveis": int(detraf_metricas.get("chamadas_moveis") or 0),
                    "segundos_moveis": int(detraf_metricas.get("seg_moveis") or 0),
                    "chamadas_fixas": int(detraf_metricas.get("chamadas_fixas") or 0),
                    "segundos_fixas": int(detraf_metricas.get("seg_fixas") or 0),
                    "chamadas_cruzaram_gh": int(detraf_metricas.get("chamadas_cruza_gh") or 0),
                    "chamadas_cng": int(detraf_metricas.get("chamadas_cng") or 0),
                    "segundos_cng": int(detraf_metricas.get("seg_cng") or 0),
                    "chamadas_cng_origem_movel": int(detraf_metricas.get("chamadas_cng_movel") or 0),
                    "segundos_cng_origem_movel": int(detraf_metricas.get("seg_cng_movel") or 0),
                    "chamadas_cng_origem_fixo": int(detraf_metricas.get("chamadas_cng_fixo") or 0),
                    "segundos_cng_origem_fixo": int(detraf_metricas.get("seg_cng_fixo") or 0),
                    "chamadas_outros": int(detraf_metricas.get("chamadas_outros") or 0),
                    "segundos_outros": int(detraf_metricas.get("seg_outros") or 0),
                    "chamadas_destino_movel": int(detraf_metricas.get("chamadas_destino_movel") or 0),
                    "segundos_destino_movel": int(detraf_metricas.get("seg_destino_movel") or 0),
                    "chamadas_destino_fixo": int(detraf_metricas.get("chamadas_destino_fixo") or 0),
                    "segundos_destino_fixo": int(detraf_metricas.get("seg_destino_fixo") or 0),
                }
            }
        )

        registrar_log(
            "conferencia_resumo",
            id_importacao=id_importacao,
            processadas=processadas,
            validas=validas,
            invalidas=invalidas,
            sem_cdr=sem_cdr,
            delta_tolerancia=dashboard_metricas.get("chamadas_delta_acima_tolerancia"),
            eot_divergente=dashboard_metricas.get("chamadas_eot_divergente"),
            multiplas=dashboard_metricas.get("chamadas_multiplas_divergencias"),
        )

        cursor.execute(
            """
            SELECT
                COALESCE(DATE(data_hora), DATE(criado_em)) AS dia,
                SUM(CASE WHEN status = 'CONFERIDO' THEN 1 ELSE 0 END) AS conferidos,
                SUM(CASE WHEN status = 'DIVERGENTE' THEN 1 ELSE 0 END) AS divergentes,
                SUM(CASE WHEN status = 'PERDIDO' THEN 1 ELSE 0 END) AS perdidos
            FROM conferencia_resultados
            WHERE id_importacao_detraf = %s
            GROUP BY dia
            ORDER BY dia ASC
            """,
            (id_importacao,),
        )
        timeline_status = []
        for linha in cursor.fetchall() or []:
            dia = linha.get("dia")
            if hasattr(dia, "isoformat"):
                dia = dia.isoformat()
            timeline_status.append(
                {
                    "data": dia,
                    "conferidos": int(linha.get("conferidos") or 0),
                    "divergentes": int(linha.get("divergentes") or 0),
                    "perdidos": int(linha.get("perdidos") or 0),
                }
            )

        cursor.execute(
            f"""
            SELECT
                COALESCE(DATE(data_hora), data_referencia) AS dia,
                SUM(CASE WHEN {cond_cng} THEN 1 ELSE 0 END) AS cng,
                SUM(CASE WHEN UPPER(COALESCE(tarifa_aplicada,'')) = 'VU-M' THEN 1 ELSE 0 END) AS movel,
                SUM(CASE WHEN UPPER(COALESCE(tarifa_aplicada,'')) = 'TU-RL' THEN 1 ELSE 0 END) AS fixo
            FROM detraf_normalizado
            WHERE id_importacao = %s
            GROUP BY dia
            ORDER BY dia ASC
            """,
            (id_importacao,),
        )
        timeline_tarifas = []
        for linha in cursor.fetchall() or []:
            dia = linha.get("dia")
            if hasattr(dia, "isoformat"):
                dia = dia.isoformat()
            timeline_tarifas.append(
                {
                    "data": dia,
                    "movel": int(linha.get("movel") or 0),
                    "fixo": int(linha.get("fixo") or 0),
                    "cng": int(linha.get("cng") or 0),
                }
            )

        return {
            "importacao": {
                "id": info["id"],
                "id_cliente": info.get("id_cliente"),
                "cliente": info.get("nome_cliente"),
                "arquivo": info.get("nome_arquivo"),
                "periodo_inicial": info.get("periodo_inicial"),
                "periodo_final": info.get("periodo_final"),
                "janela": _formatar_janela(info.get("periodo_inicial"), info.get("periodo_final")),
                "eqt_credora": info.get("eqt_credora"),
                "eqt_devedora": info.get("eqt_devedora"),
            },
            "status": {
                "processadas": processadas,
                "validas": validas,
                "invalidas": invalidas,
                "sem_cdr": sem_cdr,
            },
            "resumo": resumo,
            "filtros": {
                "descritor": descritores,
                "gh": ghs,
            },
            "gh_metricas": gh_metricas,
            "dashboard": dashboard_metricas,
            "timeline": {
                "status": timeline_status,
                "tarifas": timeline_tarifas,
            },
        }
    finally:
        conexao.close()


@app.get("/api/conferencia/resultados")
def listar_conferencia_resultados(
    id_importacao: int,
    pagina: int = 1,
    limite: int = 25,
    status: Optional[List[str]] = Query(None),
    busca: Optional[str] = None,
    descritor: Optional[str] = None,
    gh: Optional[str] = None,
    apenas_sem_cdr: bool = False,
    diferenca_min: Optional[int] = Query(None, alias="diferenca_min"),
    eot_divergente: bool = False,
    cruza_gh: bool = False,
    tarifa: Optional[str] = Query(None),
    assinante_a: Optional[str] = Query(None, alias="assinante_a"),
    assinante_b: Optional[str] = Query(None, alias="assinante_b"),
    data_inicio: Optional[str] = Query(None, alias="data_inicio"),
    data_fim: Optional[str] = Query(None, alias="data_fim"),
    multi_divergencias: bool = False,
    gh_inconsistente: bool = False,
    sigame: bool = False,
):
    pagina = max(1, pagina)
    limite = max(1, min(limite, 200))
    offset = (pagina - 1) * limite
    limite_base = limite

    where, where_alias, parametros = _montar_filtros_conferencia(
        id_importacao,
        status,
        busca,
        descritor,
        gh,
        apenas_sem_cdr,
        diferenca_min,
        eot_divergente,
        cruza_gh,
        tarifa,
        assinante_a,
        assinante_b,
        data_inicio,
        data_fim,
        multi_divergencias,
        gh_inconsistente,
        sigame,
    )
    requer_pos_filtragem = multi_divergencias or eot_divergente
    consulta_limite = None if requer_pos_filtragem else limite
    consulta_offset = 0 if requer_pos_filtragem else offset
    total, registros = _consultar_conferencia_resultados(where, where_alias, parametros, consulta_limite, consulta_offset)
    total_base = total
    filtros_aplicados = {
        "status": status,
        "descritor": descritor,
        "gh": gh,
        "apenas_sem_cdr": apenas_sem_cdr,
        "diferenca_min": diferenca_min,
        "eot_divergente": eot_divergente,
        "cruza_gh": cruza_gh,
        "tarifa": tarifa,
        "assinante_a": assinante_a,
        "assinante_b": assinante_b,
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "multi_divergencias": multi_divergencias,
        "gh_inconsistente": gh_inconsistente,
        "sigame": sigame,
    }
    registrar_log(
        "listar_resultados_base",
        id_importacao=id_importacao,
        pagina=pagina,
        limite=limite_base,
        total_base=total_base,
        filtros=filtros_aplicados,
    )

    itens = []
    for linha in registros:
        data_fmt, hora_fmt = _formatar_data_display(linha.get("data_hora"))
        snapshot_payload = linha.get("snapshot_cdr")
        disposition = _obter_disposition_cdr(snapshot_payload)
        tem_sigame, assinante_sigame = _extrair_sigame_snapshot(snapshot_payload)
        detalhes_filtrados, divergencias_resumidas, possui_eot = _filtrar_detalhes_divergencia(
            linha.get("detalhes_divergencia"), disposition
        )
        qtd_divergencias = len(divergencias_resumidas)
        itens.append(
            {
                "id": linha["id"],
                "status": linha.get("status"),
                "observacao": linha.get("observacao"),
                "descricao_divergencia": linha.get("descricao_divergencia"),
                "assinante_a": linha.get("assinante_a"),
                "assinante_b": linha.get("assinante_b"),
                "tem_sigame": tem_sigame,
                "assinante_sigame": assinante_sigame,
                "descritor": linha.get("descritor"),
                "gh": linha.get("gh"),
                "data": data_fmt,
                "hora": hora_fmt,
                "duracao_detraf": _formatar_segundos(linha.get("duracao_detraf_seg")),
                "duracao_cdr": _formatar_segundos(linha.get("duracao_cdr_seg")),
                "eot_detraf": linha.get("eot_detraf"),
                "eot_cdr": linha.get("eot_cdr"),
                "id_registro_detraf": linha.get("id_registro_detraf"),
                "id_registro_cdr": linha.get("id_registro_cdr"),
                "delta_duracao_seg": linha.get("delta_duracao_seg"),
                "delta_hora_seg": linha.get("delta_hora_seg"),
                "tem_cdr": bool(linha.get("id_registro_cdr")),
                "divergencias": divergencias_resumidas,
                "qtd_divergencias": qtd_divergencias,
                "tem_multiplas_divergencias": qtd_divergencias > 1,
                "tem_divergencia_eot": possui_eot,
            }
        )

    if eot_divergente or multi_divergencias:
        itens_filtrados = itens
        if eot_divergente:
            itens_filtrados = [item for item in itens_filtrados if item["tem_divergencia_eot"]]
        if multi_divergencias:
            itens_filtrados = [item for item in itens_filtrados if item["tem_multiplas_divergencias"]]
        total = len(itens_filtrados)
        inicio = (pagina - 1) * limite_base
        fim = inicio + limite_base
        itens = itens_filtrados[inicio:fim]

    registrar_log(
        "listar_resultados_resposta",
        id_importacao=id_importacao,
        pagina=pagina,
        limite=limite_base,
        total_base=total_base,
        total_final=total,
        aplicou_eot=eot_divergente,
        aplicou_multi=multi_divergencias,
    )

    return {
        "total": total,
        "pagina": pagina,
        "por_pagina": limite_base,
        "resultados": itens,
    }


@app.get("/api/conferencia/resultados/{resultado_id}")
def obter_conferencia_resultado(resultado_id: int):
    conexao = db()
    try:
        cursor = conexao.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, id_cliente, id_importacao_detraf, id_importacao_cdr,
                   status, observacao, descricao_divergencia, detalhes_divergencia,
                   delta_duracao_seg, delta_hora_seg,
                   assinante_a, assinante_b, descritor, gh, data_hora,
                   duracao_detraf_seg, duracao_cdr_seg, eot_detraf, eot_cdr,
                   snapshot_detraf, snapshot_cdr
            FROM conferencia_resultados
            WHERE id = %s
            LIMIT 1
            """,
            (resultado_id,),
        )
        registro = cursor.fetchone()
        if not registro:
            raise HTTPException(status_code=404, detail="Resultado não encontrado.")
        detalhes_raw = registro.pop("detalhes_divergencia", None)
        detraf = _carregar_snapshot(registro.pop("snapshot_detraf", None))
        cdr = _carregar_snapshot(registro.pop("snapshot_cdr", None))
        if detraf.get("partes_gh_origem"):
            partes = detraf["partes_gh_origem"]
            if isinstance(partes, str):
                try:
                    partes = json.loads(partes)
                except (json.JSONDecodeError, TypeError):
                    partes = []
            if isinstance(partes, list):
                _preencher_partes_detraf(partes)
                detraf["partes_gh_origem"] = partes
        disposition = _obter_disposition_cdr(cdr)
        detalhes_filtrados, _, _ = _filtrar_detalhes_divergencia(detalhes_raw, disposition)
        registro["detalhes_divergencia"] = detalhes_filtrados
        registro["detraf"] = detraf
        registro["cdr"] = cdr
        if not registro["detalhes_divergencia"] and (registro.get("observacao") or registro.get("descricao_divergencia")):
            registro["detalhes_divergencia"] = [
                {
                    "tipo": registro.get("descricao_divergencia") or "informativo",
                    "mensagem": registro.get("observacao") or "Sem detalhes adicionais.",
                }
            ]
        return registro
    finally:
        conexao.close()


@app.post("/api/conferencia/processar")
def processar_conferencia_manual(entrada: ConferenciaProcessarEntrada):
    mes_referencia = (entrada.mes_referencia or "").strip()
    if mes_referencia and not re.fullmatch(r"\d{6}", mes_referencia):
        raise HTTPException(status_code=400, detail="Mês de referência inválido. Utilize o formato YYYYMM.")
    operadoras_limpas: List[str] = []
    if entrada.operadoras:
        for valor in entrada.operadoras:
            nome = (valor or "").strip()
            if nome and nome not in operadoras_limpas:
                operadoras_limpas.append(nome)

    detraf = _obter_importacao(entrada.id_importacao_detraf)
    if not detraf or detraf.get("tipo_arquivo") != "DETRAF":
        raise HTTPException(status_code=404, detail="Importação DETRAF não encontrada.")
    if detraf.get("status") != "CONCLUIDO":
        raise HTTPException(status_code=400, detail="A importação DETRAF precisa estar concluída.")

    id_cliente = detraf.get("id_cliente")
    if not id_cliente:
        raise HTTPException(status_code=400, detail="Importação DETRAF sem cliente associado.")

    if entrada.id_importacao_cdr:
        cdr = _obter_importacao(entrada.id_importacao_cdr)
        if not cdr or cdr.get("tipo_arquivo") != "CDR":
            raise HTTPException(status_code=404, detail="Importação CDR não encontrada.")
        if cdr.get("id_cliente") != id_cliente:
            raise HTTPException(status_code=400, detail="CDR pertence a outro cliente.")
        if cdr.get("status") != "CONCLUIDO":
            raise HTTPException(status_code=400, detail="Importação CDR precisa estar concluída.")
    else:
        cdr = _buscar_importacao_recente(id_cliente, "CDR")
        if not cdr:
            raise HTTPException(status_code=400, detail="Nenhuma importação CDR disponível para o cliente.")

    periodo_inicio = detraf.get("periodo_inicial") or cdr.get("periodo_inicial")
    periodo_fim = detraf.get("periodo_final") or cdr.get("periodo_final")

    exec_id = registrar_execucao_conferencia(
        id_cliente,
        detraf["id"],
        cdr["id"],
        mes_referencia=mes_referencia or None,
        operadoras=operadoras_limpas or None,
    )
    callback = _callback_execucao(exec_id)

    registrar_log(
        "processar_conferencia_inicio",
        execucao=exec_id,
        id_cliente=id_cliente,
        id_importacao_detraf=detraf["id"],
        id_importacao_cdr=cdr["id"],
        forcar_normalizacao=entrada.forcar_normalizacao,
        mes_referencia=mes_referencia or None,
        operadoras=operadoras_limpas,
    )

    def _rodar_conferencia():
        try:
            resumo = executar_batimento(
                id_cliente=id_cliente,
                id_importacao_detraf=detraf["id"],
                id_importacao_cdr=cdr["id"],
                periodo_inicio=periodo_inicio,
                periodo_fim=periodo_fim,
                notificar_execucao=callback,
                forcar_normalizacao=entrada.forcar_normalizacao,
            )
            detalhe_normalizacao = " com normalização refeita" if entrada.forcar_normalizacao else ""
            atualizar_controle_importacao(
                detraf["id"],
                mensagem=(
                    f"Conferência manual executada{detalhe_normalizacao} com CDR {cdr['nome_arquivo']} "
                    f"(Conferidos: {resumo.get('conferidos', 0)}, Divergentes: {resumo.get('divergentes', 0)}, "
                    f"Perdidos: {resumo.get('perdidos', 0)})."
                ),
            )
            registrar_log(
                "processar_conferencia_concluida",
                execucao=exec_id,
                id_importacao_detraf=detraf["id"],
                id_importacao_cdr=cdr["id"],
                forcar_normalizacao=entrada.forcar_normalizacao,
                mes_referencia=mes_referencia or None,
                operadoras=operadoras_limpas,
                resumo=resumo,
            )
        except Exception as exc:
            atualizar_execucao_conferencia(
                exec_id,
                status_execucao="ERRO",
                mensagem=str(exc),
                erro_resumido=str(exc),
            )
            registrar_log(
                "processar_conferencia_erro",
                execucao=exec_id,
                id_importacao_detraf=detraf["id"],
                id_importacao_cdr=cdr["id"],
                forcar_normalizacao=entrada.forcar_normalizacao,
                mes_referencia=mes_referencia or None,
                operadoras=operadoras_limpas,
                erro=str(exc),
            )

    threading.Thread(target=_rodar_conferencia, daemon=True).start()

    return {
        "mensagem": "Conferência iniciada.",
        "id_execucao": exec_id,
        "id_importacao_cdr": cdr["id"],
    }


@app.get("/api/conferencia/execucoes/{exec_id}")
def obter_status_execucao(exec_id: int):
    dados = obter_execucao_conferencia(exec_id)
    if not dados:
        raise HTTPException(status_code=404, detail="Execução não encontrada.")
    return dados


@app.get("/api/conferencia/export")
def exportar_conferencia_resultados(
    id_importacao: int,
    status: Optional[List[str]] = Query(None),
    busca: Optional[str] = None,
    descritor: Optional[str] = None,
    gh: Optional[str] = None,
    apenas_sem_cdr: bool = False,
    diferenca_min: Optional[int] = Query(None, alias="diferenca_min"),
    eot_divergente: bool = False,
    cruza_gh: bool = False,
    tarifa: Optional[str] = Query(None),
    assinante_a: Optional[str] = Query(None, alias="assinante_a"),
    assinante_b: Optional[str] = Query(None, alias="assinante_b"),
    data_inicio: Optional[str] = Query(None, alias="data_inicio"),
    data_fim: Optional[str] = Query(None, alias="data_fim"),
    multi_divergencias: bool = False,
    gh_inconsistente: bool = False,
    sigame: bool = False,
):
    where, where_alias, parametros = _montar_filtros_conferencia(
        id_importacao,
        status,
        busca,
        descritor,
        gh,
        apenas_sem_cdr,
        diferenca_min,
        eot_divergente,
        cruza_gh,
        tarifa,
        assinante_a,
        assinante_b,
        data_inicio,
        data_fim,
        multi_divergencias,
        gh_inconsistente,
        sigame,
    )
    total, registros = _consultar_conferencia_resultados(where, where_alias, parametros, limite=None)

    if eot_divergente or multi_divergencias:
        registros_filtrados = registros
        if eot_divergente:
            registros_filtrados = [
                linha
                for linha in registros_filtrados
                if _filtrar_detalhes_divergencia(
                    linha.get("detalhes_divergencia"), _obter_disposition_cdr(linha.get("snapshot_cdr"))
                )[2]
            ]
        if multi_divergencias:
            registros_filtrados = [
                linha
                for linha in registros_filtrados
                if len(
                    _filtrar_detalhes_divergencia(
                        linha.get("detalhes_divergencia"), _obter_disposition_cdr(linha.get("snapshot_cdr"))
                    )[1]
                )
                > 1
            ]
        registros = registros_filtrados
        total = len(registros)

    filtros_export = {
        "status": status,
        "descritor": descritor,
        "gh": gh,
        "apenas_sem_cdr": apenas_sem_cdr,
        "diferenca_min": diferenca_min,
        "eot_divergente": eot_divergente,
        "cruza_gh": cruza_gh,
        "tarifa": tarifa,
        "assinante_a": assinante_a,
        "assinante_b": assinante_b,
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "multi_divergencias": multi_divergencias,
        "gh_inconsistente": gh_inconsistente,
        "sigame": sigame,
    }
    registrar_log("exportar_resultados", id_importacao=id_importacao, total=total, filtros=filtros_export)

    cabecalho = [
        "Status",
        "Data",
        "Hora",
        "Assinante A",
        "Assinante B",
        "Descritor",
        "GH",
        "Duração DETRAF",
        "Duração CDR",
        "Delta duração (s)",
        "Qtd divergências",
        "Tipos de divergência",
        "Observação",
    ]

    def _tipos_divergencia_csv(linha: dict) -> List[str]:
        disposition = _obter_disposition_cdr(linha.get("snapshot_cdr"))
        _, tipos_validos, _ = _filtrar_detalhes_divergencia(linha.get("detalhes_divergencia"), disposition)
        return tipos_validos

    def gerar():
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow(cabecalho)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        for linha in registros:
            data_fmt, hora_fmt = _formatar_data_display(linha.get("data_hora"))
            tipos_validos = _tipos_divergencia_csv(linha)
            writer.writerow(
                [
                    linha.get("status"),
                    data_fmt,
                    hora_fmt,
                    linha.get("assinante_a"),
                    linha.get("assinante_b"),
                    linha.get("descritor"),
                    linha.get("gh"),
                    _formatar_segundos(linha.get("duracao_detraf_seg")),
                    _formatar_segundos(linha.get("duracao_cdr_seg")),
                    linha.get("delta_duracao_seg"),
                    len(tipos_validos),
                    ", ".join(tipos_validos),
                    linha.get("observacao"),
                ]
            )
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    headers = {
        "Content-Disposition": f"attachment; filename=conferencia_{id_importacao}.csv",
        "X-Total-Registros": str(total),
    }
    return StreamingResponse(gerar(), media_type="text/csv", headers=headers)


# ======================================
# Logs - limpeza e download
# ======================================


def _serializar_resultado(resultado):
    return {"tipo": resultado.tipo, "detalhes": resultado.detalhes}


def _converter_int(valor, campo):
    if valor is None or valor == "":
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise ValueError(f"Valor inválido para {campo}.")


def _normalizar_data(valor: Optional[str]) -> Optional[str]:
    if not valor:
        return None
    if isinstance(valor, (datetime, date, time)):
        if isinstance(valor, time):
            # Se receber apenas hora, descartamos (não aplicável neste contexto)
            return None
        return valor.isoformat()
    texto = str(valor).strip()
    if not texto:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(texto, fmt)
            return dt.isoformat()
        except ValueError:
            continue
    # tentativa final com fromisoformat
    try:
        dt = datetime.fromisoformat(texto)
        return dt.isoformat()
    except ValueError:
        raise ValueError(f"Data inválida: {valor}")


def _normalizar_lista_int(valores) -> List[int]:
    if not valores:
        return []
    if isinstance(valores, (int, str)):
        valores = [valores]
    resultado = []
    for valor in valores:
        if valor in (None, ""):
            continue
        try:
            numero = int(valor)
        except (TypeError, ValueError):
            raise ValueError(f"Identificador inválido: {valor}")
        if numero > 0:
            resultado.append(numero)
    return resultado


def _sanear_limpeza(
    clientes,
    alvos_brutos,
    opcoes,
    periodo_inicio=None,
    periodo_fim=None,
    ids_importacoes=None,
):
    if not alvos_brutos:
        raise ValueError("Informe ao menos um alvo de limpeza.")

    alvos = {alvo.strip().upper() for alvo in alvos_brutos if alvo and alvo.strip()}
    if not alvos:
        raise ValueError("Nenhum alvo válido informado.")

    periodo_inicio_norm = _normalizar_data(periodo_inicio)
    periodo_fim_norm = _normalizar_data(periodo_fim)
    ids_base = _normalizar_lista_int(ids_importacoes)

    configuracoes = {}

    if "LOGS" in alvos:
        cfg_logs = opcoes.get("LOGS", {})
        configuracoes["LOGS"] = {
            "dias": _converter_int(cfg_logs.get("dias"), "LOGS.dias"),
            "manter": _converter_int(cfg_logs.get("manter"), "LOGS.manter"),
        }

    if "TMP" in alvos:
        cfg_tmp = opcoes.get("TMP", {})
        tipos_tmp = cfg_tmp.get("tipos")
        if tipos_tmp:
            tipos_tmp = [t.upper() for t in tipos_tmp if t]
        configuracoes["TMP"] = {
            "tipos": tipos_tmp,
            "periodo_inicio": _normalizar_data(cfg_tmp.get("de") or cfg_tmp.get("periodo_inicio")),
            "periodo_fim": _normalizar_data(cfg_tmp.get("ate") or cfg_tmp.get("periodo_fim")),
            "dias": _converter_int(cfg_tmp.get("dias"), "TMP.dias"),
            "ids": _normalizar_lista_int(cfg_tmp.get("ids")),
        }

    if "DETRAF" in alvos:
        cfg_detraf = opcoes.get("DETRAF", {})
        configuracoes["DETRAF"] = {
            "periodo_inicio": _normalizar_data(cfg_detraf.get("de") or cfg_detraf.get("periodo_inicio")),
            "periodo_fim": _normalizar_data(cfg_detraf.get("ate") or cfg_detraf.get("periodo_fim")),
            "ids": _normalizar_lista_int(cfg_detraf.get("ids")),
        }

    if "CDR" in alvos:
        cfg_cdr = opcoes.get("CDR", {})
        configuracoes["CDR"] = {
            "periodo_inicio": _normalizar_data(cfg_cdr.get("de") or cfg_cdr.get("periodo_inicio")),
            "periodo_fim": _normalizar_data(cfg_cdr.get("ate") or cfg_cdr.get("periodo_fim")),
            "ids": _normalizar_lista_int(cfg_cdr.get("ids")),
        }

    return alvos, configuracoes, periodo_inicio_norm, periodo_fim_norm, ids_base


def _agrupar_importacoes_por_tipo(ids_importacoes: List[int]) -> Dict[str, List[int]]:
    if not ids_importacoes:
        return {}
    placeholders = ",".join(["%s"] * len(ids_importacoes))
    agrupados: Dict[str, List[int]] = {}
    conexao = db()
    try:
        cursor = conexao.cursor()
        cursor.execute(
            f"""
            SELECT id, UPPER(tipo_arquivo)
            FROM controle_importacoes
            WHERE id IN ({placeholders})
            """,
            tuple(ids_importacoes),
        )
        for identificador, tipo in cursor.fetchall():
            if identificador is None or not tipo:
                continue
            chave = str(tipo).upper()
            valores = agrupados.setdefault(chave, [])
            valores.append(int(identificador))
    finally:
        conexao.close()
    return {chave: valores for chave, valores in agrupados.items() if valores}


def _executar_limpeza_core(
    clientes,
    alvos_brutos,
    opcoes,
    remover_controle,
    periodo_inicio=None,
    periodo_fim=None,
    ids_importacoes=None,
):
    alvos, configuracoes, base_inicio, base_fim, base_ids = _sanear_limpeza(
        clientes,
        alvos_brutos,
        opcoes,
        periodo_inicio,
        periodo_fim,
        ids_importacoes,
    )

    resultados = []
    ids_por_tipo = _agrupar_importacoes_por_tipo(base_ids)

    if "LOGS" in alvos:
        cfg_logs = configuracoes.get("LOGS", {})
        resultado = limpar_logs(VAR_DIR, cfg_logs.get("dias"), cfg_logs.get("manter"))
        resultados.append(_serializar_resultado(resultado))

    if "TMP" in alvos:
        cfg_tmp = configuracoes.get("TMP", {})
        tipos_tmp = cfg_tmp.get("tipos")
        ids_tmp = buscar_importacoes(
            clientes,
            tipos_tmp,
            periodo_inicio=cfg_tmp.get("periodo_inicio") or base_inicio,
            periodo_fim=cfg_tmp.get("periodo_fim") or base_fim,
            ids=cfg_tmp.get("ids") or base_ids,
        )
        resultado = limpar_arquivos_tmp(
            VAR_DIR,
            ids_tmp,
            cfg_tmp.get("dias"),
        )
        resultados.append(_serializar_resultado(resultado))

    if "DETRAF" in alvos:
        cfg_detraf = configuracoes.get("DETRAF", {})
        ids_detraf = cfg_detraf.get("ids")
        if ids_detraf is None and base_ids:
            ids_detraf = ids_por_tipo.get("DETRAF")
        if ids_detraf is None:
            ids_detraf = buscar_importacoes(
                clientes,
                ["DETRAF"],
                periodo_inicio=cfg_detraf.get("periodo_inicio") or base_inicio,
                periodo_fim=cfg_detraf.get("periodo_fim") or base_fim,
                ids=base_ids,
            )
        resultado = limpar_detraf(ids_detraf, remover_controle)
        resultados.append(_serializar_resultado(resultado))
        if ids_detraf and not remover_controle:
            marcar_importacoes_removidas(
                ids_detraf,
                "Importação DETRAF removida pela limpeza manual.",
            )

    if "CDR" in alvos:
        cfg_cdr = configuracoes.get("CDR", {})
        ids_cdr = cfg_cdr.get("ids")
        if ids_cdr is None and base_ids:
            ids_cdr = ids_por_tipo.get("CDR")
        if ids_cdr is None:
            ids_cdr = buscar_importacoes(
                clientes,
                ["CDR"],
                periodo_inicio=cfg_cdr.get("periodo_inicio") or base_inicio,
                periodo_fim=cfg_cdr.get("periodo_fim") or base_fim,
                ids=base_ids,
            )
        resultado = limpar_cdr(ids_cdr, remover_controle)
        resultados.append(_serializar_resultado(resultado))
        if ids_cdr and not remover_controle:
            marcar_importacoes_removidas(
                ids_cdr,
                "Importação CDR removida pela limpeza manual.",
            )

    return resultados


@app.get("/api/logs")
def listar_logs_endpoint():
    """Lista os arquivos de log disponíveis na pasta de logs."""
    return _listar_logs()


@app.get("/api/logs/{nome_log}")
def baixar_log(nome_log: str):
    caminho = _caminho_log_seguro(nome_log)
    return FileResponse(
        caminho,
        media_type="text/plain",
        filename=caminho.name,
    )


@app.delete("/api/logs/{nome_log}")
def remover_log(nome_log: str):
    caminho = _caminho_log_seguro(nome_log)
    try:
        caminho.unlink()
    except OSError as erro:
        raise HTTPException(status_code=500, detail=f"Falha ao remover log: {erro}")
    return {"mensagem": f"Log {caminho.name} removido."}


@app.post("/api/logs/cleanup")
def limpeza_avancada_logs(config: LogsCleanup):
    """Remove logs por critérios de antiguidade e/ou limite de quantidade."""
    if config.older_than_days is None and config.keep_last is None:
        raise HTTPException(status_code=400, detail="Informe older_than_days e/ou keep_last.")

    if config.older_than_days is not None and config.older_than_days < 0:
        raise HTTPException(status_code=400, detail="older_than_days deve ser positivo.")
    if config.keep_last is not None and config.keep_last < 0:
        raise HTTPException(status_code=400, detail="keep_last deve ser positivo.")

    agora = datetime.now()
    entradas: List[tuple[Path, float]] = []
    for arquivo in LOG_DIR.glob("*.log"):
        try:
            stat = arquivo.stat()
        except OSError:
            continue
        entradas.append((arquivo, stat.st_mtime))

    entradas.sort(key=lambda item: item[1], reverse=True)

    removidos = []
    falhas = []

    for indice, (arquivo, mtime) in enumerate(entradas):
        motivos: List[str] = []
        if config.older_than_days is not None:
            idade = agora - datetime.fromtimestamp(mtime)
            if idade > timedelta(days=config.older_than_days):
                motivos.append("older_than_days")

        if config.keep_last is not None and indice >= config.keep_last:
            motivos.append("keep_last")

        if not motivos:
            continue

        try:
            arquivo.unlink()
            removidos.append({"nome": arquivo.name, "motivos": motivos})
        except OSError as erro:
            falhas.append({"nome": arquivo.name, "erro": str(erro)})

    return {
        "removidos": removidos,
        "falhas": falhas,
        "restantes": _listar_logs(),
    }


@app.post("/api/limpeza/manual")
def executar_limpeza_manual(entrada: LimpezaManualEntrada):
    try:
        resultados = _executar_limpeza_core(
            entrada.clientes,
            entrada.alvos,
            entrada.opcoes,
            entrada.remover_controle,
            periodo_inicio=entrada.periodo_inicio,
            periodo_fim=entrada.periodo_fim,
            ids_importacoes=entrada.ids_importacoes,
        )
    except ValueError as erro:
        raise HTTPException(status_code=400, detail=str(erro))

    registrar_execucao(entrada.dict(), resultados)

    return {"mensagem": "Limpeza concluída.", "resultados": resultados}


@app.get("/api/limpeza/resumo")
def obter_resumo_limpeza():
    logs = _listar_logs()
    tamanho_logs = sum(item.get("tamanho_bytes", 0) for item in logs)

    conexao = db()
    total_tmp_bytes = 0
    pendentes_temporarios = []
    detraf = []
    total_detraf = 0
    cdr = []
    total_cdr = 0

    try:
        cursor = conexao.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT tipo_arquivo, COUNT(1) AS quantidade
            FROM arquivos_importacao
            WHERE removido_em IS NULL
            GROUP BY tipo_arquivo
            """
        )
        pendentes_temporarios = cursor.fetchall()

        cursor.execute(
            """
            SELECT caminho_arquivo
            FROM arquivos_importacao
            WHERE removido_em IS NULL
            """
        )
        arquivos_pendentes = cursor.fetchall()

        for item in arquivos_pendentes:
            caminho = Path(item.get("caminho_arquivo") or "")
            if not caminho:
                continue
            try:
                if caminho.exists():
                    total_tmp_bytes += caminho.stat().st_size
            except OSError:
                continue

        cursor.execute("SELECT COUNT(1) AS total FROM detraf_operadora_batimento")
        total_detraf = cursor.fetchone()["total"] or 0

        cursor.execute(
            """
            SELECT cli.nome_cliente, COUNT(1) AS registros
            FROM detraf_operadora_batimento dob
            JOIN controle_importacoes ci ON ci.id = dob.id_importacao
            JOIN clientes cli ON cli.id_cliente = ci.id_cliente
            GROUP BY cli.nome_cliente
            ORDER BY registros DESC
            LIMIT 20
            """
        )
        detraf = cursor.fetchall()

        cursor.execute("SELECT COUNT(1) AS total FROM cdr_tabelas_importadas")
        total_cdr = cursor.fetchone()["total"] or 0

        cursor.execute(
            """
            SELECT cli.nome_cliente, COUNT(1) AS tabelas
            FROM cdr_tabelas_importadas cti
            JOIN controle_importacoes ci ON ci.id = cti.id_importacao
            JOIN clientes cli ON cli.id_cliente = ci.id_cliente
            GROUP BY cli.nome_cliente
            ORDER BY tabelas DESC
            LIMIT 20
            """
        )
        cdr = cursor.fetchall()

    finally:
        conexao.close()

    return {
        "logs": {
            "quantidade": len(logs),
            "tamanho_total": tamanho_logs,
        },
        "temporarios": {
            "pendentes": sum(item.get("quantidade", 0) for item in pendentes_temporarios),
            "por_tipo": pendentes_temporarios,
            "tamanho_total": total_tmp_bytes,
        },
        "detraf": {
            "total_registros": total_detraf,
            "por_cliente": detraf,
        },
        "cdr": {
            "total_tabelas": total_cdr,
            "por_cliente": cdr,
        },
    }
# ======================================
# Relatórios (exportação CSV)
# ======================================


def _formatar_csv(valor):
    if isinstance(valor, (datetime, date, time)):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return str(valor)
    return valor


@app.get("/api/reports/detraf_csv")
def relatorio_detraf_csv(id_importacao: int):
    conexao = db()
    cursor_meta = conexao.cursor(dictionary=True)

    try:
        cursor_meta.execute(
            """
            SELECT id, nome_arquivo, tipo_arquivo
            FROM controle_importacoes
            WHERE id = %s
            """,
            (id_importacao,),
        )
        meta = cursor_meta.fetchone()
        if not meta:
            raise HTTPException(status_code=404, detail="Importação não encontrada.")
        if meta["tipo_arquivo"] != "DETRAF":
            raise HTTPException(status_code=400, detail="Apenas importações DETRAF permitem exportação de batimento.")
    finally:
        cursor_meta.close()

    cursor_dados = conexao.cursor(dictionary=True)
    cursor_dados.execute(
        """
        SELECT
            sequencial,
            assinante_a,
            eqt_a,
            cnl_a,
            area_local_a,
            data_chamada,
            hora_atendimento,
            assinante_b,
            eqt_b,
            cnl_b,
            area_local_b,
            duracao_real_segundos,
            poi,
            descritor_cdr,
            duracao_calculada,
            categoria_assinante_a,
            fds,
            causa_saida,
            contador_saidas_parciais,
            valor_remuneracao,
            gh,
            eqt_credora,
            eqt_devedora
        FROM detraf_operadora_batimento
        WHERE id_importacao = %s
        ORDER BY id ASC
        """,
        (id_importacao,),
    )

    cabecalho = [
        "sequencial",
        "assinante_a",
        "eqt_a",
        "cnl_a",
        "area_local_a",
        "data_chamada",
        "hora_atendimento",
        "assinante_b",
        "eqt_b",
        "cnl_b",
        "area_local_b",
        "duracao_real_segundos",
        "poi",
        "descritor_cdr",
        "duracao_calculada",
        "categoria_assinante_a",
        "fds",
        "causa_saida",
        "contador_saidas_parciais",
        "valor_remuneracao",
        "gh",
        "eqt_credora",
        "eqt_devedora",
    ]

    def gerar_csv() -> Iterable[str]:
        buffer = io.StringIO()
        escritor = csv.writer(buffer, delimiter=";")
        escritor.writerow(cabecalho)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)

        try:
            while True:
                linhas = cursor_dados.fetchmany(1000)
                if not linhas:
                    break
                for linha in linhas:
                    escritor.writerow([_formatar_csv(linha[col]) for col in cabecalho])
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)
        finally:
            cursor_dados.close()
            conexao.close()

    nome_base = Path(meta.get("nome_arquivo") or f"import_{id_importacao}").stem
    nome_arquivo = f"{nome_base}_batimento.csv"

    return StreamingResponse(
        gerar_csv(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={nome_arquivo}"
        },
    )
