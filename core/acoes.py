"""Ações viáveis (seção 5.3).

Antes de decidir, o core calcula, para cada agente vivo e no estado congelado
do turno, as ações viáveis: custo pagável, insumos existentes, permitida na
estação, sem tempestade (pescar), e para curar pelo menos um alvo vivo com
vida < 3 e remédio em estoque. A viabilidade é pré-saturação por desenho.
"""
from __future__ import annotations

from .estado import Estado
from .preset import Preset, ACOES_ORDEM

# Chaves especiais do dict de reservas (não colidem com nomes de itens).
RESERVA_ALIMENTO = "__alimento__"


def chave_cura(agente_idx: int) -> str:
    """Chave da reserva de cura para um alvo (pontos de vida já 'prometidos')."""
    return f"__cura_{agente_idx}__"


def acoes_viaveis(estado: Estado, agente_idx: int, preset: Preset,
                  reservas: dict[str, int] | None = None) -> list[dict]:
    """Calcula as ações viáveis para o agente no estado congelado do turno.

    Retorna uma lista de dicionários `{"acao": id, "custo": int, "alvos": list|None}`,
    na ordem canônica da tabela de ações (seção 5.3).

    `reservas` (opcional) é um dict item→quantidade já reservada por agentes que
    decidiram ANTES deste no mesmo turno. Os insumos/remédio disponíveis para
    este agente são o estoque MENOS as reservas — evitando que dois agentes
    escolham a mesma ação quando só há insumo para um (ex.: 1 remédio, 1 madeira).
    """
    agente = estado.agente(agente_idx)
    if not agente.vivo:
        return []

    reservas = reservas or {}

    def _disponivel_item(item: str) -> int:
        return estado.estoque.get(item, 0) - reservas.get(item, 0)

    # Alimento disponível MENOS o custo já reservado por agentes anteriores.
    disponivel = estado.disponivel(preset) - reservas.get(RESERVA_ALIMENTO, 0)
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

        # 2. Insumos existentes (descontando reservas de agentes anteriores)
        if not all(_disponivel_item(item) >= qtd for item, qtd in insumos.items()):
            continue

        # 3. Estação
        if e_inverno and acao_id in ("coletar_trigo", "coletar_erva"):
            continue

        # 4. Tempestade
        if tempestade and acao_id == "pescar":
            continue

        # 5. Curar: pelo menos um alvo vivo ainda ferido e remédio disponível.
        #    Descontamos o remédio já reservado E as curas já reservadas por alvo
        #    (um ferido com vida 2 só precisa de 1 cura; a 2ª seria invalidada).
        if acao_id == "curar":
            if _disponivel_item("remedio") < 1:
                continue
            alvos = [a.indice for a in estado.agentes
                     if a.vivo
                     and a.vida + reservas.get(chave_cura(a.indice), 0) < preset.vida_max]
            if not alvos:
                continue
            resultado.append({"acao": "curar", "custo": custo, "alvos": alvos})
            continue

        # Ação coletar/transformar/forragear/passar
        resultado.append({"acao": acao_id, "custo": custo, "alvos": None})

    return resultado


def reservar_acao(reservas: dict[str, int], acao_id: str, alvo: int | None,
                  preset: Preset) -> None:
    """Registra em `reservas` tudo que a ação decidida vai consumir.

    - insumos/remédio (ver `insumos_consumidos`);
    - o custo em alimento (`RESERVA_ALIMENTO`), para que o próximo agente não
      escolha uma coleta que o estoque já não paga;
    - 1 ponto de cura no alvo (`chave_cura(alvo)`), para não curar duas vezes
      quem só precisa de uma cura.
    """
    for item, qtd in insumos_consumidos(acao_id, preset).items():
        reservas[item] = reservas.get(item, 0) + qtd
    custo = preset.acoes.get(acao_id, {}).get("custo", 0)
    if custo:
        reservas[RESERVA_ALIMENTO] = reservas.get(RESERVA_ALIMENTO, 0) + custo
    if acao_id == "curar" and alvo is not None:
        k = chave_cura(alvo)
        reservas[k] = reservas.get(k, 0) + 1


def insumos_consumidos(acao_id: str, preset: Preset) -> dict[str, int]:
    """Insumos/consumíveis que uma ação reserva para efeito de alocação.

    - transformar: os `insumos` do preset (ex.: fazer_pao → trigo 3 + madeira 1).
    - curar: 1 remédio (consumido na execução).
    - demais ações: nada.
    """
    a = preset.acoes.get(acao_id, {})
    if a.get("categoria") == "transformar":
        return dict(a.get("insumos", {}))
    if acao_id == "curar":
        return {"remedio": 1}
    return {}
