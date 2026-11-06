"""Configuração do mundo MCP.

A config é um JSON com chaves:
- `mundo_versao`: "1"
- `coleta`: {"padrao": [int], "madeira": [int]} — listas de unidades
   retornadas por `coletar`, indexadas por `escolher_lista(seed, lista)`.
- `transformacao`: {"sucesso_ppm": int} — ppm de sucesso de transformar.

`hash_json` devolve o SHA-256 do JSON canônico (sort_keys=True,
separators=(",", ":"), ensure_ascii=False). O mesmo objeto → mesmo hash.

`config_hash` aplica `hash_json` na config do mundo.

`info()` devolve um dict estável com a versão do mundo e o config_hash
para os clientes conferirem.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

CAMINHO_CONFIG = Path(__file__).parent.parent / "mcp_mundo_config.json"

_CONFIG_CACHE: dict | None = None
_HASH_CACHE: str | None = None


def hash_json(obj: Any) -> str:
    """SHA-256 do JSON canônico (chaves ordenadas, sem espaços)."""
    canon = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _config_padrao() -> dict:
    """Config padrão do mundo (usada se o arquivo não existir)."""
    return {
        "mundo_versao": "1",
        "coleta": {
            # Distribuição de unidades por coleta — indexada por (seed * len) >> 64
            "padrao": [0, 1, 1, 1, 2, 2, 3],     # trigo/erva/peixe/carne
            "madeira": [1, 1, 2, 2, 3],           # madeira (mais generoso)
        },
        "transformacao": {
            "sucesso_ppm": 850_000,  # 85% de sucesso
        },
    }


def carregar_config(caminho: str | Path | None = None) -> dict:
    """Carrega a config do mundo do disco (com cache).

    Se o arquivo não existir, usa a config padrão e a persiste.
    """
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None and caminho is None:
        return _CONFIG_CACHE

    p = Path(caminho) if caminho else CAMINHO_CONFIG
    if not p.exists():
        cfg = _config_padrao()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
        _validar_config(cfg)

    if caminho is None:
        _CONFIG_CACHE = cfg
    return cfg


def _validar_config(cfg: dict) -> None:
    if cfg.get("mundo_versao") != "1":
        raise ValueError(f"mundo_versao inesperado: {cfg.get('mundo_versao')!r}")
    if "coleta" not in cfg or "padrao" not in cfg["coleta"] or "madeira" not in cfg["coleta"]:
        raise ValueError("config sem coleta.{padrao,madeira}")
    if "transformacao" not in cfg or "sucesso_ppm" not in cfg["transformacao"]:
        raise ValueError("config sem transformacao.sucesso_ppm")
    for k in ("padrao", "madeira"):
        if not isinstance(cfg["coleta"][k], list) or not cfg["coleta"][k]:
            raise ValueError(f"coleta.{k} deve ser lista não-vazia")
        if not all(isinstance(x, int) and x >= 0 for x in cfg["coleta"][k]):
            raise ValueError(f"coleta.{k} deve conter apenas inteiros >= 0")
    if not isinstance(cfg["transformacao"]["sucesso_ppm"], int):
        raise ValueError("transformacao.sucesso_ppm deve ser int")


def config_hash(cfg: dict | None = None) -> str:
    """SHA-256 do JSON canônico da config do mundo."""
    global _HASH_CACHE
    if cfg is None:
        if _HASH_CACHE is None:
            _HASH_CACHE = hash_json(carregar_config())
        return _HASH_CACHE
    return hash_json(cfg)


def info() -> dict:
    """Info estável do mundo (versão + config_hash)."""
    return {
        "mundo_versao": "1",
        "config_hash": config_hash(),
    }


def salvar_config(cfg: dict, caminho: str | Path | None = None) -> None:
    """Salva uma nova config no disco e invalida os caches."""
    global _CONFIG_CACHE, _HASH_CACHE
    _validar_config(cfg)
    p = Path(caminho) if caminho else CAMINHO_CONFIG
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    _CONFIG_CACHE = None
    _HASH_CACHE = None
