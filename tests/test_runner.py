"""Testes do runner do Strands com um modelo falso (sem rede).

O modelo falso emite uma chamada de tool e, se for invocado de novo, um texto
final. Contar as invocações mostra quantas chamadas ao LLM cada decisão custa.
"""
from __future__ import annotations

import json

import pytest
from strands.models import Model

from agentes import strands_runner

VIAVEIS = [{"acao": "pescar", "alvos": None}, {"acao": "forragear", "alvos": None}]


class ModeloFalso(Model):
    """Primeira invocação: chama a tool. Invocações seguintes: texto final."""

    def __init__(self, acao="pescar", args=None):
        self.chamadas = 0
        self.acao = acao
        self.args = args if args is not None else {"mensagem": "vou pescar"}

    def update_config(self, **kwargs):
        pass

    def get_config(self):
        return {}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError
        yield  # pragma: no cover  (torna a função um gerador assíncrono)

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.chamadas += 1
        yield {"messageStart": {"role": "assistant"}}
        if self.chamadas == 1:
            yield {"contentBlockStart": {"start": {"toolUse": {
                "name": self.acao, "toolUseId": "t1"}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {
                "input": json.dumps(self.args)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": "pronto"}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {"metadata": {"usage": {"inputTokens": 1, "outputTokens": 1,
                                      "totalTokens": 2},
                            "metrics": {"latencyMs": 1}}}


@pytest.fixture
def modelo(monkeypatch):
    m = ModeloFalso()
    monkeypatch.setattr(strands_runner, "_criar_modelo", lambda cfg: m)
    return m


def test_decisao_usa_uma_unica_chamada_ao_modelo(modelo):
    """Escolhida a tool, o loop encerra: sem 2ª chamada só para gerar texto final."""
    r = strands_runner.decidir_via_strands("sys", ["pescar", "forragear"], "obs", VIAVEIS)
    assert r["acao"] == "pescar"
    assert r["mensagem"] == "vou pescar"
    assert modelo.chamadas == 1, f"esperava 1 chamada ao modelo, houve {modelo.chamadas}"


def test_sem_tool_chamada_devolve_none(monkeypatch):
    """Modelo que só responde texto (sem escolher ação) → None (o chamador faz fallback)."""
    class SoTexto(ModeloFalso):
        async def stream(self, messages, tool_specs=None, system_prompt=None, **kw):
            self.chamadas += 1
            yield {"messageStart": {"role": "assistant"}}
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": "não sei"}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
            yield {"metadata": {"usage": {"inputTokens": 1, "outputTokens": 1,
                                          "totalTokens": 2},
                                "metrics": {"latencyMs": 1}}}

    monkeypatch.setattr(strands_runner, "_criar_modelo", lambda cfg: SoTexto())
    assert strands_runner.decidir_via_strands("sys", ["pescar"], "obs", VIAVEIS) is None


def test_limite_de_taxa_falha_rapido_e_devolve_none(monkeypatch):
    """Provedor limitando (429): poucas tentativas e None → o chamador faz fallback."""
    from strands.types.exceptions import ModelThrottledException

    class SempreLimitado(ModeloFalso):
        async def stream(self, messages, tool_specs=None, system_prompt=None, **kw):
            self.chamadas += 1
            raise ModelThrottledException("429 rate limit")
            yield  # pragma: no cover

    m = SempreLimitado()
    monkeypatch.setattr(strands_runner, "_criar_modelo", lambda cfg: m)
    monkeypatch.setattr(strands_runner, "ESPERA_INICIAL_S", 0)  # sem espera no teste
    monkeypatch.setattr(strands_runner, "ESPERA_MAXIMA_S", 0)

    assert strands_runner.decidir_via_strands("sys", ["pescar"], "obs", VIAVEIS) is None
    assert m.chamadas == strands_runner.TENTATIVAS_MODELO  # 3, e não as 6 do padrão


def test_curar_tambem_encerra_o_loop_e_leva_o_alvo(monkeypatch):
    m = ModeloFalso(acao="curar", args={"alvo": 1, "mensagem": "curo o Bento"})
    monkeypatch.setattr(strands_runner, "_criar_modelo", lambda cfg: m)
    viaveis = [{"acao": "curar", "alvos": [1]}]
    r = strands_runner.decidir_via_strands("sys", ["curar"], "obs", viaveis)
    assert r == {"acao": "curar", "alvo": 1, "mensagem": "curo o Bento"}
    assert m.chamadas == 1


# ------------------------------------------------------------ provedores

def test_modelo_anthropic_usa_cliente_nativo_sem_base_url():
    from strands.models.anthropic import AnthropicModel
    cfg = {"provedor": "anthropic", "model": "claude-haiku-4-5-20251001",
           "api_key": "chave", "temperature": 0.3,
           # base_url com /v1 quebraria (/v1/v1/messages); deve ser ignorada
           "base_url": "https://api.anthropic.com/v1"}
    m = strands_runner._criar_modelo(cfg)
    assert isinstance(m, AnthropicModel)
    assert m.get_config()["model_id"] == "claude-haiku-4-5-20251001"
    assert str(m.client.base_url).rstrip("/") == "https://api.anthropic.com"


def test_modelo_anthropic_sem_chave_levanta():
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        strands_runner._criar_modelo({"provedor": "anthropic", "api_key": None})


def test_modelo_anthropic_modelo_padrao_e_o_id_correto():
    m = strands_runner._criar_modelo({"provedor": "anthropic", "api_key": "k"})
    assert m.get_config()["model_id"] == "claude-haiku-4-5-20251001"


# ------------------------------------------- diagnóstico e custo de tokens

def test_erro_do_llm_aparece_no_log_com_cabecalhos_de_limite(monkeypatch, capsys):
    """Antes o erro era engolido; agora o log mostra a causa e o limite da conta."""
    from types import SimpleNamespace
    from strands.types.exceptions import ModelThrottledException

    class Limitado(ModeloFalso):
        async def stream(self, messages, tool_specs=None, system_prompt=None, **kw):
            self.chamadas += 1
            causa = Exception("Error code: 429")
            causa.response = SimpleNamespace(headers={
                "x-ratelimit-limit-tokens": "6000", "retry-after": "7",
                "content-type": "application/json"})
            raise ModelThrottledException("Rate limit reached: TPM Limit 6000") from causa
            yield  # pragma: no cover

    monkeypatch.setattr(strands_runner, "_criar_modelo", lambda cfg: Limitado())
    monkeypatch.setattr(strands_runner, "ESPERA_INICIAL_S", 0)
    monkeypatch.setattr(strands_runner, "ESPERA_MAXIMA_S", 0)

    assert strands_runner.decidir_via_strands("sys", ["pescar"], "obs", VIAVEIS) is None
    saida = capsys.readouterr().out
    assert "[LLM] chamada falhou" in saida
    assert "TPM Limit 6000" in saida
    assert "x-ratelimit-limit-tokens" in saida and "retry-after" in saida
    assert "content-type" not in saida          # só cabeçalhos relevantes


def test_schema_das_tools_e_enxuto():
    """O schema vai em TODA chamada; a descrição de `mensagem` tem que ser curta."""
    esc = {"acao": None, "alvo": None, "mensagem": ""}
    tools = strands_runner._fabricar_tools(["pescar", "curar", "forragear"], esc)
    for t in tools:
        desc = t.tool_spec["inputSchema"]["json"]["properties"]["mensagem"]["description"]
        assert len(desc) <= 60, f"{t.tool_name}: descrição de mensagem longa ({len(desc)})"


# ------------------------------------------- modelos locais / lentos (Ollama)

OLLAMA = {"provedor": "openai", "base_url": "http://localhost:11434/v1",
          "model": "hf.co/openbmb/MiniCPM5-2B-GGUF:Q4_K_M"}


def test_servidor_local_nao_exige_chave():
    m = strands_runner._criar_modelo({**OLLAMA, "api_key": None})
    assert m.get_config()["model_id"].startswith("hf.co/")


def test_servidor_local_nunca_recebe_a_chave_real():
    """A chave de outro provedor (ex.: Groq) não pode ir para um servidor local."""
    m = strands_runner._criar_modelo({**OLLAMA, "api_key": "gsk_chave_real_da_groq"})
    assert m.client_args["api_key"] == "local"


def test_servidor_remoto_continua_exigindo_chave():
    cfg = {"provedor": "openai", "base_url": "https://api.exemplo.com/v1", "api_key": None}
    with pytest.raises(RuntimeError, match="api_key"):
        strands_runner._criar_modelo(cfg)


def test_reasoning_effort_none_chega_aos_parametros_da_requisicao():
    """É o que impede o MiniCPM de gastar todos os tokens 'pensando'."""
    m = strands_runner._criar_modelo({**OLLAMA, "reasoning_effort": "none"})
    assert m.get_config()["params"]["reasoning_effort"] == "none"


def test_sem_reasoning_effort_o_parametro_nao_e_enviado():
    m = strands_runner._criar_modelo({**OLLAMA})
    assert "reasoning_effort" not in m.get_config()["params"]


def test_timeout_e_max_tokens_configuraveis():
    m = strands_runner._criar_modelo({**OLLAMA, "timeout_s": 300, "max_tokens": 900})
    assert m.client_args["timeout"] == 300.0
    assert m.get_config()["params"]["max_tokens"] == 900


def test_padroes_de_timeout_e_max_tokens():
    m = strands_runner._criar_modelo({**OLLAMA})
    assert m.client_args["timeout"] == strands_runner.TIMEOUT_HTTP_S
    assert m.get_config()["params"]["max_tokens"] == strands_runner.MAX_TOKENS_SAIDA


def test_groq_nao_e_tratado_como_local():
    # provedor groq tem URL fixa na nuvem; sem chave continua falhando
    with pytest.raises(RuntimeError):
        strands_runner._criar_modelo({"provedor": "groq", "api_key": None})
