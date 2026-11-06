"""Servidor FastAPI — serve a API e os arquivos estáticos do frontend.

Rotas (compatíveis com `frontend/js/api.js`):
- GET  /partidas                       — lista partidas
- POST /partidas                       — cria partida
- GET  /partidas/{id}                  — metadados da partida
- POST /partidas/{id}/iniciar          — inicia
- POST /partidas/{id}/turno            — executa próximo turno
- POST /partidas/{id}/encerrar         — encerra
- POST /partidas/{id}/retomar          — destrava (alias)
- POST /partidas/{id}/reset-lock       — destrava
- GET  /partidas/{id}/estado           — estado atual
- GET  /partidas/{id}/agentes/{aid}/prompt
- PUT  /partidas/{id}/agentes/{aid}/prompt
- GET  /partidas/{id}/analise/{tipo}   — JSON (estoque, ganhos-perdas, vidas, eventos, conversas, decisoes)
- GET  /partidas/{id}/analise/{tipo}.csv — CSV
- GET  /config/llm                     — lê config_llm.json
- PUT  /config/llm                     — salva config_llm.json
- POST /config/llm/testar              — testa LLM (z-ai chat)
- GET  /config/lbm                     — lê config_lbm.json
- PUT  /config/lbm                     — salva config_lbm.json
- GET  /config/lbm/perfis              — lista perfis
- POST /config/lbm/testar              — testa LBM (heurística)
- GET  /comparar?a=X&b=Y               — compara duas partidas
- DELETE /partidas                     — limpa tudo (usado pelo botão 🗑️)
- /  →  serve frontend/index.html e estáticos

Rodar:  python server.py   (ou uvicorn server:app --reload)
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse, Response, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import partida
import armazenamento
from mcp_mundo import config_mcp

ROOT = Path(__file__).parent
CAMINHO_CONFIG_LLM = ROOT / "config_llm.json"
CAMINHO_CONFIG_LBM = ROOT / "config_lbm.json"
FRONTEND_DIR = ROOT / "frontend"

app = FastAPI(title="Aldeia de Agentes", version="1.0")


# ==================== Partidas ====================


@app.get("/partidas")
def listar_partidas():
    return armazenamento.listar()


class CriarPartidaReq(BaseModel):
    nome: str | None = None
    seed: str | int = "42"
    n_agentes: int = 5
    n_turnos: int = 20
    decisor: str = "llm"
    rodadas_conselho: int = 1
    lbm_habilitado: bool = True
    # Aceito mas não persistido aqui (config LLM vive em config_llm.json);
    # o frontend envia para compatibilidade.
    llm_params: dict | None = None


@app.post("/partidas")
def criar_partida(req: CriarPartidaReq):
    try:
        seed = int(str(req.seed))
        p = partida.criar(req.nome, seed, req.n_agentes, req.n_turnos,
                          req.decisor, req.rodadas_conselho,
                          req.lbm_habilitado)
        # Não retornar _estado para o cliente
        p.pop("_estado", None)
        return p
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/admin/limpar")
def admin_limpar():
    """Alias do DELETE /partidas — limpa todo o histórico.
    Mantido para compat com frontend/js/index.js que chama POST /admin/limpar.
    """
    armazenamento.limpar_tudo()
    return {"ok": True}


@app.delete("/partidas")
def limpar_partidas():
    armazenamento.limpar_tudo()
    return {"ok": True}


@app.get("/partidas/{pid}")
def obter_partida(pid: int):
    p = armazenamento.carregar(pid)
    if p is None:
        raise HTTPException(404, f"partida {pid} não encontrada")
    p.pop("_estado", None)
    return p


@app.post("/partidas/{pid}/iniciar")
def iniciar_partida(pid: int):
    try:
        p = partida.iniciar(pid)
        p.pop("_estado", None)
        return p
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/partidas/{pid}/turno")
def executar_turno(pid: int):
    try:
        p = partida.executar_turno(pid)
        p.pop("_estado", None)
        return p
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/partidas/{pid}/encerrar")
def encerrar_partida(pid: int):
    try:
        p = partida.encerrar(pid)
        p.pop("_estado", None)
        return p
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/partidas/{pid}/retomar")
def retomar_partida(pid: int):
    try:
        p = partida.retomar(pid)
        p.pop("_estado", None)
        return p
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/partidas/{pid}/reset-lock")
def reset_lock_partida(pid: int):
    return retomar_partida(pid)


@app.get("/partidas/{pid}/estado")
def estado_partida(pid: int):
    try:
        return partida.estado_atual(pid)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/partidas/{pid}/agentes/{aid}/prompt")
def obter_prompt(pid: int, aid: int):
    try:
        return {"texto": partida.obter_prompt(pid, aid)}
    except Exception as e:
        raise HTTPException(400, str(e))


class EditarPromptReq(BaseModel):
    texto: str


@app.put("/partidas/{pid}/agentes/{aid}/prompt")
def editar_prompt(pid: int, aid: int, req: EditarPromptReq):
    try:
        p = partida.editar_prompt(pid, aid, req.texto)
        p.pop("_estado", None)
        return p
    except Exception as e:
        raise HTTPException(400, str(e))


class EditarConfigReq(BaseModel):
    prompt: str | None = None
    skills: str | None = None       # texto livre (habilidades)
    tools: list[str] | None = None  # lista de ids (ações do MCP)


@app.put("/partidas/{pid}/agentes/{aid}/config")
def editar_config(pid: int, aid: int, req: EditarConfigReq):
    try:
        p = partida.editar_config(pid, aid, req.prompt, req.skills, req.tools)
        p.pop("_estado", None)
        return p
    except Exception as e:
        raise HTTPException(400, str(e))


# ==================== Catálogo (tools) ====================
# Skills são texto livre por agente (sem catálogo de opções). Só as tools têm
# catálogo (as ações do MCP virtual).


@app.get("/catalogo/tools")
def catalogo_tools():
    from agentes import catalogo as _cat
    return {"tools": _cat.tools_publicas()}


@app.get("/catalogo/skills-padrao")
def catalogo_skills_padrao():
    """Texto padrão de habilidades (para a UI oferecer 'restaurar padrão')."""
    from agentes import catalogo as _cat
    return {"texto": _cat.PADRAO_SKILLS}


# ==================== Análise ====================


@app.get("/partidas/{pid}/analise/{tipo}")
def analise(pid: int, tipo: str):
    """Retorna JSON com dados estruturados para a página de Análise.

    Lê do `historico` persistido (uma entrada por turno, com decisoes,
    movimentos, eventos_vida, etc.).
    """
    p = armazenamento.carregar(pid)
    if p is None:
        raise HTTPException(404, f"partida {pid} não encontrada")

    if tipo == "estoque":
        # turnos: [{turno: int, itens: {item: qtd}}]
        # Itens = saldo final em cada turno (acumulado a partir do estoque_inicial)
        saldo = dict(p["estoque_inicial"])
        turnos = []
        for t in p["historico"]:
            for m in t.get("movimentos", []):
                if m["item"] != "alimento_solto":
                    saldo[m["item"]] = saldo.get(m["item"], 0) + m["delta"]
            turnos.append({"turno": t["turno"], "itens": dict(saldo)})
        return {"turnos": turnos}

    if tipo == "ganhos-perdas":
        turnos = []
        for t in p["historico"]:
            turnos.append({
                "turno": t["turno"],
                "movimentos": t.get("movimentos", []),
            })
        return {"turnos": turnos}

    if tipo == "vidas":
        eventos = []
        for t in p["historico"]:
            for e in t.get("eventos_vida", []):
                # Preenche o turno (não vem no evento)
                eventos.append({
                    "turno": t["turno"],
                    "indice": e["indice"],
                    "vida_antes": e["vida_antes"],
                    "vida_depois": e["vida_depois"],
                    "motivo": e["motivo"],
                })
        return {"eventos": eventos}

    if tipo == "eventos":
        turnos = []
        for t in p["historico"]:
            turnos.append({
                "numero": t["turno"],
                "estacao": t.get("estacao", "normal"),
                "tempestade": t.get("tempestade", False),
                "fartura": t.get("fartura", False),
                "doenca": t.get("doenca", []),
                "praga": t.get("praga"),
            })
        return {"turnos": turnos}

    if tipo == "conversas":
        return {"mensagens": p.get("mensagens", [])}

    if tipo == "decisoes":
        # Achata todas as decisões de todos os turnos do histórico
        decisoes = []
        for t in p["historico"]:
            for d in t.get("decisoes", []):
                # Garante que turno está no dicionário
                dd = dict(d)
                dd["turno"] = t["turno"]
                decisoes.append(dd)
        return {"decisoes": decisoes}

    raise HTTPException(404, f"tipo de análise desconhecido: {tipo}")


@app.get("/partidas/{pid}/analise/{tipo}.csv")
def analise_csv(pid: int, tipo: str):
    """Exporta CSV simples do tipo solicitado."""
    dados = analise(pid, tipo).body  # já é JSON
    d = json.loads(dados)
    linhas = []
    if tipo == "estoque":
        linhas.append("turno,item,quantidade")
        for t in d["turnos"]:
            for item, qtd in t["itens"].items():
                linhas.append(f"{t['turno']},{item},{qtd}")
    elif tipo == "ganhos-perdas":
        linhas.append("turno,tipo,item,delta")
        for t in d["turnos"]:
            for m in t["movimentos"]:
                linhas.append(f"{t['turno']},{m['tipo']},{m['item']},{m['delta']}")
    else:
        linhas.append(f"# {tipo}")
        linhas.append(json.dumps(d, ensure_ascii=False))
    csv = "\n".join(linhas) + "\n"
    return Response(content=csv, media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={tipo}.csv"})


# ==================== Comparar ====================


@app.get("/comparar")
def comparar(a: int, b: int):
    pa = armazenamento.carregar(a)
    pb = armazenamento.carregar(b)
    if pa is None or pb is None:
        raise HTTPException(404, "partida não encontrada")

    mesma_seed = pa["seed"] == pb["seed"]
    mesmo_cenario = pa.get("cenario_hash") == pb.get("cenario_hash")

    def resumo(p):
        if p.get("placar_final"):
            return p["placar_final"]
        return None

    diferencas = {}
    if pa["decisor"] != pb["decisor"]:
        diferencas["decisor"] = {"a": pa["decisor"], "b": pb["decisor"]}
    if pa["status"] != pb["status"]:
        diferencas["status"] = {"a": pa["status"], "b": pb["status"]}

    return {
        "a": {"id": pa["id"], "seed": pa["seed"], "decisor": pa["decisor"],
              "status": pa["status"], "turno_atual": pa["turno_atual"],
              "n_turnos": pa["n_turnos"], "resultado": resumo(pa)},
        "b": {"id": pb["id"], "seed": pb["seed"], "decisor": pb["decisor"],
              "status": pb["status"], "turno_atual": pb["turno_atual"],
              "n_turnos": pb["n_turnos"], "resultado": resumo(pb)},
        "mesma_seed": mesma_seed,
        "mesmo_cenario": mesmo_cenario,
        "diferencas": diferencas,
    }


# ==================== Configuração LLM ====================


def _ler_config(caminho: Path, padrao: dict) -> dict:
    if caminho.exists():
        try:
            return json.loads(caminho.read_text(encoding="utf-8"))
        except Exception:
            return dict(padrao)
    return dict(padrao)


def _salvar_config(caminho: Path, dados: dict) -> None:
    caminho.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")


PADRAO_LLM = {
    "provedor": "zai",
    "model": "z-ai-chat",
    "base_url": "",
    "api_key_configured": False,
    "temperature": 0.7,
    "modo": "json",
}


@app.get("/config/llm")
def get_config_llm():
    import config_env
    cfg = _ler_config(CAMINHO_CONFIG_LLM, PADRAO_LLM)
    cfg.pop("api_key", None)  # nunca devolve a chave
    # O flag reflete a presença de GROQ_API_KEY no ambiente (.env).
    cfg["api_key_configured"] = bool(config_env.api_key())
    return cfg


@app.put("/config/llm")
async def put_config_llm(req: Request):
    body = await req.body()
    dados = json.loads(body.decode("utf-8"))
    cfg_atual = _ler_config(CAMINHO_CONFIG_LLM, PADRAO_LLM)
    # A api_key NÃO é persistida no JSON — segredo vive só no .env (GROQ_API_KEY).
    dados.pop("api_key", None)
    cfg_atual.update(dados)
    cfg_atual.pop("api_key", None)
    import config_env
    cfg_atual["api_key_configured"] = bool(config_env.api_key())
    _salvar_config(CAMINHO_CONFIG_LLM, cfg_atual)
    return cfg_atual


class TestarLlmReq(BaseModel):
    provedor: str | None = "zai"
    model: str | None = None
    base_url: str | None = None
    modo: str | None = None
    api_key: str | None = None


@app.post("/config/llm/testar")
def testar_llm(req: TestarLlmReq):
    """Testa o LLM chamando a API do provedor (Groq ou OpenAI-compat) via httpx."""
    import httpx
    import config_env
    t0 = time.time()
    try:
        # A chave vem do .env (GROQ_API_KEY); o body pode sobrepor para teste.
        api_key = req.api_key or config_env.api_key()
        if not api_key:
            return {"ok": False, "erro": "sem API key — defina GROQ_API_KEY no .env",
                    "latencia_ms": 0, "modelo": req.model or "?"}

        # Endpoint por provedor
        if req.provedor == "groq":
            url = "https://api.groq.com/openai/v1/chat/completions"
            model = req.model or "llama-3.3-70b-versatile"
        else:  # openai ou compatível
            url = req.base_url or "https://api.openai.com/v1/chat/completions"
            if not url.endswith("/chat/completions"):
                url = url.rstrip("/") + "/chat/completions"
            model = req.model or "gpt-4o-mini"

        with httpx.Client(timeout=30) as client:
            r = client.post(url,
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                json={"model": model,
                      "messages": [{"role": "user", "content": "Responda apenas: OK"}],
                      "temperature": 0.7,
                      "max_tokens": 10})
        lat = int((time.time() - t0) * 1000)
        if r.status_code != 200:
            return {"ok": False, "erro": f"HTTP {r.status_code}: {r.text[:200]}",
                    "latencia_ms": lat, "modelo": model}
        data = r.json()
        resposta = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"ok": True, "latencia_ms": lat, "modelo": model,
                "resposta": resposta[:200]}
    except httpx.TimeoutException:
        return {"ok": False, "erro": "timeout (30s)", "latencia_ms": 30000,
                "modelo": req.model or "?"}
    except Exception as e:
        return {"ok": False, "erro": str(e),
                "latencia_ms": int((time.time() - t0) * 1000),
                "modelo": req.model or "?"}


def testar_llm(req: TestarLlmReq):
    """Testa o LLM chamando `z-ai chat` com um prompt curto."""
    t0 = time.time()
    try:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            out_path = f.name
        r = subprocess.run(
            ["z-ai", "chat", "--prompt", "Responda apenas: OK",
             "--output", out_path],
            capture_output=True, text=True, timeout=30,
        )
        lat = int((time.time() - t0) * 1000)
        if r.returncode != 0:
            return {"ok": False, "erro": r.stderr[:300] or "falha desconhecida",
                    "latencia_ms": lat, "modelo": req.model or "z-ai"}
        data = json.loads(Path(out_path).read_text(encoding="utf-8"))
        resposta = (data.get("content") or
                    (data.get("choices", [{}])[0].get("message", {}).get("content", "")))
        Path(out_path).unlink(missing_ok=True)
        return {"ok": True, "latencia_ms": lat, "modelo": req.model or "z-ai",
                "resposta": resposta[:200]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "erro": "timeout (30s)", "latencia_ms": 30000,
                "modelo": req.model or "z-ai"}
    except Exception as e:
        return {"ok": False, "erro": str(e), "latencia_ms": int((time.time() - t0) * 1000),
                "modelo": req.model or "z-ai"}


# ==================== Configuração LBM ====================


@app.get("/config/lbm")
def get_config_lbm():
    cfg = _ler_config(CAMINHO_CONFIG_LBM, {})
    cfg.pop("api_key", None)
    return cfg


@app.put("/config/lbm")
async def put_config_lbm(req: Request):
    body = await req.body()
    dados = json.loads(body.decode("utf-8"))
    cfg_atual = _ler_config(CAMINHO_CONFIG_LBM, {})
    cfg_atual.update(dados)
    if "api_key" in dados and dados["api_key"]:
        cfg_atual["api_key_configured"] = True
    cfg_atual.pop("api_key", None)
    _salvar_config(CAMINHO_CONFIG_LBM, cfg_atual)
    return cfg_atual


@app.get("/config/lbm/perfis")
def perfis_lbm():
    cfg = _ler_config(CAMINHO_CONFIG_LBM, {"perfis": {}})
    return {"perfis": list(cfg.get("perfis", {}).keys())}


@app.post("/config/lbm/testar")
def testar_lbm():
    """Testa o LBM — roda a heurística numa observação sintética."""
    from decisores import lbm
    t0 = time.time()
    try:
        obs_sintetica = {
            "versao": 1,
            "partida": {"turno": 1, "turnos_total": 20, "estacao": "normal",
                        "clima": {"tempestade": False, "fartura": False}},
            "eu": {"agente": 0, "nome": "Aria", "vida": 3},
            "agentes": [{"agente": 0, "nome": "Aria", "vida": 3, "status": "vivo"}],
            "estoque": {"alimento_solto": 0,
                        "itens": {"trigo": 0, "peixe": 0, "carne": 0, "pao": 0,
                                  "peixe_assado": 0, "carne_assada": 0,
                                  "madeira": 0, "erva": 0, "remedio": 0}},
            "historico": [], "mensagens": [],
            "acoes_viaveis": [{"acao": "forragear", "custo": 0, "alvos": None},
                              {"acao": "passar", "custo": 1, "alvos": None}],
        }
        d = lbm.decidir(obs_sintetica, "", 0)
        lat = int((time.time() - t0) * 1000)
        return {"ok": True, "latencia_ms": lat,
                "mensagem": f"acao={d.acao} conf={d.confianca:.2f} origem={d.origem}"}
    except Exception as e:
        return {"ok": False, "latencia_ms": int((time.time() - t0) * 1000),
                "mensagem": str(e)}


# ==================== Static frontend ====================


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


# Monta estáticos em /css, /js, e arquivos .html soltos
app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")

# Alias /frontend/* → serve o mesmo conteúdo (compatibilidade)
app.mount("/frontend/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="frontend-css")
app.mount("/frontend/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="frontend-js")


@app.get("/frontend/{pagina}.html")
def frontend_pagina_html(pagina: str):
    p = FRONTEND_DIR / f"{pagina}.html"
    if not p.exists() or not p.is_file():
        raise HTTPException(404, f"página {pagina} não encontrada")
    return FileResponse(p)


@app.get("/frontend/")
@app.get("/frontend")
def frontend_index():
    return FileResponse(FRONTEND_DIR / "index.html")





# Rota coringa para os outros .html (jogo.html, config.html, etc.)
@app.get("/{pagina}.html")
def pagina_html(pagina: str):
    p = FRONTEND_DIR / f"{pagina}.html"
    if not p.exists() or not p.is_file():
        raise HTTPException(404, f"página {pagina} não encontrada")
    return FileResponse(p)


if __name__ == "__main__":
    import uvicorn
    # Escuta apenas em localhost (acesso só a partir desta máquina).
    uvicorn.run(app, host="127.0.0.1", port=8000)
