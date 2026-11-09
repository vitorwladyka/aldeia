"""Limitador de tokens por minuto (janela deslizante) para chamadas ao LLM.

Provedores gratuitos limitam tokens por minuto (TPM). Disparar as chamadas do
conselho em rajada estoura o limite (429) e cai no fallback. O limitador, em vez
disso, ESPERA até a chamada caber na janela de 60 s — o turno fica mais lento,
mas as decisões vêm do LLM.

Os tokens são estimados (caracteres / 4); o provedor pode contar um pouco
diferente, então convém configurar um limite ~10% abaixo do real.
"""
from __future__ import annotations

import threading
import time
from collections import deque


class LimitadorTpm:
    JANELA_S = 60.0

    def __init__(self, relogio=time.monotonic, dormir=time.sleep):
        # relógio e sleep injetáveis para testar sem esperar de verdade
        self._relogio = relogio
        self._dormir = dormir
        self._usos: deque[tuple[float, int]] = deque()   # (instante, tokens)
        self._lock = threading.Lock()

    def _descartar_expirados(self, agora: float) -> None:
        while self._usos and agora - self._usos[0][0] >= self.JANELA_S:
            self._usos.popleft()

    def esperar(self, tokens: int, limite: int) -> float:
        """Bloqueia até `tokens` caberem em `limite`/min e registra o uso.

        Devolve quantos segundos esperou. `limite <= 0` desliga o limitador. Uma
        chamada maior que o limite inteiro passa quando a janela está vazia
        (senão esperaria para sempre).
        """
        if limite <= 0:
            return 0.0
        esperado = 0.0
        while True:
            with self._lock:
                agora = self._relogio()
                self._descartar_expirados(agora)
                usado = sum(t for _, t in self._usos)
                if usado + tokens <= limite or not self._usos:
                    self._usos.append((agora, tokens))
                    return esperado
                # espera o registro mais antigo sair da janela
                espera = self.JANELA_S - (agora - self._usos[0][0])
            espera = max(espera, 0.05)
            self._dormir(espera)      # fora do lock: outras threads não travam
            esperado += espera
