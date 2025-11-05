import os
from datetime import datetime

def iniciar_log(nome_arquivo='execucao_detraf.log'):
    """Cria um arquivo de log com data e hora da execução."""
    os.makedirs('var/logs', exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    caminho = f"var/logs/{nome_arquivo.replace('.log', '')}_{timestamp}.log"
    return open(caminho, 'w', encoding='utf-8')

def registrar_log(arquivo_log, mensagem):
    """Registra mensagens no arquivo de log."""
    agora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    arquivo_log.write(f'[{agora}] {mensagem}\n')
    arquivo_log.flush()
