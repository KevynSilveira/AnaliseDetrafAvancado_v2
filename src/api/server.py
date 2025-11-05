# ======================================
# API DETRAF CONFERÊNCIA V2
# ======================================
# Responsável por:
# - Servir dados para a interface web
# - Fazer upload e controle de importações
# - Calcular KPIs e métricas DETRAF
# ======================================

import os
import threading
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import mysql.connector as mysql
from mysql.connector.pooling import MySQLConnectionPool
from pydantic import BaseModel

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

# Cria pool de conexões
pool = MySQLConnectionPool(pool_name="detraf_pool", pool_size=5, **DBCFG)

# Função simples para pegar conexão
def db():
    return pool.get_connection()

# ======================================
# Inicialização do Banco
# ======================================
def ensure_tables():
    sql = """
    CREATE TABLE IF NOT EXISTS controle_importacoes (
        id INT AUTO_INCREMENT PRIMARY KEY,
        arquivo VARCHAR(255) NOT NULL,
        data_hora DATETIME NOT NULL,
        status VARCHAR(30) NOT NULL,
        progresso INT NOT NULL DEFAULT 0
    )
    """
    c = db()
    try:
        cur = c.cursor()
        cur.execute(sql)
        c.commit()
    finally:
        c.close()

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

        cur.execute("""
            SELECT classificacao, COUNT(1) AS q
            FROM detraf_operadora_batimento
            GROUP BY classificacao
        """)
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


@app.get("/api/imports")
def list_imports():
    """Lista todas as importações"""
    c = db()
    try:
        cur = c.cursor(dictionary=True)
        cur.execute("""
            SELECT id, arquivo,
                   DATE_FORMAT(data_hora, '%Y-%m-%d %H:%i:%s') AS data_hora,
                   status, progresso
            FROM controle_importacoes
            ORDER BY id DESC LIMIT 50
        """)
        return cur.fetchall()
    finally:
        c.close()


@app.get("/api/imports/{imp_id}")
def get_import(imp_id: int):
    """Retorna uma importação específica"""
    c = db()
    try:
        cur = c.cursor(dictionary=True)
        cur.execute("""
            SELECT id, arquivo,
                   DATE_FORMAT(data_hora, '%Y-%m-%d %H:%i:%s') AS data_hora,
                   status, progresso
            FROM controle_importacoes WHERE id=%s
        """, (imp_id,))
        row = cur.fetchone()
        return row or {}
    finally:
        c.close()


@app.post("/api/imports")
def upload_import(file: UploadFile = File(...)):
    """Faz upload do arquivo e simula progresso"""
    nome = file.filename
    destino = VAR_DIR / "tmp" / nome

    with open(destino, "wb") as f:
        while chunk := file.file.read(1024 * 1024):
            f.write(chunk)

    c = db()
    try:
        cur = c.cursor()
        cur.execute("""
            INSERT INTO controle_importacoes (arquivo, data_hora, status, progresso)
            VALUES (%s, %s, %s, %s)
        """, (nome, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "em_andamento", 0))
        c.commit()
        imp_id = cur.lastrowid
    finally:
        c.close()

    # Thread para simular progresso
    def worker(path: Path, idimp: int):
        try:
            total = os.path.getsize(path)
            lidos = 0
            with open(path, "rb") as fh:
                while chunk := fh.read(1024 * 512):
                    lidos += len(chunk)
                    prog = int(lidos * 100 / max(total, 1))
                    cc = db()
                    cur2 = cc.cursor()
                    cur2.execute(
                        "UPDATE controle_importacoes SET progresso=%s WHERE id=%s",
                        (prog, idimp),
                    )
                    cc.commit()
                    cc.close()
            cc = db()
            cur3 = cc.cursor()
            cur3.execute(
                "UPDATE controle_importacoes SET status=%s, progresso=100 WHERE id=%s",
                ("concluido", idimp),
            )
            cc.commit()
            cc.close()
        except Exception:
            cc = db()
            cur4 = cc.cursor()
            cur4.execute(
                "UPDATE controle_importacoes SET status=%s WHERE id=%s",
                ("erro", idimp),
            )
            cc.commit()
            cc.close()

    threading.Thread(target=worker, args=(destino, imp_id), daemon=True).start()
    return {"id": imp_id, "arquivo": nome}
