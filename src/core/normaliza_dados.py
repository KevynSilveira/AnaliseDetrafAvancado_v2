from __future__ import annotations

import json
import re
import time as systime
from datetime import datetime, date, time as dt_time, timedelta
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import mysql.connector as mysql

from .banco.conexao_banco import obter_conexao
from .banco.clientes_schema import conexao_banco_cliente, obter_banco_cliente
from .gh import calcular_segmentos_gh

TELEFONE_RGX = re.compile(r"\D")
DDD_VALIDO = {f"{i:02d}" for i in range(11, 100)}
TOLL_PREFIXOS = ("0800", "0300", "0500", "0900")


def _eh_destino_cng(destino_raw: Optional[str], destino_norm: Optional[str]) -> bool:
    """Retorna True quando o destino representa um CNG (0800/0300/0500/0900 ou literal CNG)."""
    if not destino_raw and not destino_norm:
        return False
    destino_raw_fmt = (destino_raw or "").strip().upper()
    if destino_raw_fmt == "CNG":
        return True

    digitos_raw = TELEFONE_RGX.sub("", destino_raw or "")
    if digitos_raw and any(digitos_raw.startswith(prefix) for prefix in TOLL_PREFIXOS):
        return True

    digitos_norm = TELEFONE_RGX.sub("", destino_norm or "")
    if digitos_norm and any(digitos_norm.startswith(prefix.lstrip("0")) for prefix in TOLL_PREFIXOS):
        return True

    return False


def _extrair_ddd(numero: Optional[str]) -> Optional[str]:
    if numero and len(numero) >= 2:
        return numero[0:2]
    return None


def _remover_prefixos_especiais(digitos: str) -> str:
    # remove DDI repetido 55 enquanto houver mais de 11 dígitos
    while len(digitos) > 11 and digitos.startswith("55"):
        digitos = digitos[2:]
    # remove prefixos 00 ou 55 quando tiver 12 ou 13 dígitos
    if len(digitos) in (12, 13) and digitos[:2] in {"00", "55"}:
        digitos = digitos[2:]
    # remove CSPs (0XX) quantas vezes forem necessárias enquanto restar algo > DDD
    while len(digitos) > 11 and len(digitos) >= 3 and digitos[0] == "0":
        digitos = re.sub(r"^0\d{2}", "", digitos, count=1)
    return digitos


def _tratar_toll_free(digitos: str) -> Tuple[str, bool]:
    for prefixo in TOLL_PREFIXOS:
        if digitos.startswith(prefixo):
            sem_zero = digitos.lstrip("0")
            return sem_zero[:10], True
    return digitos, False


def _normalizar_telefone(valor: Optional[str], ddd_base: Optional[str] = None) -> Optional[str]:
    if not valor:
        return None
    digitos = TELEFONE_RGX.sub("", str(valor))
    if not digitos:
        return None

    digitos, eh_toll = _tratar_toll_free(digitos)
    digitos = _remover_prefixos_especiais(digitos)

    if len(digitos) > 13:
        digitos = digitos[-11:]

    if len(digitos) == 9 and digitos[0] == "9" and ddd_base:
        digitos = ddd_base + digitos
    elif len(digitos) == 8 and digitos[0] in {"2", "3", "4", "5"} and ddd_base:
        digitos = ddd_base + digitos
    elif len(digitos) in (12, 13) and digitos[:2] in {"00", "55"}:
        digitos = digitos[2:]

    if len(digitos) == 11 and digitos.startswith("0"):
        digitos = digitos[1:]

    if len(digitos) not in (10, 11):
        return None

    if not eh_toll:
        ddd = digitos[:2]
        if ddd not in DDD_VALIDO:
            return None

    return digitos


def _tipo_numero(valor: Optional[str]) -> Optional[str]:
    if not valor:
        return None
    digitos = TELEFONE_RGX.sub("", str(valor))
    if len(digitos) < 10:
        return None
    codigo_inicial = digitos[2]
    if len(digitos) == 11 and codigo_inicial == "9":
        return "MOVEL"
    if codigo_inicial in {"2", "3", "4", "5"}:
        return "FIXO"
    return None


