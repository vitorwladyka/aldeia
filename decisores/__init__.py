"""Decisores: dado uma observação + prompt do agente, devolve uma ação.

Três implementações:
- `bot`: determinístico (round-robin pelas ações viáveis).
- `llm`: chama o LLM real via `z-ai chat` (papel de "Claude").
- `lbm`: heurística rápida em memória (papel de "Laya") — devolve ação + confiança.

`hibrido.decidir()` orquestra LBM → se confiança < threshold → LLM.
"""
from .bot import decidir as bot_decidir
from .llm import decidir as llm_decidir
from .lbm import decidir as lbm_decidir

__all__ = ["bot_decidir", "llm_decidir", "lbm_decidir"]
