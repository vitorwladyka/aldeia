"""Orquestração de uma partida: criar, iniciar, executar turno, encerrar.

Fluxo do turno (seção 5.5/5.6):
1. `motor.iniciar_turno(estado, seed, preset, n_turnos)` — basal, eventos,
   ordem, doença, praga.
2. Para cada agente vivo: gerar observação, decidir ação (bot/llm/lbm/hibrido).
3. `motor.executar_acoes(estado, acoes, seed, preset, mundo)` — executa em
   memória na ordem canônica (curar, transformar, coletar, forragear, passar).
4. Atualiza histórico (com decisões e eventos_vida por turno), placar parcial.
5. Persiste.

ESTRUTURA DE PERSISTÊNCIA (data/partida_{id}.json):
- historico: lista de {turno, estacao, tempestade, fartura, doenca, praga,
  ordem, movimentos, eventos_vida, decisoes, acoes_executadas, placar}
- decisoes_ultimo_turno: alias para historico[-1].decisoes (acesso rápido)
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from core import motor, observacao, placar as placar_mod
from core.acoes import (acoes_viaveis, reservar_acao, detectar_conflitos,
                        alertas_aldeia)
from core.estado import Agente, Estado
from core.hashing import cenario_hash, mcp_config_hash, preset_hash
from core.mcp_cliente import MundoMemoria
from core.preset import Preset
from decisores import bot as _bot
from decisores import laya_router as _lbm
from decisores import regras as _regras
from hibrido import decidir as _hibrido
from hibrido import local_da_acao as _hibrido_local
from hibrido import _carregar_threshold as _hibrido_threshold
from agentes import catalogo as _catalogo


# Prompt default rico com contexto da partida.
# Placeholders preenchidos em criar() com os valores da partida.
# {nome} é preenchido por agente; os demais ({n_agentes}, {turno_final},
# {turno_inverno}) são preenchidos na criação da partida.
_PROMPT_TEMPLATE = """Você é {{nome}}, um dos {n_agentes} membros de uma aldeia cooperativa.
Sobreviver até o turno {turno_final} é o objetivo comum.

PRIORIDADES: 1º ninguém morrer; 2º recuperar vidas dos feridos; 3º manter o máximo de vidas; 4º maximizar o estoque.

REGRAS DO MUNDO:
- Cada turno, cada agente paga um basal: 1 alimento no normal, 3 no inverno (a partir do turno {turno_inverno}).
- Sem alimento para o basal, perde 1 vida. Vida 0 = morte permanente.
- Vida não regenera sozinha; só se recupera com remédio.
- Estoque é compartilhado: toda ação com custo consome do mesmo estoque.
- É comida: peixe, carne, pão, peixe_assado e carne_assada.
- Não é comida: trigo, erva, madeira e remédio — precisam ser transformados.

CONSELHO:
- Todo turno a aldeia se reúne: cada um coloca uma carta (ação) na mesa, depois vocês conversam e podem trocar de carta. As cartas finais são executadas.
- Converse de verdade: reaja ao que os outros disseram, aponte conflitos de recurso e necessidades sem cobertura, proponha divisão de tarefas.
- Fale pelo parâmetro `mensagem` da tool que você chamar (1-2 frases).

