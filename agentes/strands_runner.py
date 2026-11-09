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

import json
from urllib.parse import urlparse

from strands import Agent, ModelRetryStrategy, tool
from strands.types.tools import ToolContext

from . import catalogo
from .limitador import LimitadorTpm
import config_env

# Um limitador para o processo todo (as chamadas dos agentes dividem a mesma cota).
_limitador = LimitadorTpm()
SAIDA_ESTIMADA_TOKENS = 150   # a resposta (tool call + fala) também conta no TPM

# Limite de taxa do provedor: falha RÁPIDO e deixa o chamador usar o fallback.
# O padrão do Strands (6 tentativas, 4s..240s) travava um único turno por minutos.
TENTATIVAS_MODELO = 3
ESPERA_INICIAL_S = 2
ESPERA_MAXIMA_S = 10
TIMEOUT_HTTP_S = 30.0
MAX_TOKENS_SAIDA = 400     # cabe a tool + a fala de 1-2 frases do conselho


def _encerrar_loop(tool_context) -> None:
    """Decisão tomada: encerra o loop do agente antes de uma 2ª chamada ao modelo.

    Sem isso o Strands chama o modelo de novo só para gerar um texto final que
    ninguém usa — dobrando tokens e latência de cada decisão.
    """
    if tool_context is None:
        return
    try:
        tool_context.agent.cancel(after_current_tools=True)
    except Exception:
        pass


def _carregar_config() -> dict:
    """Config do LLM a partir do .env (fallback JSON) — ver config_env."""
    return config_env.config_llm()