def _definir_tarifa(destino_raw: Optional[str], destino_norm: Optional[str], origem_norm: Optional[str]) -> Optional[str]:
    destino_tipo = _tipo_numero(destino_norm or destino_raw)
    origem_tipo = _tipo_numero(origem_norm)

    if _eh_destino_cng(destino_raw, destino_norm):
        if origem_tipo == "MOVEL":
            return "VU-M"
        if origem_tipo == "FIXO":
            return "TU-RL"
        return None

    if destino_tipo == "MOVEL":
        return "VU-M"
    if destino_tipo == "FIXO":
        return "TU-RL"
    return None


def _normalizar_hora(hora_ref: Optional[object]) -> Optional[dt_time]:
    if hora_ref is None:
        return None
    if isinstance(hora_ref, dt_time):
        return hora_ref
    if isinstance(hora_ref, datetime):
        return hora_ref.time()
    if isinstance(hora_ref, timedelta):
        total = int(hora_ref.total_seconds()) % 86400
        return (datetime.min + timedelta(seconds=total)).time()
    if isinstance(hora_ref, str):
        bruto = hora_ref.strip()
        if not bruto:
            return None
        for fmt in ("%H:%M:%S", "%H%M%S"):
            try:
                return datetime.strptime(bruto, fmt).time()
            except ValueError:
                continue
        return None
    return None


def _combinar_data_hora(data_ref: Optional[date], hora_ref: Optional[object]) -> Optional[datetime]:
    hora_formatada = _normalizar_hora(hora_ref)
    if data_ref and hora_formatada:
        return datetime.combine(data_ref, hora_formatada)
    if data_ref:
        return datetime.combine(data_ref, dt_time.min)
    return None


def _duracao_calculada_para_segundos(valor) -> int:
    if valor is None:
        return 0
    try:
        return int(round(float(valor) * 60))
    except (TypeError, ValueError):
        return 0


def _carregar_detraf_normalizado_existente(id_cliente: int, id_importacao: int) -> List[Dict]:
    conexao = obter_conexao()
    cursor = conexao.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT id_registro, sequencial, data_hora, duracao_segundos, duracao_calculada_seg,
                   assinante_a_norm, assinante_b_norm, descritor, gh, eot_credora, eot_devedora,
                   poi, tarifa_aplicada, segundos_gh_normal, segundos_gh_reduzido, detalhes_gh,
                   chave_batimento, snapshot
            FROM detraf_normalizado
            WHERE id_cliente=%s AND id_importacao=%s
            """,
            (id_cliente, id_importacao),
        )
        linhas = cursor.fetchall()
    finally:
        cursor.close()
        conexao.close()

    if not linhas:
        return []

    resultado: List[Dict] = []
    for linha in linhas:
        segmentos = linha.get("detalhes_gh")
        if isinstance(segmentos, str):
            try:
                segmentos = json.loads(segmentos)
            except json.JSONDecodeError:
                segmentos = []
        resultado.append(
            {
                "id_registro": linha["id_registro"],
                "sequencial": linha.get("sequencial"),
                "data_hora": linha.get("data_hora"),
                "duracao_segundos": int(linha.get("duracao_segundos") or 0),
                "duracao_calculada": int(linha.get("duracao_calculada_seg") or 0),
                "assinante_a": linha.get("assinante_a_norm"),
                "assinante_b": linha.get("assinante_b_norm"),
                "descritor": linha.get("descritor"),
                "gh": linha.get("gh"),
                "eqt_credora": linha.get("eot_credora"),
                "eqt_devedora": linha.get("eot_devedora"),
                "poi": linha.get("poi"),
                "tarifa_aplicada": linha.get("tarifa_aplicada"),
                "segundos_gh_normal": int(linha.get("segundos_gh_normal") or 0),
                "segundos_gh_reduzido": int(linha.get("segundos_gh_reduzido") or 0),
                "segmentos_gh": segmentos or [],
                "snapshot": linha.get("snapshot"),
                "chave": linha.get("chave_batimento"),
            }
        )
    return resultado


def _carregar_cdr_normalizado_existente(id_cliente: int, id_importacao: int) -> List[Dict]:
    conexao = obter_conexao()
    cursor = conexao.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT id_registro, data_hora, duracao_segundos, caller_norm, callee_norm, descritor,
                   gh, eot, chave_batimento, snapshot
            FROM cdr_normalizado
            WHERE id_cliente=%s AND id_importacao=%s
            """,
            (id_cliente, id_importacao),
        )
        linhas = cursor.fetchall()
    finally:
        cursor.close()
        conexao.close()

    if not linhas:
        return []

    resultado: List[Dict] = []
    for linha in linhas:
        snapshot_raw = linha.get("snapshot")
        snapshot = {}
        if snapshot_raw:
            try:
                snapshot = json.loads(snapshot_raw)
            except json.JSONDecodeError:
                snapshot = {}
        disposition = snapshot.get("disposition")
        if disposition is not None:
            disposition = str(disposition).strip().upper() or None
        sentido = snapshot.get("sentido")
        if sentido is not None:
            sentido = str(sentido).strip().upper() or None
        eot_a = snapshot.get("eot_a")
        if eot_a is not None:
            eot_a = str(eot_a).strip() or None
        eot_b = snapshot.get("eot_b")
        if eot_b is not None:
            eot_b = str(eot_b).strip() or None

        resultado.append(
            {
                "id_registro": linha["id_registro"],
                "data_hora": linha.get("data_hora"),
                "duracao_segundos": int(linha.get("duracao_segundos") or 0),
                "caller_norm": linha.get("caller_norm"),
                "callee_norm": linha.get("callee_norm"),
                "descritor": linha.get("descritor"),
                "disposition": disposition,
                "sentido": sentido,
                "eot_a": eot_a,
                "eot_b": eot_b,
                "eot": linha.get("eot"),
                "snapshot": snapshot_raw,
                "chave": linha.get("chave_batimento"),
            }
        )
    return resultado


