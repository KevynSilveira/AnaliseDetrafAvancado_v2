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
import subprocess
import threading
from functools import lru_cache
from pathlib import Path
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_DOWN
from typing import Dict, Iterable, List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
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

# ======================================
# Inicialização do Banco
# ======================================
def ensure_tables():
    criar_tabela_clientes()
    criar_tabela_controle_importacoes()
    criar_tabela_detraf_operadora_batimento()
    criar_tabela_arquivos_importacao()
    criar_tabela_cdr_tabelas_importadas()
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


def importar_dump_cdr(caminho_dump: Path, id_cliente: int):
    """Executa o dump CDR diretamente no banco dedicado do cliente."""
    if not DBCFG.get("database"):
        raise RuntimeError("Banco de dados não configurado para importação CDR.")

    nome_banco_cliente = garantir_banco_cliente(id_cliente)

    comando = ["mysql"]
    if DBCFG.get("host"):
        comando.extend(["-h", DBCFG["host"]])
    if DBCFG.get("port"):
        comando.extend(["-P", str(DBCFG["port"])])
    if DBCFG.get("user"):
        comando.extend(["-u", DBCFG["user"]])

    ambiente = os.environ.copy()
    if DBCFG.get("password"):
        ambiente["MYSQL_PWD"] = DBCFG["password"]

    # Remove tabela CDR anterior, se existir
    conexao_cli = conexao_banco_cliente(id_cliente)
    try:
        cursor_cli = conexao_cli.cursor()
        cursor_cli.execute("DROP TABLE IF EXISTS cdr")
        conexao_cli.commit()
    finally:
        conexao_cli.close()

    comando.extend(["-D", nome_banco_cliente])

    with open(caminho_dump, "rb") as conteudo_dump:
        subprocess.run(
            comando,
            stdin=conteudo_dump,
            check=True,
            env=ambiente,
        )

    periodo_inicial = None
    periodo_final = None

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
    finally:
        conexao_cli.close()

    tabela_utilizada = f"{nome_banco_cliente}.cdr"
    tabelas_finais = [tabela_utilizada]

    return periodo_inicial, periodo_final, tabela_utilizada, tabelas_finais


INSERT_DETRAF_SQL = """
    INSERT INTO detraf_operadora_batimento (
        id_importacao, sequencial, assinante_a, eqt_a, cnl_a, area_local_a, data_chamada,
        hora_atendimento, assinante_b, eqt_b, cnl_b, area_local_b, duracao_real_segundos,
        poi, descritor_cdr, duracao_calculada, categoria_assinante_a, fds,
        causa_saida, contador_saidas_parciais, valor_remuneracao, gh, eqt_credora, eqt_devedora
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s
    )
"""


def _hhmmss_para_segundos(valor: str) -> int:
    try:
        h = int(valor[0:2])
        m = int(valor[2:4])
        s = int(valor[4:6])
        return h * 3600 + m * 60 + s
    except (TypeError, ValueError, IndexError):
        return 0


def _minutos_decimal(valor: str) -> Decimal:
    try:
        bruto = valor.strip().lstrip("0")
        if not bruto:
            return Decimal("0.0")
        calculado = Decimal(bruto) / Decimal("10")
        return calculado.quantize(Decimal("0.1"), rounding=ROUND_DOWN)
    except (ArithmeticError, ValueError, AttributeError):
        return Decimal("0.0")


def _valor_remuneracao(valor: str) -> Decimal:
    try:
        bruto = valor.strip().lstrip("0")
        if not bruto:
            return Decimal("0.00000")
        calculado = Decimal(bruto) / Decimal("100000")
        return calculado.quantize(Decimal("0.00001"), rounding=ROUND_DOWN)
    except (ArithmeticError, ValueError, AttributeError):
        return Decimal("0.00000")


def _parse_data(valor: str):
    try:
        return datetime.strptime(valor, "%Y%m%d").date()
    except (ValueError, TypeError):
        return None


def _parse_hora(valor: str):
    try:
        return datetime.strptime(valor, "%H%M%S").time()
    except (ValueError, TypeError):
        return None


