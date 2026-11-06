"""Runner do Strands: cria o Agent conforme o provider e captura a decisão.

Modelo *actions-as-tools*: cada ação permitida vira uma tool do Strands. Quando
o agente chama uma tool, a chamada É a decisão (a tool grava num acumulador).
Encerramos lendo o acumulador após a execução.

Provider configurável via `config_llm.json`:
- "groq"           → OpenAIModel com base_url da Groq.
- "openai"/compat  → OpenAIModel com base_url do config.
- "bedrock"        → BedrockModel (credenciais AWS do ambiente).

Qualquer falha (sem credencial, rede, provider inválido, nenhuma tool chamada)
devolve None — o decisor LLM então aplica o fallback determinístico.
"""
from __future__ import annotations

from strands import Agent, tool

from . import catalogo
import config_env


def _carregar_config() -> dict:
    """Config do LLM a partir do .env (fallback JSON) — ver config_env."""
    return config_env.config_llm()


def _criar_modelo(cfg: dict):
    """Cria o modelo do Strands conforme o provider. Levanta se indisponível."""
    provedor = (cfg.get("provedor") or "groq").lower()

    if provedor == "bedrock":
        from strands.models.bedrock import BedrockModel
        model_id = cfg.get("model") or "anthropic.claude-3-5-sonnet-20241022-v2:0"
        return BedrockModel(model_id=model_id)

    # groq / openai-compatível
    from strands.models.openai import OpenAIModel
    api_key = cfg.get("api_key")
    if not api_key:
        raise RuntimeError("sem api_key para o provider OpenAI-compatível")

    if provedor == "groq":
        base_url = "https://api.groq.com/openai/v1"
        model_id = cfg.get("model") or "llama-3.3-70b-versatile"
    else:
        base_url = cfg.get("base_url") or "https://api.openai.com/v1"
        model_id = cfg.get("model") or "gpt-4o-mini"

    return OpenAIModel(
        client_args={"api_key": api_key, "base_url": base_url},
        model_id=model_id,
        params={"temperature": cfg.get("temperature", 0.7), "max_tokens": 200},
    )


def _fabricar_tools(tools_ids: list[str], escolha: dict) -> list:
    """Cria as tools do Strands; cada uma grava a escolha no acumulador.

    `escolha` é um dict mutável {"acao": None, "alvo": None}. Só a primeira
    chamada conta (chamadas seguintes são ignoradas).

    O id da ação é capturado por closure (fábrica), NÃO como argumento default
    — o `@tool` do Strands inspeciona a assinatura e transformaria um default em
    parâmetro da tool (e Pydantic rejeita nomes com underscore inicial).
    """
    def _fabrica_simples(acao_id: str, desc: str):
        def executar() -> str:
            if escolha["acao"] is None:
                escolha["acao"] = acao_id
            return "ok"
        executar.__doc__ = desc
        return tool(executar, name=acao_id)

    def _fabrica_curar(desc: str):
        def curar(alvo: int) -> str:
            if escolha["acao"] is None:
                escolha["acao"] = "curar"
                escolha["alvo"] = alvo
            return "ok"
        curar.__doc__ = desc + " alvo = índice do agente ferido."
        return tool(curar, name="curar")

    tools = []
    for acao_id in tools_ids:
        desc = catalogo.DESCRICAO_TOOLS.get(acao_id, acao_id)
        if acao_id == "curar":
            tools.append(_fabrica_curar(desc))
        else:
            tools.append(_fabrica_simples(acao_id, desc))
    return tools


def decidir_via_strands(system_prompt: str, tools_ids: list[str],
                        obs_texto: str, viaveis: list[dict]) -> dict | None:
    """Roda o Agent do Strands e devolve {"acao", "alvo"} ou None.

    None sinaliza indisponibilidade/erro/sem escolha → o chamador faz fallback.
    """
    escolha: dict = {"acao": None, "alvo": None}
    try:
        cfg = _carregar_config()
        model = _criar_modelo(cfg)
        tools = _fabricar_tools(tools_ids, escolha)
        agent = Agent(model=model, system_prompt=system_prompt, tools=tools,
                      callback_handler=None)
        prompt = (
            f"{obs_texto}\n\n"
            "Escolha UMA ação chamando a tool correspondente. "
            "Chame exatamente uma tool."
        )
        agent(prompt)
    except Exception:
        return None
    return escolha if escolha["acao"] else None
