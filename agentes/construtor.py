"""Constrói o system prompt e a lista de tools efetivas de um agente.

- `montar_system_prompt(prompt_base, skills_texto)`: concatena o prompt base
  com o texto de habilidades (skills) do agente.
- `tools_efetivas(tools_ids, viaveis)`: interseção entre as tools do agente e
  as ações viáveis do turno, preservando a ordem canônica; vazio → ["passar"].
"""
from __future__ import annotations

from . import catalogo


def montar_system_prompt(prompt_base: str, skills_texto: str) -> str:
    """Compoe o system prompt: prompt base + texto de habilidades (skills).

    `skills_texto` é texto livre (editável por agente). Se vazio, retorna só o
    prompt base.
    """
    base = (prompt_base or "").strip()
    skills = (skills_texto or "").strip()
    if not skills:
        return base
    if base:
        return f"{base}\n\n# Habilidades\n{skills}"
    return f"# Habilidades\n{skills}"


def tools_efetivas(tools_ids: list[str], viaveis: list[dict]) -> list[str]:
    """Interseção entre as tools do agente e as ações viáveis do turno.

    Preserva a ordem canônica do catálogo (= ordem do preset). Se a interseção
    for vazia, devolve ["passar"] — garantindo que o agente sempre tem ao menos
    uma ação para escolher.
    """
    permitidas = set(tools_ids or [])
    viaveis_ids = {v["acao"] for v in (viaveis or [])}
    efetivas = [
        tid for tid in catalogo.IDS_TOOLS
        if tid in permitidas and tid in viaveis_ids
    ]
    return efetivas if efetivas else ["passar"]
