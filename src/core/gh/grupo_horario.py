from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Sequence

from .feriados import eh_feriado

STFC_WINDOWS = {
    "SEGSEX": [
        (0, 360, "R"),    # 00:00-06:00
        (360, 1440, "N"),  # 06:00-24:00
    ],
    "SABADO": [
        (0, 360, "R"),
        (360, 840, "N"),   # 06:00-14:00
        (840, 1440, "R"),
    ],
    "DOMINGO": [
        (0, 1440, "R"),
    ],
}

SMP_WINDOWS = {
    "SEGSEX": [
        (0, 420, "R"),     # 00:00-07:00
        (420, 1260, "N"),  # 07:00-21:00
        (1260, 1440, "R"),
    ],
    "SABADO": [
        (0, 420, "R"),
        (420, 1260, "N"),
        (1260, 1440, "R"),
    ],
    "DOMINGO": [
        (0, 1440, "R"),
    ],
}


@dataclass
class SegmentoGH:
    gh: str
    segundos: int
    inicio: str
    fim: str


@dataclass
class ResultadoGrupoHorario:
    segundos_normal: int
    segundos_reduzido: int
    segmentos: Sequence[SegmentoGH]


def _tipo_dia_referencia(moment: datetime) -> str:
    if not moment:
        return "SEGSEX"
    data = moment.date()
    if eh_feriado(data):
        return "DOMINGO"
    weekday = data.weekday()  # 0=Mon .. 6=Sun
    if weekday == 5:
        return "SABADO"
    if weekday == 6:
        return "DOMINGO"
    return "SEGSEX"


def determinar_gh_momento(moment: datetime, tarifa: str) -> str:
    if not moment:
        return "R"
    tabela = SMP_WINDOWS if tarifa == "VU-M" else STFC_WINDOWS
    tipo_dia = _tipo_dia_referencia(moment)
    janela = tabela.get(tipo_dia, tabela["SEGSEX"])
    minuto = moment.hour * 60 + moment.minute
    for inicio, fim, gh in janela:
        if inicio <= minuto < fim:
            return gh
    return "R"


def calcular_segmentos_gh(
    inicio: datetime,
    duracao_segundos: int,
    tarifa: str,
) -> ResultadoGrupoHorario:
    if not inicio or duracao_segundos <= 0:
        return ResultadoGrupoHorario(0, 0, [])

    moment = inicio
    restante = duracao_segundos
    segmentos: List[SegmentoGH] = []
    total_normal = 0
    total_reduzido = 0

    while restante > 0:
        gh = determinar_gh_momento(moment, tarifa)
        proximo_minuto = (moment.replace(second=0, microsecond=0) + timedelta(minutes=1))
        delta = int((proximo_minuto - moment).total_seconds())
        if delta <= 0:
            delta = 60
        if delta > restante:
            delta = restante

        fim = moment + timedelta(seconds=delta)
        segmentos.append(SegmentoGH(gh=gh, segundos=delta, inicio=moment.isoformat(), fim=fim.isoformat()))
        if gh == "N":
            total_normal += delta
        else:
            total_reduzido += delta

        restante -= delta
        moment = fim

    return ResultadoGrupoHorario(
        segundos_normal=total_normal,
        segundos_reduzido=total_reduzido,
        segmentos=segmentos,
    )
