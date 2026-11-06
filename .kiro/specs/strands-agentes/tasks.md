# Plano de Implementação — Strands Agents com prompt, skills e tools

- [ ] 1. Dependências e base do pacote `agentes/`
  - Adicionar `strands-agents>=1.64` e `strands-agents[openai]` ao
    `requirements.txt`.
  - Criar o pacote `agentes/` com `__init__.py`.
  - Confirmar import do Strands na venv (`from strands import Agent, tool`;
    `from strands.models.openai import OpenAIModel`).
  - _Requisitos: 8.1, 8.2_

- [ ] 2. Catálogo programático de skills e tools (`agentes/catalogo.py`)
  - Definir `SKILLS` (dict id→{nome, descricao, instrucao}) com as 4 skills:
    `sobrevivencia`, `cura`, `transformacao`, `coleta`, derivando as instruções
    do `_PROMPT_TEMPLATE` atual.
  - Definir `IDS_TOOLS` (12 ações do preset), `PADRAO_SKILLS`, `PADRAO_TOOLS`.
  - Expor helpers `skill(id)`, `skills_publicas()`, `tools_publicas()` para a API.
  - _Requisitos: 2.1, 2.5, 3.1, 3.4, 4.5_

- [ ] 3. Construtor de prompt e tools (`agentes/construtor.py`)
  - `montar_system_prompt(prompt_base, skills_ids)`: concatena prompt base +
    instruções das skills ativas (ordem estável; ignora ids desconhecidos).
  - `tools_efetivas(tools_ids, viaveis)`: interseção na ordem canônica das
    ações viáveis; vazio → `["passar"]`.
  - Escrever testes unitários (sem rede) cobrindo concatenação estável, ids
    desconhecidos e interseção vazia.
  - _Requisitos: 2.3, 2.4, 3.2, 3.3_

- [ ] 4. Runner Strands (`agentes/strands_runner.py`)
  - `_carregar_config()` lê `config_llm.json`.
  - `_criar_modelo(cfg)`: groq/openai-compat → `OpenAIModel` (base_url+api_key);
    bedrock → `BedrockModel`. Sem credencial → levanta/retorna sinal de
    indisponível.
  - `decidir_via_strands(system_prompt, tools_ids, obs_texto, viaveis)`: fabrica
    tools com `@tool` (captura em acumulador; `curar` recebe `alvo`), cria
    `Agent(..., callback_handler=None)`, roda e devolve `{acao, alvo}` ou `None`.
  - Tratar exceções (rede/timeout/provider inválido) retornando `None`.
  - _Requisitos: 1.1, 2.1, 2.2, 5.1, 5.2, 5.3, 5.4_

- [ ] 5. Reescrever o decisor LLM sobre o runner (`decisores/llm.py`)
  - Trocar a chamada `httpx` pela orquestração: ler `_skills`/`_tools` da
    observação (default = padrões), montar system prompt e tools efetivas,
    chamar `decidir_via_strands`, mapear para `Decisao(origem="llm")`.
  - Manter `_fallback` determinístico (primeira viável, conf 0.5) e validação de
    alvo em `curar`.
  - Preservar a assinatura `decidir(observacao, prompt_agente, agente_idx)`.
  - Testar com `decidir_via_strands` mockado: escolha válida, ação inválida,
    sem escolha, `curar` com/sem alvo.
  - _Requisitos: 1.1, 1.2, 1.3, 1.4, 1.5_

- [ ] 6. Modelo de dados do agente (prompt + skills + tools) em `partida.py`
  - `criar()`: gravar `skills=PADRAO_SKILLS` e `tools=PADRAO_TOOLS` em cada
    agente (idênticos), além do `prompt`.
  - Leitura retroativa: helper que devolve skills/tools do agente aplicando os
    padrões quando ausentes (partidas antigas), sem reescrever o arquivo.
  - Na geração da observação dos agentes escalados, injetar `obs["_skills"]` e
    `obs["_tools"]` do agente.
  - _Requisitos: 4.1, 4.2, 4.3, 4.5, 7.1, 7.2, 7.3_

- [ ] 7. API de catálogo e edição de config do agente (`server.py` + `partida.py`)
  - `GET /catalogo/skills` e `GET /catalogo/tools` a partir do catálogo.
  - `PUT /partidas/{pid}/agentes/{aid}/config` com `{prompt, skills, tools}`:
    validar ids contra o catálogo, persistir no JSON, valer no próximo turno.
  - Função `editar_config(pid, aid, prompt, skills, tools)` em `partida.py`.
  - `estado_atual` passa a devolver `skills` e `tools` por agente.
  - Manter `PUT .../prompt` para compatibilidade (edita só o prompt).
  - _Requisitos: 4.3, 4.4, 6.2_

- [ ] 8. UI de edição de prompt, skills e tools (`frontend/`)
  - `api.js`: `configAgente(pid, aid, dados)`, `catalogoSkills()`,
    `catalogoTools()`.
  - `jogo.js`: modal com seções Prompt (textarea), Skills (checkboxes) e Tools
    (checkboxes), carregando catálogo + estado atual do agente; salvar via novo
    endpoint.
  - `jogo.html`: marcar que tools = ações do MCP e skills = habilidades; subir
    cache-buster para `?v=17` (css+js).
  - _Requisitos: 6.1, 6.2, 6.3, 6.4_

- [ ] 9. Verificação end-to-end e limpeza
  - Confirmar que `python server.py` inicia e o fluxo `criar→iniciar→turno`
    roda para `bot` (sem tocar no Strands).
  - Reaproveitar/rodar o teste da Fase 0 (LBM resolve tudo → Strands não é
    chamado).
  - Teste `llm` com `decidir_via_strands` mockado em partida real (1 turno),
    conferindo que a decisão respeita a lista de tools do agente.
  - Remover arquivos de teste temporários; garantir que nada de temporário fica
    no repositório.
  - _Requisitos: 1.5, 7.1, 8.3_
```
