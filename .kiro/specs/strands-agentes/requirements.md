# Requisitos — Migração para Strands Agents (AWS) com prompt, skills e tools separados

## Introdução

Hoje o decisor LLM da Aldeia faz uma chamada HTTP direta à API do provedor
(Groq / OpenAI-compatível) via `httpx`, em `decisores/llm.py`. Não há framework
de agentes (não há LangGraph nem Strands). Cada agente tem um único campo
`prompt` (string) no JSON da partida.

Esta mudança introduz o **Strands Agents SDK (AWS)** como a camada de execução
do decisor LLM, e reestrutura a configuração do agente em **três partes
separadas e editáveis**:

- **prompt** — instrução principal (system prompt base), como hoje.
- **skills** — habilidades do agente (instruções especializadas), definidas
  programaticamente (sem arquivos `SKILL.md` externos), injetadas no system
  prompt quando ativas.
- **tools** — acessos ao MCP virtual (pescar, caçar, curar, etc.), modelo
  *actions-as-tools*: cada ação do jogo vira uma tool do Strands; a lista de
  tools do agente define o que ele pode fazer.

Todos os agentes começam idênticos (mesmo prompt, mesmas skills, mesmas tools,
definidos por um padrão programático) e cada um pode ser editado
individualmente depois, como já ocorre com o prompt hoje. A persistência
continua em JSON (`data/partida_{id}.json`), sem SQLite.

O fluxo híbrido LBM (Laya) → LLM é preservado: o Strands só é acionado quando a
decisão da Laya fica abaixo do threshold de confiança ou quando há colisão de
local. Os decisores `bot` e `lbm` (heurística) permanecem inalterados.

### Escopo

Dentro do escopo:
- Substituir a chamada `httpx` do decisor LLM por uma execução via Strands.
- Modelo de dados por agente com `prompt`, `skills`, `tools` (lista) no JSON.
- Padrão programático de prompt/skills/tools aplicado na criação da partida.
- Provider de modelo configurável (Groq/OpenAI-compat/Bedrock) via
  `config_llm.json`.
- UI de edição por agente expandida para os três campos.
- Preservar o contrato de decisão (uma ação viável → `Decisao`).

Fora do escopo:
- Introduzir SQLite ou qualquer banco.
- Alterar o motor determinístico, o preset, ou os decisores `bot`/`lbm`.
- Tornar o decisor LLM determinístico.
- Skills baseadas em arquivos `SKILL.md` externos.

---

## Requisitos

### Requisito 1 — Execução do decisor LLM via Strands Agents

**História de usuário:** Como mantenedor do projeto, quero que o decisor LLM
use o Strands Agents SDK em vez da chamada HTTP manual, para padronizar a
execução dos agentes num framework de agentes e habilitar tools/skills.

#### Critérios de aceitação

1. QUANDO o decisor LLM precisa decidir a ação de um agente, O sistema DEVE
   construir e executar um `Agent` do Strands com: o modelo configurado, o
   system prompt do agente (prompt base + skills ativas) e a lista de tools
   (ações permitidas) do agente.
2. O decisor LLM DEVE continuar retornando um objeto `Decisao` com os campos
   `acao`, `alvo`, `confianca`, `origem="llm"` e `raciocinio`, mantendo a
   assinatura `decidir(observacao, prompt_agente, agente_idx)` compatível com
   os chamadores atuais (`hibrido.py` e `partida.py`).
3. A ação retornada DEVE pertencer à lista de ações viáveis da observação;
   SE o agente não produzir uma ação viável, ENTÃO o sistema DEVE aplicar o
   fallback determinístico atual (primeira ação viável) com `raciocinio`
   explicando o fallback.
4. SE o modelo/credencial não estiver disponível (sem rede, sem API key),
   ENTÃO o sistema DEVE cair no mesmo fallback determinístico, sem quebrar o
   turno.
5. A mudança NÃO DEVE alterar o comportamento dos decisores `bot` e `lbm`.

### Requisito 2 — Tools como ações do MCP virtual (actions-as-tools)

**História de usuário:** Como designer do jogo, quero que cada ação do mundo
(pescar, caçar, curar, etc.) seja uma tool do agente, para dar visibilidade do
que o agente pode fazer e permitir especializar agentes removendo/adicionando
tools.

#### Critérios de aceitação

1. O sistema DEVE definir programaticamente uma tool do Strands para cada ação
   do jogo presente no preset (`cacar`, `pescar`, `coletar_trigo`,
   `coletar_erva`, `coletar_madeira`, `assar_carne`, `assar_peixe`,
   `fazer_pao`, `preparar_remedio`, `curar`, `forragear`, `passar`).
2. QUANDO o agente escolhe uma ação chamando a tool correspondente, O sistema
   DEVE interpretar essa chamada como a decisão do agente (a tool `curar` DEVE
   aceitar o parâmetro de alvo).
3. A lista de tools de um agente DEVE restringir o que ele pode escolher:
   SE uma ação viável no jogo não estiver na lista de tools do agente, ENTÃO o
   agente NÃO DEVE poder escolhê-la.
4. SE a interseção entre as tools do agente e as ações viáveis do turno for
   vazia, ENTÃO o sistema DEVE decidir `passar` (ou a primeira viável, conforme
   o fallback) sem erro.
5. As tools DEVEM ser criadas programaticamente (via decorator/estrutura do
   Strands), sem depender de arquivos externos.