DECISÃO:
- Escolha apenas entre as ações viáveis (as tools disponíveis).
- Chame exatamente uma tool: a da sua ação final."""


NOMES_AGENTES = ["Aria", "Bento", "Cael", "Dara", "Elio", "Fenna", "Guto",
                 "Hana", "Iris", "Juno", "Kira", "Lars", "Mira", "Noa", "Otto",
                 "Pia", "Quin", "Ravi", "Sora", "Téo"]


def _agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_upper(s: str) -> str:
    """Converte status interno (minúscula) para o formato do frontend (maiúscula)."""
    return {
        "criada": "CRIADA",
        "iniciada": "EM_ANDAMENTO",  # depois de iniciar, já pode rodar turno
        "em_andamento": "EM_ANDAMENTO",
        "encerrada": "ENCERRADA",
        "pausada": "PAUSADA",
    }.get(s, s.upper())


def criar(nome: str | None, seed: int, n_agentes: int, n_turnos: int,
          decisor: str, rodadas_conselho: int = 1,
          lbm_habilitado: bool = True) -> dict:
    """Cria uma nova partida (sem iniciar).

    `decisor` deve ser "bot" ou "llm".
    `lbm_habilitado` só tem efeito quando `decisor == "llm"`: se True, cada
    decisão passa primeiro pelo LBM (Laya) e só escala para o LLM em caso de
    confiança baixa ou colisão; se False, chama o LLM diretamente.
    """
    from armazenamento import proximo_id, salvar
    if decisor not in ("bot", "llm"):
        raise ValueError(f"decisor inválido: {decisor!r} (use 'bot' ou 'llm')")
    preset = Preset.do_arquivo()

    # Estoque inicial e agentes
    estoque_inicial_dict, alimento_solto = preset.estoque_inicial(n_agentes)
    agentes = [
        Agente(indice=i, nome=NOMES_AGENTES[i % len(NOMES_AGENTES)],
               vida=preset.vida_max)
        for i in range(n_agentes)
    ]

    # Hashes do cenário
    ph = preset_hash(preset.dados)
    loop = asyncio.new_event_loop()
    try:
        info_dict = loop.run_until_complete(MundoMemoria().info())
    finally:
        loop.close()
    mh = mcp_config_hash(info_dict)
    ch = cenario_hash(ph, mh, n_agentes, n_turnos, seed, estoque_inicial_dict)

    # Prompt default dos agentes — template rico com contexto da partida.
    # Placeholders preenchidos na criação; edição por agente sobrepõe.
    # turno_inverno: 1-indexed (turno a partir do qual o inverno começa).
    turno_inverno = preset.inicio_inverno(n_turnos)
    prompt_default = _PROMPT_TEMPLATE.format(
        n_agentes=n_agentes,
        turno_final=n_turnos,
        turno_inverno=turno_inverno,
    )

    pid = proximo_id()
    partida = {
        "id": pid,
        "nome": nome or f"Partida {pid}",
        "seed": int(seed),
        "n_agentes": int(n_agentes),
        "n_turnos": int(n_turnos),
        "decisor": decisor,
        "lbm_habilitado": bool(lbm_habilitado),
        "rodadas_conselho": int(rodadas_conselho),
        "status": "criada",
        "cenario_hash": ch,
        "preset_hash": ph,
        "mcp_config_hash": mh,
        "estoque_inicial": dict(estoque_inicial_dict),
        "agentes": [
            {"indice": a.indice, "nome": a.nome, "vida": a.vida,
             "prompt": prompt_default.format(nome=a.nome),
             "skills": _catalogo.PADRAO_SKILLS,
             "tools": list(_catalogo.PADRAO_TOOLS)}
            for a in agentes
        ],
        "turno_atual": 0,
        "historico": [],
        "mensagens": [],
        "log": [],
        "placar_final": None,
        "travado": False,
        "motivo_travado": None,
        "criada_em": _agora_iso(),
        "_estado": None,
    }
    salvar(partida)
    return partida


def iniciar(partida_id: int) -> dict:
    """Inicializa o estado em memória e marca como 'iniciada'."""
    from armazenamento import carregar, salvar
    p = carregar(partida_id)
    if p is None:
        raise ValueError(f"partida {partida_id} não encontrada")
    if p["status"] != "criada":
        raise ValueError(f"partida {partida_id} já iniciada (status={p['status']})")

    preset = Preset.do_arquivo()
    estoque, alimento_solto = preset.estoque_inicial(p["n_agentes"], p["estoque_inicial"])
    agentes = [
        Agente(indice=a["indice"], nome=a["nome"], vida=a["vida"])
        for a in p["agentes"]
    ]
    estado = Estado(
        turno=0,
        estacao="normal",
        tempestade=False,
        fartura=False,
        doenca_alvos=[],
        praga=None,
        ordem_turno=[a.indice for a in agentes],
        estoque=estoque,
        alimento_solto=alimento_solto,
        agentes=agentes,
    )
    p["_estado"] = _serializar_estado(estado)
    p["status"] = "iniciada"
    p["log"].append({"t": _agora_iso(), "msg": "partida iniciada"})
    salvar(p)
    return p


def _agente_cfg(p: dict, agente_idx: int) -> dict:
    """Devolve a config (prompt, skills, tools) do agente, com padrões.

    Leitura retroativa: agentes de partidas antigas podem não ter skills/tools;
    nesse caso aplicamos os padrões do catálogo em memória (sem reescrever o
    arquivo).
    """
    ag = next((a for a in p["agentes"] if a["indice"] == agente_idx), None)
    if ag is None:
        return {"prompt": "", "skills": _catalogo.PADRAO_SKILLS,
                "tools": list(_catalogo.PADRAO_TOOLS)}
    return {
        "prompt": ag.get("prompt", ""),
        "skills": _skills_como_texto(ag.get("skills")),
        "tools": ag.get("tools") or list(_catalogo.PADRAO_TOOLS),
    }


def _skills_como_texto(skills) -> str:
    """Normaliza o campo skills para texto.

    Compatibilidade retroativa: partidas antigas podem ter `skills` como lista
    de ids (formato anterior) ou ausente. Em ambos os casos, usamos o texto
    padrão. Se já for texto, devolve como está.
    """
    if isinstance(skills, str):
        return skills
    # None ou lista (formato antigo) → texto padrão
    return _catalogo.PADRAO_SKILLS


def _injetar_cfg_obs(p: dict, obs: dict, agente_idx: int) -> dict:
    """Injeta skills/tools do agente na observação (campos internos _skills/_tools)."""
    cfg = _agente_cfg(p, agente_idx)
    obs["_skills"] = cfg["skills"]
    obs["_tools"] = cfg["tools"]
    return obs


def _decidir_para_agente(p: dict, obs: dict, prompt_agente: str, agente_idx: int,
                         preset=None, locais_ocupados: dict | None = None):
    """Chama o decisor configurado e devolve uma Decisao + latência.

    Decisores:
    - "bot": determinístico (round-robin).
    - "llm": se `lbm_habilitado` (default True), usa o híbrido Laya→LLM com
      checagem de confiança e colisão; senão, chama o LLM diretamente.

    `locais_ocupados` (opcional) mapeia local → nº de agentes já decididos na
    rodada atual; usado pelo híbrido para detectar colisão por local.
    """
    t0 = time.time()
    decisor = p["decisor"]
    if decisor == "llm":
        if p.get("lbm_habilitado", True):
            sat = preset.saturacao_limite if preset is not None else 2
            d = _hibrido(obs, prompt_agente, agente_idx,
                         locais_ocupados=locais_ocupados,
                         saturacao_limite=sat, preset=preset)
        else:
            from decisores import llm as _llm
            d = _llm.decidir(obs, prompt_agente, agente_idx)
    else:  # "bot" (ou qualquer valor inesperado → determinístico)
        d = _bot.decidir(obs, prompt_agente, agente_idx)
    lat = int((time.time() - t0) * 1000)
    return d, lat


def _decisao_para_historico(d, lat: int, turno: int, agente_idx: int) -> dict:
    """Converte uma Decisao em dict no formato esperado pelo frontend.

    `decidido_por` reflete quem realmente decidiu: "bot", "lbm" ou "llm".
    O `modelo` recebe "escalonado" quando o híbrido escalou para o LLM, para
    o frontend destacar.
    """
    acao_json = {"acao": d.acao, "alvo": d.alvo}
    # Preserva a origem real: bot→bot, lbm→lbm, llm→llm
    decidido_por_frontend = d.origem
    resposta_bruta = {
        "decidido_por": decidido_por_frontend,
        "confidence": d.confianca,
        "raciocinio": d.raciocinio,
        "origem_real": d.origem,  # para debug
    }
    # Marca modelo como "escalonado" quando o hibrido escalou para o LLM
    if d.origem == "llm" and "escalonado" in (d.raciocinio or ""):
        modelo = "escalonado"
    else:
        modelo = d.origem  # "bot" | "lbm" | "llm"
    return {
        "turno": turno,
        "indice": agente_idx,
        "origem": d.origem,
        "acao_json": __import__("json").dumps(acao_json),
        "resposta_bruta": __import__("json").dumps(resposta_bruta, ensure_ascii=False),
        "oficial": True,
        "modelo": modelo,
        "valida": True,
        "fallback": (d.origem == "bot" and d.confianca < 1.0) or "fallback" in (d.raciocinio or ""),
        "latencia_ms": lat,
        "tokens_in": None,
        "tokens_out": None,
        "erro": None,
        # Campos internos (não usados pelo frontend, mas úteis para debug)
        "_acao": d.acao,
        "_alvo": d.alvo,
        "_confianca": d.confianca,
        "_raciocinio": d.raciocinio,
    }


def _carta_cabe(carta: dict, viaveis: list[dict]) -> bool:
    """True se a carta (ação + alvo) ainda é viável dadas as ações viáveis atuais."""
    v = next((x for x in viaveis if x["acao"] == carta["acao"]), None)
    if v is None:
        return False
    if carta["acao"] == "curar":
        return carta.get("alvo") in (v.get("alvos") or [])
    return True


def _conselho_discussao(p: dict, estado, preset, mensagens: list, prox_turno: int,
                        participantes: list[int], travadas: dict,
                        reservas_travadas: dict, passadas: int,
                        origens: dict | None = None):
    """Conselho com discussão real entre agentes LLM.

    1. PROPOSTA (às cegas): cada participante coloca uma carta (ação) na mesa
       sem ver as propostas dos outros — só as cartas travadas pela Laya.
    2. DISCUSSÃO: `passadas` passadas, na ordem do turno. Cada agente vê a mesa
       completa (cartas, conflitos, necessidades, falas) e responde em UMA
       chamada: fala (`mensagem`) + carta final, que pode ser diferente da
       anterior. Para cedo quando uma passada termina sem ninguém trocar de carta.
    3. AJUSTE (rede de segurança): em ordem, o agente cuja carta já não cabe
       (insumo, alimento ou alvo de cura comprometido por cartas anteriores)
       decide de novo com as opções que restam. Garante zero ações inválidas.

    Retorna (acoes_decididas, decisoes_hist) dos participantes.
    """
    from decisores import llm as _llm_mod
    from decisores.bot import Decisao

    nomes = {a.indice: a.nome for a in estado.agentes}
    ordem = {i: n for n, i in enumerate(estado.ordem_turno)}

    # Cartas travadas (decididas pela Laya na fase 0): visíveis, mas não falam.
    travadas_cartas = {
        i: {"acao": ad.acao, "alvo": ad.alvo, "travada": True,
            "origem": (origens or {}).get(i, "lbm")}
        for i, ad in travadas.items()
    }
    cartas: dict[int, dict] = {i: dict(c) for i, c in travadas_cartas.items()}
    decisoes_ult: dict[int, dict] = {}
    falas: list[dict] = []

    def _publicar(idx, rodada, texto, acao):
        mensagens.append({"turno": prox_turno, "rodada": rodada, "agente": idx,
                          "texto": texto, "intencao_declarada": acao})

    def _mesa(idx, fase, base, passada=0, motivo=None):
        lista = [
            {"agente": i, "nome": nomes[i], "acao": c["acao"], "alvo": c["alvo"],
             "travada": c["travada"], "origem": c.get("origem"), "eu": i == idx}
            for i, c in sorted(base.items(), key=lambda kv: ordem.get(kv[0], 99))
        ]
        return {"fase": fase, "passada": passada, "cartas": lista,
                "conflitos": detectar_conflitos(estado, lista, preset),
                "alertas": alertas_aldeia(estado, preset),
                "falas": list(falas), "motivo_ajuste": motivo}

    def _decidir(idx, viaveis, mesa):
        # `mensagens=[]`: as falas do conselho vão na mesa (sem truncar o prompt).
        obs = observacao.gerar(estado, idx, preset, p["n_turnos"], viaveis,
                               _historico_para_obs(p["historico"], idx), [])
        _injetar_cfg_obs(p, obs, idx)
        obs["_mesa"] = mesa
        prompt = _agente_cfg(p, idx)["prompt"]
        t0 = time.time()
        d = _llm_mod.decidir(obs, prompt, idx)
        return d, int((time.time() - t0) * 1000)

    vivos_part = [i for i in participantes if estado.agente(i).vivo]
    if not vivos_part:
        return [], []

    # ---- 1. PROPOSTA (às cegas) ----
    for idx in vivos_part:
        a = estado.agente(idx)
        viaveis = acoes_viaveis(estado, idx, preset, reservas_travadas)
        if not viaveis:
            d, lat = Decisao("passar", None, 1.0, "bot", "sem ações viáveis"), 0
        else:
            d, lat = _decidir(idx, viaveis, _mesa(idx, "proposta", travadas_cartas))
        cartas[idx] = {"acao": d.acao, "alvo": d.alvo, "travada": False}
        decisoes_ult[idx] = _decisao_para_historico(d, lat, prox_turno, idx)
        _publicar(idx, 1, "Proposta: " + _gerar_mensagem_conselho(d, a, 1, False, 0),
                  d.acao)
        print(f"[PROPOSTA] agente={idx} ({a.nome}) → {d.acao}"
              + (f" alvo={d.alvo}" if d.alvo is not None else ""), flush=True)

    # ---- 2. DISCUSSÃO ----
    for passada in range(1, passadas + 1):
        rodada = passada + 1
        mudou = False
        for idx in vivos_part:
            a = estado.agente(idx)
            viaveis = acoes_viaveis(estado, idx, preset, reservas_travadas)
            if not viaveis:
                continue
            antes = (cartas[idx]["acao"], cartas[idx]["alvo"])
            d, lat = _decidir(idx, viaveis, _mesa(idx, "discussao", cartas, passada))
            if (d.raciocinio or "").startswith("fallback"):
                # LLM indisponível (rede, limite de taxa, sem escolha): NÃO troca a
                # carta por "a primeira ação viável" — mantém a que já está na mesa.
                print(f"[DISCUSSAO] P{passada} agente={idx} ({a.nome}) LLM "
                      f"indisponível ({d.raciocinio}) → mantém {antes[0]}", flush=True)
                continue
            texto = d.mensagem or (
                _gerar_mensagem_conselho(d, a, rodada, False, 0) + " (sem comentário)")
            cartas[idx].update(acao=d.acao, alvo=d.alvo)
            if (d.acao, d.alvo) != antes:
                mudou = True
            decisoes_ult[idx] = _decisao_para_historico(d, lat, prox_turno, idx)
            falas.append({"nome": a.nome, "texto": texto})
            _publicar(idx, rodada, texto, d.acao)
            print(f"[DISCUSSAO] P{passada} agente={idx} ({a.nome}) "
                  f"{'MUDOU' if (d.acao, d.alvo) != antes else 'manteve'} "
                  f"{antes[0]} → {d.acao} | {texto[:100]}", flush=True)
        if not mudou:
            mensagens.append({
                "turno": prox_turno, "rodada": rodada, "agente": None,
                "texto": f"✓ Consenso: ninguém mudou de carta na passada {passada}.",
                "intencao_declarada": None,
            })
            print(f"[CONSENSO] ninguém mudou de carta na passada {passada}", flush=True)
            break

    # ---- 3. AJUSTE (rede de segurança) ----
    reservas = dict(reservas_travadas)
    for idx in vivos_part:
        a = estado.agente(idx)
        carta = cartas[idx]
        viaveis = acoes_viaveis(estado, idx, preset, reservas)
        if not _carta_cabe(carta, viaveis):
            motivo = (f"'{carta['acao']}' já não cabe: os recursos (insumo, alimento "
                      f"ou alvo de cura) foram comprometidos por cartas anteriores")
            d, lat = _decidir(idx, viaveis, _mesa(idx, "ajuste", cartas, 0, motivo))
            print(f"[AJUSTE] agente={idx} ({a.nome}) {carta['acao']} → {d.acao} "
                  f"({motivo})", flush=True)
            carta.update(acao=d.acao, alvo=d.alvo)
            decisoes_ult[idx] = _decisao_para_historico(d, lat, prox_turno, idx)
            texto = d.mensagem or _gerar_mensagem_conselho(d, a, passadas + 2, False, 0)
            _publicar(idx, passadas + 2, "Ajuste: " + texto, d.acao)
        reservar_acao(reservas, carta["acao"], carta["alvo"], preset)

    acoes = [motor.AcaoDecidida(agente=i, acao=cartas[i]["acao"], alvo=cartas[i]["alvo"])
             for i in vivos_part]
    decs = [decisoes_ult[i] for i in vivos_part]
    return acoes, decs


def _rodar_conselho(p: dict, estado, preset, mensagens: list,
                     prox_turno: int, rodadas: int):
    """Roda N rodadas de conselho entre os agentes vivos.

    Cada rodada, cada agente (em ordem_turno):
      1. Vê a observação (com mensagens das rodadas anteriores)
      2. Decide uma ação via decisor configurado
      3. Publica mensagem {turno, rodada, agente, texto, intencao_declarada}

    A última rodada produz as decisões oficiais (executadas pelo motor).
    Retorna (acoes_decididas, decisoes_hist).

    FASE 0 (só quando decisor="llm" e lbm_habilitado): cada agente é consultado
    pela LBM numa passada única na ordem do turno. Os que a LBM resolve (conf >=
    threshold e sem colisão) ficam com decisão FINAL, não entram no conselho nem
    chamam o LLM. Só os agentes que escalam (conf baixa ou colisão) seguem para
    o conselho. Se ninguém escala, o conselho é pulado por completo.
    """
    from decisores.bot import Decisao

    # Acumuladores finais do turno.
    acoes_finais: dict[int, motor.AcaoDecidida] = {}
    decisoes_finais: dict[int, dict] = {}
    # Locais já ocupados por decisões FINAIS (resolvidas pela LBM na fase 0);
    # contam na colisão do conselho.
    locais_resolvidos: dict[str, int] = {}
    # Insumos/remédio já reservados por decisões FINAIS (fase 0). Evita que dois
    # agentes escolham a mesma ação quando só há insumo para um.
    reservas_resolvidas: dict[str, int] = {}
    # Agentes que precisam passar pelo conselho (ordem preservada).
    a_escalar: list[int] = []

    usa_lbm = (p["decisor"] == "llm" and p.get("lbm_habilitado", True))

    # ---- FASE R: regras determinísticas (antes da Laya e do LLM) ----
    # Só no decisor "llm". Quem a regra resolve fica com decisão final, ocupa o
    # local e reserva insumos/alimento/cura; os demais seguem para a Laya/LLM.
    if p["decisor"] == "llm":
        for idx in estado.ordem_turno:
            if not estado.agente(idx).vivo:
                continue
            viaveis_r = acoes_viaveis(estado, idx, preset, reservas_resolvidas)
            d_r = _regras.decidir(estado, idx, viaveis_r, preset,
                                  reservas_resolvidas, locais_resolvidos)
            if d_r is None:
                continue
            acoes_finais[idx] = motor.AcaoDecidida(
                agente=idx, acao=d_r.acao, alvo=d_r.alvo)
            decisoes_finais[idx] = _decisao_para_historico(d_r, 0, prox_turno, idx)
            loc_r = _hibrido_local(d_r.acao, preset)
            locais_resolvidos[loc_r] = locais_resolvidos.get(loc_r, 0) + 1
            reservar_acao(reservas_resolvidas, d_r.acao, d_r.alvo, preset)
            print(f"[REGRA] agente={idx} → {d_r.acao}"
                  + (f" alvo={d_r.alvo}" if d_r.alvo is not None else "")
                  + f" | {d_r.raciocinio}", flush=True)

    # ---- FASE 0: pré-resolução pela LBM ----
    if usa_lbm:
        sat = preset.saturacao_limite
        for idx in estado.ordem_turno:
            a = estado.agente(idx)
            if not a.vivo or idx in acoes_finais:
                continue
            viaveis = acoes_viaveis(estado, a.indice, preset, reservas_resolvidas)
            if not viaveis:
                # Sem ações viáveis: passa, decisão final, fora do conselho.
                acoes_finais[idx] = motor.AcaoDecidida(agente=idx, acao="passar")
                d = Decisao(acao="passar", confianca=1.0, origem="lbm",
                            raciocinio="sem ações viáveis")
                decisoes_finais[idx] = _decisao_para_historico(d, 0, prox_turno, idx)
                continue

            obs = observacao.gerar(estado, a.indice, preset, p["n_turnos"],
                                   viaveis,
                                   _historico_para_obs(p["historico"], a.indice),
                                   mensagens)
            # Injeta tools do agente para a Laya restringir as opções.
            _injetar_cfg_obs(p, obs, a.indice)
            _t0 = time.time()
            d_lbm = _lbm.decidir(obs, "", a.indice)
            lat_lbm = int((time.time() - _t0) * 1000)  # latência real da chamada à Laya
            local = _hibrido_local(d_lbm.acao, preset)
            colide = (locais_resolvidos.get(local, 0) + 1) > sat
            threshold = _hibrido_threshold()
            print(f"[FASE0] agente={idx} laya={d_lbm.acao} conf={d_lbm.confianca:.2f} "
                  f"threshold={threshold} colide={colide} → "
                  f"{'RESOLVE (fora do conselho)' if (d_lbm.confianca >= threshold and not colide) else 'ESCALA para o conselho/LLM'}",
                  flush=True)
            if d_lbm.confianca >= threshold and not colide:
                # LBM resolve: decisão final, ocupa o local, reserva insumos,
                # fora do conselho.
                acoes_finais[idx] = motor.AcaoDecidida(
                    agente=idx, acao=d_lbm.acao, alvo=d_lbm.alvo)
                decisoes_finais[idx] = _decisao_para_historico(
                    d_lbm, lat_lbm, prox_turno, idx)
                locais_resolvidos[local] = locais_resolvidos.get(local, 0) + 1
                reservar_acao(reservas_resolvidas, d_lbm.acao, d_lbm.alvo, preset)
            else:
                a_escalar.append(idx)

        # Se ninguém escalou, o conselho é pulado por completo.
        if not a_escalar:
            acoes = [acoes_finais[i] for i in estado.ordem_turno if i in acoes_finais]
            decs = [decisoes_finais[i] for i in estado.ordem_turno if i in decisoes_finais]
            return acoes, decs

    # ---- FASE CONSELHO ----
    # Quando usa_lbm, só os agentes escalados participam; os resolvidos pela LBM
    # já estão em acoes_finais/decisoes_finais e seus locais em locais_resolvidos.
    # Quando NÃO usa_lbm (bot ou llm-direto), todos os agentes vivos participam.
    if usa_lbm:
        participantes = a_escalar
    else:
        participantes = [i for i in estado.ordem_turno
                         if estado.agente(i).vivo and i not in acoes_finais]

    # Decisor LLM: conselho com discussão real (cartas → conversa → ajuste).
    if p["decisor"] == "llm":
        passadas = max(0, int(p.get("rodadas_conselho", 1) or 0))
        acoes_c, decs_c = _conselho_discussao(
            p, estado, preset, mensagens, prox_turno, participantes,
            dict(acoes_finais), reservas_resolvidas, passadas,
            origens={i: d["origem"] for i, d in decisoes_finais.items()})
        for ad in acoes_c:
            acoes_finais[ad.agente] = ad
        for dh in decs_c:
            decisoes_finais[dh["indice"]] = dh
        acoes = [acoes_finais[i] for i in estado.ordem_turno if i in acoes_finais]
        decs = [decisoes_finais[i] for i in estado.ordem_turno if i in decisoes_finais]
        return acoes, decs

    acoes_decididas = []
    decisoes_hist = []
    # Rastreia intenções por rodada para detectar consenso
    #intencoes[rodada] = {agente_idx: acao}
    intencoes: dict[int, dict[int, str]] = {}

    for rodada in range(1, rodadas + 1):
        # Reinicia acumuladores a cada rodada; só a última fica
        acoes_decididas = []
        decisoes_hist = []
        intencoes[rodada] = {}
        eh_ultima = (rodada == rodadas)
        # Ocupação de locais nesta rodada (para colisão no híbrido). Parte dos
        # locais já ocupados pelas decisões finais da LBM (fase 0).
        locais_ocupados: dict[str, int] = dict(locais_resolvidos)
        # Reservas de insumos nesta rodada: parte das reservas da fase 0 e
        # acumula conforme os agentes decidem (evita 2 usando o mesmo insumo).
        reservas_rodada: dict[str, int] = dict(reservas_resolvidas)

        # Verifica consenso antecipado: se rodada > 1 e todas as intenções
        # desta rodada (até agora) forem iguais às da rodada anterior, para.
        # A verificação é feita DENTRO do loop de agentes, mas só dispara
        # o break de consenso quando todos os agentes já decidiram nesta rodada.
        for idx in participantes:
            a = estado.agente(idx)
            if not a.vivo:
                continue
            viaveis = acoes_viaveis(estado, a.indice, preset, reservas_rodada)
            if not viaveis:
                # Sempre registra passar como oficial (consenso ou última)
                acoes_decididas.append(
                    motor.AcaoDecidida(agente=a.indice, acao="passar"))
                d = Decisao(acao="passar", confianca=1.0, origem="bot",
                            raciocinio="sem ações viáveis")
                decisoes_hist.append(
                    _decisao_para_historico(d, 0, prox_turno, a.indice))
                # Publica intenção de "passar" no conselho
                mensagens.append({
                    "turno": prox_turno, "rodada": rodada,
                    "agente": a.indice,
                    "texto": "Sem ações viáveis — vou passar",
                    "intencao_declarada": "passar",
                })
                continue

            obs = observacao.gerar(estado, a.indice, preset, p["n_turnos"],
                                   viaveis,
                                   _historico_para_obs(p["historico"], a.indice),
                                   mensagens)
            # Injeta skills/tools do agente para o decisor LLM (Strands) usar.
            _injetar_cfg_obs(p, obs, a.indice)
            cfg_ag = _agente_cfg(p, a.indice)
            prompt_agente = cfg_ag["prompt"]

            # Este laço só atende o decisor bot (o LLM usa _conselho_discussao).
            d, lat = _decidir_para_agente(p, obs, prompt_agente, a.indice,
                                          preset=preset,
                                          locais_ocupados=locais_ocupados)

            # Registra o local ocupado pela ação final deste agente, para que
            # os próximos agentes da rodada vejam a colisão acumulada.
            local_agente = _hibrido_local(d.acao, preset)
            locais_ocupados[local_agente] = locais_ocupados.get(local_agente, 0) + 1
            # Reserva insumos, custo em alimento e ponto de cura desta ação, para
            # que os próximos agentes não disputem o mesmo recurso escasso.
            reservar_acao(reservas_rodada, d.acao, d.alvo, preset)
            print(f"[CONSELHO] R{rodada} agente={a.indice} → {d.acao}"
                  + (f" alvo={d.alvo}" if d.alvo is not None else "")
                  + f" (origem={d.origem}, conf={d.confianca:.2f}) | {d.raciocinio[:80]}",
                  flush=True)

            # Sempre registra decisão oficial (cada rodada sobrescreve; a última
            # ou a rodada de consenso fica). Sem isso, decisões eram perdidas
            # quando o consenso disparava antes da última rodada.
            acoes_decididas.append(
                motor.AcaoDecidida(agente=a.indice, acao=d.acao, alvo=d.alvo))
            decisoes_hist.append(
                _decisao_para_historico(d, lat, prox_turno, a.indice))

            # Publica mensagem em TODAS as rodadas (inclusive a última)
            texto = _gerar_mensagem_conselho(d, a, rodada, eh_ultima,
                                             len(mensagens))
            mensagens.append({
                "turno": prox_turno, "rodada": rodada,
                "agente": a.indice,
                "texto": texto,
                "intencao_declarada": d.acao,
            })
            intencoes[rodada][a.indice] = d.acao

        # Verificação de consenso no fim da rodada (depois de todos os agentes)
        # Se rodada > 1 e TODAS as intenções desta rodada == rodada anterior,
        # considera consenso e para cedo (a última rodada executada vira oficial).
        if rodada > 1 and not eh_ultima:
            anterior = intencoes.get(rodada - 1, {})
            atual = intencoes[rodada]
            # Compara só agentes que decidiram em ambas as rodadas
            agentes_em_ambas = set(anterior.keys()) & set(atual.keys())
            if agentes_em_ambas and all(
                atual[ai] == anterior[ai] for ai in agentes_em_ambas
            ):
                # Consenso! Transforma a rodada atual na oficial e para.
                # (acoes_decididas e decisoes_hist já estão preenchidos com a
                # rodada atual — precisamos só marcar como última e quebrar.)
                # Re-gera mensagens da rodada atual com eh_ultima=True
                # para incluir o raciocínio. Mais simples: refaz só as
                # decisoes_hist e mensagens da última rodada.
                # Como a refatoração é complexa, optamos por: a rodada atual
                # JÁ produziu as acoes_decididas e decisoes_hist (linhas acima),
                # só não publicamos o raciocínio nas mensagens. Vamos atualizar
                # as mensagens desta rodada para incluir o raciocínio.
                # Mensagens da rodada atual são as últimas N (uma por agente vivo).
                n_vivos = len(intencoes[rodada])
                msgs_rodada_atual = mensagens[-n_vivos:] if n_vivos > 0 else []
                # Re-gera o texto com eh_ultima=True
                for m in msgs_rodada_atual:
                    agente_idx = m["agente"]
                    ag = estado.agente(agente_idx)
                    # Recupera a Decisao correspondente
                    ddec = next(
                        (dh for dh in decisoes_hist
                         if dh["indice"] == agente_idx),
                        None
                    )
                    if ddec:
                        # Constrói Decisao sintética a partir do histórico
                        from decisores.bot import Decisao
                        d_sint = Decisao(
                            acao=ddec["_acao"],
                            alvo=ddec["_alvo"],
                            confianca=ddec["_confianca"],
                            origem=ddec["origem"],
                            raciocinio=ddec["_raciocinio"] or "",
                        )
                        m["texto"] = _gerar_mensagem_conselho(
                            d_sint, ag, rodada, True, len(mensagens))
                # Loga consenso nas mensagens
                mensagens.append({
                    "turno": prox_turno, "rodada": rodada,
                    "agente": None,  # null = mensagem do sistema (consenso)
                    "texto": f"✓ Consenso alcançado em {rodada} rodada(s) — parando cedo.",
                    "intencao_declarada": None,
                })
                break

    # Mescla as decisões finais da LBM (fase 0) com as do conselho, na ordem
    # do turno. Sem LBM, acoes_finais/decisoes_finais ficam vazios e o resultado
    # é só o conselho.
    for ad in acoes_decididas:
        acoes_finais[ad.agente] = ad
    for dh in decisoes_hist:
        decisoes_finais[dh["indice"]] = dh

    acoes = [acoes_finais[i] for i in estado.ordem_turno if i in acoes_finais]
    decs = [decisoes_finais[i] for i in estado.ordem_turno if i in decisoes_finais]
    return acoes, decs


def _gerar_mensagem_conselho(d, agente, rodada: int, eh_ultima: bool,
                              n_msgs: int) -> str:
    """Constrói o texto da mensagem do conselho a partir da decisão.

    Em rodadas iniciais, o texto é mais curto (declara intenção).
    Na última rodada, pode incluir o raciocínio.
    """
    acao = d.acao
    alvo = d.alvo
    nome = agente.nome

    # Texto base por categoria de ação
    if acao == "curar" and alvo is not None:
        base = f"Vou curar o agente {alvo}"
    elif acao == "curar":
        base = "Vou curar alguém"
    elif acao == "passar":
        base = "Vou passar a vez"
    elif acao == "forragear":
        base = "Vou forragear (busca grátis de alimento)"
    elif acao.startswith("coletar_"):
        recurso = acao.replace("coletar_", "")
        base = f"Vou coletar {recurso}"
    elif acao in ("assar_carne", "assar_peixe", "fazer_pao", "preparar_remedio"):
        base = f"Vou {acao.replace('_', ' ')}"
    elif acao == "cacar":
        base = "Vou caçar (comida fresca)"
    elif acao == "pescar":
        base = "Vou pescar (comida fresca)"
    else:
        base = f"Vou {acao}"

    # Na última rodada, pode incluir raciocínio (se curto)
    if eh_ultima and d.raciocinio and len(d.raciocinio) < 120:
        # Limpa marcadores de escalonamento do hibrido
        rac = d.raciocinio
        if rac.startswith("[escalonado:"):
            # "[escalonado: lbm conf=0.55<0.65] texto" → "texto"
            if "] " in rac:
                rac = rac.split("] ", 1)[1]
        base += f" — {rac}"

    return base


def executar_turno(partida_id: int) -> dict:
    """Executa um turno completo: iniciar_turno → decidir → executar_acoes.

    Retorna um resumo no formato esperado pelo frontend:
        {turno, vivos, placar, encerrada, motivo_pausa}
    """
    from armazenamento import carregar, salvar
    p = carregar(partida_id)
    if p is None:
        raise ValueError(f"partida {partida_id} não encontrada")
    if p["status"] not in ("iniciada", "em_andamento"):
        raise ValueError(f"partida {partida_id} não pode executar turno (status={p['status']})")
    if p.get("travado"):
        raise ValueError(f"partida {partida_id} travada: {p.get('motivo_travado')}")

    prox_turno = p["turno_atual"] + 1
    if prox_turno > p["n_turnos"]:
        raise ValueError(f"partida {partida_id} já no último turno")

    print(f"\n{'='*60}\n[TURNO {prox_turno}] partida {partida_id} "
          f"(decisor={p['decisor']}, lbm={p.get('lbm_habilitado')})", flush=True)

    preset = Preset.do_arquivo()
    estado = _desserializar_estado(p["_estado"])
    estado.turno = prox_turno
    estado.movimentos = []
    estado.eventos_vida = []
    estado.acoes_executadas = []

    # 1. Iniciar turno (basal, eventos, ordem, doença, praga)
    motor.iniciar_turno(estado, p["seed"], preset, p["n_turnos"])
    print(f"[TURNO {prox_turno}] basal/eventos aplicados | estacao={estado.estacao} "
          f"| vivos={estado.vivos} | ordem={estado.ordem_turno} "
          f"| estoque={ {k:v for k,v in estado.estoque.items() if v>0} } "
          f"| solto={estado.alimento_solto}", flush=True)

    if not estado.vivos:
        # Todos morreram no basal/doença → registra histórico vazio e encerra
        turno_hist = {
            "turno": prox_turno,
            "estacao": estado.estacao,
            "tempestade": estado.tempestade,
            "fartura": estado.fartura,
            "doenca": list(estado.doenca_alvos),
            "praga": dict(estado.praga) if estado.praga else None,
            "ordem": list(estado.ordem_turno),
            "movimentos": [_formatar_movimento(m) for m in estado.movimentos],
            "eventos_vida": [_formatar_evento_vida(e) for e in estado.eventos_vida],
            "decisoes": [],
            "acoes_executadas": [],
            "placar": placar_mod.placar(estado, preset),
        }
        p["historico"].append(turno_hist)
        p["turno_atual"] = prox_turno
        p["status"] = "encerrada"
        p["placar_final"] = turno_hist["placar"]
        p["_estado"] = _serializar_estado(estado)
        p["log"].append({"t": _agora_iso(),
                         "msg": f"turno {prox_turno}: todos mortos no basal/doença"})
        salvar(p)
        return _resumo_turno(p, estado, turno_hist["placar"], encerrada=True)

    # 2. Conselho + decisão final
    #    Roda N rodadas de conselho (cada agente declara intenção).
    #    A última rodada produz as decisões oficiais executadas pelo motor.
    #    Se rodadas_conselho=0, roda 1 rodada silenciosa (sem publicar mensagens).
    mensagens = p["mensagens"]
    rodadas_cfg = p.get("rodadas_conselho", 1) or 1
    rodadas = max(1, rodadas_cfg)
    acoes_decididas, decisoes_hist = _rodar_conselho(
        p, estado, preset, mensagens, prox_turno, rodadas
    )

    # 3. Executar ações em memória
    mundo = MundoMemoria()
    try:
        resultado = asyncio.run(motor.executar_acoes(
            estado, acoes_decididas, p["seed"], preset, mundo,
        ))
    except RuntimeError as e:
        # MCP falhou — partida fica travada (pausada)
        p["travado"] = True
        p["motivo_travado"] = str(e)
        p["status"] = "pausada"
        p["log"].append({"t": _agora_iso(), "msg": f"turno {prox_turno} travado: {e}"})
        salvar(p)
        return _resumo_turno(p, estado, None, encerrada=False, motivo_pausa=str(e))

    # 4. Atualiza histórico
    placar_parcial = placar_mod.placar(estado, preset)
    turno_hist = {
        "turno": prox_turno,
        "estacao": estado.estacao,
        "tempestade": estado.tempestade,
        "fartura": estado.fartura,
        "doenca": list(estado.doenca_alvos),
        "praga": dict(estado.praga) if estado.praga else None,
        "ordem": list(estado.ordem_turno),
        "movimentos": [_formatar_movimento(m) for m in estado.movimentos],
        "eventos_vida": [_formatar_evento_vida(e) for e in estado.eventos_vida],
        "decisoes": decisoes_hist,
        "acoes_executadas": resultado.acoes_executadas,
        # Retorno cru do MCP (coletar/transformar) para auditar sucesso/falha.
        "chamadas_mcp": resultado.chamadas_mcp,
        "placar": placar_parcial,
    }
    p["historico"].append(turno_hist)
    p["turno_atual"] = prox_turno
    p["_estado"] = _serializar_estado(estado)

    # 5. Verificar fim de partida
    encerrada = False
    if not estado.vivos:
        p["status"] = "encerrada"
        p["placar_final"] = placar_parcial
        p["log"].append({"t": _agora_iso(), "msg": f"turno {prox_turno}: todos mortos"})
        encerrada = True
    elif prox_turno >= p["n_turnos"]:
        p["status"] = "encerrada"
        p["placar_final"] = placar_parcial
        p["log"].append({"t": _agora_iso(), "msg": f"turno {prox_turno}: fim natural"})
        encerrada = True
    else:
        p["status"] = "em_andamento"
        p["log"].append({"t": _agora_iso(), "msg": f"turno {prox_turno} executado"})

    salvar(p)
    return _resumo_turno(p, estado, placar_parcial, encerrada=encerrada)


def _resumo_turno(p: dict, estado: Estado, placar: dict | None,
                  encerrada: bool, motivo_pausa: str | None = None) -> dict:
    """Constrói o resumo do turno no formato esperado pelo frontend."""
    vivos = [
        {"indice": a.indice, "nome": a.nome, "vida_atual": a.vida,
         "status": "vivo" if a.vivo else "morto",
         "morto_em_turno": a.morto_em_turno}
        for a in estado.agentes if a.vivo
    ]
    return {
        "turno": estado.turno,
        "vivos": vivos,
        "placar": placar,
        "encerrada": encerrada,
        "motivo_pausa": motivo_pausa,
        "status": _status_upper(p["status"]),
    }


def encerrar(partida_id: int) -> dict:
    """Encerra a partida antecipadamente e calcula placar final."""
    from armazenamento import carregar, salvar
    p = carregar(partida_id)
    if p is None:
        raise ValueError(f"partida {partida_id} não encontrada")
    if p["status"] == "encerrada":
        return p
    preset = Preset.do_arquivo()
    estado = _desserializar_estado(p["_estado"]) if p.get("_estado") else None
    if estado is not None:
        p["placar_final"] = placar_mod.placar(estado, preset)
    p["status"] = "encerrada"
    p["log"].append({"t": _agora_iso(), "msg": "partida encerrada manualmente"})
    salvar(p)
    return p


def retomar(partida_id: int) -> dict:
    """Destrava uma partida pausada por falha de MCP."""
    from armazenamento import carregar, salvar
    p = carregar(partida_id)
    if p is None:
        raise ValueError(f"partida {partida_id} não encontrada")
    p["travado"] = False
    p["motivo_travado"] = None
    if p["status"] == "pausada":
        p["status"] = "em_andamento"
    p["log"].append({"t": _agora_iso(), "msg": "partida destravada"})
    salvar(p)
    return p


def reset_lock(partida_id: int) -> dict:
    """Alias para retomar (chamado pelo botão 🔒 Destravar)."""
    return retomar(partida_id)


def estado_atual(partida_id: int) -> dict:
    """Devolve o estado atual da partida no formato esperado pelo frontend."""
    from armazenamento import carregar
    p = carregar(partida_id)
    if p is None:
        raise ValueError(f"partida {partida_id} não encontrada")
    preset = Preset.do_arquivo()
    estado = _desserializar_estado(p["_estado"]) if p.get("_estado") else None

    # último turno do histórico (para o painel "Turno atual")
    ultimo_turno = None
    if p["historico"]:
        h = p["historico"][-1]
        ultimo_turno = {
            "numero": h["turno"],
            "estacao": h["estacao"],
            "tempestade": h["tempestade"],
            "fartura": h["fartura"],
            "doenca": h["doenca"],
            "praga": h["praga"],
            "ordem_json": __import__("json").dumps(h["ordem"]),
        }

    # agentes com vida_atual (formato do frontend)
    agentes_fmt = []
    for a in p["agentes"]:
        # Busca o agente no estado (para vida/status atualizados)
        ag_atual = next((x for x in estado.agentes if x.indice == a["indice"]), None) if estado else None
        skills = _skills_como_texto(a.get("skills"))
        tools = a.get("tools") or list(_catalogo.PADRAO_TOOLS)
        if ag_atual:
            agentes_fmt.append({
                "indice": ag_atual.indice,
                "nome": ag_atual.nome,
                "vida_atual": ag_atual.vida,
                "status": "vivo" if ag_atual.vivo else "morto",
                "morto_em_turno": ag_atual.morto_em_turno,
                "prompt": a["prompt"],
                "skills": skills,
                "tools": tools,
            })
        else:
            agentes_fmt.append({
                "indice": a["indice"],
                "nome": a["nome"],
                "vida_atual": a["vida"],
                "status": "vivo",
                "morto_em_turno": None,
                "prompt": a["prompt"],
                "skills": skills,
                "tools": tools,
            })

    return {
        "partida": {
            "id": p["id"], "nome": p["nome"], "seed": p["seed"],
            "status": _status_upper(p["status"]),
            "turno_atual": p["turno_atual"], "n_turnos": p["n_turnos"],
            "decisor": p["decisor"],
            "lbm_habilitado": p.get("lbm_habilitado", True),
            "rodadas_conselho": p.get("rodadas_conselho", 0),
            "motivo_pausa": p.get("motivo_travado") if p.get("travado") else None,
        },
        "estoque": dict(estado.estoque) if estado else {},
        "alimento_solto": estado.alimento_solto if estado else 0,
        "agentes": agentes_fmt,
        "ultimo_turno": ultimo_turno,
        "placar_final": p.get("placar_final"),
    }


def editar_prompt(partida_id: int, agente_idx: int, texto: str) -> dict:
    from armazenamento import carregar, salvar
    p = carregar(partida_id)
    if p is None:
        raise ValueError(f"partida {partida_id} não encontrada")
    for a in p["agentes"]:
        if a["indice"] == agente_idx:
            a["prompt"] = texto
            salvar(p)
            return p
    raise ValueError(f"agente {agente_idx} não encontrado na partida {partida_id}")


def editar_config(partida_id: int, agente_idx: int,
                  prompt: str | None = None,
                  skills: str | None = None,
                  tools: list[str] | None = None) -> dict:
    """Edita prompt, skills e/ou tools de um agente (vale no próximo turno).

    Campos None são mantidos como estão. `skills` é texto livre; `tools` é uma
    lista de ids validada contra o catálogo (ids desconhecidos descartados).
    """
    from armazenamento import carregar, salvar
    p = carregar(partida_id)
    if p is None:
        raise ValueError(f"partida {partida_id} não encontrada")
    for a in p["agentes"]:
        if a["indice"] == agente_idx:
            if prompt is not None:
                a["prompt"] = prompt
            if skills is not None:
                a["skills"] = skills
            if tools is not None:
                a["tools"] = _catalogo.tool_ids_validos(tools)
            salvar(p)
            return p
    raise ValueError(f"agente {agente_idx} não encontrado na partida {partida_id}")


def obter_prompt(partida_id: int, agente_idx: int) -> str:
    from armazenamento import carregar
    p = carregar(partida_id)
    if p is None:
        raise ValueError(f"partida {partida_id} não encontrada")
    for a in p["agentes"]:
        if a["indice"] == agente_idx:
            return a["prompt"]
    raise ValueError(f"agente {agente_idx} não encontrado")


# --- Serialização do Estado ---


def _serializar_estado(estado: Estado) -> dict:
    return {
        "turno": estado.turno,
        "estacao": estado.estacao,
        "tempestade": estado.tempestade,
        "fartura": estado.fartura,
        "doenca_alvos": list(estado.doenca_alvos),
        "praga": dict(estado.praga) if estado.praga else None,
        "ordem_turno": list(estado.ordem_turno),
        "estoque": dict(estado.estoque),
        "alimento_solto": estado.alimento_solto,
        "agentes": [
            {"indice": a.indice, "nome": a.nome, "vida": a.vida,
             "vivo": a.vivo, "morto_em_turno": a.morto_em_turno}
            for a in estado.agentes
        ],
    }


def _desserializar_estado(d: dict) -> Estado:
    agentes = [
        Agente(indice=a["indice"], nome=a["nome"], vida=a["vida"],
               vivo=a["vivo"], morto_em_turno=a.get("morto_em_turno"))
        for a in d["agentes"]
    ]
    return Estado(
        turno=d["turno"], estacao=d["estacao"],
        tempestade=d["tempestade"], fartura=d["fartura"],
        doenca_alvos=list(d["doenca_alvos"]),
        praga=dict(d["praga"]) if d.get("praga") else None,
        ordem_turno=list(d["ordem_turno"]),
        estoque=dict(d["estoque"]),
        alimento_solto=d["alimento_solto"],
        agentes=agentes,
    )


def _formatar_movimento(m: dict) -> dict:
    """Movimento no formato esperado pelo frontend: {tipo, item, delta}."""
    return {"tipo": m["tipo"], "item": m["item"], "delta": m["delta"]}


def _formatar_evento_vida(e: dict) -> dict:
    """Evento de vida no formato: {turno, indice, vida_antes, vida_depois, motivo}."""
    return {
        "turno": e.get("turno", 0),  # preenchido pelo chamador se necessário
        "indice": e["agente_id"],
        "vida_antes": e["vida_antes"],
        "vida_depois": e["vida_depois"],
        "motivo": e["motivo"],
    }


def _historico_para_obs(historico_partida: list[dict], agente_idx: int) -> list[dict]:
    """Converte o histórico persistido para o formato `turno_historico` do schema.

    O schema espera, POR AGENTE:
        {turno, acao, alvo, resultado: {unidades_finais, saturada, sucesso,
         acidente, invalidada}, extrato: [{tipo, item, delta}],
         eventos: {tempestade, fartura, doenca, praga}}

    O histórico persistido tem `decisoes` (por agente) e `acoes_executadas`
    (com resultado por agente). Aqui extraímos a entrada do `agente_idx` em
    cada turno e construímos o `turno_historico` no formato do schema.

    `extrato` inclui todos os movimentos do turno (não só do agente) — o schema
    não exige que seja filtrado por agente.
    """
    out = []
    for t in historico_partida[-3:]:
        decisao = next((d for d in t.get("decisoes", []) if d["indice"] == agente_idx), None)
        acao_exec = next((a for a in t.get("acoes_executadas", [])
                          if a["agente_id"] == agente_idx), None)

        if decisao is None:
            continue

        acao = decisao.get("_acao") or decisao.get("acao") or "passar"
        alvo = decisao.get("_alvo")
        alvo = None if alvo is None else int(alvo)

        if acao_exec:
            resultado = {
                "unidades_finais": acao_exec.get("unidades_finais"),
                "saturada": acao_exec.get("saturada"),
                "sucesso": acao_exec.get("sucesso"),
                "acidente": acao_exec.get("acidente", False),
                "invalidada": acao_exec.get("invalidada_na_execucao", False),
            }
        else:
            resultado = {
                "unidades_finais": None, "saturada": None, "sucesso": None,
                "acidente": False, "invalidada": True,
            }

        extrato = [
            {"tipo": m["tipo"], "item": m["item"], "delta": m["delta"]}
            for m in t.get("movimentos", [])
        ]
        eventos = {
            "tempestade": t.get("tempestade", False),
            "fartura": t.get("fartura", False),
            "doenca": list(t.get("doenca", [])),
            "praga": dict(t["praga"]) if t.get("praga") else None,
        }
        out.append({
            "turno": t["turno"], "acao": acao, "alvo": alvo,
            "resultado": resultado, "extrato": extrato, "eventos": eventos,
        })
    return out
