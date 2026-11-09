"""Testes do conselho com discussão real (cartas → conversa → ajuste).

O LLM é simulado (`decidir_via_strands`), então a suíte roda offline. As
políticas simuladas reproduzem uma discussão: todos propõem o mesmo, veem o
conflito na mesa, falam e trocam de carta.
"""
from __future__ import annotations

import json
import re

import pytest

import armazenamento
import partida
from agentes import strands_runner
from core.acoes import alertas_aldeia, detectar_conflitos
from core.estado import Agente, Estado
from core.preset import TODOS_ITENS
from decisores import laya_router, llm
from decisores.bot import Decisao


# ---------------------------------------------------------------- helpers
@pytest.fixture(autouse=True)
def _sem_regras(monkeypatch):
    """Estes testes isolam a mecânica do conselho: desliga a fase de regras."""
    from decisores import regras
    monkeypatch.setattr(regras, "decidir", lambda *a, **k: None)

def _estado(estoque_extra=None, vidas=(3, 3, 3), alimento=30, estacao="normal"):
    estoque = {i: 0 for i in TODOS_ITENS}
    estoque.update(estoque_extra or {})
    agentes = [Agente(indice=i, nome=f"A{i}", vida=v) for i, v in enumerate(vidas)]
    return Estado(turno=1, estacao=estacao, tempestade=False, fartura=False,
                  doenca_alvos=[], praga=None,
                  ordem_turno=[a.indice for a in agentes],
                  estoque=estoque, alimento_solto=alimento, agentes=agentes)


def _carta(idx, acao, alvo=None):
    return {"agente": idx, "nome": f"A{idx}", "acao": acao, "alvo": alvo}


def _iniciar_partida(n_agentes, rodadas, lbm, estoque, alimento=30):
    """Cria e inicia uma partida llm com estoque controlado."""
    p = partida.criar("conselho", 42, n_agentes, 5, "llm", rodadas, lbm)
    pid = p["id"]
    partida.iniciar(pid)
    d = armazenamento.carregar(pid)
    d["_estado"]["estoque"] = {i: 0 for i in TODOS_ITENS}
    d["_estado"]["estoque"].update(estoque)
    d["_estado"]["alimento_solto"] = alimento
    armazenamento.salvar(d)
    return pid


def _fake_llm(monkeypatch, politica):
    """Substitui o Strands por `politica(idx, fase, texto) -> (acao, mensagem)`."""
    chamadas: list[dict] = []

    def fake(system, tids, obs_texto, viaveis):
        idx = int(re.search(r"Eu: \w+ \(id=(\d+)", obs_texto).group(1))
        fase = re.search(r"CONSELHO DA ALDEIA: (\w+)", obs_texto).group(1)
        chamadas.append({"idx": idx, "fase": fase, "texto": obs_texto})
        resposta = politica(idx, fase, obs_texto)
        if resposta is None:  # simula LLM indisponível (rede / limite de taxa)
            return None
        acao, mensagem = resposta
        assert acao in tids, f"{acao} fora das tools efetivas {tids}"
        return {"acao": acao, "alvo": None, "mensagem": mensagem}

    monkeypatch.setattr(llm, "decidir_via_strands", fake)
    return chamadas


def _turno(pid):
    partida.executar_turno(pid)
    d = armazenamento.carregar(pid)
    h = d["historico"][-1]
    msgs = [m for m in d["mensagens"] if m["turno"] == 1]
    acoes = {x["indice"]: json.loads(x["acao_json"])["acao"] for x in h["decisoes"]}
    invalidadas = [a for a in h["acoes_executadas"] if a.get("invalidada_na_execucao")]
    return acoes, msgs, invalidadas


# ---------------------------------------------------- conflitos e alertas

def test_conflito_de_insumo(preset):
    e = _estado({"trigo": 9, "madeira": 1})
    cartas = [_carta(0, "fazer_pao"), _carta(1, "fazer_pao")]
    conflitos = detectar_conflitos(e, cartas, preset)
    assert any("madeira" in c and "A0" in c and "A1" in c for c in conflitos)


def test_sem_conflito_quando_ha_insumo_para_todos(preset):
    e = _estado({"trigo": 6, "madeira": 2})
    cartas = [_carta(0, "fazer_pao"), _carta(1, "fazer_pao")]
    assert detectar_conflitos(e, cartas, preset) == []


