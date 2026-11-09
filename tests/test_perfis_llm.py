"""Testes dos perfis de LLM (config_env + endpoints), em arquivo temporário."""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

import config_env
import server


@pytest.fixture
def arquivo(tmp_path, monkeypatch):
    """Aponta o config_llm.json para um arquivo temporário (nunca toca o real)."""
    caminho = tmp_path / "config_llm.json"
    monkeypatch.setattr(config_env, "_CAMINHO_LLM", caminho)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return caminho


@pytest.fixture
def cliente(arquivo):
    return TestClient(server.app)


def _escrever(arquivo, dados):
    arquivo.write_text(json.dumps(dados), encoding="utf-8")


# ---------------------------------------------------------- normalização

def test_arquivo_ausente_traz_os_perfis_padrao(arquivo):
    d = config_env.ler_llm()
    assert d["perfil_ativo"] == "groq"
    assert {"groq", "local-llama", "local-minicpm", "claude"} <= set(d["perfis"])


def test_formato_antigo_plano_vira_um_perfil(arquivo):
    _escrever(arquivo, {"provedor": "groq", "model": "qwen/qwen3.8-27b",
                        "temperature": 0.7, "api_key_configured": True, "modo": "json"})
    d = config_env.ler_llm()
    assert list(d["perfis"]) == ["groq"] and d["perfil_ativo"] == "groq"
    assert d["perfis"]["groq"]["model"] == "qwen/qwen3.8-27b"
    assert "api_key_configured" not in d["perfis"]["groq"]      # metadado fora do perfil


def test_perfil_ativo_invalido_cai_no_primeiro(arquivo):
    _escrever(arquivo, {"perfil_ativo": "fantasma",
                        "perfis": {"a": {"provedor": "groq"}, "b": {"provedor": "openai"}}})
    assert config_env.ler_llm()["perfil_ativo"] == "a"


def test_segredo_nunca_entra_nem_sai_do_arquivo(arquivo):
    _escrever(arquivo, {"perfil_ativo": "a",
                        "perfis": {"a": {"provedor": "groq", "api_key": "gsk_vazou"}}})
    assert "api_key" not in config_env.ler_llm()["perfis"]["a"]
    config_env.atualizar_perfil("a", {"api_key": "gsk_vazou", "model": "m"})
    assert "gsk_vazou" not in arquivo.read_text(encoding="utf-8")


# ---------------------------------------------------------- config efetiva

def test_config_llm_usa_o_perfil_ativo_e_a_chave_do_provedor(arquivo, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_groq")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave_ant")
    _escrever(arquivo, {"perfil_ativo": "claude", "perfis": {
        "groq": {"provedor": "groq", "model": "m1"},
        "claude": {"provedor": "anthropic", "model": "claude-haiku-4-5-20251001"}}})
    cfg = config_env.config_llm()
    assert cfg["perfil"] == "claude" and cfg["provedor"] == "anthropic"
    assert cfg["api_key"] == "chave_ant"
    config_env.ativar_perfil("groq")
    assert config_env.config_llm()["api_key"] == "gsk_groq"


def test_campos_avancados_e_padroes(arquivo):
    _escrever(arquivo, {"perfil_ativo": "x", "perfis": {"x": {
        "provedor": "openai", "base_url": "http://localhost:11434/v1",
        "timeout_s": 300, "reasoning_effort": "none", "tpm_limite": 5400}}})
    cfg = config_env.config_llm()
    assert (cfg["timeout_s"], cfg["reasoning_effort"], cfg["tpm_limite"]) == (300.0, "none", 5400)
    _escrever(arquivo, {"perfil_ativo": "x", "perfis": {"x": {"provedor": "groq"}}})
    cfg = config_env.config_llm()
    assert (cfg["timeout_s"], cfg["max_tokens"], cfg["tpm_limite"]) == (30.0, 400, 0)
    assert cfg["reasoning_effort"] is None


def test_temperatura_zero_e_respeitada(arquivo):
    """Antes `or 0.7` transformava temperature=0 em 0.7."""
    _escrever(arquivo, {"perfil_ativo": "x", "perfis": {"x": {"provedor": "groq", "temperature": 0}}})
    assert config_env.config_llm()["temperature"] == 0.0


# ---------------------------------------------------------- operações

def test_criar_perfil_copia_o_ativo_e_o_ativa(arquivo):
    _escrever(arquivo, {"perfil_ativo": "a", "perfis": {"a": {"provedor": "groq", "model": "m"}}})
    config_env.criar_perfil("meu teste")
    d = config_env.ler_llm()
    assert d["perfil_ativo"] == "meu teste"
    assert d["perfis"]["meu teste"] == d["perfis"]["a"]


@pytest.mark.parametrize("nome", ["", "   ", "a/b", "x" * 41, "a;b"])
def test_nome_invalido_e_rejeitado(arquivo, nome):
    with pytest.raises(config_env.PerfilInvalido):
        config_env.criar_perfil(nome)


