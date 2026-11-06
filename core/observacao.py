"""Geração e validação da observação do agente (seção 6.1).

A observação é um JSON único por agente, definido pelo schema em
`core/schemas/observacao_v1.json`. O core valida cada observação com
`jsonschema` antes de persisti-la e de enviá-la ao decisor.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from jsonschema import Draft202012Validator

from .estado import Estado
from .preset import TODOS_ITENS, Preset

CAMINHO_SCHEMA = Path(__file__).parent / "schemas" / "observacao_v1.json"

_SCHEMA_CACHE = None
_VALIDATOR_CACHE: Draft202012Validator | None = None


def schema() -> dict:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        with open(CAMINHO_SCHEMA, encoding="utf-8") as f:
            _SCHEMA_CACHE = json.load(f)
    return _SCHEMA_CACHE


def validator() -> Draft202012Validator:
    """Validador pré-compilado (muito mais rápido que jsonschema.validate)."""
    global _VALIDATOR_CACHE
    if _VALIDATOR_CACHE is None:
        _VALIDATOR_CACHE = Draft202012Validator(schema())
    return _VALIDATOR_CACHE


def validar(observacao: dict) -> None:
    """Valida a observação contra o schema. Levanta exceção se inválida."""
    validator().validate(observacao)


def renderizar_texto(observacao: dict, max_tokens: int | None = None,
                     max_chars: int | None = None) -> str:
    """Renderiza a observação como texto (serialização canônica).

    Usado para a LLM (texto) e para o LBM (compacto, com limite).
    """
    if max_tokens is not None:
        # Estimativa: 4 caracteres por token
        max_chars = max_chars or max_tokens * 4
    return json.dumps(observacao, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _gerar_papel_por_id(observacao: dict, alimento_disp: int) -> str:
    """Gera instrução de papel baseada no ID do agente e no estado do jogo.

    Descoberta do diagnostico_laya11.py: o Laya ignora instruções de coordenação
    multi-agente ("não pesque se outros vão pescar"), mas segue instruções de
    PAPEL individual ("você é id=0, considere coletar madeira").

    Estratégia: monta lista de papéis úteis baseada no estado, depois usa ID
    como índice direto (id=0 → papel[0], id=1 → papel[1], etc).
    Isso garante distribuição automática — cada agente recebe papel diferente.
    """
    eu = observacao.get("eu", {})
    agente_id = eu.get("agente", 0)
    itens = observacao.get("estoque", {}).get("itens", {})

    # Insumos disponíveis
    trigo = itens.get("trigo", 0)
    peixe = itens.get("peixe", 0)
    carne = itens.get("carne", 0)
    madeira = itens.get("madeira", 0)
    erva = itens.get("erva", 0)
    remedio = itens.get("remedio", 0)

    # Há feridos?
    agentes = observacao.get("agentes", [])
    ha_feridos = any(a.get("status") == "vivo" and a.get("vida", 3) < 3 for a in agentes)
    n_agentes = len([a for a in agentes if a.get("status") == "vivo"])

    # Constrói lista de papéis ÚNICOS, em ordem de prioridade
    # Cada agente (por ID) pega um papel diferente
    papeis = []

    # PRIORIDADE 1: cura (se há feridos)
    if ha_feridos and remedio > 0:
        papeis.append(("curar", "há feridos e temos remédio — PRIORIZE curar"))
    if ha_feridos and remedio == 0 and erva >= 2 and madeira >= 1:
        papeis.append(("preparar_remedio", "há feridos sem remédio — PRIORIZE preparar remédio"))
    if ha_feridos and erva < 2:
        papeis.append(("coletar_erva", "há feridos — colete erva para remédio futuro"))

    # PRIORIDADE 2: transformar insumos em comida de alto valor
    if trigo >= 3 and madeira >= 1:
        papeis.append(("fazer_pao", f"temos {trigo} trigo + {madeira} madeira — fazer pão rende 18 pts de comida"))
    if peixe >= 2 and madeira >= 1:
        papeis.append(("assar_peixe", f"temos {peixe} peixe + {madeira} madeira — assar peixe rende 22 pts"))
    if carne >= 2 and madeira >= 1:
        papeis.append(("assar_carne", f"temos {carne} carne + {madeira} madeira — assar carne rende 26 pts"))

    # PRIORIDADE 3: coletar insumos para repor estoque
    papeis.append(("coletar_madeira", f"madeira={madeira} — sempre útil para transformar"))
    papeis.append(("coletar_trigo", f"trigo={trigo} — para fazer pão"))
    papeis.append(("coletar_erva", f"erva={erva} — para preparar remédio"))

    # PRIORIDADE 4: coletar comida fresca
    if alimento_disp < 30:
        papeis.append(("pescar", f"alimento={alimento_disp} — pescar rende peixe (comida)"))
    if alimento_disp < 20:
        papeis.append(("cacar", f"alimento={alimento_disp} — caçar rende carne (comida)"))

    # PRIORIDADE 5: forragear (sempre útil, grátis)
    papeis.append(("forragear", "grátis, 60% de +1 alimento — não gasta estoque"))

    # Se não há papéis (caso raro), retorna string vazia
    if not papeis:
        return ""

    # Seleciona papel pelo ID do agente (garante distribuição)
    # ID 0 → papel[0], ID 1 → papel[1], ..., ID N → papel[N % len(papeis)]
    papel_idx = agente_id % len(papeis)
    acao_sugerida, motivo = papeis[papel_idx]

    return f"SEU PAPEL (id={agente_id}): considere '{acao_sugerida}' — {motivo}."


def renderizar_texto_compacto(observacao: dict, max_tokens: int = 500) -> str:
    """Renderização compacta para o LBM (seção 7).

    Ordem de prioridade, cortando do fim se faltar espaço:
    1. turno, turnos restantes, estação, clima
    2. minha vida e a dos outros agentes
    3. estoque (alimento solto e itens)
    4. ações viáveis com custo
    5. resultado do último turno
    6. turnos anteriores
    7. mensagens da conversa

    Cada item inteiro entra ou sai, sem texto cortado no meio.
    """
    max_chars = max_tokens * 4
    partes: list[str] = []

    # 0. Contexto do jogo — LÊ do config_lbm.json (configurável)
    e_est = observacao.get("estoque", {})
    e_alim = e_est.get("alimento_solto", 0)
    for item_alim in ["peixe", "carne", "pao", "peixe_assado", "carne_assada"]:
        vals = {"peixe": 4, "carne": 6, "pao": 18, "peixe_assado": 22, "carne_assada": 26}
        e_alim += vals.get(item_alim, 0) * e_est.get("itens", {}).get(item_alim, 0)

    # Lê template do config_lbm.json
    import json as _json
    from pathlib import Path as _Path
    _config_lbm = _Path(__file__).parent.parent / "config_lbm.json"
    _template = None
    if _config_lbm.exists():
        try:
            _cfg = _json.loads(_config_lbm.read_text(encoding="utf-8"))
            _template = _cfg.get("state_template")
        except:
            pass

    if not _template:
        _template = (
            "JOGO DE SOBREVIVÊNCIA. Objetivo: todos vivos até o fim.\n"
            "REGRA 1: Cada turno cada agente paga basal (1 alimento normal, 3 no inverno).\n"
            "REGRA 2: Sem alimento, perde 1 vida. Vida 0 = morte.\n"
            "REGRA 3: Trigo, erva, madeira e remédio NÃO são comida. Precisam ser transformados.\n"
            "REGRA 4: Só peixe, carne, pão, peixe_assado e carne_assada são comida.\n"
            "REGRA 5: Coletar CUSTA alimento. Se disponível baixo, evite coletar.\n"
            "REGRA 6: No máximo 2 agentes por local rendem plenamente.\n"
            "REGRA 7: Forragear custa 0 e tem 60% de chance de +1 alimento.\n"
            "ALERTA: Alimento disponível = {alimento_disponivel}. {alerta_alimento}\n"
            "EVITE que todos escolham a mesma ação — dividam as tarefas!"
        )

    # Substitui placeholders — strings curtas para não diluir o template
    # (diagnóstico mostrou que menos texto = mais confiança do Laya)
    if e_alim < 10:
        alerta = "POUCO alimento — priorize forragear e transformar."
    else:
        alerta = "Alimento ok."

    # Alerta de feridos — aparece SEMPRE que há agentes com vida baixa
    # (Laya ignora essa info — testes diag10 mostraram conf=1.0 em pescar mesmo
    #  com alerta explícito "PRIORIZE coletar_erva". Mas Claude usa quando escala.)
    e_est = observacao.get("estoque", {})
    e_itens = e_est.get("itens", {})
    tem_remedio = e_itens.get("remedio", 0) > 0
    agentes_vida_baixa = [
        a for a in observacao["agentes"] if a["status"] == "vivo" and a["vida"] < 3
    ]
    alerta_feridos = ""
    if agentes_vida_baixa:
        nomes_feridos = ", ".join(
            f"{a['nome']}(v={a['vida']}/3)" for a in agentes_vida_baixa
        )
        status_remedio = "com remédio" if tem_remedio else "sem remédio"
        alerta_feridos = f"\nFERIDOS: {nomes_feridos} ({status_remedio})."

    contexto_jogo = _template.replace("{alimento_disponivel}", str(e_alim))
    contexto_jogo = contexto_jogo.replace("{alerta_alimento}", alerta)
    if alerta_feridos:
        contexto_jogo += alerta_feridos
    partes.append(contexto_jogo)

    # Variável para armazenar o papel gerado (será preenchido e adicionado depois das ações)
    papel_gerado = None

    # 1. Partida — compacto (sem "restantes" nem flags False)
    p = observacao["partida"]
    clima_bits = []
    if p["clima"]["tempestade"]:
        clima_bits.append("tempestade")
    if p["clima"]["fartura"]:
        clima_bits.append("fartura")
    clima_str = f", {','.join(clima_bits)}" if clima_bits else ""
    partes.append(f"Turno {p['turno']}/{p['turnos_total']}, {p['estacao']}{clima_str}")

    # 2. Agentes — formato compacto, mas mostra vida quando há feridos
    eu = observacao["eu"]
    partes.append(f"Eu: {eu['nome']} (id={eu['agente']}, vida={eu['vida']}/3)")
    outros = [a for a in observacao["agentes"] if a["agente"] != eu["agente"]]
    if outros:
        vivos = [a for a in outros if a["status"] == "vivo"]
        mortos = [a for a in outros if a["status"] != "vivo"]
        # Se há alguém ferido, mostra vida de cada um (informação crítica para decisão de curar)
        algum_ferido = any(a["vida"] < 3 for a in vivos)
        if algum_ferido:
            vivos_str = ", ".join(f"{a['nome']}(v={a['vida']}/3)" for a in vivos)
            partes.append(f"Outros vivos: {vivos_str}")
        else:
            partes.append(f"Outros: {len(vivos)} vivos")
        if mortos:
            nomes_mortos = ", ".join(a["nome"] for a in mortos)
            partes.append(f"Mortos: {nomes_mortos}")

    # 3. Estoque — compacto (sem trailing comma quando vazio)
    e = observacao["estoque"]
    itens_str = ", ".join(f"{k}={v}" for k, v in e["itens"].items() if v > 0)
    if itens_str:
        partes.append(f"Estoque: solto={e['alimento_solto']}, {itens_str}")
    else:
        partes.append(f"Estoque: solto={e['alimento_solto']}")

    # 3.5 Contexto de outros agentes (quando disponível — usado na fase anti-colisão)
    # Se o hibrido.py injetar `acoes_outros_agentes` na observação, mostramos aqui
    acoes_outros = observacao.get("acoes_outros_agentes")
    if acoes_outros:
        # Renderiza: "Outros vão: A1 pescar, A2 forragear"
        partes_outros = []
        for a in acoes_outros:
            alvo_str = f"→{a['alvo']}" if a.get("alvo") is not None else ""
            partes_outros.append(f"A{a['agente']} {a['acao']}{alvo_str}")
        if partes_outros:
            partes.append("Outros vão: " + ", ".join(partes_outros))

    # 4. Ações viáveis — formato COMPACTO (só custo)
    # Otimização: state enriquecido estava causando truncamento (1278 tokens > 1024 limite)
    # e deixando o Laya lento (1600ms vs 400ms). Voltamos para formato compacto.
    # A informação de recompensa está implícita no papel por ID (que vem depois).
    custos = {
        "cacar": 12, "pescar": 8, "coletar_trigo": 5, "coletar_erva": 4,
        "coletar_madeira": 3, "assar_carne": 0, "assar_peixe": 0,
        "fazer_pao": 0, "preparar_remedio": 0, "forragear": 0,
        "curar": 0, "passar": 1,
    }
    partes_acoes = []
    for a in observacao["acoes_viaveis"]:
        acao_id = a["acao"]
        custo = custos.get(acao_id, "?")
        if acao_id == "curar" and a.get("alvos"):
            alvos_str = ",".join(str(x) for x in a["alvos"])
            partes_acoes.append(f"curar(0,alvos={alvos_str})")
        else:
            partes_acoes.append(f"{acao_id}({custo})")
    acoes_str = ", ".join(partes_acoes)
    partes.append(f"Ações: {acoes_str}")

    # 4.5 PAPEL POR ID — mantido (é o que diversifica as escolhas)
    # Descoberta diag11: papel por ID foi a ÚNICA variação que diversificou escolhas
    # do Laya (4 ações únicas vs 1 nos outros testes)
    papel_gerado = _gerar_papel_por_id(observacao, e_alim)
    if papel_gerado:
        partes.append(papel_gerado)

    # 5. Mensagens do conselho (PRIORIZADAS — antes do histórico)
    for m in observacao["mensagens"]:
        partes.append(f"T{m['turno']}R{m['rodada']} Agente {m['agente']}: {m['texto']}"
                      + (f" (intenção: {m['intencao_declarada']})" if m.get('intencao_declarada') else ""))

    # 6. Resultado do último turno
    if observacao["historico"]:
        h = observacao["historico"][-1]
        r = h["resultado"]
        partes.append(f"Último turno {h['turno']}: ação={h['acao']}, alvo={h['alvo']}, "
                      f"unidades={r['unidades_finais']}, acidente={r['acidente']}, invalidada={r['invalidada']}")

    # 7. Turnos anteriores (exceto o último já incluso)
    if len(observacao["historico"]) > 1:
        for h in observacao["historico"][:-1]:
            partes.append(f"Turno {h['turno']}: ação={h['acao']}, invalidada={h['resultado']['invalidada']}")

    # Junta; se passar do limite, corta partes do fim (sem cortar no meio de uma parte)
    texto = ""
    for parte in partes:
        candidato = (texto + "\n" + parte) if texto else parte
        if len(candidato) > max_chars:
            break
        texto = candidato
    return texto


def gerar(
    estado: Estado,
    agente_idx: int,
    preset: Preset,
    n_turnos: int,
    acoes_viaveis_agente: list[dict],
    historico: list[dict],
    mensagens: list[dict],
) -> dict:
    """Gera a observação do agente `agente_idx` no estado atual.

    `historico` é uma lista de dicionários no formato `turno_historico` do schema,
    ordenados por turno crescente, máximo 3.
    `mensagens` é uma lista de dicionários no formato `mensagem` do schema.
    """
    agente = estado.agente(agente_idx)
    turno = estado.turno

    obs = {
        "versao": 1,
        "partida": {
            "turno": turno,
            "turnos_total": n_turnos,
            "turnos_restantes": max(0, n_turnos - turno),
            "estacao": estado.estacao,
            "inicio_inverno": preset.inicio_inverno(n_turnos),
            "clima": {
                "tempestade": estado.tempestade,
                "fartura": estado.fartura,
            },
        },
        "eu": {
            "agente": agente.indice,
            "nome": agente.nome,
            "vida": agente.vida,
        },
        "agentes": [
            {
                "agente": a.indice,
                "nome": a.nome,
                "vida": a.vida,
                "status": "vivo" if a.vivo else "morto",
            }
            for a in estado.agentes
        ],
        "estoque": {
            "alimento_solto": estado.alimento_solto,
            "itens": {item: estado.estoque.get(item, 0) for item in TODOS_ITENS},
        },
        "historico": historico[-3:] if len(historico) > 3 else historico,
        "mensagens": mensagens,
        "acoes_viaveis": acoes_viaveis_agente,
    }

    validar(obs)
    return obs