def _chave_unificacao_gh(registro: Dict) -> Tuple:
    return (
        (registro.get("assinante_a") or "").strip(),
        (registro.get("assinante_b") or "").strip(),
        registro.get("data_chamada"),
        registro.get("hora_atendimento"),
        registro.get("eqt_credora"),
        registro.get("eqt_devedora"),
    )


def _mesclar_registros_por_gh(registros: Sequence[Dict]) -> Dict:
    base = dict(registros[0])
    partes = []
    total_real = 0
    total_calc_seg = 0

    for item in registros:
        dur_real = int(item.get("duracao_real_segundos") or 0)
        dur_calc_seg = _duracao_calculada_para_segundos(item.get("duracao_calculada"))
        partes.append(
            {
                "id": item.get("id"),
                "sequencial": item.get("sequencial"),
                "gh": (item.get("gh") or "").strip() or None,
                "duracao_real_segundos": dur_real,
                "duracao_calculada_seg": dur_calc_seg,
            }
        )
        total_real += dur_real
        total_calc_seg += dur_calc_seg

    base["duracao_real_segundos"] = total_real
    if total_calc_seg:
        base["duracao_calculada"] = total_calc_seg / 60
    base["__gh_unificado"] = True
    base["__gh_partes"] = partes
    return base


def _unificar_registros_por_gh(registros: Sequence[Dict]) -> List[Dict]:
    agrupados: Dict[Tuple, List[Dict]] = {}
    for registro in registros:
        chave = _chave_unificacao_gh(registro)
        agrupados.setdefault(chave, []).append(registro)

    resultado: List[Dict] = []
    for itens in agrupados.values():
        ghs = {(item.get("gh") or "").strip().upper() for item in itens if item.get("gh")}
        if len(itens) > 1 and len(ghs) > 1:
            resultado.append(_mesclar_registros_por_gh(itens))
        else:
            resultado.extend(itens)
    return resultado


def _hora_para_segundos(data_hora: Optional[datetime]) -> Optional[int]:
    if not data_hora:
        return None
    return data_hora.hour * 3600 + data_hora.minute * 60 + data_hora.second


def _gerar_chave(assinante_a: Optional[str], assinante_b: Optional[str], data_hora: Optional[datetime]) -> Optional[str]:
    if not (assinante_a and assinante_b and data_hora):
        return None
    minuto = data_hora.replace(second=0, microsecond=0)
    return f"{assinante_a}:{assinante_b}:{minuto.isoformat()}"


def _json_dump(payload: Dict) -> str:
    return json.dumps(payload, default=str, ensure_ascii=False)


