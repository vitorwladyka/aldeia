# Design — Migração para Strands Agents com prompt, skills e tools separados

## Visão geral

O decisor LLM da Aldeia passa a executar via **Strands Agents SDK**
(`strands-agents 1.64.0`, instalado e validado no Python 3.14 da venv). A
configuração de cada agente é reestruturada em três partes independentes e
editáveis — **prompt**, **skills** e **tools** — persistidas no JSON da partida.

O contrato externo do decisor (`decidir(observacao, prompt_agente, agente_idx)
→ Decisao`) e o fluxo híbrido LBM→LLM (Fase 0 + conselho) permanecem. A mudança
é interna ao decisor LLM e no modelo de dados do agente.

```
partida._rodar_conselho
  └─ (escalado) → decisores/llm.decidir(obs, prompt, idx)   ← reescrito
                    ├─ monta system prompt = prompt_base + skills ativas
                    ├─ monta tools Strands = ações permitidas ∩ ações viáveis
                    ├─ cria Agent(model=provider_configurado, system_prompt, tools)
                    ├─ roda o loop; captura a 1ª chamada de tool como decisão
                    └─ fallback determinístico se falhar
```

### Decisões de projeto (e alternativas)

- **Actions-as-tools com captura da 1ª chamada** (escolhido) em vez de
  `agent.structured_output()`. Motivo: o requisito pede que as ações do MCP
  virtual sejam tools visíveis e que a lista de tools restrinja o agente.
  `structured_output` daria a decisão como JSON, mas não expõe "o que o agente
  pode fazer" como tools. Fica documentado como alternativa.
- **Loop encerrado na 1ª tool válida.** Cada tool, ao ser chamada, registra a
  escolha num acumulador e sinaliza parada. Não precisamos que o modelo
  "continue" após escolher — a decisão é atômica. Implementado via uma tool que
  grava em estado compartilhado + limite de 1 iteração/`max_tokens` curto.
- **Provider configurável** via `config_llm.json`, usando `OpenAIModel`
  (Groq/OpenAI-compat por `base_url`+`api_key`) ou `BedrockModel`.
- **Skills e tools programáticas** em módulos Python novos
  (`agentes/catalogo.py`), sem arquivos `SKILL.md`.
- **Compatibilidade retroativa**: agentes antigos no JSON (só com `prompt`)
  recebem skills/tools padrão ao serem lidos, sem quebrar.

---

## Arquitetura de componentes

### Novos módulos

```
agentes/
  __init__.py
  catalogo.py        # catálogo programático de SKILLS e TOOLS (ids + textos + specs)
  construtor.py      # monta system_prompt e lista de tools Strands a partir do agente
  strands_runner.py  # cria o Agent Strands, roda e captura a decisão
```

### Catálogo programático (`agentes/catalogo.py`)

Define dois catálogos estáticos:

**SKILLS** — dicionário `id → {nome, descricao, instrucao}`. As instruções
derivam das estratégias já existentes no `_PROMPT_TEMPLATE`. Catálogo inicial:

| id | nome | foco da instrução |
|----|------|-------------------|
| `sobrevivencia` | Sobrevivência basal | pagar basal, evitar fome, forragear quando alimento baixo |
| `cura` | Cura e remédios | priorizar feridos, caminho erva→remédio→curar |
| `transformacao` | Transformação de insumos | assar/fazer pão/remédio quando há insumos parados |
| `coleta` | Coleta e coordenação | coletar insumos, evitar saturação de local |

**TOOLS** — lista dos ids de ação do preset. Cada ação vira uma tool. Não há
texto de instrução próprio (a instrução vem das skills); a tool carrega só
nome + descrição curta + assinatura (parâmetro `alvo` só para `curar`).

```python
IDS_TOOLS = ["cacar","pescar","coletar_trigo","coletar_erva","coletar_madeira",
             "assar_carne","assar_peixe","fazer_pao","preparar_remedio",
             "curar","forragear","passar"]

PADRAO_SKILLS = ["sobrevivencia","cura","transformacao","coleta"]  # todas ativas
PADRAO_TOOLS  = list(IDS_TOOLS)                                     # todas ativas
```

### Construtor (`agentes/construtor.py`)

```python
def montar_system_prompt(prompt_base: str, skills_ids: list[str]) -> str:
    # prompt_base + "\n\n## Habilidades\n" + concat das instruções das skills
    # ativas (ordem estável do catálogo). Skills desconhecidas são ignoradas.

def tools_efetivas(tools_ids: list[str], viaveis: list[dict]) -> list[str]:
    # interseção entre tools do agente e ações viáveis do turno, preservando a
    # ordem canônica. Se vazia → ["passar"] (ou primeira viável).
```

### Runner Strands (`agentes/strands_runner.py`)

Responsável por criar o modelo conforme `config_llm.json`, montar as tools
Strands com `@tool`, rodar o agente e capturar a decisão.

