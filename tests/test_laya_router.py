"""Testes do adaptador HTTP do Laya (sem depender do endpoint real)."""
from __future__ import annotations

import pytest

from decisores import laya_router as lr
from decisores.bot import Decisao


@pytest.fixture
def obs():
    return {
        "versao": 1,
        "partida": {"turno": 1, "turnos_total": 20, "estacao": "normal",
                    "clima": {"tempestade": False, "fartura": False}},
        "eu": {"agente": 0, "nome": "Aria", "vida": 2},
        "agentes": [{"agente": 0, "nome": "Aria", "vida": 2, "status": "vivo"},
                    {"agente": 1, "nome": "Bento", "vida": 1, "status": "vivo"}],
        "estoque": {"alimento_solto": 5, "itens": {"erva": 2, "madeira": 1, "remedio": 1}},
        "acoes_viaveis": [{"acao": "forragear", "alvos": None},
                          {"acao": "coletar_erva", "alvos": None},
                          {"acao": "curar", "alvos": [0, 1]},
                          {"acao": "passar", "alvos": None}],
        "_tools": ["forragear", "coletar_erva", "curar", "passar"],
    }


class _FakeResp:
    def __init__(self, data): self._d = data
    def raise_for_status(self): pass
    def json(self): return self._d


class _FakeClient:
    def __init__(self, data): self._d = data
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def post(self, url, json=None, headers=None): return _FakeResp(self._d)


def _mock_http(monkeypatch, resposta):
    monkeypatch.setattr(lr, "_falha_ate", 0.0)
    monkeypatch.setattr(lr.httpx, "Client", lambda timeout=None: _FakeClient(resposta))


def test_state_e_questions(obs):
    state = lr._montar_state(obs)
    assert state["minha_vida"] == 2 and len(state["feridos"]) == 2
    q = lr._montar_questions(["forragear", "coletar_erva"])
    assert q["acao"]["type"] == "choice"
    assert set(q["acao"]["criteria"]) == {"forragear", "coletar_erva"}


def test_parsing_formato_real_pega_maior_confianca(monkeypatch):
    # formato do laya-serve: answers.acao com 'choice' e vários campos de conf
    _mock_http(monkeypatch, {"answers": {"acao": {
        "choice": "forragear",
        "confidence": 0.31, "answer_confidence": 0.78, "x_jev_confidence": 0.55,
        "probabilities": {"forragear": 0.78, "passar": 0.22},
    }}})
    r = lr._chamar_laya({}, {})
    assert r["selection"] == "forragear"
    assert abs(r["confidence"] - 0.78) < 1e-9  # maior entre os campos


def test_passar_removido_quando_ha_alternativa(monkeypatch, obs):
    capt = {}
    monkeypatch.setattr(lr, "_montar_questions",
                        lambda opcoes: capt.setdefault("opcoes", opcoes) or {"acao": {}})
    monkeypatch.setattr(lr, "_chamar_laya",
                        lambda s, q: {"selection": "forragear", "confidence": 0.9})
    lr.decidir(obs, "", 0)
    assert "passar" not in capt["opcoes"]
    assert "forragear" in capt["opcoes"]


def test_fallback_heuristica_quando_endpoint_fora(monkeypatch, obs):
    monkeypatch.setattr(lr, "_chamar_laya", lambda s, q: None)
    d = lr.decidir(obs, "", 0)
    # cai na heurística; ação dentro das opções do agente
    assert d.acao in ("forragear", "coletar_erva", "curar")
    assert d.origem == "lbm"


def test_acao_fora_das_opcoes_cai_na_heuristica(monkeypatch, obs):
    monkeypatch.setattr(lr, "_chamar_laya",
                        lambda s, q: {"selection": "cacar", "confidence": 0.9})
    d = lr.decidir(obs, "", 0)
    assert d.acao != "cacar"  # cacar não está nas tools viáveis do agente


def test_curar_resolve_alvo_menor_indice(monkeypatch, obs):
    monkeypatch.setattr(lr, "_chamar_laya",
                        lambda s, q: {"selection": "curar", "confidence": 0.9})
    d = lr.decidir(obs, "", 0)
    assert d.acao == "curar" and d.alvo == 0
