"""Testes do decisor LLM (Strands) com o runner mockado (sem rede)."""
from __future__ import annotations

import pytest

from decisores import llm


@pytest.fixture
def obs():
    return {
        "versao": 1,
        "partida": {"turno": 1, "turnos_total": 20, "estacao": "normal",
                    "clima": {"tempestade": False, "fartura": False}},
        "eu": {"agente": 0, "nome": "Aria", "vida": 2},
        "agentes": [{"agente": 0, "nome": "Aria", "vida": 2, "status": "vivo"},
                    {"agente": 1, "nome": "Bento", "vida": 1, "status": "vivo"}],
        "estoque": {"alimento_solto": 50, "itens": {"remedio": 1}},
        "historico": [], "mensagens": [],
        "acoes_viaveis": [
            {"acao": "pescar", "custo": 8, "alvos": None},
            {"acao": "forragear", "custo": 0, "alvos": None},
            {"acao": "curar", "custo": 0, "alvos": [0, 1]},
            {"acao": "passar", "custo": 1, "alvos": None},
        ],
    }


def test_escolha_valida(monkeypatch, obs):
    monkeypatch.setattr(llm, "decidir_via_strands",
                        lambda s, t, o, v: {"acao": "pescar", "alvo": None})
    d = llm.decidir(obs, "base", 0)
    assert d.acao == "pescar" and d.origem == "llm" and d.confianca == 1.0


def test_curar_com_alvo_valido(monkeypatch, obs):
    monkeypatch.setattr(llm, "decidir_via_strands",
                        lambda s, t, o, v: {"acao": "curar", "alvo": 1})
    d = llm.decidir(obs, "base", 0)
    assert d.acao == "curar" and d.alvo == 1


def test_curar_alvo_invalido_corrigido(monkeypatch, obs):
    monkeypatch.setattr(llm, "decidir_via_strands",
                        lambda s, t, o, v: {"acao": "curar", "alvo": 99})
    d = llm.decidir(obs, "base", 0)
    assert d.acao == "curar" and d.alvo == 0  # menor índice ferido


def test_acao_invalida_cai_no_fallback(monkeypatch, obs):
    monkeypatch.setattr(llm, "decidir_via_strands",
                        lambda s, t, o, v: {"acao": "cacar", "alvo": None})
    d = llm.decidir(obs, "base", 0)
    assert d.confianca == 0.5 and "fallback" in d.raciocinio


def test_sem_escolha_cai_no_fallback(monkeypatch, obs):
    monkeypatch.setattr(llm, "decidir_via_strands", lambda s, t, o, v: None)
    d = llm.decidir(obs, "base", 0)
    assert d.confianca == 0.5


def test_tools_do_agente_restringem(monkeypatch, obs):
    capt = {}
    def captura(system, tids, obs_texto, viaveis):
        capt["tids"] = tids
        return {"acao": "forragear", "alvo": None}
    monkeypatch.setattr(llm, "decidir_via_strands", captura)
    obs["_tools"] = ["forragear", "passar"]  # sem pescar/curar
    llm.decidir(obs, "base", 0)
    assert "pescar" not in capt["tids"]
    assert "forragear" in capt["tids"]


def test_sem_viaveis_passa(obs):
    d = llm.decidir({"acoes_viaveis": []}, "base", 0)
    assert d.acao == "passar" and d.confianca == 1.0
