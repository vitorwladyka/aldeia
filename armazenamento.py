"""Persistência simples em JSON: uma partida por arquivo em `data/`.

Sem banco de dados, sem concorrência — suficiente para rodar localmente.
Para produção, trocar por SQLite/Postgres mantendo a mesma interface.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DIRETORIO = Path(__file__).parent / "data"
DIRETORIO.mkdir(parents=True, exist_ok=True)


def _caminho(partida_id: int) -> Path:
    return DIRETORIO / f"partida_{partida_id}.json"


def listar() -> list[dict]:
    """Lista metadados de todas as partidas, ordenadas por id decrescente."""
    out = []
    for p in sorted(DIRETORIO.glob("partida_*.json"), reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append({
                "id": d["id"], "nome": d.get("nome"), "seed": d["seed"],
                "n_agentes": d["n_agentes"], "n_turnos": d["n_turnos"],
                "decisor": d["decisor"], "status": d["status"],
                "turno_atual": d.get("turno_atual", 0),
                "criada_em": d.get("criada_em"),
            })
        except Exception:
            continue
    return out


def carregar(partida_id: int) -> dict | None:
    p = _caminho(partida_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def salvar(partida: dict) -> None:
    p = _caminho(partida["id"])
    p.write_text(json.dumps(partida, ensure_ascii=False, indent=2), encoding="utf-8")


def proximo_id() -> int:
    """Maior id existente + 1 (ou 1 se não há partidas)."""
    ids = []
    for p in DIRETORIO.glob("partida_*.json"):
        try:
            ids.append(int(p.stem.split("_")[1]))
        except ValueError:
            continue
    return (max(ids) + 1) if ids else 1


def limpar_tudo() -> None:
    """Apaga todas as partidas. Usado pelo botão 'Limpar histórico'."""
    for p in DIRETORIO.glob("partida_*.json"):
        p.unlink()