def test_nome_duplicado_e_rejeitado(arquivo):
    _escrever(arquivo, {"perfil_ativo": "a", "perfis": {"a": {"provedor": "groq"}}})
    with pytest.raises(config_env.PerfilInvalido):
        config_env.criar_perfil("a")


def test_excluir_ativo_passa_para_outro_e_nao_apaga_o_ultimo(arquivo):
    _escrever(arquivo, {"perfil_ativo": "a", "perfis": {
        "a": {"provedor": "groq"}, "b": {"provedor": "openai"}}})
    config_env.excluir_perfil("a")
    assert config_env.ler_llm()["perfil_ativo"] == "b"
    with pytest.raises(config_env.PerfilInvalido):
        config_env.excluir_perfil("b")


def test_atualizar_com_valor_vazio_remove_o_campo(arquivo):
    _escrever(arquivo, {"perfil_ativo": "a", "perfis": {"a": {
        "provedor": "openai", "reasoning_effort": "none", "timeout_s": 300}}})
    config_env.atualizar_perfil("a", {"reasoning_effort": "", "timeout_s": None, "model": "m"})
    assert config_env.ler_llm()["perfis"]["a"] == {"provedor": "openai", "model": "m"}


def test_ativar_inexistente_falha(arquivo):
    with pytest.raises(config_env.PerfilInvalido):
        config_env.ativar_perfil("nao-existe")


# ---------------------------------------------------------- endpoints

def test_get_devolve_perfil_ativo_plano_e_lista_de_perfis(cliente, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_secreta")
    r = cliente.get("/config/llm").json()
    assert r["perfil_ativo"] == "groq" and r["provedor"] == "groq"
    assert {p["nome"] for p in r["perfis"]} >= {"groq", "claude"}
    assert r["api_key_configured"] is True
    assert "gsk_secreta" not in json.dumps(r) and "api_key" not in r


def test_put_altera_so_o_perfil_ativo(cliente):
    cliente.post("/config/llm/perfil-ativo", json={"nome": "local-llama"})
    cliente.put("/config/llm", json={"model": "llama3.2:1b", "timeout_s": 120})
    d = config_env.ler_llm()["perfis"]
    assert d["local-llama"]["model"] == "llama3.2:1b" and d["local-llama"]["timeout_s"] == 120
    assert d["groq"]["model"] == config_env.PERFIS_PADRAO["groq"]["model"]   # intacto


def test_trocar_de_perfil_muda_a_config_do_runner(cliente, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    cliente.post("/config/llm/perfil-ativo", json={"nome": "claude"})
    assert config_env.config_llm()["provedor"] == "anthropic"
    cliente.post("/config/llm/perfil-ativo", json={"nome": "local-minicpm"})
    cfg = config_env.config_llm()
    assert cfg["base_url"].endswith("11434/v1") and cfg["reasoning_effort"] == "none"


def test_criar_e_excluir_pela_api(cliente):
    r = cliente.post("/config/llm/perfis", json={"nome": "novo"}).json()
    assert r["perfil_ativo"] == "novo"
    assert cliente.post("/config/llm/perfis", json={"nome": "novo"}).status_code == 400
    r = cliente.delete("/config/llm/perfis/novo").json()
    assert "novo" not in [p["nome"] for p in r["perfis"]]
    assert cliente.delete("/config/llm/perfis/nao-existe").status_code == 400


def test_ativar_perfil_inexistente_da_400(cliente):
    resp = cliente.post("/config/llm/perfil-ativo", json={"nome": "fantasma"})
    assert resp.status_code == 400 and "inexistente" in resp.json()["detail"]


# ------------------------------------------------- "Testar conexão" local

class _Resp:
    status_code = 200
    def json(self): return {"choices": [{"message": {"content": "OK"}}]}


def _fake_httpx(monkeypatch, capturado):
    class Cliente:
        def __init__(self, timeout=None): capturado["timeout"] = timeout
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, headers=None, json=None):
            capturado.update(url=url, headers=headers, json=json)
            return _Resp()
    monkeypatch.setattr(httpx, "Client", Cliente)


def test_testar_servidor_local_nao_exige_chave_e_respeita_timeout(cliente, monkeypatch):
    cap = {}
    _fake_httpx(monkeypatch, cap)
    r = cliente.post("/config/llm/testar", json={
        "provedor": "openai", "base_url": "http://localhost:11434/v1",
        "model": "llama3.2", "timeout_s": 300, "reasoning_effort": "none"}).json()
    assert r["ok"] is True, r
    assert cap["timeout"] == 300
    assert cap["json"]["reasoning_effort"] == "none"
    assert cap["headers"]["Authorization"] == "Bearer local"      # nunca uma chave real


def test_testar_remoto_sem_chave_continua_falhando(cliente):
    r = cliente.post("/config/llm/testar", json={"provedor": "openai",
                     "base_url": "https://api.exemplo.com/v1"}).json()
    assert r["ok"] is False and "API key" in r["erro"]
