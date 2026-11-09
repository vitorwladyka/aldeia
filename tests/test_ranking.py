"""Endpoints de pontuação: /ranking e /ranking/partida/{id}."""
from __future__ import annotations

from fastapi.testclient import TestClient

import partida
import server


def _jogar(n_turnos: int, ate_o_fim: bool) -> int:
    p = partida.criar("ranking", 42, 2, n_turnos, "bot", 1, False)
    partida.iniciar(p["id"])
    for _ in range(n_turnos if ate_o_fim else 1):
        if partida.executar_turno(p["id"]).get("encerrada"):
            break
    return p["id"]


def test_pontuacao_da_partida_encerrada():
    pid = _jogar(3, ate_o_fim=True)
    r = TestClient(server.app).get(f"/ranking/partida/{pid}")
    assert r.status_code == 200
    dados = r.json()
    assert dados["status"] == "ENCERRADA"
    assert dados["resultado"]["pontuacao_total"] == dados["pontuacao_total"]
    assert "detalhamento" in dados["resultado"]
    assert dados["classificacao"]


def test_partida_em_andamento_da_404():
    pid = _jogar(5, ate_o_fim=False)
    r = TestClient(server.app).get(f"/ranking/partida/{pid}")
    assert r.status_code == 404


def test_ranking_ordena_por_pontuacao():
    _jogar(3, ate_o_fim=True)
    _jogar(5, ate_o_fim=False)
    r = TestClient(server.app).get("/ranking")
    assert r.status_code == 200
    linhas = r.json()["ranking"]
    assert len(linhas) == 2
    pts = [l["pontuacao_total"] for l in linhas]
    assert pts == sorted(pts, reverse=True)
    for campo in ("nome", "status", "n_vivos", "n_agentes", "soma_vidas",
                  "valor_estoque", "turno_atual", "n_turnos", "decisor"):
        assert campo in linhas[0]
