# src/web/routes/importacoes.py
from fastapi import APIRouter, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse
import os, shutil, subprocess, mysql.connector
from datetime import datetime

router = APIRouter()

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "sua_senha",
    "database": "spx_o"
}

UPLOAD_DIR = "/var/tmp/detraf_imports"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/importar_arquivo")
async def importar_arquivo(
    id_cliente: int = Form(...),
    tipo_arquivo: str = Form(...),  # 'CDR' ou 'DETRAF'
    arquivo: UploadFile = None
):
    nome_arquivo = arquivo.filename
    ext = os.path.splitext(nome_arquivo)[1].lower()

    # Validação da extensão
    if tipo_arquivo == "CDR" and ext != ".sql":
        raise HTTPException(status_code=400, detail="Apenas arquivos .sql são aceitos para CDR.")
    if tipo_arquivo == "DETRAF" and ext != ".txt":
        raise HTTPException(status_code=400, detail="Apenas arquivos .txt são aceitos para DETRAF.")

    tmp_path = os.path.join(UPLOAD_DIR, nome_arquivo)
    with open(tmp_path, "wb") as buffer:
        shutil.copyfileobj(arquivo.file, buffer)

    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()

    periodo_inicial = periodo_final = None

    if tipo_arquivo == "CDR":
        # Executa o dump completo da base do cliente
        subprocess.run(f"mysql -u {DB_CONFIG['user']} -p{DB_CONFIG['password']} {DB_CONFIG['database']} < {tmp_path}", shell=True, check=True)

        # Detecta tabela recém-criada (última tabela de CDR)
        cursor.execute("SHOW TABLES LIKE 'cdr_%'")
        tabelas = [t[0] for t in cursor.fetchall()]
        tabela_recente = sorted(tabelas)[-1] if tabelas else None

        if tabela_recente:
            cursor.execute(f"SELECT MIN(calldate), MAX(calldate) FROM {tabela_recente}")
            periodo_inicial, periodo_final = cursor.fetchone()

    elif tipo_arquivo == "DETRAF":
        # Apenas registra o arquivo, importação será tratada no módulo de import_detraf
        pass

    # Registro no controle de importações
    cursor.execute("""
        INSERT INTO controle_importacoes (id_cliente, nome_arquivo, tipo_arquivo, periodo_inicial, periodo_final)
        VALUES (%s, %s, %s, %s, %s)
    """, (id_cliente, nome_arquivo, tipo_arquivo, periodo_inicial, periodo_final))
    conn.commit()

    cursor.close()
    conn.close()

    return JSONResponse(content={
        "status": "ok",
        "mensagem": f"{tipo_arquivo} importado com sucesso!",
        "periodo_inicial": str(periodo_inicial),
        "periodo_final": str(periodo_final)
    })
