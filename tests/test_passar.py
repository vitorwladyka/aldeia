"""Testes da mecânica de 'passar' (custo 1 fixo; sem alimento → perde vida)."""
from __future__ import annotations

import asyncio

from core.estado import Agente, Estado
from core import motor
from core.acoes import acoes_viaveis
from core.mcp_cliente import MundoMemoria
from core.preset import TODOS_ITENS


def _estado(alimento_solto, vida=3):
    ag = Agente(indice=0, nome="Aria", vida=vida)
    return Estado(turno=1, estacao="normal", tempestade=False, fartura=False,
                  doenca_alvos=[], praga=None, ordem_turno=[0],
                  estoque={i: 0 for i in TODOS_ITENS},
                  alimento_solto=alimento_solto, agentes=[ag])


def _executar_passar(estado, preset):
    ad = [motor.AcaoDecidida(agente=0, acao="passar")]
    return asyncio.run(motor.executar_acoes(estado, ad, 42, preset, MundoMemoria()))


def test_preset_passar_custa_1(preset):
    assert preset.acao("passar")["custo"] == 1


def test_passar_sempre_viavel_sem_alimento(preset):
    e = _estado(0)
    viaveis = [v["acao"] for v in acoes_viaveis(e, 0, preset)]
    assert "passar" in viaveis


def test_passar_com_alimento_paga_1(preset):
    e = _estado(5, vida=3)
    _executar_passar(e, preset)
    assert e.alimento_solto == 4
    assert e.agente(0).vida == 3


def test_passar_sem_alimento_perde_vida(preset):
    e = _estado(0, vida=3)
    _executar_passar(e, preset)
    assert e.agente(0).vida == 2
    assert any(ev["motivo"] == "fome" for ev in e.eventos_vida)


def test_passar_sem_alimento_vida_1_morre(preset):
    e = _estado(0, vida=1)
    _executar_passar(e, preset)
    assert e.agente(0).vida == 0
    assert not e.agente(0).vivo
