"""Decisor híbrido: Laya (LBM) → LLM por threshold e colisão.

Fluxo (por agente, quando o LBM está habilitado):
1. LBM decide rapidamente em memória e devolve (acao, alvo, confiança).
2. Escala para o LLM se QUALQUER uma destas for verdade:
   - confiança do LBM < threshold; OU
   - a ação do LBM causa colisão (3º+ agente no mesmo local/tarefa no turno).
3. Caso contrário, usa a decisão do LBM.

Threshold padrão: 0.5 (lido de `config_lbm.json`).

A contagem de colisão usa a visão dos agentes que JÁ decidiram antes na rodada
(passada em `locais_ocupados`). Conta por "local" (alinhado à saturação do jogo):
ações de coleta compartilham um local (peixe, carne, trigo, erva, madeira); as
demais ações colidem só com elas mesmas. O limite segue `saturacao_limite` do
preset (default 2) — a partir do 3º agente no mesmo local, escala para o LLM.

Retorna uma `Decisao` com `origem` indicando quem decidiu ("lbm" ou "llm")
e a confiança final usada. O `raciocinio` explica a rota tomada.
"""
from __future__ import annotations

import json
from pathlib import Path

from decisores.bot import Decisao
from decisores import laya_router as _lbm
from decisores import llm as _llm

CAMINHO_CONFIG = Path(__file__).parent / "config_lbm.json"


def _carregar_threshold() -> float:
    try:
        import config_env
        return config_env.config_laya()["threshold"]
    except Exception:
        try:
            cfg = json.loads(CAMINHO_CONFIG.read_text(encoding="utf-8"))
            return float(cfg.get("threshold", 0.5))
        except Exception:
            return 0.5


def local_da_acao(acao: str, preset=None) -> str:
    """Devolve o "local" de uma ação para efeito de colisão/saturação.

    Ações de coleta compartilham o local do recurso (peixe, carne, trigo, erva,
    madeira). As demais ações colidem apenas com elas mesmas, então o próprio
    id da ação serve de local.

    Se `preset` for fornecido, lê o campo `local` da ação de coleta; senão usa
    um mapa fixo equivalente ao preset padrão.
    """
    if preset is not None:
        try:
            a = preset.acao(acao)
            if a.get("categoria") == "coletar" and a.get("local"):
                return a["local"]
        except Exception:
            pass
    mapa_coleta = {
        "cacar": "carne",
        "pescar": "peixe",
        "coletar_trigo": "trigo",
        "coletar_erva": "erva",
        "coletar_madeira": "madeira",
    }
    return mapa_coleta.get(acao, acao)


def decidir(observacao: dict, prompt_agente: str, agente_idx: int,
            threshold: float | None = None,
            locais_ocupados: dict[str, int] | None = None,
            saturacao_limite: int = 2,
            preset=None) -> Decisao:
    """Roteia entre LBM e LLM baseado na confiança do LBM e em colisão.

    `threshold` override opcional; default vem de `config_lbm.json`.
    `locais_ocupados` mapeia local → nº de agentes já decididos (antes deste)
    que ocupam aquele local na rodada atual. A partir do 3º ocupante
    (`> saturacao_limite`) a decisão do LBM é considerada colidida.
    """
    if threshold is None:
        threshold = _carregar_threshold()

    # 1. LBM decide
    d_lbm = _lbm.decidir(observacao, prompt_agente, agente_idx)

    # 2a. Checa colisão por local (se houver contexto da rodada)
    colisao = False
    local = None
    if locais_ocupados is not None:
        local = local_da_acao(d_lbm.acao, preset)
        ja_no_local = locais_ocupados.get(local, 0)
        # Este agente seria o (ja_no_local + 1)-ésimo no local.
        if (ja_no_local + 1) > saturacao_limite:
            colisao = True

    # 2b. Confiança suficiente e sem colisão → usa LBM
    if d_lbm.confianca >= threshold and not colisao:
        return d_lbm

    # 3. Confiança baixa ou colisão → escala para LLM
    d_llm = _llm.decidir(observacao, prompt_agente, agente_idx)
    if colisao:
        motivo = (f"[escalonado: colisao local={local} "
                  f"(>{saturacao_limite} agentes)] ")
    else:
        motivo = f"[escalonado: lbm conf={d_lbm.confianca:.2f}<{threshold:.2f}] "
    return Decisao(
        acao=d_llm.acao,
        alvo=d_llm.alvo,
        confianca=d_llm.confianca,
        origem="llm",
        raciocinio=motivo + (d_llm.raciocinio or ""),
    )
