from .conexao_banco import obter_conexao

####################################  CLIENTES  ####################################

def criar_tabela_clientes():
    """Cria a tabela clientes."""
    conexao = obter_conexao()
    cursor = conexao.cursor()

    sql = """
    CREATE TABLE IF NOT EXISTS clientes (
        id_cliente INT AUTO_INCREMENT PRIMARY KEY,
        nome_cliente VARCHAR(100) NOT NULL,
        ativo TINYINT(1) DEFAULT 1,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """
    cursor.execute(sql)
    _garantir_coluna(cursor, "clientes", "schema_cliente", "VARCHAR(64) NULL")
    conexao.commit()
    cursor.close()
    conexao.close()
    print("Tabela clientes criada/verificada com sucesso.")


####################################  CONTROLE DE IMPORTAÇÕES  ####################################

def _garantir_coluna(cursor, tabela, coluna, definicao):
    """Garante que uma coluna exista na tabela, incluindo-a se necessário."""
    cursor.execute(
        """
        SELECT COUNT(1)
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        """,
        (tabela, coluna),
    )
    existe = cursor.fetchone()[0]
    if not existe:
        cursor.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}")


def criar_tabela_controle_importacoes():
    """Cria a tabela controle_importacoes (histórico de importações) e garante colunas auxiliares."""
    conexao = obter_conexao()
    cursor = conexao.cursor()

    sql = """
    CREATE TABLE IF NOT EXISTS controle_importacoes (
        id INT AUTO_INCREMENT PRIMARY KEY,
        id_cliente INT NOT NULL,
        nome_arquivo VARCHAR(255) NOT NULL,
        tipo_arquivo ENUM('DETRAF','CDR') NOT NULL,
        periodo_inicial DATE NULL,
        periodo_final DATE NULL,
        data_importacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status ENUM('PROCESSANDO','CONCLUIDO','ERRO') DEFAULT 'PROCESSANDO',
        mensagem TEXT NULL,
        FOREIGN KEY (id_cliente) REFERENCES clientes(id_cliente)
    )
    """
    cursor.execute(sql)

    # Colunas extras utilizadas pela web (metadados da importação)
    _garantir_coluna(cursor, "controle_importacoes", "eqt_credora", "VARCHAR(255) NULL")
    _garantir_coluna(cursor, "controle_importacoes", "eqt_devedora", "VARCHAR(255) NULL")
    _garantir_coluna(cursor, "controle_importacoes", "linhas_processadas", "INT DEFAULT 0")
    _garantir_coluna(cursor, "controle_importacoes", "tabela_referencia", "VARCHAR(255) NULL")
    cursor.execute(
        """
        ALTER TABLE controle_importacoes
        MODIFY COLUMN status ENUM('PROCESSANDO','CONCLUIDO','ERRO','REMOVIDO') DEFAULT 'PROCESSANDO'
        """
    )

    conexao.commit()
    cursor.close()
    conexao.close()
    print("Tabela controle_importacoes criada/verificada com sucesso.")


####################################  DETRAF OPERADORA BATIMENTO  #####################################

def criar_tabela_detraf_operadora_batimento():
    """Cria a tabela detraf_operadora_batimento com FK para controle_importacoes."""
    conexao = obter_conexao()
    cursor = conexao.cursor()

    sql = """
    CREATE TABLE IF NOT EXISTS detraf_operadora_batimento (
        id INT AUTO_INCREMENT PRIMARY KEY,
        id_importacao INT,
        sequencial CHAR(10),
        assinante_a VARCHAR(21),
        eqt_a CHAR(3),
        cnl_a CHAR(5),
        area_local_a CHAR(4),
        data_chamada DATE,
        hora_atendimento TIME,
        assinante_b VARCHAR(20),
        eqt_b CHAR(3),
        cnl_b CHAR(5),
        area_local_b CHAR(4),
        duracao_real_segundos INT,
        poi CHAR(10),
        descritor_cdr CHAR(5),
        duracao_calculada DECIMAL(10,1),
        categoria_assinante_a CHAR(2),
        fds CHAR(2),
        causa_saida CHAR(1),
        contador_saidas_parciais CHAR(2),
        valor_remuneracao DECIMAL(18,5),
        gh CHAR(1),
        eqt_credora CHAR(3),
        eqt_devedora CHAR(3),
        importado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (id_importacao) REFERENCES controle_importacoes(id),
        INDEX idx_descritor (descritor_cdr),
        INDEX idx_data (data_chamada),
        INDEX idx_gh (gh)
    )
    """
    cursor.execute(sql)
    _garantir_coluna(cursor, "detraf_operadora_batimento", "classificacao", "VARCHAR(20) NULL")
    _garantir_coluna(cursor, "detraf_operadora_batimento", "tipo_chamada", "VARCHAR(30) NULL")
    conexao.commit()
    cursor.close()
    conexao.close()
    print("Tabela detraf_operadora_batimento criada/verificada conforme layout ATA 2013.")


####################################  ARQUIVOS IMPORTADOS  ####################################


def criar_tabela_arquivos_importacao():
    """Registra os arquivos transferidos para acompanhar limpezas."""
    conexao = obter_conexao()
    cursor = conexao.cursor()

    sql = """
    CREATE TABLE IF NOT EXISTS arquivos_importacao (
        id INT AUTO_INCREMENT PRIMARY KEY,
        id_importacao INT NOT NULL,
        caminho_arquivo VARCHAR(500) NOT NULL,
        tipo_arquivo ENUM('CDR','DETRAF','OUTRO') DEFAULT 'OUTRO',
        removido_em DATETIME NULL,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (id_importacao) REFERENCES controle_importacoes(id)
    )
    """
    cursor.execute(sql)
    conexao.commit()
    cursor.close()
    conexao.close()
    print("Tabela arquivos_importacao criada/verificada com sucesso.")


####################################  TABELAS CDR IMPORTADAS  ####################################


def criar_tabela_cdr_tabelas_importadas():
    """Mantém o vínculo entre importações CDR e tabelas criadas."""
    conexao = obter_conexao()
    cursor = conexao.cursor()

    sql = """
    CREATE TABLE IF NOT EXISTS cdr_tabelas_importadas (
        id INT AUTO_INCREMENT PRIMARY KEY,
        id_importacao INT NOT NULL,
        nome_tabela VARCHAR(255) NOT NULL,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (id_importacao) REFERENCES controle_importacoes(id)
    )
    """
    cursor.execute(sql)
    conexao.commit()
    cursor.close()
    conexao.close()
print("Tabela cdr_tabelas_importadas criada/verificada com sucesso.")
