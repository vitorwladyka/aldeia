"""Decisor LLM — executa via Strands Agents SDK (AWS).

Modelo *actions-as-tools*: as ações permitidas do agente viram tools do Strands.
O agente escolhe chamando a tool correspondente; a chamada é a decisão.

Fluxo:
1. Lê skills/tools do agente da observação (campos internos `_skills`/`_tools`,
   injetados por `partida.py`; default = padrões do catálogo).
2. Monta o system prompt (prompt base + skills ativas) e as tools efetivas
   (tools do agente ∩ ações viáveis do turno).
3. Roda o Agent do Strands e captura a ação escolhida.
4. Se falhar (sem credencial, rede, resposta inválida), aplica o fallback
   determinístico: primeira ação viável, confiança 0.5.

Mantém a assinatura `decidir(observacao, prompt_agente, agente_idx)` e retorna
uma `Decisao` com `origem="llm"`, compatível com `hibrido.py` e `partida.py`.
"""
from __future__ import annotations

from .bot import Decisao
from core.observacao import renderizar_texto_compacto
from agentes import catalogo
from agentes.construtor import montar_system_prompt, tools_efetivas
from agentes.strands_runner import decidir_via_strands


def _fallback(viaveis: list[dict], motivo: str) -> Decisao:
    """Fallback determinístico: primeira ação viável, confiança 0.5."""
    a = viaveis[0]
    alvo = None
    if a["acao"] == "curar" and a.get("alvos"):
        alvo = sorted(a["alvos"])[0]
    return Decisao(acao=a["acao"], alvo=alvo, confianca=0.5, origem="llm",
                   raciocinio=f"fallback: {motivo}")


def _validar_alvo(acao: str, alvo, viaveis: list[dict]):
    """Valida/corrige o alvo de 'curar'; demais ações não têm alvo."""
    if acao != "curar":
        return None
    alvos_validos = next((v["alvos"] for v in viaveis
                          if v["acao"] == "curar" and v.get("alvos")), [])
    if not alvos_validos:
        return None
    if alvo in alvos_validos:
        return alvo
    return sorted(alvos_validos)[0]


def decidir(observacao: dict, prompt_agente: str, agente_idx: int) -> Decisao:
    viaveis = observacao.get("acoes_viaveis", [])
    if not viaveis:
        return Decisao(acao="passar", confianca=1.0, origem="llm",
                       raciocinio="nenhuma ação viável")

    # skills (texto) e tools (lista) do agente, injetadas por partida.py.
    skills_texto = observacao.get("_skills")
    if skills_texto is None:
        skills_texto = catalogo.PADRAO_SKILLS
    tools_ids = observacao.get("_tools") or catalogo.PADRAO_TOOLS

    system = montar_system_prompt(prompt_agente, skills_texto)
    tids = tools_efetivas(tools_ids, viaveis)
    # Se a única opção efetiva é passar (interseção vazia), decide passar direto.
    if tids == ["passar"] and not any(v["acao"] == "passar" for v in viaveis):
        # 'passar' sempre é viável no jogo, mas por segurança: se não estiver
        # entre as viáveis, cai no fallback.
        return _fallback(viaveis, "sem interseção tools∩viáveis")

    obs_texto = renderizar_texto_compacto(observacao, max_tokens=500)
    escolha = decidir_via_strands(system, tids, obs_texto, viaveis)
    if not escolha:
        return _fallback(viaveis, "Strands indisponível ou sem escolha")

    acao = escolha.get("acao")
    viaveis_ids = {v["acao"] for v in viaveis}
    if acao not in viaveis_ids:
        return _fallback(viaveis, f"ação fora das viáveis: {acao!r}")

    alvo = _validar_alvo(acao, escolha.get("alvo"), viaveis)
    return Decisao(acao=acao, alvo=alvo, confianca=1.0, origem="llm",
                   raciocinio=f"strands: {acao}")
