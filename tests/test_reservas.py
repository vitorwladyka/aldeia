"""Testes da reserva de insumos escassos entre agentes no mesmo turno.

Cenário real: dois agentes decidem na mesma rodada; se só há insumo para um
(1 remédio, 1 madeira), o segundo NÃO deve ver a ação como viável.
"""
from __future__ import annotations

import json

import armazenamento
import partida
from core.acoes import acoes_viaveis, insumos_consumidos
from core.estado import Agente, Estado
from core.preset import TODOS_ITENS


def _estado(estoque_extra=None, vidas=(3, 3), alimento=20):
    estoque = {i: 0 for i in TODOS_ITENS}
    estoque.update(estoque_extra or {})
    agentes = [Agente(indice=i, nome=f"A{i}", vida=v) for i, v in enumerate(vidas)]
    return Estado(turno=1, estacao="normal", tempestade=False, fartura=False,
                  doenca_alvos=[], praga=None,
                  ordem_turno=[a.indice for a in agentes],
                  estoque=estoque, alimento_solto=alimento, agentes=agentes)


def _ids(viaveis):
    return [v["acao"] for v in viaveis]


# --- insumos_consumidos ---

def test_insumos_consumidos_transformar(preset):
    assert insumos_consumidos("fazer_pao", preset) == {"trigo": 3, "madeira": 1}


def test_insumos_consumidos_curar(preset):
    assert insumos_consumidos("curar", preset) == {"remedio": 1}


def test_insumos_consumidos_coleta_e_forragear_vazio(preset):
    assert insumos_consumidos("pescar", preset) == {}
    assert insumos_consumidos("forragear", preset) == {}


# --- acoes_viaveis com reservas ---

def test_sem_reservas_comportamento_inalterado(preset):
    e = _estado({"trigo": 3, "madeira": 1})
    assert "fazer_pao" in _ids(acoes_viaveis(e, 0, preset))
    assert "fazer_pao" in _ids(acoes_viaveis(e, 0, preset, {}))


def test_reserva_madeira_remove_fazer_pao(preset):
    """1 madeira, já reservada por outro agente → fazer_pao some das viáveis."""
    e = _estado({"trigo": 6, "madeira": 1})
    reservas = {"trigo": 3, "madeira": 1}  # outro agente já vai fazer pão
    assert "fazer_pao" not in _ids(acoes_viaveis(e, 1, preset, reservas))


def test_madeira_suficiente_para_dois_mantem_fazer_pao(preset):
    """2 madeiras e 6 trigo: dá para dois pães; a reserva de um não bloqueia o outro."""
    e = _estado({"trigo": 6, "madeira": 2})
    reservas = {"trigo": 3, "madeira": 1}
    assert "fazer_pao" in _ids(acoes_viaveis(e, 1, preset, reservas))


def test_reserva_remedio_remove_curar(preset):
    """1 remédio já reservado → curar some para o segundo agente."""
    e = _estado({"remedio": 1}, vidas=(2, 2))
    assert "curar" in _ids(acoes_viaveis(e, 1, preset))
    assert "curar" not in _ids(acoes_viaveis(e, 1, preset, {"remedio": 1}))


def test_passar_sempre_viavel_mesmo_com_reservas(preset):
    e = _estado({"trigo": 3, "madeira": 1}, alimento=0)
    assert "passar" in _ids(acoes_viaveis(e, 1, preset, {"madeira": 1, "trigo": 3}))


# --- reserva de alimento (custos de coleta) ---

def test_reservar_acao_registra_custo_em_alimento(preset):
    from core.acoes import reservar_acao, RESERVA_ALIMENTO
    r = {}
    reservar_acao(r, "pescar", None, preset)
    assert r[RESERVA_ALIMENTO] == 8


def test_reserva_alimento_remove_coleta_que_nao_cabe(preset):
    """12 de alimento: pescar (8) cabe uma vez; reservado, a 2ª não cabe mais."""
    from core.acoes import RESERVA_ALIMENTO
    e = _estado(alimento=12)
    assert "pescar" in _ids(acoes_viaveis(e, 1, preset))
    assert "pescar" not in _ids(acoes_viaveis(e, 1, preset, {RESERVA_ALIMENTO: 8}))


def test_reserva_alimento_mantem_acoes_gratis(preset):
    from core.acoes import RESERVA_ALIMENTO
    e = _estado(alimento=12)
    ids = _ids(acoes_viaveis(e, 1, preset, {RESERVA_ALIMENTO: 12}))
    assert "forragear" in ids and "passar" in ids


# --- reserva de alvo de cura ---

def test_reservar_acao_curar_registra_ponto_de_cura(preset):
    from core.acoes import reservar_acao, chave_cura
    r = {}
    reservar_acao(r, "curar", 1, preset)
    assert r["remedio"] == 1
    assert r[chave_cura(1)] == 1


def test_alvo_ja_reservado_sai_da_lista_de_alvos(preset):
    """Ferido com vida 2 já tem 1 cura reservada → não é mais alvo viável."""
    from core.acoes import chave_cura
    e = _estado({"remedio": 2}, vidas=(3, 2))
    viaveis = acoes_viaveis(e, 0, preset)
    assert next(v for v in viaveis if v["acao"] == "curar")["alvos"] == [1]
    reservas = {"remedio": 1, chave_cura(1): 1}
    assert "curar" not in _ids(acoes_viaveis(e, 0, preset, reservas))