### Requisito 3 — Skills como habilidades programáticas separadas do prompt

**História de usuário:** Como designer do jogo, quero habilidades (skills)
definidas separadamente do prompt principal, para especializar agentes sem
reescrever o prompt base.

#### Critérios de aceitação

1. O sistema DEVE definir um catálogo programático de skills, cada uma com um
   identificador e um texto de instrução (habilidade).
2. QUANDO um agente tem skills ativas, O sistema DEVE compor o system prompt
   final concatenando o prompt base com os textos das skills ativas, de forma
   estável e legível.
3. As skills DEVEM ser uma lista independente das tools (editáveis
   separadamente); ativar/desativar uma skill NÃO DEVE alterar o prompt base
   nem a lista de tools.
4. As skills DEVEM ser criadas programaticamente, sem arquivos `SKILL.md`
   externos.

### Requisito 4 — Modelo de dados do agente: prompt + skills + tools no JSON

**História de usuário:** Como usuário, quero que cada agente tenha prompt,
skills e tools persistidos e editáveis por partida, mantendo o armazenamento
em JSON.

#### Critérios de aceitação

1. QUANDO uma partida é criada, CADA agente DEVE receber uma cópia do padrão
   programático: `prompt` (base), `skills` (lista de ids) e `tools` (lista de
   ids), gravados em `data/partida_{id}.json` no objeto do agente.
2. Inicialmente TODOS os agentes DEVEM ter o mesmo prompt, as mesmas skills e
   as mesmas tools (o padrão).
3. O sistema DEVE permitir editar `prompt`, `skills` e `tools` de um agente
   individualmente após a criação, persistindo no JSON da partida (mesma lógica
   do prompt hoje).
4. A edição DEVE valer a partir do próximo turno, como já ocorre com o prompt.
5. O padrão (prompt base, skills padrão, tools padrão) DEVE ser definido
   programaticamente no código, não em arquivo externo.

### Requisito 5 — Provider de modelo configurável

**História de usuário:** Como mantenedor, quero escolher o provider de modelo
(Groq/OpenAI-compat/Bedrock) por configuração, para rodar local com Groq ou
migrar para Bedrock sem mudar código.

#### Critérios de aceitação

1. O sistema DEVE ler o provider e os parâmetros do modelo de `config_llm.json`
   (provedor, model, base_url, temperature, api_key/credencial).
2. QUANDO o provedor é "groq" ou OpenAI-compatível, O sistema DEVE configurar o
   Strands com o provider correspondente (OpenAI-compatível/LiteLLM) apontando
   para o endpoint e a chave configurados.
3. QUANDO o provedor é "bedrock", O sistema DEVE usar o provider Bedrock do
   Strands com as credenciais AWS do ambiente.
4. SE o provider configurado for inválido ou faltar credencial, ENTÃO o sistema
   DEVE registrar o erro e cair no fallback determinístico (Requisito 1.4).

### Requisito 6 — UI de edição de prompt, skills e tools por agente

**História de usuário:** Como usuário, quero editar prompt, skills e tools de
cada agente pela interface, para visualizar e especializar o que cada agente
faz.

#### Critérios de aceitação

1. QUANDO abro a edição de um agente, A UI DEVE mostrar o prompt (texto), as
   skills disponíveis com indicação de quais estão ativas, e as tools
   disponíveis com indicação de quais estão ativas.
2. QUANDO salvo as alterações, A UI DEVE persistir prompt, skills e tools via
   API, e a edição DEVE valer a partir do próximo turno.
3. A UI DEVE deixar claro que tools são as ações do MCP virtual que o agente
   pode executar e skills são habilidades/instruções.
4. A UI DEVE funcionar com cache-busting adequado (versão dos assets
   atualizada) para evitar servir JS/CSS antigos.

### Requisito 7 — Preservar o fluxo híbrido LBM → Strands/LLM

**História de usuário:** Como designer do jogo, quero que o Strands só seja
acionado quando a Laya (LBM) não resolver, para manter custo/latência baixos.

#### Critérios de aceitação

1. QUANDO o decisor é `llm` com LBM habilitado, O sistema DEVE acionar o
   Strands SOMENTE para os agentes que escalam (confiança abaixo do threshold
   ou colisão de local), mantendo a Fase 0 de pré-resolução pela Laya.
2. QUANDO o decisor é `llm` sem LBM, O sistema DEVE usar o Strands diretamente
   para todos os agentes.
3. A regra de colisão por local e o pulo do conselho (quando ninguém escala)
   DEVEM continuar valendo sem alteração de comportamento.

### Requisito 8 — Dependências e compatibilidade de ambiente

**História de usuário:** Como mantenedor, quero as dependências instaladas e
compatíveis com o ambiente local (Python 3.14), para rodar sem surpresas.

#### Critérios de aceitação

1. O sistema DEVE adicionar `strands-agents` (e, se necessário, o pacote de
   provider, ex.: suporte OpenAI/LiteLLM) ao `requirements.txt`.
2. A instalação DEVE funcionar na venv do projeto (Python 3.14); SE houver
   incompatibilidade, ENTÃO o problema DEVE ser documentado e uma alternativa
   proposta (ex.: pinagem de versão ou provider alternativo).
3. O servidor DEVE continuar iniciando (`python server.py`) e o fluxo
   `criar → iniciar → turno` DEVE rodar end-to-end para `bot` sem depender do
   Strands, e para `llm` quando houver credencial.
