from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, date
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .banco.conexao_banco import obter_conexao
from .normaliza_dados import normalizar_cdr, normalizar_detraf

TOLERANCIA_TEMPO_SEG = 300  # 5 minutos
TOLERANCIA_DURACAO_SEG = 10

StatusTipo = str
PRIORIDADE_MOTIVOS = {
    "tempo": 0,
    "status": 1,
    "gh": 2,
    "duracao": 3,
    "eot": 4,
    "descritor": 5,
    "informativo": 6,
}
STATUS_ATENDIDO = {"ANSWERED"}
STATUS_DESCRICOES = {
    "ANSWERED": "Atendida",
    "NO ANSWER": "Sem resposta",
    "BUSY": "Ocupada",
    "FAILED": "Falha",
}


def _delta_tempo(a: Optional[datetime], b: Optional[datetime]) -> Optional[int]:
    if not a or not b:
        return None
    return abs(int((a - b).total_seconds()))


def _selecionar_candidato(detraf: Dict, candidatos: List[Dict]) -> Optional[Tuple[int, Dict, Optional[int], int]]:
    melhor: Optional[Tuple[int, Dict, Optional[int], int, float]] = None
    for idx, candidato in enumerate(candidatos):
        # ignora candidatos sem ambos telefones normalizados
        if not (candidato.get("caller_norm") and candidato.get("callee_norm")):
            continue
        delta_tempo = _delta_tempo(detraf.get("data_hora"), candidato.get("data_hora"))
        delta_duracao = abs(int(detraf.get("duracao_segundos") or 0) - int(candidato.get("duracao_segundos") or 0))
        score = (delta_tempo if delta_tempo is not None else 999999) + delta_duracao
        if melhor is None or score < melhor[-1]:
            melhor = (idx, candidato, delta_tempo, delta_duracao, score)
    if melhor:
        idx, cand, delta_t, delta_d, _ = melhor
        return idx, cand, delta_t, delta_d
    return None


def _comparar_eot(rotulo: str, eot_detraf: Optional[str], eot_cdr: Optional[str]) -> Tuple[bool, Optional[str]]:
    eot_detraf = (eot_detraf or "").strip() or None
    eot_cdr = (eot_cdr or "").strip() or None
    if eot_detraf and eot_cdr:
        if eot_detraf != eot_cdr:
            return False, f"EOT {rotulo} divergente ({eot_detraf} x {eot_cdr})"
        return True, None
    if eot_detraf and not eot_cdr:
        return False, f"EOT {rotulo} ausente no CDR"
    if eot_cdr and not eot_detraf:
        return False, f"EOT {rotulo} ausente no DETRAF"
    return True, None


def _destino_eh_0800(numero: Optional[str]) -> bool:
    if not numero:
        return False
    digitos = re.sub(r"\D", "", str(numero))
    if len(digitos) < 10:
        return False
    return digitos.startswith("0800") or digitos.startswith("800")


def _deve_inverter_eot(detraf: Dict, cdr: Optional[Dict]) -> bool:
    if not detraf:
        return False
    destino_detraf = detraf.get("assinante_b_norm") or detraf.get("assinante_b")
    if _destino_eh_0800(destino_detraf):
        return True
    if cdr:
        destino_cdr = cdr.get("callee_norm") or cdr.get("dst") or cdr.get("numero_destino")
        if _destino_eh_0800(destino_cdr):
            return True
    return False


def _traduzir_status(disposition: Optional[str]) -> str:
    if not disposition:
        return "desconhecido"
    chave = disposition.upper()
    return STATUS_DESCRICOES.get(chave, chave.title())


def _motivo(tipo: str, mensagem: str) -> Dict[str, object]:
    return {
        "tipo": tipo,
        "mensagem": mensagem,
        "prioridade": PRIORIDADE_MOTIVOS.get(tipo, PRIORIDADE_MOTIVOS["informativo"]),
    }


