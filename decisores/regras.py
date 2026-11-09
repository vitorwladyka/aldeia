"""Regras determinísticas que decidem ANTES da Laya e do LLM.

Cobrem as situações em que a resposta certa é mecânica: transformar o que já
está no estoque em comida, curar o ferido, repor a madeira que destrava as
transformações e só então coletar, mantendo folga de comida. Quando nenhuma
regra dispara, `decidir` devolve None e o fluxo segue como antes (Laya → LLM).

Tudo é derivado do preset (valores, custos, insumos); nada de números mágicos
por receita. Não usa aleatoriedade: mesmo estado → mesma decisão.
"""
from __future__ import annotations

from core.acoes import RESERVA_ALIMENTO
from core.estado import Estado
from core.preset import Preset
from decisores.bot import Decisao

ORIGEM = "regra"

# Madeira mínima em estoque (livre de reservas) antes de qualquer outra coleta.
MADEIRA_MINIMA = 2
# Trigo para ter um pão a caminho (insumos de fazer_pao).
TRIGO_MINIMO = 3
# Erva para um remédio (insumos de preparar_remedio).
ERVA_MINIMA = 2
# Turnos de basal de toda a aldeia que a comida deve cobrir após pagar uma coleta.
TURNOS_DE_FOLGA = 2
# Ordem entre as duas primeiras regras: ("transformar", "curar") ou o inverso.
ORDEM_TRANSFORMAR_CURAR = ("transformar", "curar")


def _ganho_alimentar(acao_id: str, preset: Preset) -> int:
    """Comida criada menos comida consumida como insumo (0 se não é de comida)."""
    a = preset.acao(acao_id)
    if a.get("categoria") != "transformar":
        return 0
    produto = a["mcp"][1]
    if not preset.e_alimentar(produto):
        return 0
    insumos = sum(preset.valor_alimentar(i) * q for i, q in a.get("insumos", {}).items())
    return preset.valor_alimentar(produto) - insumos


def _regra_transformar(ctx: dict) -> Decisao | None:
    preset: Preset = ctx["preset"]
    melhor, ganho = None, 0
    for v in ctx["viaveis"]:
        g = _ganho_alimentar(v["acao"], preset)
        if g > ganho:
            melhor, ganho = v["acao"], g
    if melhor is None:
        return None
    return _dec(melhor, None,
                f"transformar em comida ({melhor}: +{ganho} de comida líquida)")


def _regra_curar(ctx: dict) -> Decisao | None:
    v = ctx["por_acao"].get("curar")
    if not v or not v.get("alvos"):
        return None
    estado: Estado = ctx["estado"]
    reservas = ctx["reservas"]
    from core.acoes import chave_cura
    alvo = min(v["alvos"], key=lambda i: (
        estado.agente(i).vida + reservas.get(chave_cura(i), 0), i))
    return _dec("curar", alvo,
                f"curar {estado.agente(alvo).nome} (menor vida entre os feridos)")


def _regra_remedio(ctx: dict) -> Decisao | None:
    estado: Estado = ctx["estado"]
    preset: Preset = ctx["preset"]
    feridos = any(a.vivo and a.vida < preset.vida_max for a in estado.agentes)
    if feridos and ctx["item"]("remedio") == 0 and "preparar_remedio" in ctx["por_acao"]:
        return _dec("preparar_remedio", None,
                    "há ferido e nenhum remédio: preparar remédio")
    return None


def _pode_coletar(ctx: dict, acao_id: str) -> bool:
    """Coleta viável, paga com folga de comida e em local não saturado."""
    if acao_id not in ctx["por_acao"]:
        return False
    preset: Preset = ctx["preset"]
    custo = preset.acao(acao_id)["custo"]
    if ctx["comida"] - custo < ctx["folga"]:
        return False
    local = preset.acao(acao_id).get("local")
    ocupados = ctx["locais_ocupados"]
    return ocupados.get(local, 0) < preset.saturacao_limite


def _regra_madeira(ctx: dict) -> Decisao | None:
    if ctx["item"]("madeira") < MADEIRA_MINIMA and _pode_coletar(ctx, "coletar_madeira"):
        return _dec("coletar_madeira", None,
                    f"madeira abaixo de {MADEIRA_MINIMA}: repor para destravar as receitas")
    return None


def _regra_insumo(ctx: dict) -> Decisao | None:
    estado: Estado = ctx["estado"]
    preset: Preset = ctx["preset"]
    if ctx["item"]("madeira") < 1:
        return None
    feridos = any(a.vivo and a.vida < preset.vida_max for a in estado.agentes)
    if (feridos and ctx["item"]("remedio") == 0 and ctx["item"]("erva") < ERVA_MINIMA
            and _pode_coletar(ctx, "coletar_erva")):
        return _dec("coletar_erva", None, "há ferido sem remédio e pouca erva: coletar erva")
    if ctx["item"]("trigo") < TRIGO_MINIMO and _pode_coletar(ctx, "coletar_trigo"):
        return _dec("coletar_trigo", None,
                    f"trigo abaixo de {TRIGO_MINIMO} e comida com folga: coletar trigo")
    return None


def _regra_poupar(ctx: dict) -> Decisao | None:
    """Comida abaixo da folga e nada mecânico a fazer: forragear (custo 0)."""
    if ctx["comida"] < ctx["folga"] and "forragear" in ctx["por_acao"]:
        return _dec("forragear", None,
                    "comida abaixo da folga: forragear em vez de gastar com coleta")
    return None


def _dec(acao: str, alvo: int | None, raciocinio: str) -> Decisao:
    return Decisao(acao=acao, alvo=alvo, confianca=1.0, origem=ORIGEM,
                   raciocinio=f"[regra] {raciocinio}")


def decidir(estado: Estado, agente_idx: int, viaveis: list[dict], preset: Preset,
            reservas: dict[str, int] | None = None,
            locais_ocupados: dict[str, int] | None = None) -> Decisao | None:
    """Primeira regra que dispara vence; None se nenhuma se aplica.

    `viaveis` já considera as reservas dos agentes anteriores no turno;
    `reservas` e `locais_ocupados` entram nas contas de folga e saturação.
    """
    if not viaveis or not estado.agente(agente_idx).vivo:
        return None
    reservas = reservas or {}
    n_vivos = len(estado.vivos)
    basal = preset.basal_inverno if estado.estacao == "inverno" else preset.basal_normal
    ctx = {
        "estado": estado, "preset": preset, "viaveis": viaveis,
        "por_acao": {v["acao"]: v for v in viaveis},
        "reservas": reservas,
        "locais_ocupados": locais_ocupados or {},
        "comida": estado.disponivel(preset) - reservas.get(RESERVA_ALIMENTO, 0),
        "folga": TURNOS_DE_FOLGA * basal * n_vivos,
        "item": lambda nome: estado.estoque.get(nome, 0) - reservas.get(nome, 0),
    }
    primeiras = {"transformar": _regra_transformar, "curar": _regra_curar}
    sequencia = [primeiras[n] for n in ORDEM_TRANSFORMAR_CURAR] + [
        _regra_remedio, _regra_madeira, _regra_insumo, _regra_poupar]
    for regra in sequencia:
        d = regra(ctx)
        if d is not None:
            return d
    return None
