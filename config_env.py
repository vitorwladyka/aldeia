"""Carregamento centralizado de configuração.

Divisão de responsabilidades (opção B):
- SEGREDO (API key) vem do `.env` (fora do versionamento). É o único dado
  sensível; não fica nos JSONs.
- CONFIG NÃO-SENSÍVEL (provedor, modelo, temperatura, base_url, URL do Laya,
  timeout, threshold) vem dos JSONs (`config_llm.json`, `config_lbm.json`),
  que são editáveis pela UI de Configuração.

Assim a UI e o runtime concordam: ambos usam os JSONs para config editável, e o
segredo vive só no `.env`.

PERFIS DE LLM: o `config_llm.json` guarda vários perfis nomeados (ex.: groq,
local-llama, claude) e qual está ativo. Trocar de provedor é trocar o perfil
ativo; o resto do sistema só enxerga `config_llm()` (o perfil ativo + a chave).
O formato antigo (um único bloco plano) continua sendo lido como um perfil só.
"""
from __future__ import annotations

import copy
import json
import os
import re
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


# Variável de ambiente da chave de cada provedor. Os demais (groq, openai-compat)
# usam GROQ_API_KEY, como sempre.
_VARIAVEL_CHAVE = {"anthropic": "ANTHROPIC_API_KEY"}


def api_key(provedor: str | None = None) -> str | None:
    """A API key do provedor LLM — SOMENTE do ambiente (.env).

    `provedor` escolhe a variável: anthropic → ANTHROPIC_API_KEY; qualquer outro
    (ou None) → GROQ_API_KEY.
    """
    nome = _VARIAVEL_CHAVE.get((provedor or "").lower(), "GROQ_API_KEY")
    return os.environ.get(nome)


# --------------------------------------------------------------------------
# Perfis de LLM
# --------------------------------------------------------------------------

# Perfis oferecidos quando ainda não há config_llm.json (clone novo).
PERFIS_PADRAO = {
    "groq": {"provedor": "groq", "model": "llama-3.3-70b-versatile",
             "temperature": 0.7},
    "local-llama": {"provedor": "openai", "base_url": "http://localhost:11434/v1",
                    "model": "llama3.2", "temperature": 0.5, "timeout_s": 300},
    "local-minicpm": {"provedor": "openai", "base_url": "http://localhost:11434/v1",
                      "model": "hf.co/openbmb/MiniCPM5-2B-GGUF:Q4_K_M",
                      "temperature": 0.3, "timeout_s": 300,
                      "reasoning_effort": "none"},
    "claude": {"provedor": "anthropic", "model": "claude-haiku-4-5-20251001",
               "temperature": 0.7},
}

# Chaves que nunca pertencem a um perfil (segredo ou metadado do arquivo).
_FORA_DO_PERFIL = {"api_key", "api_key_configured", "perfis", "perfil_ativo", "perfil"}
_NOME_PERFIL = re.compile(r"^[\w.\- ]{1,40}$")


class PerfilInvalido(ValueError):
    """Nome inexistente/duplicado/inválido, ou operação não permitida."""


def _limpar_perfil(dados: dict) -> dict:
    """Só os campos de configuração: sem segredos, metadados ou valores vazios."""
    return {k: v for k, v in dados.items()
            if k not in _FORA_DO_PERFIL and v is not None and v != ""}


def normalizar_llm(j: dict) -> dict:
    """Converte qualquer formato do arquivo em {"perfil_ativo", "perfis"}.

    - Já com `perfis`: usa como está.
    - Formato antigo (bloco plano): vira um único perfil, nomeado pelo provedor.
    - Vazio/ausente: perfis padrão.
    """
    perfis = j.get("perfis")
    if isinstance(perfis, dict) and perfis:
        perfis = {n: _limpar_perfil(p) for n, p in perfis.items() if isinstance(p, dict)}
    else:
        plano = _limpar_perfil(j)
        perfis = ({plano.get("provedor") or "groq": plano} if plano
                  else copy.deepcopy(PERFIS_PADRAO))
    ativo = j.get("perfil_ativo")
    if ativo not in perfis:
        ativo = next(iter(perfis))
    return {"perfil_ativo": ativo, "perfis": perfis}


def ler_llm() -> dict:
    """Perfis do config_llm.json, já normalizados."""
    return normalizar_llm(_json(_CAMINHO_LLM))


