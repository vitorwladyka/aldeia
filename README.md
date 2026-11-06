# Aldeia de Agentes

Jogo cooperativo em turnos onde agentes LLM/LBM vivem numa aldeia e precisam
sobreviver: coletar recursos, transformar comida, curar feridos, conversar.

## Arquitetura

```
aldeia/
├── core/                       # Motor do jogo (determinístico, em memória)
│   ├── estado.py               #   Estado imutável do turno
│   ├── motor.py                #   Executa turno: basal → eventos → ações
│   ├── acoes.py                #   Ações viáveis por agente
│   ├── eventos.py              #   Tempestade, fartura, doença, praga
│   ├── pagamento.py            #   Algoritmo de consumo de alimento
│   ├── preset.py               #   Carrega/valida presets/padrao.json
│   ├── rng.py                  #   RNG determinístico (SHA-256 por chave)
│   ├── mcp_cliente.py          #   Cliente do MCP (memória ou HTTP)
│   ├── observacao.py           #   Gera a observação JSON do agente
│   ├── placar.py               #   Pontuação: vivos → vidas → estoque
│   ├── hashing.py              #   preset_hash, mcp_config_hash, cenario_hash
│   └── schemas/observacao_v1.json
├── mcp_mundo/                  # Mundo externo (MCP)
│   ├── sorteio.py              #   u_lt(u, ppm), escolher_lista(u, lista)
│   ├── config_mcp.py           #   carregar_config, config_hash, info
│   └── mcp_mundo_config.json   #   Config default (criada automaticamente)
├── decisores/                  # Decisores de ação
│   ├── bot.py                  #   Determinístico (round-robin)
│   ├── lbm.py                  #   Laya: heurística com confiança
│   └── llm.py                  #   Claude: z-ai chat (chamada real)
├── hibrido.py                  # Orquestra Laya → Claude por threshold
├── partida.py                  # Orquestra turnos: iniciar + decidir + executar
├── armazenamento.py            # Persistência JSON em data/
├── server.py                   # FastAPI: API + estáticos do frontend
├── presets/padrao.json         # Balanceamento (12 ações, eventos, valores)
├── config_lbm.json             # Threshold, perfis, state_template
├── frontend/                   # HTML/CSS/JS dark theme
│   ├── index.html              #   Home
│   ├── jogo.html               #   Criar e jogar partidas
│   ├── agentes.html            #   Lista de agentes
│   ├── config.html             #   Configurar LLM/LBM
│   ├── analise.html            #   Gráficos pós-partida
│   ├── historia.html           #   Historia visual
│   └── ranking.html            #   Ranking de partidas
├── requirements.txt
└── scripts/smoke_test.py       # Teste end-to-end (bot)
```

## Como rodar

```bash
pip install -r requirements.txt
python server.py
# Abra http://localhost:8000/
```

## Decisores

| Decisor | Descrição | Latência | Rede |
|---------|-----------|----------|------|
| `bot`   | Determinístico (round-robin pelas ações viáveis) | ~0ms | não |
| `llm`   | Claude direto via `z-ai chat` | ~500ms | sim |
| `lbm`   | Híbrido: Laya → se conf < threshold → Claude | ~0ms (Laya) ou ~500ms (Claude) | depende |

O LBM (papel de "Laya") é uma heurística Python que devolve ação + confiança
calibrada. Para trocar pela Laya real: substituir o corpo de
`decisores/lbm.py:decidir()` por uma chamada HTTP ao endpoint do Laya,
mantendo a assinatura.

## Fluxo do turno (seção 5.5/5.6)

1. **Basal**: cada agente vivo paga `basal` (1 normal, 3 inverno) em alimento.
   Se não consegue pagar, perde 1 vida.
2. **Eventos globais**: tempestade, fartura, doença (1 ou 2 alvos), praga.
3. **Ordem do turno**: agentes vivos ordenados por `chave(seed, turno, "ordem", agente)`.
4. **Decisão**: para cada agente, gera observação e pede ação ao decisor.
5. **Execução**: ações executadas em memória na ordem canônica
   (curar → transformar → coletar → forragear → passar).
6. **Persiste**: histórico (com decisões, movimentos, eventos_vida) + placar.

## Endpoints da API

| Método | Rota | Descrição |
|--------|------|-----------|
| GET    | `/partidas` | Lista partidas |
| POST   | `/partidas` | Cria partida |
| DELETE | `/partidas` | Limpa tudo |
| GET    | `/partidas/{id}` | Metadados |
| POST   | `/partidas/{id}/iniciar` | Inicia |
| POST   | `/partidas/{id}/turno` | Executa próximo turno |
| POST   | `/partidas/{id}/encerrar` | Encerra manualmente |
| POST   | `/partidas/{id}/retomar` | Destrava (pós-falha MCP) |
| POST   | `/partidas/{id}/reset-lock` | Alias de retomar |
| GET    | `/partidas/{id}/estado` | Estado atual |
| GET    | `/partidas/{id}/agentes/{aid}/prompt` | Prompt do agente |
| PUT    | `/partidas/{id}/agentes/{aid}/prompt` | Edita prompt |
| GET    | `/partidas/{id}/analise/{tipo}` | JSON (estoque, ganhos-perdas, vidas, eventos, conversas, decisoes) |
| GET    | `/partidas/{id}/analise/{tipo}.csv` | CSV |
| GET    | `/comparar?a=X&b=Y` | Compara partidas |
| GET    | `/config/llm` | Lê config_llm.json |
| PUT    | `/config/llm` | Salva config_llm.json |
| POST   | `/config/llm/testar` | Testa z-ai chat |
| GET    | `/config/lbm` | Lê config_lbm.json |
| PUT    | `/config/lbm` | Salva config_lbm.json |
| GET    | `/config/lbm/perfis` | Lista perfis |
| POST   | `/config/lbm/testar` | Testa LBM (heurística) |

## Testes

```bash
python scripts/smoke_test.py
```

Cria uma partida `bot` (3 agentes, 20 turnos), roda 3 turnos e valida estado.
Cria também uma partida `lbm` (3 agentes) e roda 1 turno.
