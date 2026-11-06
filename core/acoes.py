"""Ações viáveis (seção 5.3).

Antes de decidir, o core calcula, para cada agente vivo e no estado congelado
do turno, as ações viáveis: custo pagável, insumos existentes, permitida na
estação, sem tempestade (pescar), e para curar pelo menos um alvo vivo com
vida < 3 e remédio em estoque. A viabilidade é pré-saturação por desenho.
"""
from __future__ import annotations

from .estado import Estado
from .preset import Preset, ACOES_ORDEM


def acoes_viaveis(estado: Estado, agente_idx: int, preset: Preset) -> list[dict]:
    """Calcula as ações viáveis para o agente no estado congelado do turno.

    Retorna uma lista de dicionários `{"acao": id, "custo": int, "alvos": list|None}`,
    na ordem canônica da tabela de ações (seção 5.3).
    """
    agente = estado.agente(agente_idx)
    if not agente.vivo:
        return []

    disponivel = estado.disponivel(preset)
    e_inverno = estado.estacao == "inverno"
    tempestade = estado.tempestade
    resultado = []

    for acao_id in ACOES_ORDEM:
        a = preset.acoes[acao_id]
        categoria = a["categoria"]
        custo = a["custo"]
        insumos = a.get("insumos", {})

        # 'passar' é a rede de segurança: SEMPRE viável, mesmo sem alimento para
        # pagar o custo (na execução, se não pagar, perde 1 vida — como o basal).
        if acao_id == "passar":
            resultado.append({"acao": "passar", "custo": custo, "alvos": None})
            continue

        # 1. Custo pagável
        if custo > disponivel:
            continue

        # 2. Insumos existentes
        if not all(estado.estoque.get(item, 0) >= qtd for item, qtd in insumos.items()):
            continue

        # 3. Estação
        if e_inverno and acao_id in ("coletar_trigo", "coletar_erva"):
            continue

        # 4. Tempestade
        if tempestade and acao_id == "pescar":
            continue

        # 5. Curar: pelo menos um alvo vivo com vida < 3 e remédio em estoque
        if acao_id == "curar":
            if estado.estoque.get("remedio", 0) < 1:
                continue
            alvos = [a.indice for a in estado.agentes
                     if a.vivo and a.vida < preset.vida_max]
            if not alvos:
                continue
            resultado.append({"acao": "curar", "custo": custo, "alvos": alvos})
            continue

        # Ação coletar/transformar/forragear/passar
        resultado.append({"acao": acao_id, "custo": custo, "alvos": None})

    return resultado