def test_conflito_de_alimento(preset):
    e = _estado(alimento=10)
    cartas = [_carta(0, "pescar"), _carta(1, "pescar")]  # 8 + 8 > 10
    assert any(c.startswith("Alimento") for c in detectar_conflitos(e, cartas, preset))


def test_conflito_de_saturacao_de_local(preset):
    e = _estado(alimento=100)
    cartas = [_carta(i, "pescar") for i in range(3)]
    assert any("Local 'peixe'" in c for c in detectar_conflitos(e, cartas, preset))


def test_conflito_de_cura_duplicada(preset):
    e = _estado({"remedio": 2}, vidas=(3, 2, 3))
    cartas = [_carta(0, "curar", 1), _carta(2, "curar", 1)]  # A1 só precisa de 1
    assert any(c.startswith("Cura") for c in detectar_conflitos(e, cartas, preset))


def test_alertas_madeira_critica_e_comida_baixa(preset):
    e = _estado({"madeira": 0}, alimento=2)
    alertas = alertas_aldeia(e, preset)
    assert any("madeira" in a for a in alertas)
    assert any(a.startswith("Comida") for a in alertas)


def test_alertas_feridos(preset):
    e = _estado(vidas=(3, 1, 3))
    assert any("Feridos" in a and "A1" in a for a in alertas_aldeia(e, preset))


# ------------------------------------------------------- prompt da mesa

def test_mesa_renderiza_cartas_conflitos_e_falas():
    mesa = {
        "fase": "discussao", "passada": 1,
        "alertas": ["Insumo crítico: madeira=0"],
        "cartas": [
            {"nome": "Aria", "acao": "fazer_pao", "alvo": None, "eu": True},
            {"nome": "Bento", "acao": "pescar", "alvo": None, "travada": True},
        ],
        "conflitos": ["Insumo 'madeira': as cartas pedem 2, mas o estoque tem 1"],
        "falas": [{"nome": "Bento", "texto": "Eu pesco, ninguém mais precisa."}],
    }
    texto = llm.renderizar_mesa(mesa)
    assert "DISCUSSÃO" in texto
    assert "Aria (você): fazer_pao" in texto
    assert "[travada" in texto
    assert "Conflitos detectados" in texto and "madeira" in texto
    assert 'Bento: "Eu pesco, ninguém mais precisa."' in texto
    assert "Necessidades da aldeia" in texto


def test_mesa_proposta_e_ajuste_tem_instrucoes_proprias():
    proposta = llm.renderizar_mesa({"fase": "proposta", "cartas": []})
    ajuste = llm.renderizar_mesa({"fase": "ajuste", "cartas": [],
                                  "motivo_ajuste": "madeira esgotada"})
    assert "ninguém conversou" in proposta.lower()
    assert "AJUSTE" in ajuste and "madeira esgotada" in ajuste


def test_decidir_devolve_a_fala_do_agente(monkeypatch):
    obs = {
        "versao": 1,
        "partida": {"turno": 1, "turnos_total": 20, "estacao": "normal",
                    "clima": {"tempestade": False, "fartura": False}},
        "eu": {"agente": 0, "nome": "Aria", "vida": 3},
        "agentes": [{"agente": 0, "nome": "Aria", "vida": 3, "status": "vivo"}],
        "estoque": {"alimento_solto": 5, "itens": {}},
        "historico": [], "mensagens": [],
        "acoes_viaveis": [{"acao": "forragear", "custo": 0, "alvos": None},
                          {"acao": "passar", "custo": 1, "alvos": None}],
    }
    monkeypatch.setattr(llm, "decidir_via_strands", lambda s, t, o, v: {
        "acao": "forragear", "alvo": None, "mensagem": "Vou forragear: falta comida."})
    d = llm.decidir(obs, "base", 0)
    assert d.mensagem == "Vou forragear: falta comida."


def test_tool_registra_a_mensagem_junto_da_acao():
    escolha = {"acao": None, "alvo": None, "mensagem": ""}
    tools = strands_runner._fabricar_tools(["pescar", "curar"], escolha)
    tools[0](mensagem="peixe acabou")
    assert escolha["acao"] == "pescar" and escolha["mensagem"] == "peixe acabou"


# ----------------------------------------------- fluxo completo (mockado)