def avaliar_divergencias(
    detraf: Dict,
    cdr: Optional[Dict],
    delta_t: Optional[int],
    delta_d: Optional[int],
) -> Tuple[str, List[Dict[str, object]]]:
    motivos: List[Dict[str, object]] = []

    if delta_t is not None and delta_t > TOLERANCIA_TEMPO_SEG:
        minutos = delta_t / 60
        motivos.append(
            _motivo(
                "tempo",
                f"Horários distantes em {delta_t}s (~{minutos:.1f} min), acima da tolerância de ±{TOLERANCIA_TEMPO_SEG//60} min.",
            )
        )
        return "PERDIDO", motivos

    if not cdr:
        return "PERDIDO", [_motivo("informativo", "Nenhum CDR correspondente disponível.")]

    if delta_d is not None and delta_d > TOLERANCIA_DURACAO_SEG:
        motivos.append(
            _motivo(
                "duracao",
                f"Diferença de {delta_d}s entre as durações (tolerância {TOLERANCIA_DURACAO_SEG}s).",
            )
        )

    descritor_detraf = detraf.get("descritor")
    descritor_cdr = (cdr or {}).get("descritor")
    if descritor_detraf and descritor_cdr and descritor_detraf != descritor_cdr:
        motivos.append(_motivo("descritor", "Descritor divergente entre DETRAF e CDR."))

    disposition = (cdr or {}).get("disposition")
    if not disposition:
        motivos.append(_motivo("status", "Status da chamada no CDR não foi informado."))
    elif disposition.upper() not in STATUS_ATENDIDO:
        motivos.append(
            _motivo("status", f"Status da chamada no CDR é '{_traduzir_status(disposition)}'.")
        )

    detraf_eot_a = detraf.get("eqt_devedora") or detraf.get("eot_devedora")
    detraf_eot_b = detraf.get("eqt_credora") or detraf.get("eot_credora")
    cdr_eot_a = (cdr or {}).get("eot_a")
    cdr_eot_b = (cdr or {}).get("eot_b")

    if _deve_inverter_eot(detraf, cdr):
        detraf_eot_a, detraf_eot_b = detraf_eot_b, detraf_eot_a

    for rotulo, detraf_val, cdr_val in (
        ("A", detraf_eot_a, cdr_eot_a),
        ("B", detraf_eot_b, cdr_eot_b),
    ):
        ok_eot, mensagem = _comparar_eot(rotulo, detraf_val, cdr_val)
        if not ok_eot and mensagem:
            motivos.append(_motivo("eot", mensagem))

    gh_operadora = (detraf.get("gh") or "").strip().upper()
    segundos_normais = int(detraf.get("segundos_gh_normal") or 0)
    segundos_reduzidos = int(detraf.get("segundos_gh_reduzido") or 0)
    if gh_operadora == "N" and segundos_reduzidos > 0:
        minutos = round(segundos_reduzidos / 60, 2)
        motivos.append(
            _motivo("gh", f"Chamada cruza período reduzido ({minutos} min) mas GH informado = N.")
        )
    if gh_operadora == "R" and segundos_normais > 0:
        minutos = round(segundos_normais / 60, 2)
        motivos.append(
            _motivo("gh", f"Chamada com {minutos} min em horário normal, porém GH informado = R.")
        )

    motivos.sort(key=lambda item: item["prioridade"])
    if motivos:
        return "DIVERGENTE", motivos
    return "CONFERIDO", motivos


def _descrever_divergencia(detraf: Dict, cdr: Optional[Dict], delta_t: Optional[int], delta_d: Optional[int]):
    status, motivos = avaliar_divergencias(detraf, cdr, delta_t, delta_d)
    if motivos:
        principal = motivos[0]
        return status, principal["tipo"], principal["mensagem"], motivos
    return status, None, "OK", motivos


def _persistir(id_importacao_detraf: int, linhas: Sequence[Tuple]) -> None:
    conexao = obter_conexao()
    cursor = conexao.cursor()
    try:
        cursor.execute(
            "DELETE FROM conferencia_resultados WHERE id_importacao_detraf=%s",
            (id_importacao_detraf,),
        )
        if linhas:
            sql = (
                """
                INSERT INTO conferencia_resultados (
                    id_cliente, id_importacao_detraf, id_importacao_cdr, id_registro_detraf,
                    id_registro_cdr, status, delta_duracao_seg, delta_hora_seg, descricao_divergencia,
                    observacao, detalhes_divergencia, chave_batimento, descritor, gh, assinante_a,
                    assinante_b, data_hora, duracao_detraf_seg, duracao_cdr_seg, eot_detraf, eot_cdr,
                    snapshot_detraf, snapshot_cdr
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                )
                """
            )
            cursor.executemany(sql, linhas)
        conexao.commit()
    finally:
        cursor.close()
        conexao.close()


