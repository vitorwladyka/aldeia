// jogo.js — criar partida, iniciar, executar turnos (versão dark v4)
let partidaId = null;
let autoTimer = null;
let agenteEditando = null;
let agentesCache = [];        // últimos agentes carregados (com skills/tools)
let catalogoToolsCache = null;

// === Catálogo de serviços MCP ===
// Cada serviço = uma ação que o mundo expõe via MCP para os agentes consultarem
const SERVICOS_MCP = [
  { id: "cacar",           label: "cacar",         icon: "🏹", desc: "caçar carne" },
  { id: "pescar",          label: "pescar",        icon: "🎣", desc: "pescar peixe" },
  { id: "coletar_trigo",   label: "coletar_trigo", icon: "🌾", desc: "coletar trigo" },
  { id: "coletar_erva",    label: "coletar_erva",  icon: "🌿", desc: "coletar erva" },
  { id: "coletar_madeira", label: "coletar_madeira", icon: "🪵", desc: "coletar madeira" },
  { id: "forragear",       label: "forragear",     icon: "🍃", desc: "buscar alimento grátis" },
  { id: "transformar",     label: "transformar",   icon: "🔥", desc: "assar/fazer pão/remédio" },
  { id: "curar",           label: "curar",         icon: "💊", desc: "curar agente ferido" },
];

// Estilo (classe CSS + ícone + rótulo) por origem da decisão.
function estiloDecisor(origem) {
  if (origem === "llm") return { cls: "llm", icon: "🧠", label: "LLM" };
  if (origem === "bot") return { cls: "bot", icon: "🤖", label: "BOT" };
  if (origem === "regra") return { cls: "regra", icon: "📏", label: "REGRA" };
  return { cls: "lbm", icon: "⚡", label: "LBM" };
}

// === Inicialização ===
document.addEventListener("DOMContentLoaded", async () => {
  desenharMcpHub(new Set());  // desenha hub vazio na carga inicial
  const params = new URLSearchParams(location.search);
  const id = params.get("id");
  if (id) {
    partidaId = parseInt(id);
    await carregarEstado();
  }
});

// === Criar partida ===
document.getElementById("btn-criar").addEventListener("click", async () => {
  const decisor = document.getElementById("f-decisor").value;
  const dados = {
    nome: document.getElementById("f-nome").value || null,
    seed: document.getElementById("f-seed").value,
    n_agentes: parseInt(document.getElementById("f-n").value),
    n_turnos: parseInt(document.getElementById("f-turnos").value),
    decisor: decisor,
    rodadas_conselho: parseInt(document.getElementById("f-rodadas").value),
    lbm_habilitado: decisor === "llm" && document.getElementById("f-lbm").checked,
  };
  if (decisor === "llm") {
    try {
      const c = await API.configLlm();
      dados.llm_params = {
        provedor: c.provedor || "groq",
        base_url: c.base_url,
        model: c.model,
        temperature: c.temperature,
        modo: c.modo || (c.provedor === "groq" ? "tools" : "json"),
      };
    } catch (e) {
      alert("Não foi possível carregar config LLM: " + e.message);
      return;
    }
  }
  try {
    const p = await API.criarPartida(dados);
    partidaId = p.id;
    await carregarEstado();
  } catch (e) {
    alert("Erro ao criar: " + e.message);
  }
});

document.getElementById("f-decisor").addEventListener("change", (e) => {
  const ehLlm = e.target.value === "llm";
  document.getElementById("aviso-llm").hidden = !ehLlm;
  document.getElementById("label-lbm").hidden = !ehLlm;
});

document.getElementById("btn-iniciar").addEventListener("click", async () => {
  try { await API.iniciar(partidaId); await carregarEstado(); }
  catch (e) { alert(e.message); }
});

document.getElementById("btn-turno").addEventListener("click", async () => {
  const btn = document.getElementById("btn-turno");
  const btnAuto = document.getElementById("btn-auto");
  btn.disabled = true;
  btnAuto.disabled = true;  // não liga o automático no meio de um turno manual
  btn.textContent = "⏳ Executando...";
  try {
    const r = await API.turno(partidaId);
    await carregarEstado();
    log(`✓ Turno ${r.turno}: vivos=${(r.vivos||[]).length}, estoque=${r.placar?.valor_estoque}`);
    if (r.encerrada) {
      log("🏁 Partida encerrada!");
      if (autoTimer) { clearInterval(autoTimer); autoTimer = null; trocarAuto(false); }
    }
  } catch (e) {
    const msg = e.message || "";
    if (msg.includes("409")) {
      document.getElementById("btn-reset-lock").hidden = false;
      alert("Turno travado. Clique em 'Destravar' e tente de novo.");
    } else {
      alert(e.message);
    }
  } finally {
    btn.disabled = autoTimer !== null || btn.dataset.statusOk !== "1";
    btnAuto.disabled = btn.dataset.statusOk !== "1";
    btn.textContent = "▶ Próximo turno";
  }
});

