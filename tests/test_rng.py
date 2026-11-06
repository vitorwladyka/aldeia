"""Testes do RNG determinístico e dos sorteios em aritmética inteira."""
from __future__ import annotations

import pytest

from core import rng
from mcp_mundo.sorteio import u_lt, escolher_lista


def test_chave_deterministica():
    c1 = rng.chave(42, 1, "ordem", 0)
    c2 = rng.chave(42, 1, "ordem", 0)
    assert c1 == c2
    # chaves diferentes para entradas diferentes
    assert rng.chave(42, 1, "ordem", 0) != rng.chave(42, 1, "ordem", 1)
    assert rng.chave(42, 1, "ordem", 0) != rng.chave(42, 2, "ordem", 0)


def test_chave_dominio_uint64():
    c = rng.chave(42, 1, "x", -1)
    assert 0 <= c < (1 << 64)


def test_validar_seed_rejeita_invalidos():
    with pytest.raises(ValueError):
        rng.validar_seed(-1)
    with pytest.raises(ValueError):
        rng.validar_seed(1 << 64)
    with pytest.raises(ValueError):
        rng.validar_seed(True)  # bool não é seed


def test_u_lt_fronteiras():
    assert u_lt(0, 1_000_000) is True        # 0 < qualquer ppm > 0
    assert u_lt(0, 0) is False               # 0 < 0 é falso
    # u/2^64 com u = 2^64-1 ≈ 0.99999...; é < 1.0 (ppm=1_000_000), então True.
    assert u_lt((1 << 64) - 1, 1_000_000) is True
    # mas com ppm abaixo do topo, u no máximo não é menor:
    assert u_lt((1 << 64) - 1, 999_999) is False


def test_u_lt_valida_dominio():
    with pytest.raises(ValueError):
        u_lt(-1, 500000)
    with pytest.raises(ValueError):
        u_lt(0, 2_000_000)  # ppm fora de [0, 1_000_000]


def test_escolher_lista_indice_estavel():
    lista = [0, 1, 2, 3]
    # u=0 → índice 0; u no topo → último índice
    assert escolher_lista(0, lista) == 0
    assert escolher_lista((1 << 64) - 1, lista) == 3


def test_ordem_turno_determinista_e_cobre_todos():
    vivos = [0, 1, 2, 3, 4]
    o1 = rng.ordem_turno(42, 1, vivos)
    o2 = rng.ordem_turno(42, 1, vivos)
    assert o1 == o2
    assert sorted(o1) == sorted(vivos)  # permutação, não perde/duplica
