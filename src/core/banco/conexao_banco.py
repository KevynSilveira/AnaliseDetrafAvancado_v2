import mysql.connector
from dotenv import load_dotenv
import os

# Carrega o arquivo .env dentro da pasta configs
base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../configs'))
env_path = os.path.join(base_dir, '.env')


def obter_conexao():
    """Cria e retorna uma conexão com o banco de dados MySQL."""
    load_dotenv(env_path)
    conexao = mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASS'),
        database=os.getenv('DB_NAME')
    )
    return conexao
