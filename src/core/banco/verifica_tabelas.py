from .conexao_banco import obter_conexao

####################################  CONTROLE DE IMPORTAÇÕES  ####################################

def criar_tabela_controle_importacoes():
    """Cria a tabela controle_importacoes (histórico de importações)."""
    conexao = obter_conexao()
    cursor = conexao.cursor()

    sql = """
    CREATE TABLE IF NOT EXISTS controle_importacoes (
        id_importacao INT AUTO_INCREMENT PRIMARY KEY,
        nome_arquivo VARCHAR(255) NOT NULL,
        data_importacao DATETIME DEFAULT CURRENT_TIMESTAMP,
        status ENUM('SUCESSO','ERRO','PROCESSANDO') DEFAULT 'PROCESSANDO',
        linhas_importadas INT DEFAULT 0
    )
    """
    cursor.execute(sql)
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
        FOREIGN KEY (id_importacao) REFERENCES controle_importacoes(id_importacao),
        INDEX idx_descritor (descritor_cdr),
        INDEX idx_data (data_chamada),
        INDEX idx_gh (gh)
    )
    """
    cursor.execute(sql)
    conexao.commit()
    cursor.close()
    conexao.close()
    print("Tabela detraf_operadora_batimento criada/verificada conforme layout ATA 2013.")

