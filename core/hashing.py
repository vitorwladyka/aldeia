"""Hashes do cenário (seção 5.8).

- `preset_hash` = SHA-256 do JSON canônico do preset completo.
- `mcp_config_hash` = `config_hash` do MCP (já calculado em `mcp_mundo.config_mcp`).
- `cenario_hash` = hash de `{"cenario_versao": "1", "preset_hash": ...,
   "mcp_config_hash": ..., "n_agentes": N, "n_turnos": T, "seed": "<decimal>",
   "estoque_inicial": {item: quantidade}}`.
"""
from __future__ import annotations

from mcp_mundo.config_mcp import hash_json


def preset_hash(preset_dados: dict) -> str:
    return hash_json(preset_dados)


def mcp_config_hash(mcp_info: dict) -> str:
    # `mcp_info` já vem com `config_hash` de info(); usamos este.
    return mcp_info["config_hash"]


def cenario_hash(preset_hash_val: str, mcp_config_hash_val: str,
                 n_agentes: int, n_turnos: int, seed: int,
                 estoque_inicial: dict) -> str:
    """Hash do cenário (define "mesmo cenário").

    `seed` entra como decimal sem zeros à esquerda; `estoque_inicial` é um dict
    item→quantidade.
    """
    obj = {
        "cenario_versao": "1",
        "preset_hash": preset_hash_val,
        "mcp_config_hash": mcp_config_hash_val,
        "n_agentes": int(n_agentes),
        "n_turnos": int(n_turnos),
        "seed": str(int(seed)),
        "estoque_inicial": {k: int(v) for k, v in estoque_inicial.items()},
    }
    return hash_json(obj)