def normalizar_detraf(id_cliente: int, id_importacao: int, notificar_progresso: Optional[Callable[[int, int], None]] = None) -> List[Dict]:
    existentes = _carregar_detraf_normalizado_existente(id_cliente, id_importacao)
    if existentes:
        if notificar_progresso:
            total_existentes = len(existentes)
            notificar_progresso(total_existentes, total_existentes)
        return existentes

    conexao = obter_conexao()
    cursor = conexao.cursor(dictionary=True)
    try:
        cursor.execute(
            "DELETE FROM detraf_normalizado WHERE id_importacao=%s",
            (id_importacao,),
        )
        conexao.commit()

        cursor.execute(
            """
            SELECT id, sequencial, assinante_a, assinante_b, data_chamada, hora_atendimento,
                   duracao_real_segundos, duracao_calculada, descritor_cdr, gh, eqt_credora,
                   eqt_devedora, poi
            FROM detraf_operadora_batimento
            WHERE id_importacao=%s
            """,
            (id_importacao,),
        )
        registros_brutos = cursor.fetchall()
        registros = _unificar_registros_por_gh(registros_brutos)
        total = len(registros)

        sql_insert = (
            """
            INSERT INTO detraf_normalizado (
                id_cliente, id_importacao, id_registro, sequencial, data_hora, data_referencia,
                hora_segundos, duracao_segundos, duracao_calculada_seg, assinante_a_norm,
                assinante_b_norm, descritor, gh, eot_credora, eot_devedora, poi,
                tarifa_aplicada, segundos_gh_normal, segundos_gh_reduzido, detalhes_gh,
                chave_batimento, snapshot
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
            )
            """
        )

        lote: List[Tuple] = []
        normalizados: List[Dict] = []

        processados = 0
        for registro in registros:
            data_hora = _combinar_data_hora(registro.get("data_chamada"), registro.get("hora_atendimento"))
            duracao_segundos = int(registro.get("duracao_real_segundos") or 0)
            duracao_calc = _duracao_calculada_para_segundos(registro.get("duracao_calculada"))
            assinante_a = _normalizar_telefone(registro.get("assinante_a"))
            ddd_a = _extrair_ddd(assinante_a)
            assinante_b = _normalizar_telefone(registro.get("assinante_b"), ddd_base=ddd_a)
            chave = _gerar_chave(assinante_a, assinante_b, data_hora)
            tarifa_aplicada = _definir_tarifa(registro.get("assinante_b"), assinante_b, assinante_a)
            tarifa_base = tarifa_aplicada or "TU-RL"
            gh_resultado = calcular_segmentos_gh(data_hora, duracao_segundos, tarifa_base)
            segmentos_gh = [segmento.__dict__ for segmento in gh_resultado.segmentos]

            registro_snapshot = dict(registro)
            registro_snapshot.update(
                {
                    "tarifa_aplicada": tarifa_aplicada,
                    "segundos_gh_normal": gh_resultado.segundos_normal,
                    "segundos_gh_reduzido": gh_resultado.segundos_reduzido,
                    "segmentos_gh": segmentos_gh,
                }
            )
            if registro.get("__gh_unificado"):
                registro_snapshot["gh_unificado"] = True
                registro_snapshot["partes_gh_origem"] = registro.get("__gh_partes", [])
            snapshot = _json_dump(registro_snapshot)

            normalizado = {
                "id_registro": registro["id"],
                "sequencial": registro.get("sequencial"),
                "data_hora": data_hora,
                "duracao_segundos": duracao_segundos,
                "duracao_calculada": duracao_calc,
                "assinante_a": assinante_a,
                "assinante_b": assinante_b,
                "descritor": registro.get("descritor_cdr"),
                "gh": registro.get("gh"),
                "eqt_credora": registro.get("eqt_credora"),
                "eqt_devedora": registro.get("eqt_devedora"),
                "poi": registro.get("poi"),
                "tarifa_aplicada": tarifa_aplicada,
                "segundos_gh_normal": gh_resultado.segundos_normal,
                "segundos_gh_reduzido": gh_resultado.segundos_reduzido,
                "segmentos_gh": segmentos_gh,
                "snapshot": snapshot,
                "chave": chave,
            }
            normalizados.append(normalizado)

            lote.append(
                (
                    id_cliente,
                    id_importacao,
                    registro["id"],
                    registro.get("sequencial"),
                    data_hora,
                    registro.get("data_chamada"),
                    _hora_para_segundos(data_hora),
                    duracao_segundos,
                    duracao_calc,
                    assinante_a,
                    assinante_b,
                    registro.get("descritor_cdr"),
                    registro.get("gh"),
                    registro.get("eqt_credora"),
                    registro.get("eqt_devedora"),
                    registro.get("poi"),
                    tarifa_aplicada,
                    gh_resultado.segundos_normal,
                    gh_resultado.segundos_reduzido,
                    json.dumps(segmentos_gh, ensure_ascii=False),
                    chave,
                    snapshot,
                )
            )

            if len(lote) >= 500:
                cursor.executemany(sql_insert, lote)
                conexao.commit()
                lote.clear()
            processados += 1
            if notificar_progresso and processados % 1000 == 0:
                notificar_progresso(processados, total)

        if lote:
            cursor.executemany(sql_insert, lote)
            conexao.commit()

        if notificar_progresso:
            notificar_progresso(total, total)
        return normalizados
    finally:
        cursor.close()
        conexao.close()


