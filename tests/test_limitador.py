"""Testes do limitador de tokens por minuto (relógio falso: sem esperar de verdade)."""
from __future__ import annotations

from agentes import strands_runner
from agentes.limitador import LimitadorTpm
from tests.test_runner import ModeloFalso, VIAVEIS


class Relogio:
    """Relógio controlável: `dormir` avança o tempo em vez de bloquear."""

    def __init__(self):
        self.t = 1000.0
        self.dormidas: list[float] = []

    def agora(self):
        return self.t

    def dormir(self, s):
        self.dormidas.append(s)
        self.t += s


def _limitador():
    r = Relogio()
    return LimitadorTpm(relogio=r.agora, dormir=r.dormir), r


def test_desligado_nao_espera():
    lim, r = _limitador()
    assert lim.esperar(10_000, 0) == 0.0
    assert r.dormidas == []


def test_dentro_do_limite_nao_espera():
    lim, r = _limitador()
    assert lim.esperar(2000, 6000) == 0.0
    assert lim.esperar(2000, 6000) == 0.0
    assert lim.esperar(2000, 6000) == 0.0       # 6000 = limite exato, ainda cabe
    assert r.dormidas == []


def test_estourando_espera_a_janela_liberar():
    lim, r = _limitador()
    lim.esperar(4000, 6000)                      # t=1000
    r.t += 10                                    # 10 s depois...
    esperou = lim.esperar(4000, 6000)            # 8000 > 6000 → precisa esperar
    assert abs(esperou - 50.0) < 0.5             # a 1ª chamada sai da janela em t=1060
    assert r.t >= 1060


def test_janela_expirada_libera_sem_esperar():
    lim, r = _limitador()
    lim.esperar(6000, 6000)
    r.t += 61                                    # passou a janela inteira
    assert lim.esperar(6000, 6000) == 0.0


def test_chamada_maior_que_o_limite_passa_quando_janela_vazia():
    lim, r = _limitador()
    assert lim.esperar(9000, 6000) == 0.0        # não pode travar para sempre
    assert r.dormidas == []


def test_runner_espera_antes_de_chamar_o_llm(monkeypatch, capsys):
    """Duas decisões seguidas acima do TPM: a 2ª aguarda e avisa no log."""
    lim, r = _limitador()
    monkeypatch.setattr(strands_runner, "_limitador", lim)
    monkeypatch.setattr(strands_runner, "_carregar_config", lambda: {"tpm_limite": 3000})
    modelo = ModeloFalso()
    monkeypatch.setattr(strands_runner, "_criar_modelo", lambda cfg: modelo)

    grande = "x" * 8000                          # ≈ 2000 tokens só no prompt
    strands_runner.decidir_via_strands("sys", ["pescar"], grande, VIAVEIS)
    assert r.dormidas == []                      # 1ª cabe
    modelo.chamadas = 0                          # reaproveita o modelo falso
    strands_runner.decidir_via_strands("sys", ["pescar"], grande, VIAVEIS)
    assert sum(r.dormidas) > 0                   # 2ª precisou esperar
    assert "aguardou" in capsys.readouterr().out
