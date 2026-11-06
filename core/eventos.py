"""Eventos globais do turno (seção 5.5).

Ordem: tempestade, fartura, doença, praga. Todos depois do basal.
"""
from __future__ import annotations

from . import rng
from .estado import Estado
from .preset import Preset

RECURSOS_PRAGA = ["trigo", "erva", "peixe", "carne"]


def calcular_eventos(estado: Estado, seed: int, preset: Preset) -> None:
    """Preenche estado.doenca_alvos e estado.praga a partir das chaves do turno.

    Não muta estoque nem vidas — isso é feito pelo motor na ordem canônica.
    """
    turno = estado.turno
    epp = preset.eventos_ppm

    # Tempestade e fartura já estão no estado (decididas no iniciar_turno).
    # Aqui calculamos alvos da doença e recurso da praga.

    if rng.ocorre_evento(seed, turno, "doenca", epp["doenca"]):
        k = rng.doenca_k(seed, turno)
        vivos_no_momento = estado.vivos
        k = min(k, len(vivos_no_momento))
        estado.doenca_alvos = rng.alvos_doenca(seed, turno, k, vivos_no_momento)
    else:
        estado.doenca_alvos = []

    if rng.ocorre_evento(seed, turno, "praga", epp["praga"]):
        idx = rng.indice_praga_recurso(seed, turno)
        recurso = RECURSOS_PRAGA[idx]
        quantidade = estado.estoque.get(recurso, 0)
        perdido = quantidade * preset.praga_ppm // 1_000_000
        if perdido > 0:
            estado.praga = {"recurso": recurso, "perdido": perdido}
        else:
            estado.praga = None
    else:
        estado.praga = None


def ocorre_tempestade(seed: int, turno: int, preset: Preset) -> bool:
    return rng.ocorre_evento(seed, turno, "tempestade", preset.eventos_ppm["tempestade"])


def ocorre_fartura(seed: int, turno: int, preset: Preset) -> bool:
    return rng.ocorre_evento(seed, turno, "fartura", preset.eventos_ppm["fartura"])
