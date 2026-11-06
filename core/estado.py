"""Estado imutável do jogo: estoque, agentes, vidas.

Usado pelo motor em memória. Não há mutação direta — sempre via funções do motor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .preset import TODOS_ITENS, ITENS_ALIMENTARES


@dataclass
class Agente:
    indice: int
    nome: str
    vida: int
    vivo: bool = True
    morto_em_turno: int | None = None

    def clone(self) -> "Agente":
        return Agente(self.indice, self.nome, self.vida, self.vivo, self.morto_em_turno)


@dataclass
class Estado:
    """Estado congelável do turno (mutado apenas durante a execução em memória)."""

    turno: int
    estacao: Literal["normal", "inverno"]
    tempestade: bool
    fartura: bool
    doenca_alvos: list[int]
    praga: dict | None  # {"recurso": str, "perdido": int} ou None
    ordem_turno: list[int]
    estoque: dict[str, int] = field(default_factory=dict)
    alimento_solto: int = 0
    agentes: list[Agente] = field(default_factory=list)
    # Resultados do turno (preenchidos durante a execução)
    movimentos: list[dict] = field(default_factory=list)
    eventos_vida: list[dict] = field(default_factory=list)
    acoes_executadas: list[dict] = field(default_factory=list)

    def clone(self) -> "Estado":
        return Estado(
            turno=self.turno,
            estacao=self.estacao,
            tempestade=self.tempestade,
            fartura=self.fartura,
            doenca_alvos=list(self.doenca_alvos),
            praga=dict(self.praga) if self.praga else None,
            ordem_turno=list(self.ordem_turno),
            estoque=dict(self.estoque),
            alimento_solto=self.alimento_solto,
            agentes=[a.clone() for a in self.agentes],
            movimentos=[dict(m) for m in self.movimentos],
            eventos_vida=[dict(e) for e in self.eventos_vida],
            acoes_executadas=[dict(a) for a in self.acoes_executadas],
        )

    def agente(self, indice: int) -> Agente:
        return next(a for a in self.agentes if a.indice == indice)

    @property
    def vivos(self) -> list[int]:
        return [a.indice for a in self.agentes if a.vivo]

    def disponivel(self, preset) -> int:
        """Soma de alimento_solto + valor(item) * qtd para itens alimentares."""
        d = self.alimento_solto
        for item in ITENS_ALIMENTARES:
            d += preset.valor_alimentar(item) * self.estoque.get(item, 0)
        return d