def _mapear_colunas_cdr(cursor) -> Dict[str, str]:
    cursor.execute("SHOW COLUMNS FROM cdr")
    colunas = {linha[0].lower(): linha[0] for linha in cursor.fetchall()}

    def selecionar(*nomes):
        for nome in nomes:
            if nome.lower() in colunas:
                return colunas[nome.lower()]
        return None

    mapa = {
        "id": selecionar("id", "cdr_id", "uniqueid"),
        "calldate": selecionar("calldate", "data", "datahora"),
        "src": selecionar("src", "caller", "origem", "cnum"),
        "dst": selecionar("dst", "callee", "destino", "cnum_b"),
        "billsec": selecionar("billsec", "bilsec", "duracao", "duration"),
        "duration_total": selecionar("duration", "tempo_total"),
        "channel": selecionar("channel"),
        "dstchannel": selecionar("dstchannel"),
        "lastdata": selecionar("lastdata"),
        "eot_a": selecionar("eot_a", "EOT_A"),
        "eot_b": selecionar("eot_b", "EOT_B"),
        "sigame": selecionar("sigame"),
        "sentido": selecionar("sentido"),
        "ruri": selecionar("ruri"),
        "uri": selecionar("uri"),
        "dialed_number": selecionar("dialed_number"),
        "disposition": selecionar("disposition", "status"),
    }

    if not (mapa["id"] and mapa["calldate"] and mapa["src"] and mapa["dst"] and mapa["billsec"]):
        raise RuntimeError("Tabela CDR não possui colunas mínimas necessárias (id, calldate, src, dst, billsec/duration).")

    return mapa


MAX_DESCRITOR_CDR = 20


