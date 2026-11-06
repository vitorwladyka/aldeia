"""Cliente do MCP "mundo".

Define a interface `MundoProtocol` que tanto o MCP real (FastMCP client)
quanto um MCP falso em memória (para testes) implementam. O core depende
só desta interface, não do protocolo FastMCP.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Protocol

from mcp_mundo.config_mcp import carregar_config, config_hash, info as _info
from mcp_mundo.sorteio import escolher_lista, u_lt


RECURSOS_VALIDOS = {"trigo", "peixe", "carne", "erva", "madeira"}
PRODUTOS_VALIDOS = {"pao", "peixe_assado", "carne_assada", "remedio"}
SEED_MAX = (1 << 64) - 1


class MundoProtocol(Protocol):
    """Interface comum entre o MCP real e o MCP falso em memória."""

    async def info(self) -> dict: ...

    async def coletar(self, recurso: str, seed: int) -> dict: ...

    async def transformar(self, produto: str, seed: int) -> dict: ...

    async def ac_id(self) -> str:
        """Identificador do mundo (ex.: config_hash)."""
        ...


def _validar_seed(seed: int) -> None:
    if isinstance(seed, bool):
        raise ValueError("seed não pode ser booleano")
    if not isinstance(seed, int):
        raise ValueError(f"seed deve ser inteiro (recebi {type(seed).__name__})")
    if seed < 0 or seed > SEED_MAX:
        raise ValueError(f"seed fora do domínio uint64 [0, 2^64-1]: {seed}")


class MundoMemoria(MundoProtocol):
    """MCP falso em memória com a MESMA lógica do servidor real.

    Útil para testes das fases 2 e 3 sem subir processo separado.
    """

    def __init__(self, config: dict | None = None, caminho_config: str | None = None) -> None:
        if config is None:
            self._config = carregar_config(caminho_config)
        else:
            self._config = config
        self._hash = config_hash(self._config)

    async def info(self) -> dict:
        return _info()

    async def coletar(self, recurso: str, seed: int) -> dict:
        if recurso not in RECURSOS_VALIDOS:
            raise ValueError(f"recurso desconhecido: {recurso!r}")
        _validar_seed(seed)
        lista_nome = "madeira" if recurso == "madeira" else "padrao"
        lista = self._config["coleta"][lista_nome]
        return {"recurso": recurso, "unidades": escolher_lista(seed, lista)}

    async def transformar(self, produto: str, seed: int) -> dict:
        if produto not in PRODUTOS_VALIDOS:
            raise ValueError(f"produto desconhecido: {produto!r}")
        _validar_seed(seed)
        sucesso = u_lt(seed, self._config["transformacao"]["sucesso_ppm"])
        return {"produto": produto, "sucesso": sucesso, "unidades": 1 if sucesso else 0}

    async def ac_id(self) -> str:
        return self._hash


class MundoHTTP(MundoProtocol):
    """Cliente HTTP do MCP real via FastMCP.

    Usado em fases posteriores quando o servidor MCP roda como processo
    separado. Para fases 1-3 usamos `MundoMemoria`.
    """

    def __init__(self, url: str, timeout_s: float = 5.0) -> None:
        # Import preguiçoso: fastmcp.Client pode não estar disponível em testes.
        self._url = url
        self._timeout_s = timeout_s
        self._client = None

    async def _ensure_client(self) -> Any:
        if self._client is None:
            from fastmcp import Client  # type: ignore

            self._client = Client(self._url, timeout=self._timeout_s)
        return self._client

    async def info(self) -> dict:
        c = await self._ensure_client()
        async with c:
            return await c.call_tool("info", {})

    async def coletar(self, recurso: str, seed: int) -> dict:
        c = await self._ensure_client()
        async with c:
            return await c.call_tool("coletar", {"recurso": recurso, "seed": seed})

    async def transformar(self, produto: str, seed: int) -> dict:
        c = await self._ensure_client()
        async with c:
            return await c.call_tool("transformar", {"produto": produto, "seed": seed})

    async def ac_id(self) -> str:
        info_dict = await self.info()
        return info_dict.get("config_hash", "")
