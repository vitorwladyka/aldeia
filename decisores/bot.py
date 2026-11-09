"""Decisor bot — determinístico, sem rede.

Estratégia: round-robin pelas ações viáveis pelo índice do agente.
Para `curar`, escolhe o alvo de menor índice (estável).

Retorna uma `Decisao` com confiança=1.0 (sempre usada, nunca escala).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Decisao:
    acao: str
    alvo: int | None = None
    confianca: float = 1.0
    origem: str = "bot"  # bot | lbm | llm
    raciocinio: str = ""
    # Fala do agente para os demais no conselho (escrita pelo LLM na mesma
    # chamada que escolhe a ação). Vazia quando o decisor não fala (bot/Laya).
    mensagem: str = ""


def decidir(observacao: dict, prompt_agente: str, agente_idx: int) -> Decisao:
    viaveis = observacao.get("acoes_viaveis", [])
    if not viaveis:
        # Sem ações viáveis — passa
        return Decisao(acao="passar", confianca=1.0, origem="bot",
                       raciocinio="nenhuma ação viável")

    # Round-robin: cada agente pega uma ação diferente
    idx = agente_idx % len(viaveis)
    a = viaveis[idx]
    alvo = None
    if a["acao"] == "curar" and a.get("alvos"):
        # Escolhe o alvo de menor índice (estável)
        alvo = sorted(a["alvos"])[0]
    return Decisao(acao=a["acao"], alvo=alvo, confianca=1.0, origem="bot",
                   raciocinio=f"round-robin[{idx}]")
