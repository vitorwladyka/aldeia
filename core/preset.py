"""Carregamento e hashing do preset.

Regras:
- Apenas inteiros, strings, listas e objetos. SEM ponto flutuante.
- `preset_hash` = SHA-256 do JSON canônico do preset completo.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp_mundo.config_mcp import hash_json

CAMINHO_PRESET = Path(__file__).parent.parent / "presets" / "padrao.json"

ACOES_ORDEM = [
    "cacar", "pescar", "coletar_trigo", "coletar_erva", "coletar_madeira",
    "assar_carne", "assar_peixe", "fazer_pao", "preparar_remedio",
    "curar", "forragear", "passar",
]

CATEGORIAS = {"coletar", "transformar", "curar", "forragear", "passar"}


class Preset:
    """Preset carregado e validado."""

    def __init__(self, dados: dict) -> None:
        _recusar_floats(dados)
        self._dados = dados
        self._validar()
        self._hash = hash_json(dados)

    @classmethod
    def do_arquivo(cls, caminho: Path | str | None = None) -> "Preset":
        p = Path(caminho) if caminho else CAMINHO_PRESET
        with open(p, encoding="utf-8") as f:
            dados = json.load(f)
        return cls(dados)

    @property
    def dados(self) -> dict:
        return self._dados

    @property
    def hash(self) -> str:
        return self._hash

    # --- Atalhos ---

    @property
    def turnos(self) -> int:
        return self._dados["turnos"]

    @property
    def vida_max(self) -> int:
        return self._dados["vida_max"]

    @property
    def basal_normal(self) -> int:
        return self._dados["basal"]["normal"]

    @property
    def basal_inverno(self) -> int:
        return self._dados["basal"]["inverno"]

    @property
    def inverno_ppm(self) -> int:
        return self._dados["inverno_ppm"]

    @property
    def valores_alimentares(self) -> dict[str, int]:
        return self._dados["valores_alimentares"]

    @property
    def valores_pontuacao_nao_alimentares(self) -> dict[str, int]:
        return self._dados["valores_pontuacao_nao_alimentares"]

    @property
    def eventos_ppm(self) -> dict[str, int]:
        return self._dados["eventos_ppm"]

    @property
    def fartura_coleta_ppm(self) -> int:
        return self._dados["fartura_coleta_ppm"]

    @property
    def praga_ppm(self) -> int:
        return self._dados["praga_ppm"]

    @property
    def forragem_ppm(self) -> int:
        return self._dados["forragem_ppm"]

    @property
    def saturacao_limite(self) -> int:
        return self._dados["saturacao_limite"]

    @property
    def acoes(self) -> dict[str, dict]:
        return self._dados["acoes"]

    @property
    def estoque_inicial_ppm_por_agente(self) -> dict[str, int]:
        return self._dados["estoque_inicial_ppm_por_agente"]

    # --- Derivados ---

    def turnos_de_inverno(self, turnos_total: int | None = None) -> int:
        """(T * inverno_ppm + 999_999) // 1_000_000 (seção 5.8)."""
        t = turnos_total if turnos_total is not None else self.turnos
        return (t * self.inverno_ppm + 999_999) // 1_000_000

    def inicio_inverno(self, turnos_total: int | None = None) -> int:
        """1-indexed: turnos_total - turnos_de_inverno + 1."""
        t = turnos_total if turnos_total is not None else self.turnos
        return t - self.turnos_de_inverno(t) + 1

    def e_inverno(self, turno: int, turnos_total: int | None = None) -> bool:
        return turno >= self.inicio_inverno(turnos_total)

    def basal_do_turno(self, turno: int, turnos_total: int | None = None) -> int:
        return self.basal_inverno if self.e_inverno(turno, turnos_total) else self.basal_normal

    def valor_alimentar(self, item: str) -> int:
        return self.valores_alimentares.get(item, 0)

    def e_alimentar(self, item: str) -> bool:
        return item in self.valores_alimentares

    def valor_pontuacao(self, item: str) -> int:
        if self.e_alimentar(item):
            return self.valores_alimentares[item]
        return self.valores_pontuacao_nao_alimentares.get(item, 0)

    def valor_pontuacao_total(self, estoque: dict, alimento_solto: int) -> int:
        """Soma: alimento_solto + valor_pontuacao(item) * qtd(item) para cada item."""
        total = alimento_solto
        for item, qtd in estoque.items():
            if qtd <= 0:
                continue
            total += self.valor_pontuacao(item) * qtd
        return total

    def acao(self, acao_id: str) -> dict:
        return self._dados["acoes"][acao_id]

    def estoque_inicial(self, n_agentes: int, override: dict | None = None) -> tuple[dict, int]:
        """Calcula o estoque inicial (itens, alimento_solto) para N agentes.

        Se `override` for fornecido, usa-o diretamente (dicionário item→qtd).
        Retorna (estoque, alimento_solto), onde alimento_solto é sempre 0.
        """
        if override is not None:
            estoque = {item: 0 for item in TODOS_ITENS}
            for item, qtd in override.items():
                if item in estoque:
                    estoque[item] = int(qtd)
            return estoque, 0

        estoque = {}
        for item, ppm in self.estoque_inicial_ppm_por_agente.items():
            estoque[item] = (n_agentes * ppm + 999_999) // 1_000_000
        # Garante que todos os itens aparecem (com 0 se não mencionados)
        for item in TODOS_ITENS:
            estoque.setdefault(item, 0)
        return estoque, 0

    def _validar(self) -> None:
        d = self._dados
        if d.get("preset_versao") != "1":
            raise ValueError(f"preset_versao inesperado: {d.get('preset_versao')!r}")
        for k in ("turnos", "vida_max", "basal", "inverno_ppm", "valores_alimentares",
                  "valores_pontuacao_nao_alimentares", "eventos_ppm", "fartura_coleta_ppm",
                  "praga_ppm", "forragem_ppm", "saturacao_limite",
                  "estoque_inicial_ppm_por_agente", "acoes"):
            if k not in d:
                raise ValueError(f"preset sem chave obrigatória: {k}")
        if d["vida_max"] != 3:
            raise ValueError("vida_max deve ser 3 (fixo no schema v1)")
        if not isinstance(d["basal"]["normal"], int) or not isinstance(d["basal"]["inverno"], int):
            raise ValueError("basal.normal e basal.inverno devem ser int")
        for nome, a in d["acoes"].items():
            if nome not in ACOES_ORDEM:
                raise ValueError(f"ação desconhecida no preset: {nome!r}")
            if a["categoria"] not in CATEGORIAS:
                raise ValueError(f"categoria inválida em {nome}: {a['categoria']!r}")
            if not isinstance(a["custo"], int):
                raise ValueError(f"custo deve ser int em {nome}")
            if not isinstance(a["acidente_ppm"], int):
                raise ValueError(f"acidente_ppm deve ser int em {nome}")


# Itens do jogo (seção 5.1)
TODOS_ITENS = ["trigo", "peixe", "carne", "pao", "peixe_assado", "carne_assada",
               "madeira", "erva", "remedio"]

ITENS_ALIMENTARES = ["peixe", "carne", "pao", "peixe_assado", "carne_assada"]


def _recusar_floats(obj: Any) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, float):
                raise ValueError(f"chave float proibida: {k!r}")
            _recusar_floats(v)
    elif isinstance(obj, list):
        for v in obj:
            _recusar_floats(v)
    elif isinstance(obj, float):
        raise ValueError(f"float proibido no preset: {obj!r}")
