"""Pacote `mcp_mundo` — mundo externo via MCP.

Contém:
- `sorteio`: primitivas de RNG em aritmética inteira (u_lt, escolher_lista).
- `config_mcp`: carregamento, hash e info da config do mundo.
- `servidor`: servidor FastMCP (opcional, para rodar o mundo como processo separado).
"""
from . import config_mcp, sorteio  # noqa: F401

__all__ = ["config_mcp", "sorteio"]
