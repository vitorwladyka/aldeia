"""Testes do roteamento híbrido: threshold + colisão de local."""
from __future__ import annotations

import hibrido
from decisores.bot import Decisao
from decisores import laya_router, llm


def test_local_da_acao():
    assert hibrido.local_da_acao("pescar") == "peixe"
    assert hibrido.local_da_acao("cacar") == "carne"
    assert hibrido.local_da_acao("forragear") == "forragear"  # sem local → próprio id


def test_mantem_lbm_sem_colisao_e_conf_alta(monkeypatch):
    obs = {"acoes_viaveis": [{"acao": "pescar", "alvos": None}]}
    monkeypatch.setattr(laya_router, "decidir",
                        lambda o, p, i: Decisao("pescar", None, 0.95, "lbm", "fixo"))
    d = hibrido.decidir(obs, "", 0, threshold=0.5,
                        locais_ocupados={"peixe": 1}, saturacao_limite=2)
    assert d.origem == "lbm" and d.acao == "pescar"


def test_escala_por_colisao(monkeypatch):
    obs = {"acoes_viaveis": [{"acao": "pescar", "alvos": None}]}
    monkeypatch.setattr(laya_router, "decidir",
                        lambda o, p, i: Decisao("pescar", None, 0.95, "lbm", "fixo"))
    monkeypatch.setattr(llm, "decidir",
                        lambda o, p, i: Decisao("forragear", None, 1.0, "llm", "llm"))
    # peixe já com 2 ocupantes → este seria o 3º → colisão → escala
    d = hibrido.decidir(obs, "", 0, threshold=0.5,
                        locais_ocupados={"peixe": 2}, saturacao_limite=2)
    assert d.origem == "llm" and "colisao" in d.raciocinio


def test_escala_por_confianca_baixa(monkeypatch):
    obs = {"acoes_viaveis": [{"acao": "pescar", "alvos": None}]}
    monkeypatch.setattr(laya_router, "decidir",
                        lambda o, p, i: Decisao("pescar", None, 0.30, "lbm", "fixo"))
    monkeypatch.setattr(llm, "decidir",
                        lambda o, p, i: Decisao("forragear", None, 1.0, "llm", "llm"))
    d = hibrido.decidir(obs, "", 0, threshold=0.5,
                        locais_ocupados={"peixe": 0}, saturacao_limite=2)
    assert d.origem == "llm" and "conf" in d.raciocinio
