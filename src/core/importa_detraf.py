"""
Importa arquivo de Batimento (CDRs) conforme ATA DETRAF 2013 - Anexo 2.
Campos e nomes idênticos ao documento oficial.
Agora com controle de importações vinculado por chave estrangeira.
"""

import os
import re
import time
from decimal import Decimal, ROUND_DOWN
from core.banco.conexao_banco import obter_conexao
from core.utilitarios_log import iniciar_log, registrar_log


# -------------------------
# Funções auxiliares
# -------------------------
def hhmmss_para_segundos(valor):
    """Converte HHMMSS em segundos."""
    try:
        h = int(valor[0:2])
        m = int(valor[2:4])
        s = int(valor[4:6])
        return h * 3600 + m * 60 + s
    except Exception:
        return 0


def minutos_com_uma_casa(valor_str):
    """Converte string em minutos (com 1 casa decimal)."""
    try:
        bruto = valor_str.strip().lstrip("0")
        if not bruto:
            return Decimal("0.0")
        valor = Decimal(bruto) / Decimal("10")  # última casa é decimal
        return valor.quantize(Decimal("0.1"), rounding=ROUND_DOWN)
    except Exception:
        return Decimal("0.0")


def truncar_5_casas(valor_str):
    """Trunca valor da remuneração na quinta casa decimal."""
    try:
        bruto = valor_str.strip().lstrip("0")
        if not bruto:
            return Decimal("0.00000")
        val = Decimal(bruto) / Decimal("100000")
        return val.quantize(Decimal("0.00001"), rounding=ROUND_DOWN)
    except Exception:
        return Decimal("0.00000")


def importar_arquivo_batimento(caminho_arquivo):
    """Importa o arquivo de batimento conforme layout ATA 2013 e registra o controle da importação."""
    if not os.path.exists(caminho_arquivo):
        print(f"[ERRO] Arquivo não encontrado: {caminho_arquivo}")
        return

    inicio = time.time()
    log = iniciar_log("importacao_batimento.log")
    registrar_log(log, f"Início da importação: {caminho_arquivo}")

    try:
        conexao = obter_conexao()
        cursor = conexao.cursor()
        linhas = 0

        # --------------------------------------------------
        # 1. Cria registro na tabela controle_importacoes
        # --------------------------------------------------
        nome_arquivo = os.path.basename(caminho_arquivo)
        cursor.execute("""
            INSERT INTO controle_importacoes (nome_arquivo, status)
            VALUES (%s, 'PROCESSANDO')
        """, (nome_arquivo,))
        id_importacao = cursor.lastrowid
        conexao.commit()
        registrar_log(log, f"Registro de importação criado (ID {id_importacao}) para o arquivo {nome_arquivo}")

        # --------------------------------------------------
        # 2. Lê o arquivo e insere os dados linha a linha
        # --------------------------------------------------
        with open(caminho_arquivo, "r", encoding="utf-8", errors="ignore") as f:
            for linha in f:
                if len(linha) < 153 or not linha.strip():
                    continue

                sequencial = linha[0:10].strip()
                assinante_a = re.sub(r"\D", "", linha[10:31])
                eqt_a = linha[31:34].strip()
                cnl_a = linha[34:39].strip()
                area_local_a = linha[39:43].strip()

                # Converte data e hora para formatos nativos MySQL
                data_raw = linha[43:51].strip()
                data_chamada = f"{data_raw[0:4]}-{data_raw[4:6]}-{data_raw[6:8]}" if len(data_raw) == 8 else None
                hora_raw = linha[51:57].strip()
                hora_atendimento = f"{hora_raw[0:2]}:{hora_raw[2:4]}:{hora_raw[4:6]}" if len(hora_raw) == 6 else None

                assinante_b = re.sub(r"\D", "", linha[57:77])
                eqt_b = linha[77:80].strip()
                cnl_b = linha[80:85].strip()
                area_local_b = linha[85:89].strip()
                duracao_real_segundos = hhmmss_para_segundos(linha[89:96])
                poi = linha[96:106].strip()
                descritor_cdr = re.sub(r"[^A-Z]", "", linha[106:111].upper())
                duracao_calculada = minutos_com_uma_casa(linha[111:124])
                categoria_assinante_a = linha[124:126].strip()
                fds = linha[126:128].strip()
                causa_saida = linha[128:129].strip()
                contador_saidas_parciais = linha[129:131].strip()
                valor_remuneracao = truncar_5_casas(linha[131:146])
                gh = linha[146:147].strip()
                eqt_credora = linha[147:150].strip()
                eqt_devedora = linha[150:153].strip()

                sql = """
                INSERT INTO detraf_operadora_batimento (
                    id_importacao, sequencial, assinante_a, eqt_a, cnl_a, area_local_a, data_chamada,
                    hora_atendimento, assinante_b, eqt_b, cnl_b, area_local_b, duracao_real_segundos,
                    poi, descritor_cdr, duracao_calculada, categoria_assinante_a, fds,
                    causa_saida, contador_saidas_parciais, valor_remuneracao, gh, eqt_credora, eqt_devedora
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """

                valores = (
                    id_importacao, sequencial, assinante_a, eqt_a, cnl_a, area_local_a, data_chamada,
                    hora_atendimento, assinante_b, eqt_b, cnl_b, area_local_b, duracao_real_segundos,
                    poi, descritor_cdr, duracao_calculada, categoria_assinante_a, fds,
                    causa_saida, contador_saidas_parciais, valor_remuneracao, gh, eqt_credora, eqt_devedora
                )
                cursor.execute(sql, valores)
                linhas += 1

        conexao.commit()

        # --------------------------------------------------
        # 3. Atualiza o status e total de linhas da importação
        # --------------------------------------------------
        cursor.execute("""
            UPDATE controle_importacoes
            SET status='SUCESSO', linhas_importadas=%s
            WHERE id_importacao=%s
        """, (linhas, id_importacao))
        conexao.commit()

        fim = time.time()
        registrar_log(log, f"Linhas importadas: {linhas}")
        registrar_log(log, f"Tempo total: {round(fim - inicio, 2)}s")
        print(f"[OK] {linhas} linhas importadas com sucesso. (Importação ID {id_importacao})")

    except Exception as e:
        print(f"[ERRO] {e}")
        registrar_log(log, f"Erro: {e}")

        # Atualiza status para ERRO se falhar
        try:
            cursor.execute("""
                UPDATE controle_importacoes
                SET status='ERRO'
                WHERE id_importacao=%s
            """, (id_importacao,))
            conexao.commit()
        except Exception:
            pass

    finally:
        cursor.close()
        conexao.close()
        registrar_log(log, "Conexão encerrada.")
        log.close()