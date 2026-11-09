"""Regras determinísticas (decisores/regras.py) e sua fase no conselho."""
from __future__ import annotations
import armazenamento
import partida
from core.acoes import acoes_viaveis
from core.estado import Agente, Estado
from core.preset import TODOS_ITENS
from decisores import llm, regras


def _estado(estoque=None, vidas=(3, 3, 3), alimento=30):
    est = {i: 0 for i in TODOS_ITENS}
    est.update(estoque or {})
    ags = [Agente(indice=i, nome=f"A{i}", vida=v) for i, v in enumerate(vidas)]
    return Estado(turno=1, estacao="normal", tempestade=False, fartura=False,
                  doenca_alvos=[], praga=None, ordem_turno=[a.indice for a in ags],
                  estoque=est, alimento_solto=alimento, agentes=ags)


def _decidir(estado, preset, idx=0, ocupados=None):
    v = acoes_viaveis(estado, idx, preset, {})
    return regras.decidir(estado, idx, v, preset, {}, ocupados)


def test_transforma_o_que_mais_rende(preset):
    d = _decidir(_estado({"trigo": 3, "madeira": 1}), preset)
    assert (d.acao, d.origem, d.confianca) == ("fazer_pao", "regra", 1.0)


def test_cura_o_mais_ferido(preset):
    d = _decidir(_estado({"remedio": 1}, vidas=(3, 2, 1)), preset)
    assert (d.acao, d.alvo) == ("curar", 2)


def test_repoe_madeira_com_folga(preset):
    assert _decidir(_estado(), preset).acao == "coletar_madeira"


def test_sem_folga_nao_coleta_e_forrageia(preset):
    d = _decidir(_estado(alimento=5), preset)
    assert d.acao == "forragear"


def test_local_saturado_nao_coleta_madeira(preset):
    d = _decidir(_estado({"madeira": 1}), preset, ocupados={"madeira": 2})
    assert d is None or d.acao != "coletar_madeira"


def test_integracao_regra_resolve_sem_llm_nem_laya(monkeypatch):
    def proibido(*a, **k):
        raise AssertionError("LLM não deveria ser chamado")
    monkeypatch.setattr(llm, "decidir_via_strands", proibido)
    p = partida.criar("regra", 42, 2, 5, "llm", 1, False)
    partida.iniciar(p["id"])
    d = armazenamento.carregar(p["id"])
    d["_estado"]["estoque"] = {i: 0 for i in TODOS_ITENS}
    d["_estado"]["estoque"].update({"trigo": 3, "madeira": 1})
    d["_estado"]["alimento_solto"] = 30
    armazenamento.salvar(d)
    partida.executar_turno(p["id"])
    d = armazenamento.carregar(p["id"])
    decs = d["historico"][-1]["decisoes"] if d.get("historico") else []
    assert decs and all(x["origem"] == "regra" for x in decs)
