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


def _remover_coluna(cursor, tabela, coluna):
    """Remove uma coluna, caso exista."""
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
    if existe:
        cursor.execute(f"ALTER TABLE {tabela} DROP COLUMN {coluna}")


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
    _remover_coluna(cursor, "detraf_operadora_batimento", "classificacao")
    _remover_coluna(cursor, "detraf_operadora_batimento", "tipo_chamada")
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


####################################  NORMALIZAÇÃO E CONFERÊNCIA  ####################################


def criar_tabela_detraf_normalizado():
    conexao = obter_conexao()
    cursor = conexao.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS detraf_normalizado (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_cliente INT NOT NULL,
            id_importacao INT NOT NULL,
            id_registro INT NOT NULL,
            sequencial VARCHAR(30) NULL,
            data_hora DATETIME NULL,
            data_referencia DATE NULL,
            hora_segundos INT NULL,
            duracao_segundos INT DEFAULT 0,
            duracao_calculada_seg INT DEFAULT 0,
            assinante_a_norm VARCHAR(32) NULL,
            assinante_b_norm VARCHAR(32) NULL,
            descritor VARCHAR(10) NULL,
            gh CHAR(1) NULL,
            eot_credora CHAR(3) NULL,
            eot_devedora CHAR(3) NULL,
            poi VARCHAR(15) NULL,
            tarifa_aplicada VARCHAR(10) NULL,
            segundos_gh_normal INT DEFAULT 0,
            segundos_gh_reduzido INT DEFAULT 0,
            detalhes_gh LONGTEXT NULL,
            chave_batimento VARCHAR(255) NULL,
            snapshot LONGTEXT NULL,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_detraf_norm_importacao (id_importacao),
            INDEX idx_detraf_norm_cliente (id_cliente),
            INDEX idx_detraf_norm_chave (chave_batimento),
            INDEX idx_detraf_norm_data (data_hora)
        )
        """
    )
    def _garantir_coluna(nome: str, ddl: str):
        cursor.execute(
            """
            SELECT COUNT(1)
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'detraf_normalizado'
              AND COLUMN_NAME = %s
            """,
            (nome,),
        )
        existe = cursor.fetchone()
        if not existe or not existe[0]:
            cursor.execute(ddl)

    _garantir_coluna(
        "tarifa_aplicada",
        "ALTER TABLE detraf_normalizado ADD COLUMN tarifa_aplicada VARCHAR(10) NULL AFTER poi",
    )
    _garantir_coluna(
        "segundos_gh_normal",
        "ALTER TABLE detraf_normalizado ADD COLUMN segundos_gh_normal INT DEFAULT 0 AFTER tarifa_aplicada",
    )
    _garantir_coluna(
        "segundos_gh_reduzido",
        "ALTER TABLE detraf_normalizado ADD COLUMN segundos_gh_reduzido INT DEFAULT 0 AFTER segundos_gh_normal",
    )
    _garantir_coluna(
        "detalhes_gh",
        "ALTER TABLE detraf_normalizado ADD COLUMN detalhes_gh LONGTEXT NULL AFTER segundos_gh_reduzido",
    )
    _garantir_coluna(
        "assinante_b_sigame_norm",
        "ALTER TABLE detraf_normalizado ADD COLUMN assinante_b_sigame_norm VARCHAR(32) NULL AFTER assinante_b_norm",
    )
    _garantir_coluna(
        "flag_sigame",
        "ALTER TABLE detraf_normalizado ADD COLUMN flag_sigame TINYINT(1) DEFAULT 0 AFTER assinante_b_sigame_norm",
    )
    conexao.commit()
    cursor.close()
    conexao.close()
    print("Tabela detraf_normalizado criada/verificada com sucesso.")


def criar_tabela_cdr_normalizado():
    conexao = obter_conexao()
    cursor = conexao.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cdr_normalizado (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_cliente INT NOT NULL,
            id_importacao INT NOT NULL,
            id_registro VARCHAR(64) NOT NULL,
            data_hora DATETIME NULL,
            data_referencia DATE NULL,
            hora_segundos INT NULL,
            duracao_segundos INT DEFAULT 0,
            caller_norm VARCHAR(32) NULL,
            callee_norm VARCHAR(32) NULL,
            descritor VARCHAR(20) NULL,
            gh CHAR(1) NULL,
            eot VARCHAR(10) NULL,
            chave_batimento VARCHAR(255) NULL,
            snapshot LONGTEXT NULL,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_cdr_norm_importacao (id_importacao),
            INDEX idx_cdr_norm_cliente (id_cliente),
            INDEX idx_cdr_norm_chave (chave_batimento),
            INDEX idx_cdr_norm_data (data_hora)
        )
        """
    )
    conexao.commit()
    cursor.close()
    conexao.close()
    print("Tabela cdr_normalizado criada/verificada com sucesso.")


