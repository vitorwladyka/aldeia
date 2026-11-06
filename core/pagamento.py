"""Algoritmo de pagamento (seção 5.2).

Aplicado imediatamente e em sequência. Falha de um pagamento não afeta os outros.
"""
from __future__ import annotations

from .preset import ITENS_ALIMENTARES, Preset


def pagar(estoque: dict, alimento_solto: int, valor: int, preset: Preset,
          movimentos: list[dict] | None = None, causa: str | None = None,
          agente_id: int | None = None) -> tuple[dict, int]:
    """Paga `valor` de alimento, consumindo `alimento_solto` primeiro, depois itens.

    Ordem de consumo:
    1. alimento_solto (sem teto)
    2. prontos: (pao, peixe_assado, carne_assada) — por menor valor que cubra,
       senão por maior valor; empate: ordem alfabética do id
    3. crus: (peixe, carne) — mesma regra

    Retorna (novo_estoque, novo_alimento_solto). O item é consumido inteiro;
    se sobra troco, volta para alimento_solto (sem teto).

    `movimentos` (opcional) recebe um dicionário por item consumido.
    """
    if valor < 0:
        raise ValueError(f"valor não pode ser negativo: {valor}")
    if valor == 0:
        return dict(estoque), alimento_solto

    disponivel = alimento_solto + sum(
        preset.valor_alimentar(item) * estoque.get(item, 0)
        for item in ITENS_ALIMENTARES
    )
    if valor > disponivel:
        raise RuntimeError(f"pagar({valor}) > disponivel({disponivel})")

    estoque = dict(estoque)

    # 1. alimento_solto
    if alimento_solto >= valor:
        novo_solto = alimento_solto - valor
        if movimentos is not None:
            movimentos.append({
                "agente_id": agente_id, "tipo": "pagamento", "item": "alimento_solto",
                "delta": -valor, "saldo_apos": novo_solto, "causa": causa,
            })
        return estoque, novo_solto

    # 2. e 3. itens por grupo
    falta = valor - alimento_solto
    # Consome o alimento_solto primeiro
    if alimento_solto > 0 and movimentos is not None:
        movimentos.append({
            "agente_id": agente_id, "tipo": "pagamento", "item": "alimento_solto",
            "delta": -alimento_solto, "saldo_apos": 0, "causa": causa,
        })
    alimento_solto = 0

    for grupo in [("pao", "peixe_assado", "carne_assada"), ("peixe", "carne")]:
        while falta > 0:
            candidatos_disponiveis = [it for it in grupo if estoque.get(it, 0) > 0]
            if not candidatos_disponiveis:
                break
            # Candidatos com valor >= falta
            com_valor_suficiente = [it for it in candidatos_disponiveis
                                     if preset.valor_alimentar(it) >= falta]
            if com_valor_suficiente:
                # Menor valor; empate: ordem alfabética do id
                item = min(com_valor_suficiente,
                           key=lambda it: (preset.valor_alimentar(it), it))
            else:
                # Maior valor; empate: ordem alfabética do id
                item = max(candidatos_disponiveis,
                           key=lambda it: (preset.valor_alimentar(it), -ord(it[0])))
                # Corrigir: precisamos do maior valor, e em empate, ordem alfabética
                # Vamos refazer:
                maior_valor = max(preset.valor_alimentar(it) for it in candidatos_disponiveis)
                candidatos_maior = sorted(
                    [it for it in candidatos_disponiveis
                     if preset.valor_alimentar(it) == maior_valor]
                )
                item = candidatos_maior[0]

            v = preset.valor_alimentar(item)
            estoque[item] -= 1
            falta -= v
            saldo = estoque[item]
            if movimentos is not None:
                movimentos.append({
                    "agente_id": agente_id, "tipo": "pagamento", "item": item,
                    "delta": -1, "saldo_apos": saldo, "causa": causa,
                })

    if falta < 0:
        # Sobra volta ao alimento_solto, sem teto
        alimento_solto = -falta
        if movimentos is not None and alimento_solto > 0:
            movimentos.append({
                "agente_id": agente_id, "tipo": "pagamento", "item": "alimento_solto",
                "delta": alimento_solto, "saldo_apos": alimento_solto, "causa": causa,
            })

    return estoque, alimento_solto
