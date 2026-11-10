"""Página de análise: divergência intenção × ação e exportação CSV."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

import partida
import server


def _dec(idx, acao, origem):
    return {"indice": idx, "origem": origem, "acao_json": json.dumps({"acao": acao, "alvo": None}),
            "latencia_ms": 0}


def test_divergencia_usa_a_proposta_do_conselho():
    p = {
        "mensagens": [
            {"turno": 1, "rodada": 1, "agente": 0, "intencao_declarada": "cacar"},
            {"turno": 1, "rodada": 2, "agente": 0, "intencao_declarada": "pescar"},
            {"turno": 1, "rodada": 1, "agente": 1, "intencao_declarada": "forragear"},
            {"turno": 1, "rodada": 2, "agente": None, "intencao_declarada": None},
        ],
        "historico": [{
            "turno": 1,
            "decisoes": [_dec(0, "pescar", "llm"), _dec(1, "forragear", "llm"),
                         _dec(2, "fazer_pao", "lbm")],
            "acoes_executadas": [
                {"agente_id": 0, "sucesso": True, "invalidada_na_execucao": False},
                {"agente_id": 1, "sucesso": True, "invalidada_na_execucao": False},
                {"agente_id": 2, "sucesso": False, "invalidada_na_execucao": False},
            ],
        }],
    }
    linhas = {x["indice"]: x for x in server._decisoes_com_divergencia(p)}
    assert (linhas[0]["intencao"], linhas[0]["acao"], linhas[0]["diverge"]) == ("cacar", "pescar", True)
    assert linhas[1]["diverge"] is False
    assert linhas[2]["intencao"] is None and linhas[2]["diverge"] is False
    assert linhas[2]["resultado"] == "falhou"


def test_exportar_csv_de_decisoes_e_estoque():
    p = partida.criar("csv", 42, 2, 3, "bot", 1, False)
    partida.iniciar(p["id"])
    partida.executar_turno(p["id"])
    c = TestClient(server.app)
    r = c.get(f"/partidas/{p['id']}/analise/decisoes.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    linhas = r.text.strip().splitlines()
    assert linhas[0].startswith("turno,agente,origem,intencao,acao")
    assert len(linhas) == 3  # cabeçalho + 2 agentes
    r = c.get(f"/partidas/{p['id']}/analise/estoque.csv")
    assert r.status_code == 200 and r.text.startswith("turno,item,quantidade")