document.getElementById("btn-reset-lock").addEventListener("click", async () => {
  try {
    await fetch(`/partidas/${partidaId}/reset-lock`, {method: "POST"});
    document.getElementById("btn-reset-lock").hidden = true;
    log("Lock destravado.");
  } catch (e) { alert("Erro: " + e.message); }
});

let autoOcupado = false;  // evita disparar um turno antes do anterior terminar

document.getElementById("btn-auto").addEventListener("click", () => {
  if (autoTimer) return;
  trocarAuto(true);
  autoTimer = setInterval(async () => {
    if (autoOcupado) return;
    autoOcupado = true;
    try {
      const r = await API.turno(partidaId);
      await carregarEstado();
      log(`✓ Turno ${r.turno}: vivos=${(r.vivos||[]).length}`);
      if (r.encerrada) {
        clearInterval(autoTimer); autoTimer = null; trocarAuto(false);
        log("🏁 Partida encerrada!");
      }
    } catch (e) {
      log("✗ Erro: " + e.message);
      clearInterval(autoTimer); autoTimer = null; trocarAuto(false);
    } finally {
      autoOcupado = false;
    }
  }, 2000);
});

document.getElementById("btn-parar-auto").addEventListener("click", () => {
  if (autoTimer) { clearInterval(autoTimer); autoTimer = null; }
  trocarAuto(false);
});

document.getElementById("btn-encerrar").addEventListener("click", async () => {
  if (!confirm("Encerrar a partida?")) return;
  try { await API.encerrar(partidaId); await carregarEstado(); }
  catch (e) { alert(e.message); }
});

document.getElementById("btn-retomar").addEventListener("click", async () => {
  try { await API.retomar(partidaId); await carregarEstado(); }
  catch (e) { alert(e.message); }
});

document.getElementById("btn-analise").addEventListener("click", () => {
  if (partidaId) window.location.href = `analise.html?pid=${partidaId}`;
});

// === Modal de prompt ===
document.getElementById("m-cancelar").addEventListener("click", () => {
  document.getElementById("modal-prompt").classList.remove("show");
  agenteEditando = null;
});

document.getElementById("m-salvar").addEventListener("click", async () => {
  const prompt = document.getElementById("m-prompt-texto").value;
  const skills = document.getElementById("m-skills-texto").value;
  const tools = Array.from(document.querySelectorAll(".m-tool:checked")).map(c => c.value);
  try {
    await API.configAgente(partidaId, agenteEditando, { prompt, skills, tools });
    document.getElementById("modal-prompt").classList.remove("show");
    log(`✓ Agente ${agenteEditando} salvo: ${tools.length} tools (vale no próximo turno).`);
    await carregarEstado();  // atualiza os contadores nos cards
  } catch (e) { alert("Erro ao salvar: " + e.message); }
});

document.getElementById("m-skills-padrao").addEventListener("click", restaurarSkillsPadrao);

function trocarAuto(rodando) {
  document.getElementById("btn-auto").hidden = rodando;
  document.getElementById("btn-parar-auto").hidden = !rodando;
  // Com o automático ligado, o turno manual fica bloqueado.
  const btnTurno = document.getElementById("btn-turno");
  btnTurno.disabled = rodando || btnTurno.dataset.statusOk !== "1";
  btnTurno.title = rodando ? "Pare o automático para avançar manualmente" : "";
}

// ====================================================================
// MCP HUB RADIAL — desenha SVG com serviços ao redor do nó central MCP
// ====================================================================
function desenharMcpHub(servicosAtivos) {
  const svg = document.getElementById("mcp-hub");
  if (!svg) return;

  const W = 480, H = 320;
  const cx = W / 2, cy = H / 2;
  const r = 110;  // raio do anel de serviços
  const nodeR = 32;  // raio de cada nó de serviço

  let html = "";

  // Conectores (linhas do centro para cada nó)
  SERVICOS_MCP.forEach((s, i) => {
    const angle = (i / SERVICOS_MCP.length) * 2 * Math.PI - Math.PI / 2;
    const x = cx + r * Math.cos(angle);
    const y = cy + r * Math.sin(angle);
    const active = servicosAtivos.has(s.id);
    html += `<line class="mcp-connector ${active ? 'active' : ''}"
              x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" />`;
  });

  // Nó central (MCP)
  html += `<circle class="mcp-center-circle" cx="${cx}" cy="${cy}" r="42" />`;
  html += `<text class="mcp-center-label" x="${cx}" y="${cy - 4}">MCP</text>`;
  html += `<text class="mcp-center-sublabel" x="${cx}" y="${cy + 12}">server</text>`;

  // Nós de serviços
  SERVICOS_MCP.forEach((s, i) => {
    const angle = (i / SERVICOS_MCP.length) * 2 * Math.PI - Math.PI / 2;
    const x = cx + r * Math.cos(angle);
    const y = cy + r * Math.sin(angle);
    const active = servicosAtivos.has(s.id);

    html += `<g style="cursor:help">
      <circle class="mcp-node-circle ${active ? 'active' : ''}"
              cx="${x}" cy="${y}" r="${nodeR}" />
      <text x="${x}" y="${y - 4}" style="font-size:18px;text-anchor:middle;dominant-baseline:middle;pointer-events:none">${s.icon}</text>
      <text class="mcp-node-label ${active ? 'active' : ''}"
            x="${x}" y="${y + 14}">${s.label}</text>
      <title>${s.label} — ${s.desc}${active ? ' (usado neste turno)' : ''}</title>
    </g>`;
  });

  svg.innerHTML = html;
}