def processar_arquivo_detraf(caminho: Path, id_importacao: int, id_cliente: int):
    """Processa o arquivo DETRAF, populando a tabela de batimento e atualizando metadados."""
    atualizar_controle_importacao(
        id_importacao,
        mensagem="Processando arquivo DETRAF. Extraindo dados de batimento...",
        status="PROCESSANDO",
    )

    if not caminho.exists():
        raise HTTPException(status_code=404, detail="Arquivo de importação não encontrado.")

    conexao = db()
    cursor = conexao.cursor()

    garantir_banco_cliente(id_cliente)
    conexao_cli = conexao_banco_cliente(id_cliente)
    cursor_cli = conexao_cli.cursor()
    try:
        cursor_cli.execute("DELETE FROM detraf_operadora_batimento WHERE id_importacao=%s", (id_importacao,))
        conexao_cli.commit()
    except mysql.Error:
        conexao_cli.rollback()

    try:
        # Evita duplicidades caso reprocessado
        cursor.execute("DELETE FROM detraf_operadora_batimento WHERE id_importacao=%s", (id_importacao,))
        conexao.commit()

        total = 0
        datas: List[date] = []
        eqt_credoras: set[str] = set()
        eqt_devedoras: set[str] = set()

        lote: list[tuple] = []
        lote_cli: list[tuple] = []
        tamanho_lote = 1000

        tamanho_arquivo = max(caminho.stat().st_size, 1)
        bytes_processados = 0
        proximo_marco = 5

        with open(caminho, "r", encoding="utf-8", errors="ignore") as handle:
            for linha in handle:
                if len(linha) < 153:
                    continue

                sequencial = linha[0:10].strip()
                assinante_a = re.sub(r"\D", "", linha[10:31])
                eqt_a = linha[31:34].strip()
                cnl_a = linha[34:39].strip()
                area_local_a = linha[39:43].strip()

                data_ref = _parse_data(linha[43:51].strip())
                hora_ref = _parse_hora(linha[51:57].strip())

                assinante_b = re.sub(r"\D", "", linha[57:77])
                eqt_b = linha[77:80].strip()
                cnl_b = linha[80:85].strip()
                area_local_b = linha[85:89].strip()
                duracao_real_segundos = _hhmmss_para_segundos(linha[89:96])
                poi = linha[96:106].strip()
                descritor_cdr = re.sub(r"[^A-Z]", "", linha[106:111].upper())
                duracao_calculada = _minutos_decimal(linha[111:124])
                categoria_assinante_a = linha[124:126].strip()
                fds = linha[126:128].strip()
                causa_saida = linha[128:129].strip()
                contador_saidas_parciais = linha[129:131].strip()
                valor_remuneracao = _valor_remuneracao(linha[131:146])
                gh = linha[146:147].strip()
                eqt_credora = linha[147:150].strip()
                eqt_devedora = linha[150:153].strip()

                if data_ref:
                    datas.append(data_ref)
                if eqt_credora:
                    eqt_credoras.add(eqt_credora)
                if eqt_devedora:
                    eqt_devedoras.add(eqt_devedora)

                lote.append(
                    (
                        id_importacao,
                        sequencial or None,
                        assinante_a or None,
                        eqt_a or None,
                        cnl_a or None,
                        area_local_a or None,
                        data_ref,
                        hora_ref,
                        assinante_b or None,
                        eqt_b or None,
                        cnl_b or None,
                        area_local_b or None,
                        duracao_real_segundos,
                        poi or None,
                        descritor_cdr or None,
                        duracao_calculada,
                        categoria_assinante_a or None,
                        fds or None,
                        causa_saida or None,
                        contador_saidas_parciais or None,
                        valor_remuneracao,
                        gh or None,
                        eqt_credora or None,
                        eqt_devedora or None,
                    )
                )
                lote_cli.append(
                    (
                        id_importacao,
                        sequencial or None,
                        assinante_a or None,
                        eqt_a or None,
                        cnl_a or None,
                        area_local_a or None,
                        data_ref,
                        hora_ref,
                        assinante_b or None,
                        eqt_b or None,
                        cnl_b or None,
                        area_local_b or None,
                        duracao_real_segundos,
                        poi or None,
                        descritor_cdr or None,
                        duracao_calculada,
                        categoria_assinante_a or None,
                        fds or None,
                        causa_saida or None,
                        contador_saidas_parciais or None,
                        valor_remuneracao,
                        gh or None,
                        eqt_credora or None,
                        eqt_devedora or None,
                    )
                )

                total += 1
                if len(lote) >= tamanho_lote:
                    cursor.executemany(INSERT_DETRAF_SQL, lote)
                    conexao.commit()
                    lote.clear()

                if len(lote_cli) >= tamanho_lote:
                    cursor_cli.executemany(INSERT_DETRAF_SQL, lote_cli)
                    conexao_cli.commit()
                    lote_cli.clear()

                bytes_processados += len(linha.encode("utf-8", errors="ignore"))
                if tamanho_arquivo and proximo_marco <= 100:
                    progresso = int(bytes_processados / tamanho_arquivo * 100)
                    if progresso >= proximo_marco:
                        atualizar_controle_importacao(
                            id_importacao,
                            mensagem=f"Processando arquivo DETRAF ({min(progresso, 99)}% concluído)...",
                        )
                        while proximo_marco <= progresso:
                            proximo_marco += 5

        if lote:
            cursor.executemany(INSERT_DETRAF_SQL, lote)
            conexao.commit()

        if lote_cli:
            cursor_cli.executemany(INSERT_DETRAF_SQL, lote_cli)
            conexao_cli.commit()

        periodo_inicial = min(datas) if datas else None
        periodo_final = max(datas) if datas else None
        eqt_credora_val = ", ".join(sorted(eqt_credoras)) or None
        eqt_devedora_val = ", ".join(sorted(eqt_devedoras)) or None

        atualizar_controle_importacao(
            id_importacao,
            status="CONCLUIDO",
            mensagem=f"Arquivo DETRAF importado com sucesso. {total} registros processados.",
            periodo_inicial=periodo_inicial,
            periodo_final=periodo_final,
            eqt_credora=eqt_credora_val,
            eqt_devedora=eqt_devedora_val,
            linhas_processadas=total,
        )
    finally:
        try:
            cursor_cli.close()
        finally:
            conexao_cli.close()
        try:
            cursor.close()
        finally:
            conexao.close()

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
                periodo_inicial, periodo_final, tabela, novas_tabelas = importar_dump_cdr(path, id_cliente_thread)
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
                )
            else:
                processar_arquivo_detraf(path, id_registro, id_cliente_thread)
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