```python
from strands import Agent, tool
from strands.models.openai import OpenAIModel

def _criar_modelo(cfg: dict):
    provedor = cfg.get("provedor", "groq")
    if provedor == "bedrock":
        from strands.models.bedrock import BedrockModel
        return BedrockModel(model_id=cfg.get("model"))
    # groq / openai-compat
    base_url = ("https://api.groq.com/openai/v1" if provedor == "groq"
                else cfg.get("base_url"))
    return OpenAIModel(
        client_args={"api_key": cfg.get("api_key"), "base_url": base_url},
        model_id=cfg.get("model"),
        params={"temperature": cfg.get("temperature", 0.7), "max_tokens": 200},
    )

def decidir_via_strands(system_prompt, tools_ids, obs_texto, viaveis) -> dict|None:
    escolha = {"acao": None, "alvo": None}

    def _fabricar_tool(acao_id):
        if acao_id == "curar":
            @tool(name="curar")
            def _t(alvo: int) -> str:
                "Curar um agente ferido (vida < 3). alvo = índice do agente."
                escolha["acao"], escolha["alvo"] = "curar", alvo
                return "ok"
            return _t
        @tool(name=acao_id)
        def _t() -> str:
            f"Executar a ação '{acao_id}' neste turno."
            escolha["acao"] = acao_id
            return "ok"
        return _t

    tools = [_fabricar_tool(a) for a in tools_ids]
    model = _criar_modelo(_carregar_config())
    agent = Agent(model=model, system_prompt=system_prompt, tools=tools,
                  callback_handler=None)
    try:
        agent(obs_texto + "\n\nChame UMA tool para a ação escolhida.")
    except Exception:
        return None
    return escolha if escolha["acao"] else None
```

Notas de implementação:
- `callback_handler=None` silencia o streaming no console.
- O acumulador `escolha` captura a 1ª (e, na prática, única) chamada de tool.
- Para limitar o loop a uma rodada de tool, usamos `max_tokens` curto e, se o
  SDK permitir, um guard de nº máximo de tool calls (ex.: hook
  `MaxToolCallsGuard`); caso contrário, a captura da 1ª chamada já basta porque
  lemos `escolha` após o retorno.
- A execução é síncrona (`agent(...)`); o decisor roda dentro do conselho que
  já é síncrono. Se necessário, usa-se `invoke_async` com `asyncio.run`.

### Decisor LLM reescrito (`decisores/llm.py`)

```python
def decidir(observacao, prompt_agente, agente_idx) -> Decisao:
    viaveis = observacao.get("acoes_viaveis", [])
    if not viaveis:
        return Decisao("passar", None, 1.0, "llm", "nenhuma ação viável")

    # prompt_agente aqui é o prompt BASE; skills/tools vêm da observação
    # (injetadas por partida.py — ver seção de dados).
    skills_ids = observacao.get("_skills", PADRAO_SKILLS)
    tools_ids  = observacao.get("_tools",  PADRAO_TOOLS)

    system = montar_system_prompt(prompt_agente, skills_ids)
    tids   = tools_efetivas(tools_ids, viaveis)      # ∩ ações viáveis
    if not tids:
        return _fallback(viaveis, "sem interseção tools∩viáveis")

    obs_texto = renderizar_texto_compacto(observacao, max_tokens=500)
    escolha = decidir_via_strands(system, tids, obs_texto, viaveis)
    if not escolha:
        return _fallback(viaveis, "Strands indisponível/sem escolha")

    acao = escolha["acao"]
    if acao not in [v["acao"] for v in viaveis]:
        return _fallback(viaveis, f"ação fora das viáveis: {acao}")
    alvo = _validar_alvo(acao, escolha.get("alvo"), viaveis)
    return Decisao(acao, alvo, 1.0, "llm", f"strands: {acao}")
```

O `_fallback` reproduz o comportamento atual (primeira viável, confiança 0.5).

---

## Modelo de dados (JSON da partida)

### Hoje

```json
"agentes": [ { "indice": 0, "nome": "Aria", "prompt": "..." } ]
```

### Depois

```json
"agentes": [
  {
    "indice": 0, "nome": "Aria", "vida": 3,
    "prompt": "<prompt base>",
    "skills": ["sobrevivencia","cura","transformacao","coleta"],
    "tools":  ["cacar","pescar", "... todas por padrão ..."]
  }
]
```

- `criar()` em `partida.py` preenche `skills` e `tools` com `PADRAO_SKILLS` /
  `PADRAO_TOOLS` para todos os agentes (idênticos).
- Leitura retroativa: ao carregar um agente sem `skills`/`tools` (partidas
  antigas), aplica os padrões em memória (sem reescrever o arquivo), garantindo
  compatibilidade.
- Ao gerar a observação de cada agente escalado, `partida.py` injeta
  `obs["_skills"]` e `obs["_tools"]` com os valores do agente, para o decisor
  usar. (Prefixo `_` = campo interno, fora do schema público da observação; não
  é validado pelo `observacao_v1.json`.)

