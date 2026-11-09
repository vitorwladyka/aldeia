"""Decisor LLM — executa via Strands Agents SDK (AWS).

Modelo *actions-as-tools*: as ações permitidas do agente viram tools do Strands.
O agente escolhe chamando a tool correspondente; a chamada é a decisão.

Fluxo:
1. Lê skills/tools do agente da observação (campos internos `_skills`/`_tools`,
   injetados por `partida.py`; default = padrões do catálogo).
2. Monta o system prompt (prompt base + skills ativas) e as tools efetivas
   (tools do agente ∩ ações viáveis do turno).
3. Roda o Agent do Strands e captura a ação escolhida (e a `mensagem` que o
   agente escreve para os demais, quando está no conselho).
4. Se falhar (sem credencial, rede, resposta inválida), aplica o fallback
   determinístico: primeira ação viável, confiança 0.5.

Conselho: se a observação traz `_mesa` (injetada por `partida.py`), o prompt
ganha a mesa — cartas de todos, conflitos, necessidades e falas anteriores.

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
    mesa = observacao.get("_mesa")
    if mesa:
        # Conselho: o agente vê as cartas de todos, conflitos, alertas e as falas.
        obs_texto = f"{obs_texto}\n\n{renderizar_mesa(mesa)}"
    escolha = decidir_via_strands(system, tids, obs_texto, viaveis)
    if not escolha:
        return _fallback(viaveis, "Strands indisponível ou sem escolha")

    acao = escolha.get("acao")
    viaveis_ids = {v["acao"] for v in viaveis}
    if acao not in viaveis_ids:
        return _fallback(viaveis, f"ação fora das viáveis: {acao!r}")

    alvo = _validar_alvo(acao, escolha.get("alvo"), viaveis)
    mensagem = (escolha.get("mensagem") or "").strip()[:400]
    return Decisao(acao=acao, alvo=alvo, confianca=1.0, origem="llm",
                   raciocinio=mensagem or f"strands: {acao}", mensagem=mensagem)


def renderizar_mesa(mesa: dict) -> str:
    """Texto da mesa do conselho que o LLM recebe junto da observação.

    `mesa` = {fase, passada, cartas, conflitos, alertas, falas, motivo_ajuste}.
    """
    fase = mesa.get("fase", "proposta")
    titulos = {
        "proposta": "PROPOSTA — ninguém conversou ainda",
        "discussao": f"DISCUSSÃO — passada {mesa.get('passada', 1)}",
        "ajuste": "AJUSTE FINAL",
    }
    linhas = [f"=== CONSELHO DA ALDEIA: {titulos.get(fase, fase)} ==="]

    if mesa.get("alertas"):
        linhas.append("Necessidades da aldeia:")
        linhas += [f"- {t}" for t in mesa["alertas"]]

    if mesa.get("cartas"):
        linhas.append("Cartas na mesa:")
        for c in mesa["cartas"]:
            alvo = f" → alvo {c['alvo']}" if c.get("alvo") is not None else ""
            marca = " (você)" if c.get("eu") else ""
            quem = "regra determinística" if c.get("origem") == "regra" else "Laya"
            trava = f" [travada: decisão da {quem}, não muda]" if c.get("travada") else ""
            linhas.append(f"- {c['nome']}{marca}: {c['acao']}{alvo}{trava}")

    if mesa.get("conflitos"):
        linhas.append("Conflitos detectados:")
        linhas += [f"- {t}" for t in mesa["conflitos"]]

    if mesa.get("falas"):
        linhas.append("O que foi dito até agora:")
        linhas += [f"- {f['nome']}: \"{f['texto']}\"" for f in mesa["falas"]]

    if fase == "proposta":
        linhas.append(
            "Escolha a ação que considera melhor para a aldeia e chame a tool "
            "dela. Ninguém falou ainda; a `mensagem` pode ficar vazia.")
    elif fase == "discussao":
        linhas.append(
            "Agora a aldeia conversa. Avalie a mesa: se há conflito de recurso "
            "ou uma necessidade que ninguém cobre, proponha uma troca concreta. "
            "Você pode manter sua carta ou mudar. Na `mensagem` (1-2 frases) diga "
            "o que vai fazer e por quê, reagindo ao que os outros disseram. "
            "Chame a tool da ação FINAL (a mesma da sua carta, se mantiver).")
    else:  # ajuste
        linhas.append(
            f"Sua carta não é mais possível: {mesa.get('motivo_ajuste', 'recurso esgotado')}. "
            "Escolha outra ação entre as tools disponíveis e explique em uma "
            "frase na `mensagem`.")
    return "\n".join(linhas)