def executar_batimento(
    id_cliente: int,
    id_importacao_detraf: int,
    id_importacao_cdr: Optional[int],
    periodo_inicio: Optional[date] = None,
    periodo_fim: Optional[date] = None,
    notificar_execucao: Optional[Callable[[str, str, int, int, int, Optional[str]], None]] = None,
) -> Dict[str, int]:
    def atualizar(status: str, etapa: str, progresso: int, processados: int, total: int, mensagem: Optional[str] = None):
        if not notificar_execucao:
            return
        notificar_execucao(status, etapa, progresso, processados, total, mensagem)
    contexto = {"total": 0, "processados": 0}

    def _processar() -> Dict[str, int]:
        atualizar("NORMALIZANDO_DETRAF", "Normalizando DETRAF", 1, 0, 0, None)
        detraf_norm = normalizar_detraf(
            id_cliente,
            id_importacao_detraf,
            notificar_progresso=lambda proc, total: atualizar(
                "NORMALIZANDO_DETRAF",
                "Normalizando DETRAF",
                int((proc / total) * 30) if total else 30,
                proc,
                total,
                None,
            ),
        )

        if id_importacao_cdr:
            atualizar("NORMALIZANDO_CDR", "Normalizando CDR", 30, 0, 0, None)
            cdr_norm = normalizar_cdr(
                id_cliente,
                id_importacao_cdr,
                periodo_inicio,
                periodo_fim,
                notificar_progresso=lambda proc, total: atualizar(
                    "NORMALIZANDO_CDR",
                    "Normalizando CDR",
                    30 + int((proc / total) * 30) if total else 60,
                    proc,
                    total,
                    None,
                ),
            )
        else:
            cdr_norm = []

        cdr_pool: Dict[Tuple[Optional[str], Optional[str]], List[Dict]] = defaultdict(list)
        for registro in cdr_norm:
            chave = (registro.get("caller_norm"), registro.get("callee_norm"))
            cdr_pool[chave].append(registro)

        for lista in cdr_pool.values():
            lista.sort(key=lambda item: item.get("data_hora") or datetime.min)

        linhas_insert: List[Tuple] = []
        totais = {"CONFERIDO": 0, "DIVERGENTE": 0, "PERDIDO": 0}
        total_detraf = len(detraf_norm)
        contexto["total"] = total_detraf
        processados_loop = 0
        if total_detraf:
            atualizar("BATENDO_REGISTROS", "Comparando registros", 60, 0, total_detraf, None)

        for detraf in detraf_norm:
            chave = (detraf.get("assinante_a"), detraf.get("assinante_b"))
            candidatos = cdr_pool.get(chave, [])
            selecionado = _selecionar_candidato(detraf, candidatos) if candidatos else None
            candidato = None
            delta_t: Optional[int] = None
            delta_d: Optional[int] = None

            if selecionado:
                idx, candidato, delta_t, delta_d = selecionado
                candidatos.pop(idx)

            status, motivo, observacao, detalhes = _descrever_divergencia(detraf, candidato, delta_t, delta_d)
            if motivo == "tempo" and candidato is not None:
                candidatos.insert(0, candidato)
                candidato = None
                delta_t = None
                delta_d = None
            if candidato is None and not id_importacao_cdr:
                observacao = "Aguardando CDR"
                motivo = "aguardando_cdr"
                status = "PERDIDO"
                detalhes = [_motivo(motivo, observacao)]
            if candidato is None and id_importacao_cdr and not cdr_norm:
                observacao = "CDR sem registros"
                motivo = "cdr_vazio"
                status = "PERDIDO"
                detalhes = [_motivo(motivo, observacao)]
            if candidato is None and delta_t is None and cdr_norm:
                minutos = TOLERANCIA_TEMPO_SEG // 60
                observacao = f"Sem par ±{minutos} min"
                motivo = "sem_par"
                status = "PERDIDO"
                detalhes = [_motivo(motivo, observacao)]

            delta_hora = delta_t
            totais[status] = totais.get(status, 0) + 1
            processados_loop += 1
            contexto["processados"] = processados_loop
            if total_detraf and processados_loop % 1000 == 0:
                progresso = 60 + int((processados_loop / total_detraf) * 35)
                atualizar("BATENDO_REGISTROS", "Comparando registros", progresso, processados_loop, total_detraf, None)

            linhas_insert.append(
                (
                    id_cliente,
                    id_importacao_detraf,
                    id_importacao_cdr,
                    detraf["id_registro"],
                    (candidato or {}).get("id_registro"),
                    status,
                    delta_d,
                    delta_hora,
                    motivo,
                    observacao,
                    json.dumps(detalhes, ensure_ascii=False) if detalhes else None,
                    detraf.get("chave"),
                    detraf.get("descritor"),
                    detraf.get("gh"),
                    detraf.get("assinante_a"),
                    detraf.get("assinante_b"),
                    detraf.get("data_hora"),
                    detraf.get("duracao_segundos"),
                    (candidato or {}).get("duracao_segundos"),
                    detraf.get("eqt_credora"),
                    (candidato or {}).get("eot_a")
                    or (candidato or {}).get("eot_b"),
                    detraf.get("snapshot"),
                    (candidato or {}).get("snapshot"),
                )
            )

        atualizar("GRAVANDO_RESULTADOS", "Gravando classificação", 95, processados_loop, total_detraf, None)
        _persistir(id_importacao_detraf, linhas_insert)

        atualizar("CONCLUIDO", "Conferência concluída", 100, total_detraf, total_detraf, "Processamento finalizado")
        return {
            "total": len(detraf_norm),
            "conferidos": totais.get("CONFERIDO", 0),
            "divergentes": totais.get("DIVERGENTE", 0),
            "perdidos": totais.get("PERDIDO", 0),
        }

    try:
        return _processar()
    except Exception as exc:
        atualizar(
            "ERRO",
            "Erro durante a conferência",
            99,
            contexto.get("processados", 0),
            contexto.get("total", 0),
            str(exc),
        )
        raise
