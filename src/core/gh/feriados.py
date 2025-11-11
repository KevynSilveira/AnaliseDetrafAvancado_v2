from __future__ import annotations

from datetime import date
from typing import Iterable, Set

# Lista básica de feriados nacionais. Pode ser estendida conforme a necessidade do cliente.
# Utilize o formato YYYY-MM-DD.
FERIADOS_NACIONAIS = {
    "2025-01-01",  # Confraternização Universal
    "2025-04-18",  # Sexta-feira Santa
    "2025-04-21",  # Tiradentes
    "2025-05-01",  # Dia do Trabalho
    "2025-09-07",  # Independência do Brasil
    "2025-10-12",  # Nossa Senhora Aparecida
    "2025-11-02",  # Finados
    "2025-11-15",  # Proclamação da República
    "2025-12-25",  # Natal
}


def _normalizar_datas(datas: Iterable[str]) -> Set[date]:
    conjunto: Set[date] = set()
    for item in datas:
        try:
            ano, mes, dia = map(int, item.split("-"))
            conjunto.add(date(ano, mes, dia))
        except Exception:
            continue
    return conjunto


FERIADOS_NACIONAIS_DATAS = _normalizar_datas(FERIADOS_NACIONAIS)


def eh_feriado(data_referencia: date, adicionais: Iterable[str] | None = None) -> bool:
    if not data_referencia:
        return False
    if data_referencia in FERIADOS_NACIONAIS_DATAS:
        return True
    if adicionais:
        extras = _normalizar_datas(adicionais)
        if data_referencia in extras:
            return True
    return False