> Decisão: injetar skills/tools na observação via campos internos evita mudar a
> assinatura `decidir(obs, prompt, idx)` e o schema público. Alternativa
> rejeitada: mudar a assinatura do decisor (quebraria bot/lbm/hibrido).

---

## Configuração do provider (`config_llm.json`)

Campos usados pelo runner:

```json
{
  "provedor": "groq",            // "groq" | "openai" | "bedrock"
  "model": "llama-3.3-70b-versatile",
  "base_url": "",                // usado quando openai-compat
  "temperature": 0.7,
  "api_key": "..."               // groq/openai; bedrock usa credencial AWS do ambiente
}
```

- `groq` → `OpenAIModel` com `base_url=https://api.groq.com/openai/v1`.
- `openai`/compat → `OpenAIModel` com `base_url` do config.
- `bedrock` → `BedrockModel(model_id=...)`, credenciais do ambiente AWS.
- Sem `api_key`/credencial → decisor cai no fallback (R5.4 / R1.4).

---

## Fluxo híbrido (inalterado em comportamento)

`partida._rodar_conselho` continua:
- **Fase 0 (LBM):** Laya decide; resolve quem tem confiança ≥ threshold e sem
  colisão (não vai ao conselho nem ao LLM).
- **Conselho (escalados):** cada agente escalado chama `decisores/llm.decidir`,
  que agora roda via Strands. A colisão e o pulo do conselho seguem iguais.

O único ponto novo: antes de chamar `decidir`, `partida.py` injeta `_skills` e
`_tools` do agente na observação.

---

## UI (frontend)

### Edição por agente (`jogo.html` + `jogo.js`)

O modal de edição de prompt passa a ter três seções:
1. **Prompt** — textarea (como hoje).
2. **Skills** — checkboxes do catálogo (`GET /catalogo/skills`), marcando as
   ativas do agente.
3. **Tools** — checkboxes das ações (`GET /catalogo/tools`), marcando as ativas.

Salvar envia `PUT /partidas/{pid}/agentes/{aid}/config` com
`{prompt, skills, tools}`. Cache-buster dos assets sobe para `?v=17`.

### API (`server.py` + `partida.py`)

- `GET /catalogo/skills` → `[{id, nome, descricao}]`.
- `GET /catalogo/tools` → `[{id, nome, descricao}]`.
- `PUT /partidas/{pid}/agentes/{aid}/config` → body `{prompt, skills, tools}`;
  valida ids contra o catálogo; persiste no JSON; vale no próximo turno.
- O endpoint antigo `PUT .../prompt` é mantido (edita só o prompt) para
  compatibilidade, ou redirecionado para o novo.
- `estado_atual` passa a devolver `skills` e `tools` de cada agente, além do
  `prompt`.

---

## Tratamento de erros

| Situação | Comportamento |
|----------|---------------|
| Sem api_key / credencial | fallback determinístico (primeira viável), origem "llm" |
| Provider inválido | log + fallback |
| Strands lança exceção (rede/timeout) | fallback, turno não quebra |
| Modelo não chama nenhuma tool | fallback |
| Modelo chama tool fora das viáveis | fallback (revalidação já existe no motor) |
| `curar` sem alvo válido | corrige para menor índice ferido (como hoje) |
| Interseção tools∩viáveis vazia | `passar` |

---

## Estratégia de testes

Como o LLM depende de rede/credencial, os testes isolam o Strands:

1. **Catálogo e construtor (unit, sem rede):**
   - `montar_system_prompt` concatena prompt + skills ativas, ignora ids
     desconhecidos, é estável.
   - `tools_efetivas` faz a interseção na ordem canônica; vazio → `passar`.
2. **Decisor com runner mockado:** monkeypatch de `decidir_via_strands` para
   devolver uma escolha fixa; verifica mapeamento para `Decisao`, validação de
   alvo em `curar`, e fallbacks (sem escolha, ação inválida).
3. **Modelo de dados:** `criar()` grava `skills`/`tools` padrão; leitura
   retroativa de agente sem os campos aplica padrões.
4. **End-to-end determinístico:** partida `bot` roda igual (Strands não é
   tocado). Partida `llm` com LBM resolvendo tudo → Strands não é chamado
   (reaproveita os testes da Fase 0).
5. **Integração real (manual/opcional):** com `api_key` válida, 1 turno `llm`
   sem LBM, conferindo que a decisão vem do Strands e respeita a lista de tools.

Todos os testes temporários são removidos ao final; o `server.py` deve iniciar
e o smoke `bot` deve passar.

---

## Dependências

`requirements.txt` ganha:
```
strands-agents>=1.64
strands-agents[openai]   # provider OpenAI-compat (Groq)
```
(`boto3` já vem como dependência transitiva do Strands para o Bedrock.)
Instalado e validado na venv (Python 3.14): `strands-agents 1.64.0`.