def criar_tabela_conferencia_resultados():
    conexao = obter_conexao()
    cursor = conexao.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS conferencia_resultados (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            id_cliente INT NOT NULL,
            id_importacao_detraf INT NOT NULL,
            id_importacao_cdr INT NULL,
            id_registro_detraf INT NOT NULL,
            id_registro_cdr VARCHAR(64) NULL,
            status ENUM('CONFERIDO','DIVERGENTE','PERDIDO') NOT NULL,
            delta_duracao_seg INT NULL,
            delta_hora_seg INT NULL,
            descricao_divergencia VARCHAR(255) NULL,
            observacao VARCHAR(255) NULL,
            detalhes_divergencia LONGTEXT NULL,
            chave_batimento VARCHAR(255) NULL,
            descritor VARCHAR(10) NULL,
            gh CHAR(1) NULL,
            assinante_a VARCHAR(32) NULL,
            assinante_b VARCHAR(32) NULL,
            data_hora DATETIME NULL,
            duracao_detraf_seg INT DEFAULT 0,
            duracao_cdr_seg INT DEFAULT 0,
            eot_detraf CHAR(3) NULL,
            eot_cdr CHAR(3) NULL,
            snapshot_detraf LONGTEXT NULL,
            snapshot_cdr LONGTEXT NULL,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_conf_res_importacao (id_importacao_detraf),
            INDEX idx_conf_res_status (status),
            INDEX idx_conf_res_cliente (id_cliente)
        )
        """
    )
    conexao.commit()

    cursor.execute(
        """
        SELECT COUNT(1)
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'conferencia_resultados'
          AND COLUMN_NAME = 'detalhes_divergencia'
        """
    )
    possui_coluna = cursor.fetchone()
    if not possui_coluna or not possui_coluna[0]:
        cursor.execute(
            """
            ALTER TABLE conferencia_resultados
            ADD COLUMN detalhes_divergencia LONGTEXT NULL AFTER observacao
            """
        )
        conexao.commit()
    cursor.close()
    conexao.close()
    print("Tabela conferencia_resultados criada/verificada com sucesso.")


def criar_tabela_conferencia_execucoes():
    conexao = obter_conexao()
    cursor = conexao.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS conferencia_execucoes (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_cliente INT NOT NULL,
            id_importacao_detraf INT NOT NULL,
            id_importacao_cdr INT NULL,
            status_execucao ENUM('PENDENTE','NORMALIZANDO_DETRAF','NORMALIZANDO_CDR','BATENDO_REGISTROS','GRAVANDO_RESULTADOS','CONCLUIDO','ERRO') DEFAULT 'PENDENTE',
            etapa_atual VARCHAR(100) NULL,
            progresso_percentual INT DEFAULT 0,
            mensagem VARCHAR(255) NULL,
            total_registros INT DEFAULT 0,
            processados INT DEFAULT 0,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
            atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            erro_resumido TEXT NULL,
            FOREIGN KEY (id_importacao_detraf) REFERENCES controle_importacoes(id)
        )
        """
    )
    _garantir_coluna(cursor, "conferencia_execucoes", "mes_referencia", "VARCHAR(6) NULL")
    _garantir_coluna(cursor, "conferencia_execucoes", "operadoras_json", "TEXT NULL")
    conexao.commit()
    cursor.close()
    conexao.close()
    print("Tabela conferencia_execucoes criada/verificada com sucesso.")
