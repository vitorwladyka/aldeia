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


# --------------------------------------------------------------------------
# Mesa do conselho: conflitos entre cartas e alertas da aldeia
# --------------------------------------------------------------------------


def detectar_conflitos(estado: Estado, cartas: list[dict], preset: Preset) -> list[str]:
    """Descreve, em texto, onde as cartas atuais da mesa disputam o mesmo recurso.

    `cartas` é uma lista de {"agente", "nome", "acao", "alvo"} (todas as cartas
    na mesa, inclusive as travadas pela Laya). Não bloqueia nada: serve para o
    conselho enxergar o problema e discutir. A rede de segurança que invalida
    cartas impossíveis fica no fim da discussão.
    """
    conflitos: list[str] = []

    def quem(lst: list[dict]) -> str:
        return ", ".join(f"{c['nome']} ({c['acao']})" for c in lst)

    # 1. Insumos / remédio pedidos acima do estoque
    totais: dict[str, int] = {}
    por_item: dict[str, list[dict]] = {}
    for c in cartas:
        for item, qtd in insumos_consumidos(c["acao"], preset).items():
            totais[item] = totais.get(item, 0) + qtd
            por_item.setdefault(item, []).append(c)
    for item, total in totais.items():
        disp = estado.estoque.get(item, 0)
        if total > disp:
            conflitos.append(
                f"Insumo '{item}': as cartas pedem {total}, mas o estoque tem "
                f"{disp} — {quem(por_item[item])}")

    # 2. Custo total em alimento acima do disponível
    custo_total = sum(preset.acoes.get(c["acao"], {}).get("custo", 0) for c in cartas)
    disponivel = estado.disponivel(preset)
    if custo_total > disponivel:
        conflitos.append(
            f"Alimento: os custos das cartas somam {custo_total}, mas só há "
            f"{disponivel} disponível")

    # 3. Saturação de local de coleta
    por_local: dict[str, list[dict]] = {}
    for c in cartas:
        a = preset.acoes.get(c["acao"], {})
        if a.get("categoria") == "coletar" and a.get("local"):
            por_local.setdefault(a["local"], []).append(c)
    for local, lst in por_local.items():
        if len(lst) > preset.saturacao_limite:
            conflitos.append(
                f"Local '{local}': {len(lst)} agentes ({quem(lst)}); só "
                f"{preset.saturacao_limite} rendem plenamente")

    # 4. Cura duplicada além do necessário
    curas: dict[int, list[dict]] = {}
    for c in cartas:
        if c["acao"] == "curar" and c.get("alvo") is not None:
            curas.setdefault(c["alvo"], []).append(c)
    for alvo, lst in curas.items():
        try:
            ag = estado.agente(alvo)
        except StopIteration:
            continue
        faltam = preset.vida_max - ag.vida
        if len(lst) > faltam:
            conflitos.append(
                f"Cura: {len(lst)} agentes querem curar {ag.nome}, que só "
                f"precisa de {max(faltam, 0)} cura(s) — {quem(lst)}")

    return conflitos


def alertas_aldeia(estado: Estado, preset: Preset) -> list[str]:
    """Resumo das necessidades da aldeia no turno (para orientar a discussão)."""
    alertas: list[str] = []
    vivos = [a for a in estado.agentes if a.vivo]
    if not vivos:
        return alertas

    # Comida x basal
    basal = preset.basal_inverno if estado.estacao == "inverno" else preset.basal_normal
    por_turno = max(basal * len(vivos), 1)
    disponivel = estado.disponivel(preset)
    turnos_cobertos = disponivel // por_turno
    if turnos_cobertos < 3:
        alertas.append(
            f"Comida disponível ({disponivel}) cobre só {turnos_cobertos} turno(s) "
            f"de basal ({por_turno}/turno para {len(vivos)} vivos)")

    # Feridos x remédio
    feridos = [a for a in vivos if a.vida < preset.vida_max]
    if feridos:
        nomes = ", ".join(f"{a.nome}(vida {a.vida})" for a in feridos)
        remedio = estado.estoque.get("remedio", 0)
        alertas.append(f"Feridos: {nomes}; remédio em estoque: {remedio}")

    # Insumos críticos: usados em várias receitas e quase zerados
    uso: dict[str, int] = {}
    for a in preset.acoes.values():
        if a.get("categoria") == "transformar":
            for item in a.get("insumos", {}):
                uso[item] = uso.get(item, 0) + 1
    for item, n_receitas in sorted(uso.items()):
        qtd = estado.estoque.get(item, 0)
        if n_receitas >= 2 and qtd <= 1:
            alertas.append(
                f"Insumo crítico: {item}={qtd} (necessário em {n_receitas} receitas)")

    return alertas
