"""Decisor LBM (papel de "Laya") — heurística rápida em memória.

Implementa a lógica de roteamento que um LBM 1B faria, mas de forma
determinística em Python: lê a observação, escolhe a melhor ação por
regras, e devolve uma confiança baseada em quão "clara" é a decisão.

A confiança é calibrada para que:
- Casos óbvios (fome iminente, feridos com remédio) → confiança alta (>= 0.8).
- Casos médios (estoque ok, sem feridos) → confiança média (~0.6).
- Casos ambíguos (vias múltiplas igualmente boas) → confiança baixa (< 0.5).

DIVERSIFICAÇÃO POR ID: quando há múltiplas ações com a mesma prioridade
(ex: 3 insumos disponíveis para coletar), o agente usa `agente_idx % n`
para escolher — garantindo distribuição automática sem coordenação
explícita entre agentes. Isso espelha o `_gerar_papel_por_id` do
`core/observacao.py` (descoberta diag11).

Quando a confiança fica abaixo do threshold (default 0.5), o `hibrido.py`
escala para o LLM.

Para trocar pela Laya real: substituir o corpo de `decidir()` por uma
chamada HTTP ao endpoint do Laya, mantendo a assinatura.
"""
from __future__ import annotations

from .bot import Decisao


def _alimento_disponivel(observacao: dict) -> int:
    """Soma alimento_solto + valor alimentar dos itens."""
    e = observacao.get("estoque", {})
    s = e.get("alimento_solto", 0)
    valores = {"peixe": 4, "carne": 6, "pao": 18, "peixe_assado": 22, "carne_assada": 26}
    for item, v in valores.items():
        s += v * e.get("itens", {}).get(item, 0)
    return s


def _ha_feridos(observacao: dict) -> list[int]:
    """Índices dos agentes vivos com vida < 3."""
    return [a["agente"] for a in observacao["agentes"]
            if a["status"] == "vivo" and a["vida"] < 3]


def _diversificar(acoes: list[str], agente_idx: int) -> str:
    """Distribui `acoes` entre agentes por ID (round-robin)."""
    if not acoes:
        return ""
    return acoes[agente_idx % len(acoes)]