def test_discussao_resolve_conflito_de_madeira(monkeypatch):
    """Todos propõem fazer_pao (1 madeira); conversam e dividem as tarefas."""
    pid = _iniciar_partida(3, rodadas=2, lbm=False,
                           estoque={"trigo": 9, "madeira": 1})

    def politica(idx, fase, texto):
        if fase == "PROPOSTA":
            return "fazer_pao", ""
        if idx == 0:
            return "fazer_pao", "Mantenho o pão: tenho trigo e a única madeira."
        if "Insumo 'madeira'" in texto:
            return "forragear", "Só há 1 madeira; A0 faz o pão, eu vou forragear."
        return "forragear", "Sigo forrageando."

    chamadas = _fake_llm(monkeypatch, politica)
    acoes, msgs, invalidadas = _turno(pid)

    assert list(acoes.values()).count("fazer_pao") == 1 and acoes[0] == "fazer_pao"
    assert not invalidadas
    # R1 = propostas (uma por agente); R2+ = falas escritas pelos agentes
    propostas = [m for m in msgs if m["texto"].startswith("Proposta:")]
    assert len(propostas) == 3 and all(m["rodada"] == 1 for m in propostas)
    assert any(m["texto"].startswith("Mantenho o pão") for m in msgs)
    assert any(m["agente"] is None and "Consenso" in m["texto"] for m in msgs)
    # na discussão os agentes enxergam o conflito e as falas dos outros
    discussao = [c for c in chamadas if c["fase"] == "DISCUSSÃO"]
    assert any("Conflitos detectados" in c["texto"] for c in discussao)
    assert any("Mantenho o pão" in c["texto"] for c in discussao)


def test_ajuste_garante_zero_invalidadas(monkeypatch):
    """Ninguém cede na conversa: a rede de segurança refaz a decisão de quem sobra."""
    pid = _iniciar_partida(3, rodadas=1, lbm=False,
                           estoque={"trigo": 9, "madeira": 1})

    def politica(idx, fase, texto):
        if fase == "AJUSTE":
            return "forragear", "Sem madeira, vou forragear."
        return "fazer_pao", "Quero fazer pão."

    _fake_llm(monkeypatch, politica)
    acoes, msgs, invalidadas = _turno(pid)

    assert list(acoes.values()).count("fazer_pao") == 1
    assert not invalidadas
    assert len([m for m in msgs if m["texto"].startswith("Ajuste:")]) == 2


def test_sem_passadas_so_ha_propostas(monkeypatch):
    pid = _iniciar_partida(2, rodadas=0, lbm=False, estoque={"trigo": 3})
    chamadas = _fake_llm(monkeypatch, lambda idx, fase, texto: ("forragear", ""))
    acoes, msgs, invalidadas = _turno(pid)

    assert {c["fase"] for c in chamadas} == {"PROPOSTA"}
    assert all(m["texto"].startswith("Proposta:") for m in msgs)
    assert set(acoes.values()) == {"forragear"} and not invalidadas


def test_carta_da_laya_aparece_travada_na_mesa(monkeypatch):
    """Quem a Laya resolve não fala, mas os escalados veem a carta travada."""
    pid = _iniciar_partida(3, rodadas=1, lbm=True, estoque={"trigo": 3})

    def fake_laya(obs, prompt, idx):
        if idx == 0:
            return Decisao("forragear", None, 0.95, "lbm", "laya")
        return Decisao("forragear", None, 0.0, "lbm", "incerto")  # escala

    monkeypatch.setattr(laya_router, "decidir", fake_laya)
    chamadas = _fake_llm(monkeypatch, lambda idx, fase, texto: ("forragear", "ok"))
    acoes, msgs, invalidadas = _turno(pid)

    assert chamadas, "os agentes escalados deveriam ir ao conselho"
    assert all(c["idx"] != 0 for c in chamadas)            # A0 (Laya) não fala
    assert all("[travada" in c["texto"] for c in chamadas)  # mas aparece na mesa
    assert all(m["agente"] != 0 for m in msgs)
    assert 0 in acoes and not invalidadas


def test_llm_indisponivel_na_discussao_mantem_a_carta(monkeypatch):
    """Falha do LLM (ex.: limite de taxa) não pode trocar a carta de ninguém."""
    pid = _iniciar_partida(3, rodadas=1, lbm=False, estoque={"trigo": 3})

    def politica(idx, fase, texto):
        if fase == "PROPOSTA":
            return "forragear", ""
        return None  # LLM fora do ar durante a discussão

    _fake_llm(monkeypatch, politica)
    acoes, msgs, invalidadas = _turno(pid)

    assert set(acoes.values()) == {"forragear"}      # ninguém trocou de carta
    assert not invalidadas
    assert not any("sem comentário" in m["texto"] for m in msgs)  # sem fala inventada