def salvar_llm(dados: dict) -> None:
    """Grava {"perfil_ativo", "perfis"} no config_llm.json (nunca guarda segredos)."""
    saida = {"perfil_ativo": dados["perfil_ativo"],
             "perfis": {n: _limpar_perfil(p) for n, p in dados["perfis"].items()}}
    _CAMINHO_LLM.write_text(json.dumps(saida, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")


def ativar_perfil(nome: str) -> None:
    dados = ler_llm()
    if nome not in dados["perfis"]:
        raise PerfilInvalido(f"perfil inexistente: {nome!r}")
    dados["perfil_ativo"] = nome
    salvar_llm(dados)


def atualizar_perfil(nome: str, campos: dict) -> None:
    """Atualiza campos de um perfil. Valor vazio/None REMOVE o campo (limpa)."""
    dados = ler_llm()
    if nome not in dados["perfis"]:
        raise PerfilInvalido(f"perfil inexistente: {nome!r}")
    perfil = dados["perfis"][nome]
    for chave, valor in campos.items():
        if chave in _FORA_DO_PERFIL:
            continue
        if valor is None or valor == "":
            perfil.pop(chave, None)
        else:
            perfil[chave] = valor
    salvar_llm(dados)


def criar_perfil(nome: str, copiar_de: str | None = None) -> None:
    """Cria um perfil (cópia do `copiar_de` ou do ativo) e o torna o ativo."""
    nome = (nome or "").strip()
    if not _NOME_PERFIL.match(nome):
        raise PerfilInvalido("nome inválido: use 1-40 letras, números, espaço, ponto, - ou _")
    dados = ler_llm()
    if nome in dados["perfis"]:
        raise PerfilInvalido(f"já existe um perfil chamado {nome!r}")
    origem = copiar_de or dados["perfil_ativo"]
    if origem not in dados["perfis"]:
        raise PerfilInvalido(f"perfil de origem inexistente: {origem!r}")
    dados["perfis"][nome] = copy.deepcopy(dados["perfis"][origem])
    dados["perfil_ativo"] = nome
    salvar_llm(dados)


def excluir_perfil(nome: str) -> None:
    dados = ler_llm()
    if nome not in dados["perfis"]:
        raise PerfilInvalido(f"perfil inexistente: {nome!r}")
    if len(dados["perfis"]) == 1:
        raise PerfilInvalido("não é possível excluir o único perfil")
    del dados["perfis"][nome]
    if dados["perfil_ativo"] == nome:
        dados["perfil_ativo"] = next(iter(dados["perfis"]))
    salvar_llm(dados)


def _valor(perfil: dict, chave: str, padrao):
    v = perfil.get(chave)
    return padrao if v is None or v == "" else v


def config_llm() -> dict:
    """Config do LLM = perfil ATIVO + a api_key do .env (segredo nunca no JSON)."""
    dados = ler_llm()
    perfil = dados["perfis"][dados["perfil_ativo"]]
    provedor = _valor(perfil, "provedor", "groq")
    return {
        "perfil": dados["perfil_ativo"],
        "provedor": provedor,
        "model": perfil.get("model"),
        "base_url": perfil.get("base_url") or "",
        "temperature": float(_valor(perfil, "temperature", 0.7)),
        # Tokens/minuto que o provedor aceita (0 = sem limitador). Ver agentes/limitador.
        "tpm_limite": int(_valor(perfil, "tpm_limite", 0)),
        # Ajustes para modelos lentos/locais (opcionais):
        "timeout_s": float(_valor(perfil, "timeout_s", 30.0)),   # espera por resposta
        "max_tokens": int(_valor(perfil, "max_tokens", 400)),    # limite de saída
        # "none" desliga o "thinking" (ex.: MiniCPM no Ollama); vazio = não envia
        "reasoning_effort": perfil.get("reasoning_effort") or None,
        "api_key": api_key(provedor),  # segredo vem só do .env
    }


def config_laya() -> dict:
    """Config do Laya: tudo do JSON (não-sensível)."""
    j = _json(_CAMINHO_LBM)
    return {
        "url": j.get("url") or "http://localhost:8001/v1/systemone",
        "timeout_s": float(j.get("timeout_s") or 10.0),
        "threshold": float(j.get("threshold") or 0.5),
    }
