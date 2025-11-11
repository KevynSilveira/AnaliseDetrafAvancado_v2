from __future__ import annotations

import re
from datetime import date, datetime, time as dt_time
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Callable, List, Optional, TypedDict

import mysql.connector as mysql

from src.core.banco.clientes_schema import garantir_banco_cliente, conexao_banco_cliente

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


class ResumoImportacaoDetraf(TypedDict, total=False):
    periodo_inicial: Optional[date]
    periodo_final: Optional[date]
    eqt_credora: Optional[str]
    eqt_devedora: Optional[str]
    linhas_processadas: int


def _duracao_segundos(valor: str) -> int:
    """Converte o campo em segundos considerando o layout HHMMSS (posições 90-96)."""
    if not valor:
        return 0
    bruto = re.sub(r"\D", "", valor)
    if not bruto:
        return 0
    if len(bruto) >= 6:
        bruto = bruto[-6:]  # mantém HHMMSS mesmo que venha com 7 dígitos
    try:
        h = int(bruto[0:2])
        m = int(bruto[2:4])
        s = int(bruto[4:6])
        return h * 3600 + m * 60 + s
    except (ValueError, IndexError):
        try:
            return int(bruto)
        except ValueError:
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


def _parse_data(valor: str) -> Optional[date]:
    try:
        return datetime.strptime(valor, "%Y%m%d").date()
    except (ValueError, TypeError):
        return None


def _parse_hora(valor: str) -> Optional[dt_time]:
    try:
        return datetime.strptime(valor, "%H%M%S").time()
    except (ValueError, TypeError):
        return None


def _ajustar_descritor(valor: str) -> Optional[str]:
    if not valor:
        return None
    bruto = valor.upper().strip().lstrip("_")
    return bruto or None


def processar_arquivo_detraf(
    caminho: Path,
    id_importacao: int,
    id_cliente: int,
    obter_conexao_base: Callable[[], mysql.MySQLConnection],
    atualizar_controle: Callable[..., None],
) -> ResumoImportacaoDetraf:
    """Processa o arquivo DETRAF e devolve um resumo da importação."""
    atualizar_controle(
        id_importacao,
        mensagem="Processando arquivo DETRAF. Extraindo dados de batimento...",
        status="PROCESSANDO",
    )

    if not caminho.exists():
        raise FileNotFoundError("Arquivo de importação não encontrado.")

    conexao = obter_conexao_base()
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
                duracao_real_segundos = _duracao_segundos(linha[89:96])
                poi = linha[96:106].strip()
                descritor_cdr = _ajustar_descritor(linha[106:111])
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

                registro = (
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

                lote.append(registro)
                lote_cli.append(registro)
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
                        atualizar_controle(
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

        atualizar_controle(
            id_importacao,
            status="CONCLUIDO",
            mensagem=f"Arquivo DETRAF importado com sucesso. {total} registros processados.",
            periodo_inicial=periodo_inicial,
            periodo_final=periodo_final,
            eqt_credora=eqt_credora_val,
            eqt_devedora=eqt_devedora_val,
            linhas_processadas=total,
        )

        return ResumoImportacaoDetraf(
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