def test_ferido_grave_aceita_segunda_cura(preset):
    """Vida 1 precisa de 2 curas: com 1 reservada ainda é alvo viável."""
    from core.acoes import chave_cura
    e = _estado({"remedio": 3}, vidas=(3, 1))
    reservas = {"remedio": 1, chave_cura(1): 1}
    viaveis = acoes_viaveis(e, 0, preset, reservas)
    assert next(v for v in viaveis if v["acao"] == "curar")["alvos"] == [1]


# --- integração: conselho não deixa dois usarem o mesmo insumo ---

def test_conselho_nao_duplica_cura_com_um_remedio(monkeypatch):
    """Dois feridos, 1 remédio: só UM agente pode escolher curar no turno."""
    p = partida.criar("res", 42, 2, 5, "bot", 1, True)
    pid = p["id"]
    # Estado inicial controlado: 1 remédio, 2 feridos, comida de sobra.
    d = armazenamento.carregar(pid)
    d["estoque_inicial"] = {i: 0 for i in TODOS_ITENS}
    d["estoque_inicial"]["remedio"] = 1
    for ag in d["agentes"]:
        ag["vida"] = 2
    armazenamento.salvar(d)
    partida.iniciar(pid)
    d = armazenamento.carregar(pid)
    d["_estado"]["alimento_solto"] = 30
    for ag in d["_estado"]["agentes"]:
        ag["vida"] = 2
    armazenamento.salvar(d)

    # Força o bot a SEMPRE preferir 'curar' quando viável (pior caso de colisão).
    from decisores import bot as _bot
    from decisores.bot import Decisao

    def sempre_curar(obs, prompt, idx):
        for v in obs["acoes_viaveis"]:
            if v["acao"] == "curar":
                return Decisao("curar", sorted(v["alvos"])[0], 1.0, "bot", "teste")
        return Decisao(obs["acoes_viaveis"][0]["acao"], None, 1.0, "bot", "teste")

    monkeypatch.setattr(_bot, "decidir", sempre_curar)

    partida.executar_turno(pid)
    d = armazenamento.carregar(pid)
    acoes = [json.loads(x["acao_json"])["acao"] for x in d["historico"][-1]["decisoes"]]
    assert acoes.count("curar") == 1, f"esperava 1 cura com 1 remédio, veio {acoes}"


def test_conselho_nao_duplica_pao_com_uma_madeira(monkeypatch):
    """Trigo de sobra mas 1 madeira: só UM agente pode escolher fazer_pao."""
    p = partida.criar("res2", 42, 2, 5, "bot", 1, True)
    pid = p["id"]
    d = armazenamento.carregar(pid)
    d["estoque_inicial"] = {i: 0 for i in TODOS_ITENS}
    d["estoque_inicial"]["trigo"] = 9
    d["estoque_inicial"]["madeira"] = 1
    armazenamento.salvar(d)
    partida.iniciar(pid)
    d = armazenamento.carregar(pid)
    d["_estado"]["alimento_solto"] = 30
    armazenamento.salvar(d)

    from decisores import bot as _bot
    from decisores.bot import Decisao

    def sempre_pao(obs, prompt, idx):
        for v in obs["acoes_viaveis"]:
            if v["acao"] == "fazer_pao":
                return Decisao("fazer_pao", None, 1.0, "bot", "teste")
        return Decisao(obs["acoes_viaveis"][0]["acao"], None, 1.0, "bot", "teste")

    monkeypatch.setattr(_bot, "decidir", sempre_pao)

    partida.executar_turno(pid)
    d = armazenamento.carregar(pid)
    acoes = [json.loads(x["acao_json"])["acao"] for x in d["historico"][-1]["decisoes"]]
    assert acoes.count("fazer_pao") == 1, f"esperava 1 pão com 1 madeira, veio {acoes}"


def test_conselho_nao_estoura_alimento_com_coletas(monkeypatch):
    """12 de alimento, pescar custa 8: só UM dos três agentes pode pescar."""
    p = partida.criar("res3", 42, 3, 5, "bot", 1, True)
    pid = p["id"]
    partida.iniciar(pid)
    d = armazenamento.carregar(pid)
    d["_estado"]["estoque"] = {i: 0 for i in TODOS_ITENS}
    d["_estado"]["alimento_solto"] = 12 + 3  # +3 do basal dos três agentes
    armazenamento.salvar(d)

    from decisores import bot as _bot
    from decisores.bot import Decisao

    def sempre_pescar(obs, prompt, idx):
        for v in obs["acoes_viaveis"]:
            if v["acao"] == "pescar":
                return Decisao("pescar", None, 1.0, "bot", "teste")
        return Decisao("forragear", None, 1.0, "bot", "teste")

    monkeypatch.setattr(_bot, "decidir", sempre_pescar)

    partida.executar_turno(pid)
    d = armazenamento.carregar(pid)
    h = d["historico"][-1]
    acoes = [json.loads(x["acao_json"])["acao"] for x in h["decisoes"]]
    invalidadas = [a for a in h["acoes_executadas"] if a.get("invalidada_na_execucao")]
    assert acoes.count("pescar") == 1, f"esperava 1 pesca, veio {acoes}"
    assert not invalidadas, f"nenhuma ação deveria ser invalidada: {invalidadas}"
