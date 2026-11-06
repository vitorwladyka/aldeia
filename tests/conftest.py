"""Configuração compartilhada dos testes.

- `data_isolado` (autouse): redireciona a persistência (`armazenamento.DIRETORIO`)
  para um diretório temporário, garantindo que NENHUM teste toque em `data/`
  real (lição aprendida: o reuso de ids sobrescrevia partidas do usuário).
- `sem_rede` helpers: os testes que exercitam o decisor LLM mockam a chamada ao
  Strands/Laya, então a suíte roda offline e determinística.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

# Garante que a raiz do projeto está no sys.path (para importar partida, etc.).
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def data_isolado(tmp_path, monkeypatch):
    """Redireciona armazenamento.DIRETORIO para um tmp dir por teste."""
    import armazenamento
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(armazenamento, "DIRETORIO", d)
    yield d


@pytest.fixture
def preset():
    from core.preset import Preset
    return Preset.do_arquivo()
