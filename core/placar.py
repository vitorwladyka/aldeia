"""Placar e classificação (seção 5.8).

Prioridade: (1) agentes vivos, (2) soma das vidas, (3) valor do estoque.

PONTUAÇÃO TOTAL (nova): número único que combina os 3 critérios para permitir
comparação direta entre partidas. Fórmula:
    pontuacao = (n_vivos * 1000) + (soma_vidas * 100) + valor_estoque
"""
from __future__ import annotations

from .estado import Estado
from .preset import Preset


def placar(estado: Estado, preset: Preset) -> dict:
    n_vivos = sum(1 for a in estado.agentes if a.vivo)
    soma_vidas = sum(a.vida for a in estado.agentes if a.vivo)
    valor_estoque = preset.valor_pontuacao_total(estado.estoque, estado.alimento_solto)

    # Detalhamento por categoria (para análise visual)
    detalhamento = _detalhar_estoque(estado, preset)

    # Pontuação única (combina os 3 critérios)
    # Pesos: 1 agente vivo = 1000 pts, 1 vida = 100 pts, estoque = 1 pt cada
    pontuacao_total = (n_vivos * 1000) + (soma_vidas * 100) + valor_estoque

    return {
        "n_vivos": n_vivos,
        "soma_vidas": soma_vidas,
        "valor_estoque": valor_estoque,
        "pontuacao_total": pontuacao_total,
        "detalhamento": detalhamento,
    }


def _detalhar_estoque(estado: Estado, preset: Preset) -> dict:
    """Detalha o estoque por categoria para análise visual.

    Categorias:
    - comida: peixe, carne, pao, peixe_assado, carne_assada (valor alimentar)
    - insumos: trigo, erva, madeira, remedio (não alimentar)
    - alimento_solto: pontos diretos
    """
    comida = {}
    insumos = {}
    valor_comida = 0
    valor_insumos = 0

    for item, qtd in estado.estoque.items():
        if qtd <= 0:
            continue
        valor = preset.valor_pontuacao(item)
        if preset.e_alimentar(item):
            comida[item] = qtd
            valor_comida += valor * qtd
        else:
            insumos[item] = qtd
            valor_insumos += valor * qtd

    return {
        "comida": {
            "itens": comida,
            "valor_total": valor_comida,
        },
        "insumos": {
            "itens": insumos,
            "valor_total": valor_insumos,
        },
        "alimento_solto": estado.alimento_solto,
        "valor_alimento_solto": estado.alimento_solto,  # 1:1
    }


def classificacao(pontuacao: int) -> str:
    """Retorna um rótulo textual para a pontuação (para UX)."""
    if pontuacao >= 5000:
        return "🏆 Aldeia Próspera"
    if pontuacao >= 3000:
        return "🥈 Aldeia Estável"
    if pontuacao >= 1500:
        return "🥉 Aldeia Sobrevivente"
    if pontuacao >= 500:
        return "⚠️ Aldeia em Risco"
    return "💀 Aldeia Caída"
