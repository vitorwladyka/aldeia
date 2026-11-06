"""Testes do catálogo e do construtor de prompt/tools dos agentes."""
from __future__ import annotations

from agentes import catalogo, construtor


def test_skills_padrao_e_texto():
    assert isinstance(catalogo.PADRAO_SKILLS, str)
    assert len(catalogo.PADRAO_SKILLS) > 100


def test_tools_padrao_tem_todas_as_acoes():
    assert set(catalogo.PADRAO_TOOLS) == set(catalogo.IDS_TOOLS)
    for acao in ("pescar", "curar", "fazer_pao", "passar"):
        assert acao in catalogo.PADRAO_TOOLS


def test_tool_ids_validos_descarta_desconhecidos():
    out = catalogo.tool_ids_validos(["pescar", "zzz", "curar"])
    assert out == [t for t in catalogo.IDS_TOOLS if t in ("pescar", "curar")]


def test_system_prompt_concatena_base_e_skills():
    sp = construtor.montar_system_prompt("BASE", "HABILIDADES")
    assert sp.startswith("BASE")
    assert "# Habilidades" in sp
    assert "HABILIDADES" in sp


def test_system_prompt_sem_skills_so_base():
    assert construtor.montar_system_prompt("SO BASE", "") == "SO BASE"


def test_system_prompt_base_vazia():
    sp = construtor.montar_system_prompt("", "HAB")
    assert sp.startswith("# Habilidades")


def test_tools_efetivas_interseccao_ordem_canonica():
    viaveis = [{"acao": "forragear"}, {"acao": "pescar"}, {"acao": "passar"}]
    eff = construtor.tools_efetivas(["forragear", "pescar", "cacar"], viaveis)
    # ordem canônica: pescar antes de forragear; cacar não é viável
    assert eff == ["pescar", "forragear"]


def test_tools_efetivas_vazio_vira_passar():
    assert construtor.tools_efetivas(["cacar"], [{"acao": "forragear"}]) == ["passar"]
