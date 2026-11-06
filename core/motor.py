"""Motor do jogo (seções 5.5 e 5.6).

Executa um turno completo em memória. Nenhuma chamada externa dentro de uma
transação. O motor é determinístico: mesma seed, preset, configuração do MCP,
estoque inicial e decisões → mesmo estado final, bit a bit.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from . import rng
from .acoes import acoes_viaveis
from .estado import Agente, Estado
from .eventos import calcular_eventos, ocorre_fartura, ocorre_tempestade
from .pagamento import pagar
from .preset import ITENS_ALIMENTARES, Preset, TODOS_ITENS
from .mcp_cliente import MundoProtocol


# Categoria → ordem de execução (5.6)
ORDEM_CATEGORIAS = ["curar", "transformar", "coletar", "forragear", "passar"]


@dataclass
class AcaoDecidida:
    """A ação decidida pelo agente para o turno (já validada)."""

    agente: int
    acao: str
    alvo: int | None = None


@dataclass
class ResultadoTurno:
    """Resultado da execução de um turno em memória."""

    estado: Estado
    acoes_executadas: list[dict] = field(default_factory=list)
    movimentos: list[dict] = field(default_factory=list)
    eventos_vida: list[dict] = field(default_factory=list)
    chamadas_mcp: list[dict] = field(default_factory=list)
    partida_encerrada: bool = False
    motivo_encerramento: str | None = None


def iniciar_turno(estado: Estado, seed: int, preset: Preset, n_turnos: int) -> Estado:
    """Passo 1 a 5 do turno (seção 5.5): estação, eventos, ordem, basal, doença, praga.

    Retorna um novo estado com tudo preenchido até antes da decisão.
    """
    turno = estado.turno
    estado.tempestade = ocorre_tempestade(seed, turno, preset)
    estado.fartura = ocorre_fartura(seed, turno, preset)
    estado.estacao = "inverno" if preset.e_inverno(turno, n_turnos) else "normal"

    # Ordem do turno
    vivos = estado.vivos
    estado.ordem_turno = rng.ordem_turno(seed, turno, vivos)

    # Basal (passo 3): pagamento imediato, agente por agente na ordem_turno.
    basal = preset.basal_do_turno(turno, n_turnos)
    for idx in estado.ordem_turno:
        agente = estado.agente(idx)
        if not agente.vivo:
            continue
        disponivel = estado.disponivel(preset)
        if basal <= disponivel:
            estado.estoque, estado.alimento_solto = pagar(
                estado.estoque, estado.alimento_solto, basal, preset,
                movimentos=estado.movimentos, causa="basal", agente_id=idx,
            )
            # Registra basal como movimento separado (alimento consumido)
            # Já foi registrado em pagar() como pagamento. Mas 5.6 quer
            # distinguir basal dos outros pagamentos no extrato do agente.
            # Vamos adicionar um movimento "basal" sintético para o extrato.
            estado.movimentos.append({
                "agente_id": idx, "tipo": "basal", "item": "alimento_solto",
                "delta": -basal, "saldo_apos": estado.alimento_solto, "causa": "basal",
            })
        else:
            # Não paga: perde 1 vida (nunca abaixo de 0), basal NÃO cobrado.
            vida_antes = agente.vida
            agente.vida = max(0, agente.vida - 1)
            estado.eventos_vida.append({
                "agente_id": idx, "vida_antes": vida_antes,
                "vida_depois": agente.vida, "motivo": "fome",
            })
            if agente.vida == 0:
                agente.vivo = False
                agente.morto_em_turno = turno
                estado.eventos_vida.append({
                    "agente_id": idx, "vida_antes": 0,
                    "vida_depois": 0, "motivo": "morte",
                })

    # Passo 4: doença (depois do basal). Só alvos vivos neste momento.
    calcular_eventos(estado, seed, preset)
    for idx in estado.doenca_alvos:
        agente = estado.agente(idx)
        if not agente.vivo:
            continue
        vida_antes = agente.vida
        agente.vida = max(0, agente.vida - 1)
        estado.eventos_vida.append({
            "agente_id": idx, "vida_antes": vida_antes,
            "vida_depois": agente.vida, "motivo": "doenca",
        })
        if agente.vida == 0:
            agente.vivo = False
            agente.morto_em_turno = turno
            estado.eventos_vida.append({
                "agente_id": idx, "vida_antes": 0,
                "vida_depois": 0, "motivo": "morte",
            })

    # Passo 4 (continuação): praga (depois da doença).
    if estado.praga:
        recurso = estado.praga["recurso"]
        perdido = estado.praga["perdido"]
        saldo_antes = estado.estoque.get(recurso, 0)
        estado.estoque[recurso] = max(0, saldo_antes - perdido)
        estado.movimentos.append({
            "agente_id": None, "tipo": "praga", "item": recurso,
            "delta": -perdido, "saldo_apos": estado.estoque[recurso], "causa": "praga",
        })

    # Passo 5: morte por doença já tratada acima. Se todos morreram, a partida termina.
    if not estado.vivos:
        # O motor retorna; o chamador decide encerrar.
        pass

    return estado


async def executar_acoes(
    estado: Estado,
    acoes_decididas: list[AcaoDecidida],
    seed: int,
    preset: Preset,
    mundo: MundoProtocol,
    timeout_mcp_s: float = 5.0,
    max_tentativas_mcp: int = 2,
) -> ResultadoTurno:
    """Passo 7 e 8 do turno (seção 5.6): execução das ações em memória.

    Ordem: curar, transformar, coletar, forragear, passar. Dentro de cada
    categoria, segue ordem_turno. Agentes mortos são ignorados.
    """
    turno = estado.turno

    # Mapa agente → ação decidida
    acoes_por_agente = {a.agente: a for a in acoes_decididas}

    # Mapa (local, agente) → posição de saturação
    posicoes_por_local: dict[str, int] = {}

    resultado = ResultadoTurno(estado=estado)

    for categoria in ORDEM_CATEGORIAS:
        for idx in estado.ordem_turno:
            agente = estado.agente(idx)
            if not agente.vivo:
                continue
            if idx not in acoes_por_agente:
                continue
            ad = acoes_por_agente[idx]
            a = preset.acao(ad.acao)
            if a["categoria"] != categoria:
                continue
            await _executar_uma(estado, ad, seed, preset, mundo, resultado,
                                posicoes_por_local, timeout_mcp_s, max_tentativas_mcp)

    # Passo 8: aplicar mortes por acidente (já feitas em _executar_uma)
    if not estado.vivos:
        resultado.partida_encerrada = True
        resultado.motivo_encerramento = "todos_mortos"

    return resultado


async def _executar_uma(
    estado: Estado,
    ad: AcaoDecidida,
    seed: int,
    preset: Preset,
    mundo: MundoProtocol,
    resultado: ResultadoTurno,
    posicoes_por_local: dict[str, int],
    timeout_mcp_s: float,
    max_tentativas_mcp: int,
) -> None:
    """Executa uma ação para um agente, registrando movimentos, vidas e MCP."""
    turno = estado.turno
    agente = estado.agente(ad.agente)
    a = preset.acao(ad.acao)
    categoria = a["categoria"]
    custo = a["custo"]
    insumos = a.get("insumos", {})

    # Revalidação (5.6)
    invalidada = False
    # Para transformar: insumos são consumidos primeiro, depois o custo é pago
    # com o restante. A revalidação precisa verificar que após consumir insumos
    # ainda há alimento suficiente para o custo.
    if categoria == "transformar":
        estoque_apos_insumos = dict(estado.estoque)
        for item, qtd in insumos.items():
            if estoque_apos_insumos.get(item, 0) < qtd:
                invalidada = True
                break
            estoque_apos_insumos[item] -= qtd
        if not invalidada:
            # Calcula disponível após insumos
            disponivel_apos = estado.alimento_solto + sum(
                preset.valor_alimentar(item) * estoque_apos_insumos.get(item, 0)
                for item in ITENS_ALIMENTARES
            )
            if custo > disponivel_apos:
                invalidada = True
    elif categoria == "passar":
        # 'passar' nunca é invalidado por falta de alimento — é a rede de
        # segurança. Se não puder pagar o custo, perde 1 vida (tratado abaixo).
        pass
    else:
        if custo > 0 and custo > estado.disponivel(preset):
            invalidada = True
        if not all(estado.estoque.get(item, 0) >= qtd for item, qtd in insumos.items()):
            invalidada = True
    if estado.estacao == "inverno" and ad.acao in ("coletar_trigo", "coletar_erva"):
        invalidada = True
    if estado.tempestade and ad.acao == "pescar":
        invalidada = True
    if ad.acao == "curar":
        if estado.estoque.get("remedio", 0) < 1:
            invalidada = True
        else:
            alvo = estado.agente(ad.alvo) if ad.alvo is not None else None
            if alvo is None or not alvo.vivo or alvo.vida >= preset.vida_max:
                invalidada = True

    if invalidada:
        resultado.acoes_executadas.append({
            "agente_id": ad.agente, "acao": ad.acao, "alvo": ad.alvo,
            "custo": custo, "invalidada_na_execucao": True,
            "unidades_mcp": None, "unidades_finais": None,
            "posicao_local": None, "saturada": None,
            "fartura_aplicada": None, "sucesso": None, "acidente": False,
        })
        return

    # Execução por categoria
    if categoria == "curar":
        # Cobra 1, consome 1 remédio, +1 vida no alvo
        estado.estoque, estado.alimento_solto = pagar(
            estado.estoque, estado.alimento_solto, custo, preset,
            movimentos=estado.movimentos, causa="curar", agente_id=ad.agente,
        )
        estado.estoque["remedio"] -= 1
        estado.movimentos.append({
            "agente_id": ad.agente, "tipo": "cura", "item": "remedio",
            "delta": -1, "saldo_apos": estado.estoque["remedio"], "causa": "curar",
        })
        alvo = estado.agente(ad.alvo)
        vida_antes = alvo.vida
        alvo.vida = min(preset.vida_max, alvo.vida + 1)
        estado.eventos_vida.append({
            "agente_id": ad.alvo, "vida_antes": vida_antes,
            "vida_depois": alvo.vida, "motivo": "cura",
        })
        resultado.acoes_executadas.append({
            "agente_id": ad.agente, "acao": ad.acao, "alvo": ad.alvo,
            "custo": custo, "invalidada_na_execucao": False,
            "unidades_mcp": None, "unidades_finais": None,
            "posicao_local": None, "saturada": None,
            "fartura_aplicada": None, "sucesso": None, "acidente": False,
        })
        return

    if categoria == "transformar":
        # Consome insumos PRIMEIRO (para evitar que pagar() consuma um insumo
        # alimentar como peixe/carne e deixe o estoque negativo). Decisão
        # registrada em DECISOES.md (item 0.2 #23).
        for item, qtd in insumos.items():
            estado.estoque[item] -= qtd
            estado.movimentos.append({
                "agente_id": ad.agente, "tipo": "preparo", "item": item,
                "delta": -qtd, "saldo_apos": estado.estoque[item], "causa": ad.acao,
            })
        # Depois paga o custo (1 alimento) com o que sobrar
        estado.estoque, estado.alimento_solto = pagar(
            estado.estoque, estado.alimento_solto, custo, preset,
            movimentos=estado.movimentos, causa=ad.acao, agente_id=ad.agente,
        )
        mcp_seed = rng.mcp_transformar_seed(seed, turno, ad.agente)
        # Tenta até max_tentativas_mcp com a mesma seed
        mcp_resp = None
        for tentativa in range(1, max_tentativas_mcp + 1):
            try:
                mcp_resp = await asyncio.wait_for(
                    mundo.transformar(a["mcp"][1], mcp_seed),
                    timeout=timeout_mcp_s,
                )
                break
            except (asyncio.TimeoutError, Exception) as e:
                resultado.chamadas_mcp.append({
                    "agente_id": ad.agente, "ferramenta": "transformar",
                    "argumentos": {"produto": a["mcp"][1], "seed": str(mcp_seed)},
                    "resposta": None, "seed_usada": str(mcp_seed),
                    "tentativa": tentativa, "latencia_ms": None, "erro": str(e),
                })
                if tentativa == max_tentativas_mcp:
                    # Não conseguiu — segundo a 5.7, a partida fica PAUSADA.
                    raise RuntimeError(f"MCP transformar falhou após {tentativa} tentativas")

        resultado.chamadas_mcp.append({
            "agente_id": ad.agente, "ferramenta": "transformar",
            "argumentos": {"produto": a["mcp"][1], "seed": str(mcp_seed)},
            "resposta": mcp_resp, "seed_usada": str(mcp_seed),
            "tentativa": 1, "latencia_ms": None,
        })

        sucesso = mcp_resp.get("sucesso", False) if mcp_resp else False
        if sucesso:
            produto = a["mcp"][1]
            estado.estoque[produto] += 1
            estado.movimentos.append({
                "agente_id": ad.agente, "tipo": "preparo", "item": produto,
                "delta": 1, "saldo_apos": estado.estoque[produto], "causa": ad.acao,
            })

        # Acidente
        acidente = rng.acidente(seed, turno, ad.agente, a["acidente_ppm"]) if a["acidente_ppm"] > 0 else False
        if acidente:
            vida_antes = agente.vida
            agente.vida = max(0, agente.vida - 1)
            estado.eventos_vida.append({
                "agente_id": ad.agente, "vida_antes": vida_antes,
                "vida_depois": agente.vida, "motivo": "acidente",
            })
            if agente.vida == 0:
                agente.vivo = False
                agente.morto_em_turno = turno
                estado.eventos_vida.append({
                    "agente_id": ad.agente, "vida_antes": 0,
                    "vida_depois": 0, "motivo": "morte",
                })

        resultado.acoes_executadas.append({
            "agente_id": ad.agente, "acao": ad.acao, "alvo": ad.alvo,
            "custo": custo, "invalidada_na_execucao": False,
            "unidades_mcp": 1 if sucesso else 0,
            "unidades_finais": 1 if sucesso else 0,
            "posicao_local": None, "saturada": None,
            "fartura_aplicada": None, "sucesso": sucesso, "acidente": acidente,
        })
        return

    if categoria == "coletar":
        # Cobra custo, chama MCP, saturação, fartura, aplica ao estoque, acidente
        estado.estoque, estado.alimento_solto = pagar(
            estado.estoque, estado.alimento_solto, custo, preset,
            movimentos=estado.movimentos, causa=ad.acao, agente_id=ad.agente,
        )
        mcp_seed = rng.mcp_coletar_seed(seed, turno, ad.agente)
        mcp_resp = None
        for tentativa in range(1, max_tentativas_mcp + 1):
            try:
                mcp_resp = await asyncio.wait_for(
                    mundo.coletar(a["mcp"][1], mcp_seed),
                    timeout=timeout_mcp_s,
                )
                break
            except (asyncio.TimeoutError, Exception) as e:
                resultado.chamadas_mcp.append({
                    "agente_id": ad.agente, "ferramenta": "coletar",
                    "argumentos": {"recurso": a["mcp"][1], "seed": str(mcp_seed)},
                    "resposta": None, "seed_usada": str(mcp_seed),
                    "tentativa": tentativa, "latencia_ms": None, "erro": str(e),
                })
                if tentativa == max_tentativas_mcp:
                    raise RuntimeError(f"MCP coletar falhou após {tentativa} tentativas")

        resultado.chamadas_mcp.append({
            "agente_id": ad.agente, "ferramenta": "coletar",
            "argumentos": {"recurso": a["mcp"][1], "seed": str(mcp_seed)},
            "resposta": mcp_resp, "seed_usada": str(mcp_seed),
            "tentativa": 1, "latencia_ms": None,
        })

        unidades_mcp = mcp_resp.get("unidades", 0) if mcp_resp else 0
        local = a["local"]

        # Saturação: posição do agente entre as coletas efetivamente executadas e
        # pagas daquele mesmo local no turno.
        posicao = posicoes_por_local.get(local, 0) + 1
        posicoes_por_local[local] = posicao
        saturada = posicao > preset.saturacao_limite
        if saturada:
            unidades = max(0, unidades_mcp - 1)
        else:
            unidades = unidades_mcp

        # Fartura (se houve no turno)
        fartura_aplicada = False
        if estado.fartura and rng.fartura_coleta(seed, turno, ad.agente, preset.fartura_coleta_ppm):
            unidades += 1
            fartura_aplicada = True

        # Aplica ao estoque
        if unidades > 0:
            estado.estoque[local] += unidades
            estado.movimentos.append({
                "agente_id": ad.agente, "tipo": "coleta", "item": local,
                "delta": unidades, "saldo_apos": estado.estoque[local], "causa": ad.acao,
            })

        # Acidente
        acidente = rng.acidente(seed, turno, ad.agente, a["acidente_ppm"]) if a["acidente_ppm"] > 0 else False
        if acidente:
            vida_antes = agente.vida
            agente.vida = max(0, agente.vida - 1)
            estado.eventos_vida.append({
                "agente_id": ad.agente, "vida_antes": vida_antes,
                "vida_depois": agente.vida, "motivo": "acidente",
            })
            if agente.vida == 0:
                agente.vivo = False
                agente.morto_em_turno = turno
                estado.eventos_vida.append({
                    "agente_id": ad.agente, "vida_antes": 0,
                    "vida_depois": 0, "motivo": "morte",
                })

        resultado.acoes_executadas.append({
            "agente_id": ad.agente, "acao": ad.acao, "alvo": ad.alvo,
            "custo": custo, "invalidada_na_execucao": False,
            "unidades_mcp": unidades_mcp,
            "unidades_finais": unidades,
            "posicao_local": posicao, "saturada": saturada,
            "fartura_aplicada": fartura_aplicada, "sucesso": None, "acidente": acidente,
        })
        return

    if categoria == "forragear":
        # Custo 0; se u(forragem) < 0.60, alimento_solto += 1
        if rng.forragem(seed, turno, ad.agente, preset.forragem_ppm):
            estado.alimento_solto += 1
            estado.movimentos.append({
                "agente_id": ad.agente, "tipo": "forragem", "item": "alimento_solto",
                "delta": 1, "saldo_apos": estado.alimento_solto, "causa": "forragear",
            })
            unidades_finais = 1
        else:
            unidades_finais = 0
        resultado.acoes_executadas.append({
            "agente_id": ad.agente, "acao": ad.acao, "alvo": ad.alvo,
            "custo": 0, "invalidada_na_execucao": False,
            "unidades_mcp": None, "unidades_finais": unidades_finais,
            "posicao_local": None, "saturada": None,
            "fartura_aplicada": None, "sucesso": None, "acidente": False,
        })
        return

    if categoria == "passar":
        # Passar tem custo: paga `custo` de alimento; se não houver, perde 1 vida
        # (simétrico à penalidade do basal por fome). Nunca produz nada.
        pagou = False
        if custo > 0:
            if custo <= estado.disponivel(preset):
                estado.estoque, estado.alimento_solto = pagar(
                    estado.estoque, estado.alimento_solto, custo, preset,
                    movimentos=estado.movimentos, causa="passar",
                    agente_id=ad.agente,
                )
                pagou = True
            else:
                # Sem alimento para pagar o passar → perde 1 vida.
                vida_antes = agente.vida
                agente.vida = max(0, agente.vida - 1)
                estado.eventos_vida.append({
                    "agente_id": ad.agente, "vida_antes": vida_antes,
                    "vida_depois": agente.vida, "motivo": "fome",
                })
                if agente.vida == 0:
                    agente.vivo = False
                    agente.morto_em_turno = turno
                    estado.eventos_vida.append({
                        "agente_id": ad.agente, "vida_antes": 0,
                        "vida_depois": 0, "motivo": "morte",
                    })
        resultado.acoes_executadas.append({
            "agente_id": ad.agente, "acao": ad.acao, "alvo": ad.alvo,
            "custo": custo, "invalidada_na_execucao": False,
            "unidades_mcp": None, "unidades_finais": None,
            "posicao_local": None, "saturada": None,
            "fartura_aplicada": None, "sucesso": pagou, "acidente": False,
        })
        return


def placar(estado: Estado, preset: Preset) -> dict:
    """Placar (seção 5.8): agentes vivos → soma vidas → valor de pontuação do estoque."""
    n_vivos = sum(1 for a in estado.agentes if a.vivo)
    soma_vidas = sum(a.vida for a in estado.agentes if a.vivo)
    valor_estoque = preset.valor_pontuacao_total(estado.estoque, estado.alimento_solto)
    return {
        "n_vivos": n_vivos,
        "soma_vidas": soma_vidas,
        "valor_estoque": valor_estoque,
    }