// ====================================================================
// DECISÕES POR AGENTE — um cartão por agente no último turno
// ====================================================================
function escHtml(t) {
  return String(t ?? "").replace(/[&<>"']/g, c => (
    {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
}

function atualizarFlow(decisoes) {
  const resumoDiv = document.getElementById("flow-resumo");
  const decisionsDiv = document.getElementById("flow-decisions");
  const turnoLabel = document.getElementById("flow-turno");
  const THRESHOLD = 0.50;  // padrão do hibrido.py (marca na barra)

  if (!decisoes || decisoes.length === 0) {
    resumoDiv.innerHTML = "";
    turnoLabel.textContent = "(último turno)";
    decisionsDiv.innerHTML = '<p class="text-xs text-muted">Aguardando decisão…</p>';
    return;
  }

  const ultimoTurno = Math.max(...decisoes.map(d => d.turno));
  const doTurno = decisoes.filter(d => d.turno === ultimoTurno && d.oficial)
                          .sort((a, b) => a.indice - b.indice);
  turnoLabel.textContent = `(turno ${ultimoTurno})`;
  const nomeDe = i => (agentesCache.find(a => a.indice === i) || {}).nome || `Agente ${i}`;

  const contagem = {regra: 0, lbm: 0, llm: 0, bot: 0};
  const cartoes = doTurno.map(d => {
    let rb = {};
    try { rb = JSON.parse(d.resposta_bruta || "{}"); } catch {}
    let origem = rb.decidido_por || d.origem || "lbm";
    const escalonado = (d.modelo || "").includes("escalonado");
    if (escalonado) origem = "llm";
    contagem[origem] = (contagem[origem] || 0) + 1;

    let acao = "?", alvo = null;
    try { const a = JSON.parse(d.acao_json); acao = a.acao; alvo = a.alvo; } catch {}

    const conf = rb.confidence ?? rb.lbm_sugestao?.confidence ?? null;
    const estilo = estiloDecisor(origem);
    // A barra de confiança só faz sentido para a Laya (decisão ou sugestão escalada).
    const mostraBarra = conf !== null && (origem === "lbm" || escalonado);
    const barra = mostraBarra ? `
      <div class="confidence-bar-container">
        <div class="confidence-bar" title="limiar ${THRESHOLD.toFixed(2)}">
          <div class="confidence-bar-fill" style="width:${Math.round(conf * 100)}%"></div>
          <div class="confidence-threshold" style="left:${THRESHOLD * 100}%"></div>
        </div>
        <span class="confidence-value">${Number(conf).toFixed(2)}</span>
      </div>` : "";

    const raciocinio = String(rb.raciocinio || d._raciocinio || "")
      .replace(/^\[regra\]\s*/, "");
    const notaEscala = escalonado
      ? `<div class="cartao-nota aviso">⚠ Laya não resolveu — escalou para o LLM</div>` : "";
    const fallback = d.fallback
      ? `<div class="cartao-nota aviso">⚠ fallback (decisor indisponível)</div>` : "";
    const alvoTxt = alvo != null ? ` → ${escHtml(nomeDe(alvo))}` : "";
    const lat = d.latencia_ms ? `${d.latencia_ms} ms` : (origem === "regra" ? "instantâneo" : "");

    return `<div class="agente-cartao ${estilo.cls}">
      <div class="cartao-topo">
        <span class="cartao-nome">A${d.indice} ${escHtml(nomeDe(d.indice))}</span>
        <span class="decision-chip ${estilo.cls}" style="margin:0">${estilo.icon} ${estilo.label}</span>
      </div>
      <div class="cartao-acao">${escHtml(acao)}${alvoTxt}</div>
      ${barra}
      ${notaEscala}${fallback}
      ${raciocinio ? `<div class="cartao-raciocinio" title="${escHtml(raciocinio)}">${escHtml(raciocinio)}</div>` : ""}
      ${lat ? `<div class="cartao-meta">${lat}${d.modelo && !["lbm","regra","bot","llm","escalonado"].includes(d.modelo) ? ` • ${escHtml(d.modelo)}` : ""}</div>` : ""}
    </div>`;
  }).join("");

  const pilulas = [["regra", "📏 regras"], ["lbm", "⚡ Laya"], ["llm", "🧠 LLM"], ["bot", "🤖 bot"]]
    .filter(([k]) => contagem[k] > 0)
    .map(([k, rot]) => `<span class="decision-chip ${k}" style="margin:0">${contagem[k]} ${rot}</span>`)
    .join("");
  resumoDiv.innerHTML = pilulas;
  decisionsDiv.innerHTML = cartoes || '<p class="text-xs text-muted">—</p>';
}

// === Carregar estado ===
async function carregarEstado() {
  if (!partidaId) return;
  document.getElementById("form-nova").hidden = true;
  document.getElementById("painel").hidden = false;
  try {
    const estado = await API.estado(partidaId);

    const p = estado.partida;
    document.getElementById("p-titulo").textContent =
      `Partida #${p.id} — ${p.nome || "(sem nome)"} — seed ${p.seed}`;
    const status = document.getElementById("p-status");
    status.className = "status " + (p.status === "PAUSADA" ? "pausada" :
                                    p.status === "ENCERRADA" ? "encerrada" : "");
    let s = `<strong>${p.status}</strong>`;
    if (p.motivo_pausa) s += ` <span class="badge">${p.motivo_pausa}</span>`;
    s += ` <span>Turno <strong>${p.turno_atual}/${p.n_turnos}</strong></span>`;
    s += ` <span>Decisor: <strong>${p.decisor}</strong></span>`;
    if (p.decisor === "llm") {
      s += ` <span>LBM: <strong>${p.lbm_habilitado ? "ligado" : "desligado"}</strong></span>`;
    }
    s += ` <span>Conselho: <strong>${p.rodadas_conselho}</strong> passada(s) de discussão</span>`;
    status.innerHTML = s;

    // Botões
    document.getElementById("btn-iniciar").disabled = p.status !== "CRIADA";
    const btnTurno = document.getElementById("btn-turno");
    btnTurno.dataset.statusOk = p.status === "EM_ANDAMENTO" ? "1" : "0";
    btnTurno.disabled = p.status !== "EM_ANDAMENTO" || autoTimer !== null;
    document.getElementById("btn-auto").disabled = p.status !== "EM_ANDAMENTO";
    document.getElementById("btn-encerrar").disabled = p.status === "ENCERRADA";
    document.getElementById("btn-retomar").hidden = p.status !== "PAUSADA";

    // Estoque
    const t = document.getElementById("t-estoque");
    let html = "<tr><th>Item</th><th>Qtd</th><th>Valor</th></tr>";
    let totalPontos = 0;
    const valores = {
      trigo: 3, peixe: 4, carne: 6, pao: 18, peixe_assado: 22,
      carne_assada: 26, madeira: 2, erva: 2, remedio: 8,
    };
    for (const [item, qtd] of Object.entries(estado.estoque)) {
      const v = valores[item] || 0;
      totalPontos += v * qtd;
      const cor = qtd > 0 ? '' : 'color:var(--text-faint)';
      html += `<tr style="${cor}"><td>${item}</td><td>${qtd}</td><td>${v*qtd}</td></tr>`;
    }
    html += `<tr style="font-weight:600;background:var(--surface-3)"><td>alimento_solto</td><td>${estado.alimento_solto}</td><td>${estado.alimento_solto}</td></tr>`;
    html += `<tr style="font-weight:600;color:var(--success)"><td>TOTAL</td><td></td><td>${totalPontos + estado.alimento_solto}</td></tr>`;
    t.innerHTML = html;

    let disp = estado.alimento_solto;
    for (const item of ["peixe", "carne", "pao", "peixe_assado", "carne_assada"]) {
      disp += (valores[item] || 0) * (estado.estoque[item] || 0);
    }
    document.getElementById("d-disponivel").textContent = `🍽️ Alimento disponível: ${disp} pontos`;

    // Agentes
    const d = document.getElementById("d-agentes");
    d.innerHTML = "";
    agentesCache = estado.agentes;  // guarda para o modal (skills/tools)
    estado.agentes.forEach(a => {
      const card = document.createElement("div");
      card.className = "agente-card" + (a.status === "morto" ? " morto" : "");
      const nTools = (a.tools || []).length;
      card.innerHTML = `
        <div class="nome">${a.indice} ${a.nome}</div>
        <div class="vida">${"❤️".repeat(a.vida_atual)}${"🤍".repeat(3 - a.vida_atual)}</div>
        <div class="status-text">${a.status === "vivo" ? "🟢 vivo" : "💀 morto"}${a.morto_em_turno ? ` @T${a.morto_em_turno}` : ""}</div>
        <div class="text-xs text-muted">🛠️ ${nTools} tools</div>
        <div class="editar-link">✏️ editar agente</div>
      `;
      card.addEventListener("click", () => abrirPrompt(a.indice, a.nome));
      d.appendChild(card);
    });

    // Turno atual
    const ut = estado.ultimo_turno;
    if (ut) {
      let ordem = "";
      try { ordem = JSON.parse(ut.ordem_json).join(" → "); } catch {}

      const estacaoIcon = ut.estacao === "inverno" ? "❄️" : "☀️";
      const sinal = (ativo) => ativo ? '🟢' : '⚫';
      const sinalTexto = (ativo, sim, nao) => ativo ? sim : nao;

      document.getElementById("d-turno").innerHTML = `
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
          <div style="font-size:28px">${estacaoIcon}</div>
          <div>
            <div style="font-size:18px;font-weight:600;color:var(--text)">Turno ${ut.numero}</div>
            <div class="text-xs text-muted">de ${p.n_turnos} | ${ut.estacao === "inverno" ? "Inverno" : "Normal"}</div>
          </div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px">
          <div class="evento-card ${!!ut.tempestade ? 'ativo' : 'inativo'}">
            <div style="font-size:14px">${sinal(!!ut.tempestade)} ${!!ut.tempestade ? '⛈️' : '☀️'}</div>
            <div class="text-xs" style="font-weight:600">Tempestade</div>
            <div class="text-xs text-muted">${sinalTexto(!!ut.tempestade, 'pesca bloqueada', 'clima bom')}</div>
          </div>
          <div class="evento-card ${!!ut.fartura ? 'ativo' : 'inativo'}">
            <div style="font-size:14px">${sinal(!!ut.fartura)} ${!!ut.fartura ? '🌾' : '📦'}</div>
            <div class="text-xs" style="font-weight:600">Fartura</div>
            <div class="text-xs text-muted">${sinalTexto(!!ut.fartura, '+1 coletas', 'normal')}</div>
          </div>
          <div class="evento-card ${!!ut.doenca ? 'ativo' : 'inativo'}">
            <div style="font-size:14px">${sinal(!!ut.doenca)} ${!!ut.doenca ? '🤒' : '💪'}</div>
            <div class="text-xs" style="font-weight:600">Doença</div>
            <div class="text-xs text-muted">${sinalTexto(!!ut.doenca, 'alguém adoece', 'saudável')}</div>
          </div>
          <div class="evento-card ${!!ut.praga ? 'ativo' : 'inativo'}">
            <div style="font-size:14px">${sinal(!!ut.praga)} ${!!ut.praga ? '🐛' : '🛡️'}</div>
            <div class="text-xs" style="font-weight:600">Praga</div>
            <div class="text-xs text-muted">${sinalTexto(!!ut.praga, 'recurso perdido', 'protegido')}</div>
          </div>
        </div>
        <div class="text-xs text-muted" style="padding:6px;background:var(--surface-2);border-radius:var(--radius)">
          🎯 <strong>Ordem:</strong> <span class="text-mono">${ordem || "—"}</span>
        </div>
      `;
    } else {
      document.getElementById("d-turno").innerHTML =
        '<p class="text-muted text-sm">Nenhum turno executado. Clique em "Iniciar" e depois "Próximo turno".</p>';
    }

    // Carrega detalhes (histórico, conselho, decisões, ações, MCP, flow)
    await carregarDetalhesTurno();

  } catch (e) {
    document.getElementById("p-status").textContent = "Erro: " + e.message;
    console.error(e);
  }
}

// === Carregar detalhes ===
async function carregarDetalhesTurno() {
  if (!partidaId) return;
  try {
    const [eventos, conversas, decisoes, ganhosPerdas, vidas] = await Promise.all([
      API.analise(partidaId, "eventos"),
      API.analise(partidaId, "conversas"),
      API.analise(partidaId, "decisoes"),
      API.analise(partidaId, "ganhos-perdas"),
      API.analise(partidaId, "vidas"),
    ]);

    // === Atualiza o MCP HUB com serviços usados no último turno ===
    const servicosAtivos = new Set();
    if (decisoes.decisoes && decisoes.decisoes.length > 0) {
      const ultimoTurno = Math.max(...decisoes.decisoes.map(d => d.turno));
      decisoes.decisoes
        .filter(d => d.turno === ultimoTurno && d.oficial)
        .forEach(d => {
          try {
            const a = JSON.parse(d.acao_json);
            const acao = a.acao;
            // Mapeia ação -> serviço MCP
            if (acao === "cacar") servicosAtivos.add("cacar");
            else if (acao === "pescar") servicosAtivos.add("pescar");
            else if (acao === "coletar_trigo") servicosAtivos.add("coletar_trigo");
            else if (acao === "coletar_erva") servicosAtivos.add("coletar_erva");
            else if (acao === "coletar_madeira") servicosAtivos.add("coletar_madeira");
            else if (acao === "forragear") servicosAtivos.add("forragear");
            else if (acao === "curar") servicosAtivos.add("curar");
            else if (["assar_carne","assar_peixe","fazer_pao","preparar_remedio"].includes(acao)) {
              servicosAtivos.add("transformar");
            }
          } catch {}
        });
    }
    desenharMcpHub(servicosAtivos);

    // Resumo do MCP
    const mcpSummary = document.getElementById("mcp-summary");
    if (servicosAtivos.size > 0) {
      mcpSummary.innerHTML = `<span class="active-count">${servicosAtivos.size}</span> serviço(s) ativo(s) neste turno: ${[...servicosAtivos].join(", ")}`;
    } else {
      mcpSummary.textContent = "Aguardando turno…";
    }

    // === Atualiza o fluxo de decisão Laya → LLM ===
    atualizarFlow(decisoes.decisoes);

    // === Histórico de turnos (rico: eventos + ações + deltas + mortes) ===
    const hist = document.getElementById("d-historico");
    if (eventos.turnos && eventos.turnos.length > 0) {
      // Índices auxiliares para cruzar dados
      const movsPorTurno = {};
      (ganhosPerdas.turnos || []).forEach(t => {
        movsPorTurno[t.turno] = t.movimentos || [];
      });
      const decPorTurno = {};
      (decisoes.decisoes || []).forEach(d => {
        if (!d.oficial) return;
        if (!decPorTurno[d.turno]) decPorTurno[d.turno] = [];
        decPorTurno[d.turno].push(d);
      });
      const vidasPorTurno = {};
      (vidas.eventos || []).forEach(ev => {
        if (!vidasPorTurno[ev.turno]) vidasPorTurno[ev.turno] = [];
        vidasPorTurno[ev.turno].push(ev);
      });

      const turnoAtual = eventos.turnos[eventos.turnos.length - 1]?.numero;

      hist.innerHTML = eventos.turnos.map(t => {
        // Eventos do turno (clima, doença, praga)
        const evts = [];
        if (t.estacao === "inverno") evts.push("❄️");
        if (!!t.tempestade) evts.push("⛈️");
        if (!!t.fartura) evts.push("🌾");
        if (!!t.doenca) evts.push("🤒");
        if (!!t.praga) evts.push("🐛");
        const eventosStr = evts.length > 0 ? evts.join(" ") : "—";

        // Ações do turno (por agente, com origem lbm/llm)
        const acoesTurno = (decPorTurno[t.numero] || []).map(d => {
          let acao = "?", alvo = null;
          try { const a = JSON.parse(d.acao_json); acao = a.acao; alvo = a.alvo; } catch {}
          // Detecta decidido_por
          let decididoPor = "lbm";
          if (d.resposta_bruta) {
            try { const rb = JSON.parse(d.resposta_bruta); if (rb.decidido_por) decididoPor = rb.decidido_por; } catch {}
          }
          if (d.modelo && d.modelo.includes("escalonado")) decididoPor = "llm";
          const icones = {
            cacar: "🏹", pescar: "🎣", coletar_trigo: "🌾", coletar_erva: "🌿",
            coletar_madeira: "🪵", forragear: "🍃", curar: "💊",
            assar_carne: "🔥", assar_peixe: "🔥", fazer_pao: "🍞", preparar_remedio: "⚗️",
            passar: "⏸",
          };
          const ic = icones[acao] || "•";
          const alvoStr = alvo != null ? `→${alvo}` : "";
          return `<span class="turno-acao ${decididoPor}" title="${decididoPor.toUpperCase()}: ${acao}">
            ${ic} A${d.indice} ${acao}${alvoStr}
          </span>`;
        }).join("");

        // Movimentos do turno (ganhos/perdas resumidos)
        const movs = movsPorTurno[t.numero] || [];
        // Agrupa por item somando deltas
        const deltasPorItem = {};
        movs.forEach(m => {
          if (!deltasPorItem[m.item]) deltasPorItem[m.item] = 0;
          deltasPorItem[m.item] += m.delta;
        });
        const statsStr = Object.entries(deltasPorItem).map(([item, delta]) => {
          const cls = delta > 0 ? "delta-pos" : "delta-neg";
          const sinal = delta > 0 ? "+" : "";
          return `<span class="turno-stat">${item}=<span class="${cls}">${sinal}${delta}</span></span>`;
        }).join("");

        // Eventos de vida (mortes e perdas)
        const evsVida = vidasPorTurno[t.numero] || [];
        const mortes = evsVida.filter(ev => ev.vida_depois === 0);
        const perdasVida = evsVida.filter(ev => ev.vida_depois > 0 && ev.vida_depois < ev.vida_antes);
        let vidasStr = "";
        if (mortes.length > 0) {
          vidasStr += mortes.map(m => `<span class="turno-acao morte">💀 A${m.indice} morreu (${m.motivo})</span>`).join("");
        }
        if (perdasVida.length > 0) {
          vidasStr += perdasVida.map(m => `<span class="turno-acao" style="color:var(--warning)">💔 A${m.indice} ${m.vida_antes}→${m.vida_depois} (${m.motivo})</span>`).join("");
        }

        // Classes do card
        const isAtual = t.numero === turnoAtual;
        const isCritico = mortes.length > 0;
        const isInverno = t.estacao === "inverno";
        const rowCls = ["turno-row"];
        if (isAtual) rowCls.push("atual");
        if (isInverno) rowCls.push("inverno");
        if (isCritico) rowCls.push("critico");

        // Badge de estação
        const badgeCls = isCritico ? "critico" : (isInverno ? "inverno" : "normal");
        const badgeText = isCritico ? "💀 morte" : (isInverno ? "❄️ inverno" : "☀️ normal");
        const atualTag = isAtual ? ' <span style="color:var(--accent);font-size:10px;font-weight:600">● AGORA</span>' : "";

        return `<div class="${rowCls.join(" ")}">
          <div class="turno-head">
            <span><span class="turno-num">T${t.numero}</span>${atualTag}</span>
            <span>
              <span class="turno-badge ${badgeCls}">${badgeText}</span>
              <span class="turno-eventos" style="margin-left:6px">${eventosStr}</span>
            </span>
          </div>
          ${acoesTurno ? `<div class="turno-acoes">${acoesTurno}</div>` : ""}
          ${statsStr ? `<div class="turno-stats">${statsStr}</div>` : ""}
          ${vidasStr ? `<div class="turno-acoes" style="margin-top:4px">${vidasStr}</div>` : ""}
        </div>`;
      }).reverse().join("");
    } else {
      hist.innerHTML = '<div class="turno-empty">Sem turnos executados.</div>';
    }

    // === Conselho ===
    const cons = document.getElementById("d-conselho");
    if (conversas.mensagens && conversas.mensagens.length > 0) {
      const porTurno = {};
      conversas.mensagens.forEach(m => {
        if (!porTurno[m.turno]) porTurno[m.turno] = [];
        porTurno[m.turno].push(m);
      });
      const turnos = Object.keys(porTurno).sort((a,b) => b - a);
      cons.innerHTML = turnos.map(t => {
        const msgs = porTurno[t].map(m => {
          // Resiliente: aceita m.agente (novo alias) ou m.indice (compat)
          const agenteIdx = m.agente ?? m.indice;
          const ehSistema = m.agente === null || m.agente === undefined;
          const label = ehSistema ? 'Sistema' : `Agente ${agenteIdx}`;
          return `
          <div class="conselho-msg${ehSistema ? ' sistema' : ''}">
            <span class="agente-nome">R${m.rodada} — ${label}:</span>
            ${m.texto}
            ${m.intencao_declarada ? `<span class="intencao">(intenção: ${m.intencao_declarada})</span>` : ""}
          </div>
        `;}).join("");
        return `<div style="margin-bottom:8px"><strong>Turno ${t}:</strong>${msgs}</div>`;
      }).join("");
    } else {
      cons.innerHTML = '<p class="text-muted text-sm">Sem mensagens. O conselho (propostas e discussão) acontece com o decisor LLM, para os agentes que a Laya não resolveu.</p>';
    }

    // === Decisões detalhadas ===
    const dec = document.getElementById("d-decisoes");
    if (decisoes.decisoes && decisoes.decisoes.length > 0) {
      const ultimoTurno = Math.max(...decisoes.decisoes.map(d => d.turno));
      const doTurno = decisoes.decisoes.filter(d => d.turno === ultimoTurno && d.oficial);
      dec.innerHTML = `<p class="text-xs text-muted" style="margin-bottom:6px"><strong>Turno ${ultimoTurno}:</strong></p>` +
        doTurno.map(d => {
          let acao = "?", alvo = null;
          try { const a = JSON.parse(d.acao_json); acao = a.acao; alvo = a.alvo; } catch {}
          const categoria = ["cacar","pescar","coletar_trigo","coletar_erva","coletar_madeira"].includes(acao) ? "coletar" :
                            ["assar_carne","assar_peixe","fazer_pao","preparar_remedio"].includes(acao) ? "transformar" :
                            acao === "curar" ? "curar" :
                            acao === "forragear" ? "forragear" : "passar";
          const fallback = !!d.fallback;
          // Detecta decidido_por
          let decididoPor = "lbm";
          if (d.resposta_bruta) {
            try {
              const rb = JSON.parse(d.resposta_bruta);
              if (rb.decidido_por) decididoPor = rb.decidido_por;
            } catch {}
          }
          if (d.modelo && d.modelo.includes("escalonado")) decididoPor = "llm";
          const estilo = estiloDecisor(decididoPor);
          return `<div class="decisao-linha ${d.valida ? 'valida' : ''} ${fallback ? 'fallback' : ''}">
            <span class="agente-nome">A${d.indice}</span>
            <span class="acao-badge ${categoria} ${fallback ? 'fallback' : ''}">${acao}${alvo != null ? ` → ${alvo}` : ''}</span>
            <span class="decision-chip ${estilo.cls}" style="margin:0">${estilo.icon} ${estilo.label}</span>
            ${fallback ? '<span class="erro">⚠ FALLBACK</span>' : ''}
            ${d.erro ? `<div class="erro">Erro: ${d.erro.substring(0, 150)}</div>` : ''}
            <div class="meta">${d.modelo || decididoPor} | latência: ${d.latencia_ms || '?'}ms${d.tokens_in ? ` | tokens: ${d.tokens_in}→${d.tokens_out}` : ''}</div>
          </div>`;
        }).join("");
    } else {
      dec.innerHTML = '<p class="text-muted text-sm">Sem decisões ainda.</p>';
    }

    // === Ações executadas ===
    const acoes = document.getElementById("d-acoes");
    if (ganhosPerdas.turnos && ganhosPerdas.turnos.length > 0) {
      const ultimo = ganhosPerdas.turnos[ganhosPerdas.turnos.length - 1];
      if (ultimo.movimentos && ultimo.movimentos.length > 0) {
        const porTipo = {};
        ultimo.movimentos.forEach(m => {
          if (!porTipo[m.tipo]) porTipo[m.tipo] = [];
          porTipo[m.tipo].push(m);
        });
        const tipos = ["basal", "pagamento", "coleta", "preparo", "cura", "forragem", "praga"];
        const icones = { basal: "🍽️", pagamento: "💸", coleta: "📦", preparo: "🍳", cura: "💊", forragem: "🌿", praga: "🐛" };
        acoes.innerHTML = `<p class="text-xs text-muted" style="margin-bottom:6px"><strong>Turno ${ultimo.turno}:</strong></p>` +
          tipos.filter(t => porTipo[t]).map(tipo => {
            const movs = porTipo[tipo];
            return `<div style="margin-bottom:6px">
              <div class="text-xs" style="font-weight:600;color:var(--text-secondary)">${icones[tipo] || "•"} ${tipo}</div>
              ${movs.map(m => {
                const sinal = m.delta > 0 ? '+' : '';
                const cor = m.delta > 0 ? 'var(--success)' : 'var(--danger)';
                return `<div class="text-sm" style="padding:2px 10px">
                  <span style="color:${cor};font-weight:600;font-family:'JetBrains Mono',monospace">${sinal}${m.delta}</span>
                  ${m.item}
                </div>`;
              }).join("")}
            </div>`;
          }).join("");
      } else {
        acoes.innerHTML = '<p class="text-muted text-sm">Sem movimentos no último turno.</p>';
      }
    } else {
      acoes.innerHTML = '<p class="text-muted text-sm">Sem ações ainda.</p>';
    }

  } catch (e) {
    console.error("Erro ao carregar detalhes:", e);
  }
}

// === Abrir modal de edição do agente (prompt + skills + tools) ===
async function abrirPrompt(indice, nome) {
  agenteEditando = indice;
  document.getElementById("m-agente-nome").textContent = `${indice} (${nome})`;
  document.getElementById("modal-prompt").classList.add("show");

  // Carrega catálogo de tools (uma vez)
  try {
    if (!catalogoToolsCache) catalogoToolsCache = (await API.catalogoTools()).tools;
  } catch (e) {
    console.error("Erro ao carregar catálogo de tools:", e);
    catalogoToolsCache = catalogoToolsCache || [];
  }

  const ag = agentesCache.find(a => a.indice === indice) || {};
  const toolsAtivas = new Set(ag.tools || []);

  // Prompt principal
  try {
    const r = await API.obterPrompt(partidaId, indice);
    document.getElementById("m-prompt-texto").value = r.texto || ag.prompt || "";
  } catch {
    document.getElementById("m-prompt-texto").value = ag.prompt || "";
  }

  // Skills — texto livre
  document.getElementById("m-skills-texto").value = ag.skills || "";

  // Tools — checkboxes (ações do MCP)
  document.getElementById("m-tools").innerHTML = catalogoToolsCache.map(t => `
    <label class="check-item" title="${t.descricao}">
      <input type="checkbox" class="m-tool" value="${t.id}" ${toolsAtivas.has(t.id) ? "checked" : ""}>
      <span><strong>${t.id}</strong> <span class="text-xs text-muted">${t.descricao}</span></span>
    </label>`).join("");
}

// Restaura o texto padrão de habilidades no campo de skills
async function restaurarSkillsPadrao() {
  try {
    const r = await API.skillsPadrao();
    document.getElementById("m-skills-texto").value = r.texto || "";
  } catch (e) { alert("Erro ao carregar padrão: " + e.message); }
}

function log(msg) {
  const d = document.getElementById("d-log");
  d.innerHTML = `<div class="msg">${msg}</div>` + d.innerHTML;
}