def decidir(observacao: dict, prompt_agente: str, agente_idx: int) -> Decisao:
    viaveis = observacao.get("acoes_viaveis", [])
    if not viaveis:
        return Decisao(acao="passar", confianca=1.0, origem="lbm",
                       raciocinio="nenhuma ação viável")

    viaveis_por_id = {v["acao"]: v for v in viaveis}
    alimento = _alimento_disponivel(observacao)
    n_vivos = sum(1 for a in observacao["agentes"] if a["status"] == "vivo")
    basal = 3 if observacao["partida"]["estacao"] == "inverno" else 1
    itens = observacao["estoque"]["itens"]

    # 1. Fome iminente: basal > alimento disponível → forragear (grátis)
    if basal > alimento and "forragear" in viaveis_por_id:
        return Decisao(acao="forragear", confianca=0.95, origem="lbm",
                       raciocinio=f"fome iminente (basal={basal} > disp={alimento})")

    # 2. Feridos com remédio → curar (alta confiança)
    #    DIVERSIFICAÇÃO: só UM agente cura por turno (id menor dentre os que
    #    têm a ação); os outros com papel de cura fazem outra coisa.
    feridos = _ha_feridos(observacao)
    if feridos and "curar" in viaveis_por_id:
        alvos = viaveis_por_id["curar"]["alvos"]
        # Apenas o agente de menor índice (entre os vivos) cura
        vivos_idx = [a["agente"] for a in observacao["agentes"] if a["status"] == "vivo"]
        sou_o_menor = (agente_idx == min(vivos_idx))
        if sou_o_menor:
            alvo = sorted(set(alvos) & set(feridos))[0] if set(alvos) & set(feridos) else sorted(alvos)[0]
            return Decisao(acao="curar", alvo=alvo, confianca=0.92, origem="lbm",
                           raciocinio=f"feridos {feridos} — sou o menor índice, curo")
        # Outros agentes com feridos: preparam remédio ou coletam erva
        if "preparar_remedio" in viaveis_por_id and itens.get("erva", 0) >= 2:
            return Decisao(acao="preparar_remedio", confianca=0.78, origem="lbm",
                           raciocinio="feridos — outro cura, eu preparo remédio")
        if "coletar_erva" in viaveis_por_id:
            return Decisao(acao="coletar_erva", confianca=0.70, origem="lbm",
                           raciocinio="feridos — outro cura, eu colecciono erva")

    # 3. Transformar comida de alto valor — DIVERSIFICA por ID entre as opções
    transformaveis = []
    if "fazer_pao" in viaveis_por_id and itens.get("trigo", 0) >= 3:
        transformaveis.append(("fazer_pao", 0.85, "trigo→pão rende 18 pts"))
    if "assar_carne" in viaveis_por_id and itens.get("carne", 0) >= 2:
        transformaveis.append(("assar_carne", 0.85, "carne→carne_assada rende 26 pts"))
    if "assar_peixe" in viaveis_por_id and itens.get("peixe", 0) >= 2:
        transformaveis.append(("assar_peixe", 0.85, "peixe→peixe_assado rende 22 pts"))
    if transformaveis:
        # Distribui: agente_idx % len(transformaveis)
        idx = agente_idx % len(transformaveis)
        acao, conf, rac = transformaveis[idx]
        return Decisao(acao=acao, confianca=conf, origem="lbm",
                       raciocinio=f"{rac} (diversificação idx={idx})")

    # 4. Estoque de comida baixo e temos como pescar/caçar — diversifica entre os dois
    if alimento < n_vivos * basal * 2:
        opcoes = []
        if "pescar" in viaveis_por_id:
            opcoes.append("pescar")
        if "cacar" in viaveis_por_id:
            opcoes.append("cacar")
        if opcoes:
            acao = _diversificar(opcoes, agente_idx)
            return Decisao(acao=acao, confianca=0.72, origem="lbm",
                           raciocinio=f"estoque baixo ({alimento}<{n_vivos*basal*2}) → {acao} (diversificado)")

    # 5. Forragear é grátis — apenas alguns agentes (não todos!)
    if "forragear" in viaveis_por_id and alimento < n_vivos * basal * 3:
        # Apenas agentes com ID par forrageiam (para não sobrecarregar)
        if agente_idx % 2 == 0:
            return Decisao(acao="forragear", confianca=0.62, origem="lbm",
                           raciocinio="forragear grátis para estocar (id par)")

    # 6. Coletar insumos — DIVERSIFICA entre os disponíveis
    coletaveis = [a for a in ("coletar_madeira", "coletar_trigo", "coletar_erva")
                  if a in viaveis_por_id]
    if coletaveis:
        # Escolhe por "menor estoque" + offset por ID (estável)
        def estoque_de(a):
            return itens.get(a.replace("coletar_", ""), 999)
        coletaveis_sorted = sorted(coletaveis, key=estoque_de)
        # Offset por ID garante distribuição quando há 3+ agentes
        idx = agente_idx % len(coletaveis_sorted)
        acao = coletaveis_sorted[idx]
        return Decisao(acao=acao, confianca=0.55, origem="lbm",
                       raciocinio=f"estoque ok → {acao} (escolha ambígua, diversificada idx={idx})")

    # 7. Última opção: primeira ação viável (baixa confiança → escala para LLM)
    a = viaveis[0]
    alvo = None
    if a["acao"] == "curar" and a.get("alvos"):
        alvo = sorted(a["alvos"])[0]
    return Decisao(acao=a["acao"], alvo=alvo, confianca=0.30, origem="lbm",
                   raciocinio="fallback — primeira viável")
