"""Pacote `agentes` — configuração programática de agentes para o Strands.

Contém:
- `catalogo`: catálogo programático de skills (habilidades) e tools (ações do
  MCP virtual).
- `construtor`: monta o system prompt (prompt base + skills ativas) e a lista
  de tools efetivas (tools do agente ∩ ações viáveis do turno).
- `strands_runner`: cria o Agent do Strands conforme o provider configurado,
  fabrica as tools e captura a decisão do agente.
"""
