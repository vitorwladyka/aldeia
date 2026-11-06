"""RNG normativo do core.

Cada sorteio do core é determinado por uma `chave` SHA-256 de
`f"{seed}:{turno}:{tipo}:{agente}"`. As comparações usam `u_lt(chave, ppm)`
em aritmética inteira.

`seed` é uint64 (decimal como texto na API/banco); `agente` é o índice
estável, ou -1 para eventos globais.
"""
from __future__ import annotations

import hashlib

from mcp_mundo.sorteio import u_lt

SEED_MAX = (1 << 64) - 1


def validar_seed(seed: int) -> None:
    """Rejeita seeds fora do domínio uint64."""
    if isinstance(seed, bool):
        raise ValueError("seed não pode ser booleano")
    if not isinstance(seed, int):
        raise ValueError(f"seed deve ser inteiro (recebi {type(seed).__name__})")
    if seed < 0 or seed > SEED_MAX:
        raise ValueError(f"seed fora do domínio uint64 [0, 2^64-1]: {seed}")


def chave(seed: int, turno: int, tipo: str, agente: int) -> int:
    """Devolve um uint64 determinístico para (seed, turno, tipo, agente).

    `agente = -1` para eventos globais.
    """
    validar_seed(seed)
    if not isinstance(turno, int) or turno < 1:
        raise ValueError(f"turno inválido: {turno!r}")
    if not isinstance(tipo, str) or not tipo:
        raise ValueError(f"tipo inválido: {tipo!r}")
    if not isinstance(agente, int):
        raise ValueError(f"agente deve ser int: {agente!r}")
    s = f"{seed}:{turno}:{tipo}:{agente}"
    h = hashlib.sha256(s.encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big")


def indice_praga_recurso(seed: int, turno: int) -> int:
    """Índice em [0, 4) do recurso afetado pela praga.

    Recursos: [trigo, erva, peixe, carne].
    """
    c = chave(seed, turno, "praga_recurso", -1)
    return ((c >> 11) * 4) >> 53


def ocorre_evento(seed: int, turno: int, tipo: str, ppm: int) -> bool:
    """True se o evento `tipo` (global) ocorre no turno."""
    c = chave(seed, turno, tipo, -1)
    return u_lt(c, ppm)


def doenca_k(seed: int, turno: int) -> int:
    """k = 1 se u_lt(chave, 500000), senão k = 2.

    O 500000 é uma constante normativa do algoritmo (seção 5.4), não vem do preset.
    """
    c = chave(seed, turno, "doenca_k", -1)
    return 1 if u_lt(c, 500000) else 2


def ordem_turno(seed: int, turno: int, agentes_vivos: list[int]) -> list[int]:
    """Ordena os índices de agentes vivos pela chave `ordem`, crescente.

    Empate: índice (estável).
    """
    pares = []
    for a in agentes_vivos:
        c = chave(seed, turno, "ordem", a)
        pares.append((c, a))
    # Ordena por (chave, índice). Em caso de empate de chave, o índice menor vem primeiro.
    pares.sort(key=lambda x: (x[0], x[1]))
    return [a for _, a in pares]


def alvos_doenca(seed: int, turno: int, k: int, vivos: list[int]) -> list[int]:
    """Os `k` primeiros vivos pela chave `doenca_alvo`, crescente (empate: índice)."""
    pares = []
    for a in vivos:
        c = chave(seed, turno, "doenca_alvo", a)
        pares.append((c, a))
    pares.sort(key=lambda x: (x[0], x[1]))
    return [a for _, a in pares[:k]]


def acidente(seed: int, turno: int, agente: int, acidente_ppm: int) -> bool:
    """True se o agente sofre acidente ao executar a ação."""
    c = chave(seed, turno, "acidente", agente)
    return u_lt(c, acidente_ppm)


def fartura_coleta(seed: int, turno: int, agente: int, fartura_coleta_ppm: int) -> bool:
    """True se a coleta recebe +1 por fartura."""
    c = chave(seed, turno, "fartura_coleta", agente)
    return u_lt(c, fartura_coleta_ppm)


def forragem(seed: int, turno: int, agente: int, forragem_ppm: int) -> bool:
    """True se forragear rende +1 alimento solto."""
    c = chave(seed, turno, "forragem", agente)
    return u_lt(c, forragem_ppm)


def mcp_coletar_seed(seed: int, turno: int, agente: int) -> int:
    """Seed enviada ao MCP para coletar."""
    return chave(seed, turno, "mcp_coletar", agente)


def mcp_transformar_seed(seed: int, turno: int, agente: int) -> int:
    """Seed enviada ao MCP para transformar."""
    return chave(seed, turno, "mcp_transformar", agente)
