"""Testes do invariante central: determinismo.

Mesma seed + preset + decisões → mesmo resultado, bit a bit. Protege o coração
do projeto contra regressões em refatorações futuras.
"""
from __future__ import annotations

import armazenamento
import partida


def _rodar_partida_bot(seed=42, n_agentes=3, n_turnos=8):
    """Roda uma partida bot (determinística) do início ao fim e devolve o JSON."""
    p = partida.criar(f"det-{seed}", seed, n_agentes, n_turnos, "bot", 1, True)
    pid = p["id"]
    partida.iniciar(pid)
    while True:
        r = partida.executar_turno(pid)
        if r["encerrada"]:
            break
    return armazenamento.carregar(pid)


def test_bot_reproduzivel_mesma_seed():
    """Duas partidas bot com a mesma seed produzem o mesmo histórico."""
    a = _rodar_partida_bot(seed=42)
    b = _rodar_partida_bot(seed=42)
    # Compara os campos que definem o resultado (ignora id/nome/timestamps).
    assert a["historico"] == b["historico"]
    assert a["placar_final"] == b["placar_final"]
    assert a["cenario_hash"] == b["cenario_hash"]


def test_seeds_diferentes_divergem():
    """Seeds diferentes devem (quase sempre) divergir no cenário/resultado."""
    a = _rodar_partida_bot(seed=42)
    b = _rodar_partida_bot(seed=99)
    assert a["cenario_hash"] != b["cenario_hash"]


def test_cenario_hash_estavel_entre_execucoes():
    """O cenario_hash de criação é estável para os mesmos parâmetros."""
    p1 = partida.criar("h1", 7, 4, 20, "bot", 1, True)
    p2 = partida.criar("h2", 7, 4, 20, "bot", 1, True)
    assert p1["cenario_hash"] == p2["cenario_hash"]
    assert p1["preset_hash"] == p2["preset_hash"]