def eh_servidor_local(base_url: str) -> bool:
    """True se a URL aponta para esta máquina (Ollama, LM Studio, vLLM local...)."""
    host = (urlparse(base_url or "").hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1")


def _criar_modelo(cfg: dict):
    """Cria o modelo do Strands conforme o provider. Levanta se indisponível.

    Opcionais em `cfg` (vindos do config_llm.json), úteis para modelos lentos ou
    locais: `timeout_s` (espera por resposta), `max_tokens` (limite de saída) e
    `reasoning_effort` ("none" desliga o "thinking" de modelos que raciocinam).
    """
    provedor = (cfg.get("provedor") or "groq").lower()
    timeout = float(cfg.get("timeout_s") or TIMEOUT_HTTP_S)
    max_tokens = int(cfg.get("max_tokens") or MAX_TOKENS_SAIDA)

    if provedor == "bedrock":
        from strands.models.bedrock import BedrockModel
        model_id = cfg.get("model") or "anthropic.claude-3-5-sonnet-20241022-v2:0"
        return BedrockModel(model_id=model_id)

    if provedor == "anthropic":
        # Cliente nativo da Anthropic. NÃO usa base_url: o SDK já acrescenta
        # /v1/messages, e "https://api.anthropic.com/v1" viraria /v1/v1/messages.
        from strands.models.anthropic import AnthropicModel
        api_key = cfg.get("api_key")
        if not api_key:
            raise RuntimeError("sem ANTHROPIC_API_KEY para o provedor anthropic")
        return AnthropicModel(
            client_args={"api_key": api_key, "max_retries": 0, "timeout": timeout},
            model_id=cfg.get("model") or "claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            params={"temperature": cfg.get("temperature", 0.7)},
        )

    # groq / openai-compatível
    from strands.models.openai import OpenAIModel
    if provedor == "groq":
        base_url = "https://api.groq.com/openai/v1"
        model_id = cfg.get("model") or "llama-3.3-70b-versatile"
    else:
        base_url = cfg.get("base_url") or "https://api.openai.com/v1"
        model_id = cfg.get("model") or "gpt-4o-mini"

    api_key = cfg.get("api_key")
    if provedor != "groq" and eh_servidor_local(base_url):
        # Servidor local não precisa de chave e NUNCA recebe a chave real de outro
        # provedor. O cliente OpenAI só exige um valor qualquer.
        api_key = "local"
    elif not api_key:
        raise RuntimeError("sem api_key para o provider OpenAI-compatível")

    params = {"temperature": cfg.get("temperature", 0.7), "max_tokens": max_tokens}
    if cfg.get("reasoning_effort"):
        params["reasoning_effort"] = cfg["reasoning_effort"]

    return OpenAIModel(
        # max_retries=0: o cliente OpenAI não repete por conta própria; quem
        # controla as tentativas é o ModelRetryStrategy do Agent (abaixo).
        client_args={"api_key": api_key, "base_url": base_url,
                     "max_retries": 0, "timeout": timeout},
        model_id=model_id,
        params=params,
    )


def _fabricar_tools(tools_ids: list[str], escolha: dict) -> list:
    """Cria as tools do Strands; cada uma grava a escolha no acumulador.

    `escolha` é um dict mutável {"acao": None, "alvo": None}. Só a primeira
    chamada conta (chamadas seguintes são ignoradas).

    O id da ação é capturado por closure (fábrica), NÃO como argumento default
    — o `@tool` do Strands inspeciona a assinatura e transformaria um default em
    parâmetro da tool (e Pydantic rejeita nomes com underscore inicial).
    """
    # Descrição CURTA: ela se repete em todas as tools a cada chamada ao LLM, e
    # tokens contam no limite por minuto. O "como falar" está na instrução da mesa.
    doc_mensagem = "\n\nArgs:\n    mensagem: Sua fala aos outros agentes (1-2 frases)."

    def _fabrica_simples(acao_id: str, desc: str):
        def executar(mensagem: str = "", tool_context: ToolContext = None) -> str:
            if escolha["acao"] is None:
                escolha["acao"] = acao_id
                escolha["mensagem"] = mensagem
                _encerrar_loop(tool_context)
            return "ok"
        executar.__doc__ = desc + doc_mensagem
        return tool(executar, name=acao_id, context=True)

    def _fabrica_curar(desc: str):
        def curar(alvo: int, mensagem: str = "", tool_context: ToolContext = None) -> str:
            if escolha["acao"] is None:
                escolha["acao"] = "curar"
                escolha["alvo"] = alvo
                escolha["mensagem"] = mensagem
                _encerrar_loop(tool_context)
            return "ok"
        curar.__doc__ = (
            desc + "\n\nArgs:\n"
            "    alvo: Índice do agente ferido a curar.\n"
            "    mensagem: Sua fala aos outros agentes (1-2 frases)."
        )
        return tool(curar, name="curar", context=True)

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
    """Roda o Agent do Strands e devolve {"acao", "alvo", "mensagem"} ou None.

    None sinaliza indisponibilidade/erro/sem escolha → o chamador faz fallback.
    """
    escolha: dict = {"acao": None, "alvo": None, "mensagem": ""}
    try:
        cfg = _carregar_config()
        model = _criar_modelo(cfg)
        tools = _fabricar_tools(tools_ids, escolha)
        limite = int(cfg.get("tpm_limite") or 0)
        if limite > 0:
            chars = (len(system_prompt) + len(obs_texto)
                     + len(json.dumps([t.tool_spec for t in tools], ensure_ascii=False)))
            tokens = chars // 4 + SAIDA_ESTIMADA_TOKENS
            esperou = _limitador.esperar(tokens, limite)
            if esperou >= 0.5:
                print(f"[LLM] aguardou {esperou:.1f}s para respeitar tpm_limite="
                      f"{limite} (~{tokens} tokens nesta chamada)", flush=True)
        agent = Agent(
            model=model, system_prompt=system_prompt, tools=tools,
            callback_handler=None,
            retry_strategy=ModelRetryStrategy(
                max_attempts=TENTATIVAS_MODELO,
                initial_delay=ESPERA_INICIAL_S,
                max_delay=ESPERA_MAXIMA_S),
        )
        prompt = (
            f"{obs_texto}\n\n"
            "Escolha UMA ação chamando a tool correspondente. "
            "Chame exatamente uma tool."
        )
        agent(prompt)
    except Exception as e:
        # Antes isto era silencioso: só aparecia "rate limit error" sem o motivo.
        print(f"[LLM] chamada falhou → fallback | {_resumir_erro(e)}", flush=True)
        return None
    return escolha if escolha["acao"] else None


def _resumir_erro(e: Exception) -> str:
    """Resumo do erro para o log: tipo, mensagem e cabeçalhos de limite de taxa.

    O Strands encadeia o erro original (`raise ... from`), que carrega a resposta
    HTTP; dela saem `x-ratelimit-*` e `retry-after` — o limite real da conta.
    """
    partes = [f"{type(e).__name__}: {str(e)[:300]}"]
    resposta = getattr(e.__cause__ or e.__context__, "response", None)
    cabecalhos = getattr(resposta, "headers", None)
    if cabecalhos is not None:
        uteis = {k: cabecalhos[k] for k in cabecalhos.keys()
                 if k.lower().startswith("x-ratelimit") or k.lower() == "retry-after"}
        if uteis:
            partes.append(f"cabeçalhos={uteis}")
    return " | ".join(partes)
