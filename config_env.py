"""Carregamento centralizado de configuração.

Divisão de responsabilidades (opção B):
- SEGREDO (API key) vem do `.env` (fora do versionamento). É o único dado
  sensível; não fica nos JSONs.
- CONFIG NÃO-SENSÍVEL (provedor, modelo, temperatura, base_url, URL do Laya,
  timeout, threshold) vem dos JSONs (`config_llm.json`, `config_lbm.json`),
  que são editáveis pela UI de Configuração.

Assim a UI e o runtime concordam: ambos usam os JSONs para config editável, e o
segredo vive só no `.env`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except Exception:
    # Sem python-dotenv ou sem .env: segue só com o ambiente.
    pass

ROOT = Path(__file__).parent
_CAMINHO_LLM = ROOT / "config_llm.json"
_CAMINHO_LBM = ROOT / "config_lbm.json"


def _json(caminho: Path) -> dict:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return {}


def api_key() -> str | None:
    """A API key do provedor LLM — SOMENTE do ambiente (.env)."""
    return os.environ.get("GROQ_API_KEY")


def config_llm() -> dict:
    """Config do provedor LLM: dados do JSON + a api_key do .env."""
    j = _json(_CAMINHO_LLM)
    return {
        "provedor": j.get("provedor") or "groq",
        "model": j.get("model"),
        "base_url": j.get("base_url") or "",
        "temperature": float(j.get("temperature") or 0.7),
        "api_key": api_key(),  # segredo vem só do .env
    }


def config_laya() -> dict:
    """Config do Laya: tudo do JSON (não-sensível)."""
    j = _json(_CAMINHO_LBM)
    return {
        "url": j.get("url") or "http://localhost:8001/v1/systemone",
        "timeout_s": float(j.get("timeout_s") or 10.0),
        "threshold": float(j.get("threshold") or 0.5),
    }
