# src/api/clientes.py
from fastapi import APIRouter, HTTPException
from src.core.db import conectar_banco

router = APIRouter(prefix="/api/clientes", tags=["Clientes"])

@router.get("/")
def listar_clientes():
    # Lista todos os clientes ativos
    conexao = conectar_banco()
    cursor = conexao.cursor(dictionary=True)
    cursor.execute("SELECT id_cliente, nome_cliente FROM clientes WHERE ativo = 1")
    clientes = cursor.fetchall()
    cursor.close()
    conexao.close()
    return clientes

@router.post("/")
def cadastrar_cliente(dados: dict):
    # Cadastra novo cliente
    nome = dados.get("nome_cliente")
    if not nome:
        raise HTTPException(status_code=400, detail="Nome do cliente é obrigatório.")

    conexao = conectar_banco()
    cursor = conexao.cursor()
    cursor.execute("INSERT INTO clientes (nome_cliente) VALUES (%s)", (nome,))
    conexao.commit()
    cursor.close()
    conexao.close()

    return {"mensagem": "Cliente cadastrado com sucesso."}