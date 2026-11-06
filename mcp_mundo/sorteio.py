"""Sorteios determinísticos do mundo em aritmética inteira.

Todas as comparações usam `u_lt(u, ppm)` que devolve True quando
`u / 2^64 < ppm / 1_000_000`, sem nunca usar ponto flutuante.

`escolher_lista(u, lista)` devolve `lista[(u * len(lista)) >> 64]`.
"""
from __future__ import annotations

from typing import Sequence

UINT64_MAX = (1 << 64) - 1


def u_lt(u: int, ppm: int) -> bool:
    """True se `u / 2^64 < ppm / 1_000_000` em aritmética inteira.

    Equivalente a `u * 1_000_000 < ppm * 2^64`.
    """
    if not isinstance(u, int):
        raise TypeError(f"u deve ser int (recebi {type(u).__name__})")
    if not isinstance(ppm, int):
        raise TypeError(f"ppm deve ser int (recebi {type(ppm).__name__})")
    if not (0 <= u <= UINT64_MAX):
        raise ValueError(f"u fora do domínio uint64: {u}")
    if not (0 <= ppm <= 1_000_000):
        raise ValueError(f"ppm fora do domínio [0, 1_000_000]: {ppm}")
    return u * 1_000_000 < ppm * (1 << 64)


def escolher_lista(u: int, lista: Sequence[int]) -> int:
    """Devolve `lista[(u * len(lista)) >> 64]`.

    `lista` é uma lista de inteiros não-negativos; o índice é escolhido
    deterministicamente a partir de `u` (uint64).
    """
    if not isinstance(u, int):
        raise TypeError(f"u deve ser int (recebi {type(u).__name__})")
    if not (0 <= u <= UINT64_MAX):
        raise ValueError(f"u fora do domínio uint64: {u}")
    if not lista:
        raise ValueError("lista vazia")
    n = len(lista)
    idx = (u * n) >> 64
    if idx >= n:
        idx = n - 1
    return int(lista[idx])
