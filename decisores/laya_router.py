"""Adaptador do Laya (model one) — roteador de escolha rápido e barato, via HTTP.

O Laya é um roteador servido num container (laya-serve). Fala HTTP:

    POST {url}   (default: http://localhost:8001/v1/systemone)
    body: {"state": {...}, "questions": {<chave>: {type, instructions, criteria}}}
    resp: {"answers"?: {<chave>: {"selection"|"value", "confidence", "probabilities"}}}
          (algumas versões envelopam em "answers", outras trazem na raiz; a
           resposta por pergunta pode ser um dict ou uma string direta.)

Aqui montamos:
- `state`  = status atual do agente (turno, estação, vidas/feridos, estoque,
  alimento disponível, clima).
- `questions` = uma pergunta "acao" do tipo `choice`, cujos `criteria` são as
  ferramentas (tools) do agente que estão VIÁVEIS neste turno — cada uma com uma
  descrição curta do que faz. Assim o Laya só escolhe entre o que o agente
  realmente pode fazer.

A `selection` vira a ação; a `confidence` alimenta o threshold do híbrido. Para
`curar`, o alvo é resolvido deterministicamente (menor índice ferido).

URL e timeout vêm de `config_lbm.json` (`url`, `timeout_s`). Se o endpoint não
responder ou a resposta vier inválida, caímos na heurística determinística
(`decisores/lbm.py`), que simula um model one.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from .bot import Decisao
from . import lbm as _heuristica
from agentes import catalogo
from agentes.construtor import tools_efetivas

CAMINHO_CONFIG = Path(__file__).parent.parent / "config_lbm.json"
URL_PADRAO = "http://localhost:8001/v1/systemone"
TIMEOUT_PADRAO = 10.0

# Circuit breaker leve: após uma falha de HTTP, pula o Laya por um curto período
# (COOLDOWN_S) para não acumular timeouts, mas volta a tentar automaticamente —
# diferente de desistir para sempre no processo.
import time as _time

COOLDOWN_S = 15.0
_falha_ate = 0.0  # timestamp até o qual pulamos o Laya (0 = sem cooldown ativo)


def _config_laya() -> tuple[str, float]:
    """Lê url e timeout do .env (fallback config_lbm.json) — ver config_env."""
    try:
        import config_env
        c = config_env.config_laya()
        return c["url"], c["timeout_s"]
    except Exception:
        return URL_PADRAO, TIMEOUT_PADRAO


def _chamar_laya(state: dict, questions: dict) -> dict | None:
    """POST para o endpoint do Laya; devolve {selection, confidence} ou None.

    Replica o tratamento do laya-serve: desembrulha `answers` (ou raiz), pega a
    pergunta "acao", aceita dict (selection/value) ou string direta.
    """
    global _falha_ate
    # Em cooldown após falha recente? Pula o HTTP (usa fallback), mas volta a
    # tentar quando o cooldown expirar.
    if _time.monotonic() < _falha_ate:
        return None
    url, timeout = _config_laya()
    payload = {"state": state, "questions": questions}
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, json=payload,
                            headers={"Content-Type": "application/json"})
        r.raise_for_status()
        dados = r.json()
    except Exception:
        # Falha → entra em cooldown curto; volta a tentar depois.
        _falha_ate = _time.monotonic() + COOLDOWN_S
        return None
    # Sucesso → zera qualquer cooldown pendente.
    _falha_ate = 0.0

    decisoes = dados.get("answers", dados) if isinstance(dados, dict) else {}
    dec = decisoes.get("acao") if isinstance(decisoes, dict) else None
    if dec is None:
        return None

    if not isinstance(dec, dict):
        # Resposta simplificada como string direta.
        return {"selection": dec, "confidence": 1.0} if dec else None

    # A opção escolhida pode vir como 'choice', 'selection' ou 'value'
    # (varia por versão do laya-serve).
    selection = dec.get("choice") or dec.get("selection") or dec.get("value")
    if not selection:
        return None

    # Confiança que alimenta o threshold do híbrido: o MAIOR valor entre os
    # campos de confiança que o Laya devolve (confidence, answer_confidence,
    # x_jev_confidence e a probabilidade da opção escolhida). Se qualquer uma
    # dessas medidas estiver acima do threshold, a decisão da Laya é aceita.
    probs = dec.get("probabilities") or {}
    candidatos = []
    for chave in ("confidence", "answer_confidence", "x_jev_confidence"):
        v = dec.get(chave)
        if v is not None:
            try:
                candidatos.append(float(v))
            except (TypeError, ValueError):
                pass
    if selection in probs:
        try:
            candidatos.append(float(probs[selection]))
        except (TypeError, ValueError):
            pass
    confidence = max(candidatos) if candidatos else 0.0

    return {"selection": selection, "confidence": confidence}


def _alimento_disponivel(observacao: dict) -> int:
    e = observacao.get("estoque", {})
    s = e.get("alimento_solto", 0)
    valores = {"peixe": 4, "carne": 6, "pao": 18, "peixe_assado": 22, "carne_assada": 26}
    itens = e.get("itens", {})
    for item, v in valores.items():
        s += v * itens.get(item, 0)
    return s


def _montar_state(observacao: dict) -> dict:
    """Monta o dict de status atual para o Laya (claro e compacto)."""
    p = observacao["partida"]
    eu = observacao["eu"]
    agentes = observacao.get("agentes", [])
    feridos = [
        {"id": a["agente"], "nome": a["nome"], "vida": a["vida"]}
        for a in agentes if a.get("status") == "vivo" and a.get("vida", 3) < 3
    ]
    e = observacao.get("estoque", {})
    itens = {k: v for k, v in e.get("itens", {}).items() if v > 0}
    return {
        "turno": p["turno"],
        "turnos_total": p["turnos_total"],
        "estacao": p["estacao"],
        "clima": {
            "tempestade": p["clima"]["tempestade"],
            "fartura": p["clima"]["fartura"],
        },
        "minha_vida": eu["vida"],
        "feridos": feridos,
        "alimento_disponivel": _alimento_disponivel(observacao),
        "alimento_solto": e.get("alimento_solto", 0),
        "estoque_itens": itens,
    }


def _montar_questions(acoes_opcoes: list[str]) -> dict:
    """Monta o esquema de escolha com os criteria = tools viáveis descritas."""
    criteria = {aid: catalogo.DESCRICAO_TOOLS.get(aid, aid) for aid in acoes_opcoes}
    return {
        "acao": {
            "type": "choice",
            "instructions": (
                "Qual ação este agente deve tomar neste turno, considerando o "
                "status atual (vidas, feridos, estoque, alimento, clima)?"
            ),
            "criteria": criteria,
        }
    }


def _resolver_alvo(acao: str, viaveis: list[dict]) -> int | None:
    """Para 'curar', escolhe o menor índice entre os alvos viáveis."""
    if acao != "curar":
        return None
    alvos = next((v.get("alvos") for v in viaveis if v["acao"] == "curar"), None)
    return sorted(alvos)[0] if alvos else None


def decidir(observacao: dict, prompt_agente: str, agente_idx: int) -> Decisao:
    """Decide via Laya (HTTP); fallback para a heurística se indisponível."""
    viaveis = observacao.get("acoes_viaveis", [])
    if not viaveis:
        return Decisao(acao="passar", confianca=1.0, origem="lbm",
                       raciocinio="nenhuma ação viável")

    # Opções = tools do agente ∩ ações viáveis (Laya só escolhe o que pode fazer).
    tools_ids = observacao.get("_tools") or catalogo.PADRAO_TOOLS
    opcoes = tools_efetivas(tools_ids, viaveis)

    # 'passar' virou custoso e improdutivo: não oferecemos ao Laya quando há
    # qualquer alternativa. Só deixamos passar se for a única opção.
    opcoes_sem_passar = [o for o in opcoes if o != "passar"]
    if opcoes_sem_passar:
        opcoes = opcoes_sem_passar

    state = _montar_state(observacao)
    questions = _montar_questions(opcoes)
    resp = _chamar_laya(state, questions)
    if resp is None:
        # Endpoint fora do ar ou resposta inválida → heurística (model one local),
        # respeitando as opções restritas pelas tools do agente.
        return _decidir_heuristica(observacao, prompt_agente, agente_idx, opcoes)

    acao = resp["selection"]
    confianca = resp["confidence"]
    if acao not in opcoes:
        # Laya devolveu algo fora das opções — cai na heurística.
        return _decidir_heuristica(observacao, prompt_agente, agente_idx, opcoes)

    alvo = _resolver_alvo(acao, viaveis)
    return Decisao(acao=acao, alvo=alvo, confianca=confianca, origem="lbm",
                   raciocinio=f"laya: {acao} (conf={confianca:.2f})")


def _decidir_heuristica(observacao: dict, prompt_agente: str, agente_idx: int,
                        opcoes: list[str]) -> Decisao:
    """Fallback: heurística determinística, mas restrita às `opcoes` do agente.

    Reusa `lbm.decidir`; se a ação escolhida não estiver nas opções permitidas,
    força a primeira opção permitida (com confiança reduzida).
    """
    d = _heuristica.decidir(observacao, prompt_agente, agente_idx)
    if d.acao in opcoes:
        return d
    # Ação fora das tools do agente → escolhe a primeira opção permitida.
    acao = opcoes[0]
    viaveis = observacao.get("acoes_viaveis", [])
    alvo = _resolver_alvo(acao, viaveis)
    return Decisao(acao=acao, alvo=alvo, confianca=min(d.confianca, 0.5),
                   origem="lbm",
                   raciocinio=f"heurística restrita às tools → {acao}")
