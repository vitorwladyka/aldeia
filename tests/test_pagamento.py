"""Testes do algoritmo de pagamento de alimento."""
from __future__ import annotations

import pytest

from core.pagamento import pagar


def _estoque_vazio():
    return {"peixe": 0, "carne": 0, "pao": 0, "peixe_assado": 0,
            "carne_assada": 0, "trigo": 0, "madeira": 0, "erva": 0, "remedio": 0}


def test_paga_com_alimento_solto(preset):
    est = _estoque_vazio()
    novo, solto = pagar(est, 5, 2, preset)
    assert solto == 3
    assert novo == est  # não mexeu em itens


def test_valor_zero_nao_altera(preset):
    est = _estoque_vazio()
    novo, solto = pagar(est, 4, 0, preset)
    assert solto == 4


def test_consome_item_e_devolve_troco(preset):
    # Sem solto, 1 de custo: consome 1 peixe (valor 4) e devolve 3 de troco.
    est = _estoque_vazio()
    est["peixe"] = 1
    novo, solto = pagar(est, 0, 1, preset)
    assert novo["peixe"] == 0
    assert solto == 3  # troco (4 - 1)


def test_erro_quando_insuficiente(preset):
    est = _estoque_vazio()
    with pytest.raises(RuntimeError):
        pagar(est, 0, 10, preset)  # nada para pagar 10


def test_valor_negativo_rejeitado(preset):
    with pytest.raises(ValueError):
        pagar(_estoque_vazio(), 0, -1, preset)
