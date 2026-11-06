"""Catálogo programático de skills (habilidades) e tools (ações do MCP virtual).

As skills são habilidades do agente, definidas em código (sem arquivos
`SKILL.md` externos). Cada skill tem um id, um nome, uma descrição curta (para a
UI) e uma `instrucao` — o texto injetado no system prompt quando a skill está
ativa. As instruções derivam das seções do `_PROMPT_TEMPLATE` de `partida.py`.

As tools são as ações do mundo (MCP virtual). Cada ação do preset vira uma tool
do Strands; a lista de tools de um agente define o que ele pode fazer.
"""
from __future__ import annotations

# --- SKILLS (habilidades) ---

SKILLS: dict[str, dict] = {
    "sobrevivencia": {
        "nome": "Sobrevivência basal",
        "descricao": "Pagar o basal, evitar fome e forragear quando o alimento está baixo.",
        "instrucao": (
            "## Sobrevivência basal\n"
            "- Cada turno cada agente paga o basal (1 alimento no normal, 3 no inverno).\n"
            "- Sem alimento para o basal, perde 1 vida. Vida 0 = morte permanente.\n"
            "- Só peixe, carne, pão, peixe_assado e carne_assada são comida.\n"
            "- Trigo, erva, madeira e remédio NÃO são comida — precisam ser transformados.\n"
            "- Alimento baixo? Prefira forragear (grátis, 60% de +1 alimento) ou transformar insumos."
        ),
    },
    "cura": {
        "nome": "Cura e remédios",
        "descricao": "Priorizar feridos e dominar o caminho erva → remédio → curar.",
        "instrucao": (
            "## Cura e remédios\n"
            "- Vida NÃO regenera sozinha. O único modo de recuperar vida é curar com remédio.\n"
            "- Caminho da cura: coletar_erva → preparar_remedio (2 erva + 1 madeira) → curar.\n"
            "- Há ferido (vida < 3) e SEM remédio: priorize coletar erva e preparar remédio.\n"
            "- Há ferido e COM remédio: use curar imediatamente no mais crítico (vida mais baixa).\n"
            "- Não espere chegar a vida 1 — em vida 2 já prepare remédio para o próximo turno."
        ),
    },
    "transformacao": {
        "nome": "Transformação de insumos",
        "descricao": "Transformar insumos parados em comida de alto valor.",
        "instrucao": (
            "## Transformação de insumos\n"
            "- Insumos parados no estoque = desperdício. Transforme quando possível.\n"
            "- trigo + madeira → fazer_pao (comida de alto valor).\n"
            "- peixe + madeira → assar_peixe; carne + madeira → assar_carne.\n"
            "- erva + madeira → preparar_remedio.\n"
            "- Transformar é grátis (custo 0) e rende comida/remédio de alto valor — faça sempre que tiver insumos."
        ),
    },
    "coleta": {
        "nome": "Coleta e coordenação",
        "descricao": "Coletar insumos e evitar saturação de local entre agentes.",
        "instrucao": (
            "## Coleta e coordenação\n"
            "- Coletar custa alimento mas rende insumos para transformar depois.\n"
            "- No máximo 2 agentes por local rendem plenamente (o 3º+ rende menos).\n"
            "- Dividam tarefas: nem todos fazem a mesma coisa no mesmo local.\n"
            "- Alimento abundante? Colete insumos para o futuro; planeje antes do inverno."
        ),
    },
}

# --- TOOLS (ações do MCP virtual) ---
# Ids na ordem canônica do preset. Descrição curta para a UI e para a tool.

IDS_TOOLS: list[str] = [
    "cacar", "pescar", "coletar_trigo", "coletar_erva", "coletar_madeira",
    "assar_carne", "assar_peixe", "fazer_pao", "preparar_remedio",
    "curar", "forragear", "passar",
]

DESCRICAO_TOOLS: dict[str, str] = {
    "cacar": "Caçar (comida fresca: carne).",
    "pescar": "Pescar (comida fresca: peixe).",
    "coletar_trigo": "Coletar trigo (insumo para pão).",
    "coletar_erva": "Coletar erva (insumo para remédio).",
    "coletar_madeira": "Coletar madeira (insumo para transformações).",
    "assar_carne": "Assar carne → carne_assada (comida de alto valor).",
    "assar_peixe": "Assar peixe → peixe_assado (comida de alto valor).",
    "fazer_pao": "Fazer pão a partir de trigo + madeira.",
    "preparar_remedio": "Preparar remédio a partir de erva + madeira.",
    "curar": "Curar um agente ferido (vida < 3); exige o índice do alvo.",
    "forragear": "Forragear: busca grátis de alimento (60% de +1).",
    "passar": "Passar a vez: custa 1 alimento e NÃO produz nada — evite, é desperdício. Use só sem alternativa melhor.",
}

# --- Padrão de SKILLS como TEXTO LIVRE ---
# As skills do agente passaram a ser um único texto editável (não mais uma lista
# de ids). O texto padrão é a concatenação das instruções das skills acima, na
# ordem canônica do catálogo. Isso vira o conteúdo inicial do campo `skills` de
# cada agente; o usuário pode reescrever à vontade pela UI.

def skills_texto_padrao() -> str:
    """Texto padrão das habilidades (concatenação das instruções do catálogo)."""
    return "\n\n".join(s["instrucao"] for s in SKILLS.values())


PADRAO_SKILLS: str = skills_texto_padrao()

# Tools continuam como lista de ids (checkboxes na UI).
PADRAO_TOOLS: list[str] = list(IDS_TOOLS)


# --- Helpers ---

def tools_publicas() -> list[dict]:
    """Lista de tools para a UI/API: [{id, nome, descricao}] em ordem canônica."""
    return [
        {"id": tid, "nome": tid, "descricao": DESCRICAO_TOOLS.get(tid, tid)}
        for tid in IDS_TOOLS
    ]


def tool_ids_validos(ids: list[str]) -> list[str]:
    """Filtra `ids` mantendo só tools conhecidas, na ordem canônica do preset."""
    pedidos = set(ids or [])
    return [tid for tid in IDS_TOOLS if tid in pedidos]
