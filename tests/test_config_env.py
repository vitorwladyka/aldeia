"""Testes do carregamento de config (opção B: segredo no .env, resto no JSON)."""
from __future__ import annotations

import config_env


def test_api_key_vem_do_ambiente(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_teste_123")
    assert config_env.api_key() == "gsk_teste_123"


def test_api_key_ausente(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert config_env.api_key() is None


def test_config_llm_junta_json_e_env(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_xyz")
    cfg = config_env.config_llm()
    # a api_key vem do env; os demais campos vêm do JSON (ou default)
    assert cfg["api_key"] == "gsk_xyz"
    assert cfg["provedor"] in ("groq", "openai", "bedrock")
    assert "temperature" in cfg


def test_config_laya_tem_campos(monkeypatch):
    c = config_env.config_laya()
    assert "url" in c and "timeout_s" in c and "threshold" in c
    assert isinstance(c["timeout_s"], float)
    assert isinstance(c["threshold"], float)


def test_api_key_anthropic_usa_a_propria_variavel(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_groq")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-anthropic")
    assert config_env.api_key("anthropic") == "chave-anthropic"
    assert config_env.api_key("groq") == "gsk_groq"
    assert config_env.api_key() == "gsk_groq"            # padrão = Groq
    assert config_env.api_key("openai") == "gsk_groq"    # compat. como antes


def test_api_key_anthropic_ausente(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_groq")
    assert config_env.api_key("anthropic") is None       # não cai na chave da Groq