def normalizar_cdr(
    id_cliente: int,
    id_importacao_cdr: int,
    periodo_inicio: Optional[date] = None,
    periodo_fim: Optional[date] = None,
    notificar_progresso: Optional[Callable[[int, int], None]] = None,
) -> List[Dict]:
    if not id_importacao_cdr:
        return []

    existentes = _carregar_cdr_normalizado_existente(id_cliente, id_importacao_cdr)
    if existentes:
        if notificar_progresso:
            total_existentes = len(existentes)
            notificar_progresso(total_existentes, total_existentes)
        return existentes

    nome_banco = obter_banco_cliente(id_cliente)
    if not nome_banco:
        raise RuntimeError(f"Cliente {id_cliente} sem banco configurado para CDR.")

    conexao_cli = conexao_banco_cliente(id_cliente)
    cursor_cli = conexao_cli.cursor(dictionary=True)
    cursor_schema = conexao_cli.cursor()
    try:
        mapa = _mapear_colunas_cdr(cursor_schema)

        colunas_select = [
            f"`{mapa['id']}` AS registro_id",
            f"`{mapa['calldate']}` AS calldate",
            f"`{mapa['src']}` AS src",
            f"`{mapa['dst']}` AS dst",
            f"`{mapa['billsec']}` AS billsec",
        ]

        opcionais = {
            "duration_total": "duration_total",
            "accountcode": "accountcode",
            "userfield": "userfield",
            "disposition": "disposition",
            "channel": "channel",
            "dstchannel": "dstchannel",
            "lastdata": "lastdata",
            "eot_a": "eot_a",
            "eot_b": "eot_b",
            "sigame": "sigame",
            "sentido": "sentido",
            "ruri": "ruri",
            "uri": "uri",
            "dialed_number": "dialed_number",
        }

        for chave, alias in opcionais.items():
            coluna = mapa.get(chave)
            if coluna:
                colunas_select.append(f"`{coluna}` AS {alias}")

        sql = f"SELECT {', '.join(colunas_select)} FROM cdr"
        parametros: List = []
        if periodo_inicio or periodo_fim:
            condicoes = []
            if periodo_inicio:
                condicoes.append("`{}` >= %s".format(mapa['calldate']))
                parametros.append(datetime.combine(periodo_inicio, dt_time.min))
            if periodo_fim:
                condicoes.append("`{}` <= %s".format(mapa['calldate']))
                parametros.append(datetime.combine(periodo_fim + timedelta(days=1), dt_time.min))
            if condicoes:
                sql += " WHERE " + " AND ".join(condicoes)

        cursor_cli.execute(sql, tuple(parametros))
        registros = cursor_cli.fetchall()
    finally:
        cursor_schema.close()
        cursor_cli.close()
        conexao_cli.close()

    conexao = obter_conexao()
    cursor = conexao.cursor()
    try:
        for tentativa in range(3):
            try:
                cursor.execute(
                    "DELETE FROM cdr_normalizado WHERE id_cliente=%s AND id_importacao=%s",
                    (id_cliente, id_importacao_cdr),
                )
                conexao.commit()
                break
            except mysql.Error as exc:
                conexao.rollback()
                if getattr(exc, "errno", None) == 1205 and tentativa < 2:
                    systime.sleep(0.5)
                    continue
                raise

        sql_insert = (
            """
            INSERT INTO cdr_normalizado (
                id_cliente, id_importacao, id_registro, data_hora, data_referencia, hora_segundos,
                duracao_segundos, caller_norm, callee_norm, descritor, gh, eot, chave_batimento, snapshot
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
            )
            """
        )

        total = len(registros)
        normalizados: List[Dict] = []
        lote: List[Tuple] = []
        processados = 0

        for registro in registros:
            registro_id = registro.get("registro_id")
            if registro_id is None:
                registro_id = f"{registro.get('src')}-{registro.get('dst')}-{registro.get('calldate')}"
            data_hora = registro.get("calldate")
            if isinstance(data_hora, str):
                try:
                    data_hora = datetime.fromisoformat(data_hora)
                except ValueError:
                    data_hora = None
            duracao = int(registro.get("billsec") or 0)
            caller = _normalizar_telefone(registro.get("src"))
            ddd_caller = _extrair_ddd(caller)
            callee = _normalizar_telefone(registro.get("dst"), ddd_base=ddd_caller)
            descritor = registro.get("accountcode") or registro.get("userfield")
            if descritor is not None:
                descritor = str(descritor)[:MAX_DESCRITOR_CDR]
            disposition = registro.get("disposition")
            if disposition is not None:
                disposition = str(disposition).strip().upper() or None
            eot_a = registro.get("eot_a")
            if eot_a is not None:
                eot_a = str(eot_a).strip() or None
            eot_b = registro.get("eot_b")
            if eot_b is not None:
                eot_b = str(eot_b).strip() or None
            eot_preferido = eot_a or eot_b
            sentido = registro.get("sentido")
            if sentido is not None:
                sentido = str(sentido).strip().upper() or None
            snapshot = _json_dump(registro)
            chave = _gerar_chave(caller, callee, data_hora)

            normalizado = {
                "id_registro": str(registro_id),
                "data_hora": data_hora,
                "duracao_segundos": duracao,
                "caller_norm": caller,
                "callee_norm": callee,
                "descritor": descritor,
                "disposition": disposition,
                "sentido": sentido,
                "eot_a": eot_a,
                "eot_b": eot_b,
                "eot": eot_preferido,
                "snapshot": snapshot,
                "chave": chave,
            }
            normalizados.append(normalizado)

            lote.append(
                (
                    id_cliente,
                    id_importacao_cdr,
                    str(registro_id),
                    data_hora,
                    data_hora.date() if data_hora else None,
                    _hora_para_segundos(data_hora),
                    duracao,
                    caller,
                    callee,
                    descritor,
                    None,
                    eot_preferido,
                    chave,
                    snapshot,
                )
            )

            if len(lote) >= 500:
                cursor.executemany(sql_insert, lote)
                conexao.commit()
                lote.clear()
            processados += 1
            if notificar_progresso and processados % 1000 == 0:
                notificar_progresso(processados, total)

        if lote:
            cursor.executemany(sql_insert, lote)
            conexao.commit()

        if notificar_progresso:
            notificar_progresso(total, total)
        return normalizados
    finally:
        cursor.close()
        conexao.close()
