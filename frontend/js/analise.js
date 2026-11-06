// analise.js — gráficos e tabelas de análise
document.getElementById("btn-carregar").addEventListener("click", async () => {
  const pid = parseInt(document.getElementById("f-pid").value);
  await carregar(pid);
});

async function carregar(pid) {
  document.getElementById("analise").hidden = false;
  try {
    await Promise.all([
      carregarEstoque(pid),
      carregarGanhosPerdas(pid),
      carregarVidas(pid),
      carregarEventos(pid),
      carregarConversas(pid),
      carregarDecisoes(pid),
    ]);
  } catch (e) { alert(e.message); }
}

// Se vier de URL (?pid=N), carrega automaticamente
(async () => {
  const params = new URLSearchParams(location.search);
  const pid = params.get("pid");
  if (pid) {
    document.getElementById("f-pid").value = pid;
    await carregar(parseInt(pid));
  }
})();

// Exportação CSV
window.exportarCsv = async (tipo) => {
  const pid = parseInt(document.getElementById("f-pid").value);
  window.open(`/partidas/${pid}/analise/${tipo}.csv`, "_blank");
};

async function carregarEstoque(pid) {
  const r = await API.analise(pid, "estoque");
  const div = document.getElementById("estoque");
  if (!r.turnos.length) { div.innerHTML = "<p>Sem dados.</p>"; return; }
  let html = "<table><tr><th>Turno</th>";
  const itens = Object.keys(r.turnos[0].itens);
  html += itens.map(i => `<th>${i}</th>`).join("") + "</tr>";
  for (const t of r.turnos) {
    html += `<tr><td>${t.turno}</td>` + itens.map(i => `<td>${t.itens[i] || 0}</td>`).join("") + "</tr>";
  }
  html += "</table>";
  div.innerHTML = html;
}

async function carregarGanhosPerdas(pid) {
  const r = await API.analise(pid, "ganhos-perdas");
  const div = document.getElementById("ganhos-perdas");
  if (!r.turnos.length) { div.innerHTML = "<p>Sem dados.</p>"; return; }
  let html = "<table><tr><th>Turno</th><th>Tipo</th><th>Item</th><th>Delta</th></tr>";
  for (const t of r.turnos) {
    for (const m of t.movimentos) {
      html += `<tr><td>${t.turno}</td><td>${m.tipo}</td><td>${m.item}</td><td>${m.delta}</td></tr>`;
    }
  }
  html += "</table>";
  div.innerHTML = html;
}

async function carregarVidas(pid) {
  const r = await API.analise(pid, "vidas");
  const div = document.getElementById("vidas");
  if (!r.eventos.length) { div.innerHTML = "<p>Sem eventos de vida.</p>"; return; }
  let html = "<table><tr><th>Turno</th><th>Agente</th><th>Antes</th><th>Depois</th><th>Motivo</th></tr>";
  for (const e of r.eventos) {
    html += `<tr><td>${e.turno}</td><td>${e.indice}</td><td>${e.vida_antes}</td><td>${e.vida_depois}</td><td>${e.motivo}</td></tr>`;
  }
  html += "</table>";
  div.innerHTML = html;
}

async function carregarEventos(pid) {
  const r = await API.analise(pid, "eventos");
  const div = document.getElementById("eventos");
  if (!r.turnos.length) { div.innerHTML = "<p>Sem turnos.</p>"; return; }
  let html = "<table><tr><th>Turno</th><th>Estação</th><th>Tempestade</th><th>Fartura</th><th>Doença</th><th>Praga</th></tr>";
  for (const t of r.turnos) {
    html += `<tr><td>${t.numero}</td><td>${t.estacao}</td><td>${!!t.tempestade}</td><td>${!!t.fartura}</td><td>${!!t.doenca}</td><td>${!!t.praga}</td></tr>`;
  }
  html += "</table>";
  div.innerHTML = html;
}

async function carregarConversas(pid) {
  const r = await API.analise(pid, "conversas");
  const div = document.getElementById("conversas");
  if (!r.mensagens.length) { div.innerHTML = "<p>Sem mensagens.</p>"; return; }
  let html = r.mensagens.map(m => {
    // Resiliente: aceita m.agente (novo alias) ou m.indice (compat)
    const agenteIdx = m.agente ?? m.indice;
    const ehSistema = m.agente === null || m.agente === undefined;
    const label = ehSistema ? 'Sistema' : `agente ${agenteIdx}`;
    return `
    <div class="msg${ehSistema ? ' sistema' : ''}"><span class="agente">T${m.turno}R${m.rodada} ${label}:</span> ${m.texto}
    ${m.intencao_declarada ? `<span class="intencao">(intenção: ${m.intencao_declarada})</span>` : ""}</div>
  `;}).join("");
  div.innerHTML = html;
}

async function carregarDecisoes(pid) {
  const r = await API.analise(pid, "decisoes");
  const div = document.getElementById("decisoes");
  if (!r.decisoes.length) { div.innerHTML = "<p>Sem decisões.</p>"; return; }
  let html = "<table><tr><th>Turno</th><th>Agente</th><th>Origem</th><th>Ação</th><th>Válida</th><th>Fallback</th><th>Latência (ms)</th></tr>";
  for (const d of r.decisoes) {
    let acao = "-";
    try { acao = JSON.parse(d.acao_json).acao; } catch {}
    html += `<tr><td>${d.turno}</td><td>${d.indice}</td><td>${d.origem}</td><td>${acao}</td><td>${!!d.valida}</td><td>${!!d.fallback}</td><td>${d.latencia_ms ?? "-"}</td></tr>`;
  }
  html += "</table>";
  div.innerHTML = html;
}

document.getElementById("btn-comparar").addEventListener("click", async () => {
  const a = parseInt(document.getElementById("f-a").value);
  const b = parseInt(document.getElementById("f-b").value);
  const div = document.getElementById("comparacao");
  try {
    const r = await API.comparar(a, b);
    if (!r.mesma_seed) {
      div.innerHTML = `<p><strong>Atenção:</strong> as seeds são diferentes (${r.a.seed} vs ${r.b.seed}). A comparação não é controlada.</p>`;
    } else {
      div.innerHTML = `<p>✓ Mesma seed (${r.a.seed})${r.mesmo_cenario ? " e mesmo cenário" : ""}.</p>`;
    }
    let html = `<table><tr><th></th><th>Partida A (#${r.a.id})</th><th>Partida B (#${r.b.id})</th></tr>`;
    html += `<tr><td>Seed</td><td>${r.a.seed}</td><td>${r.b.seed}</td></tr>`;
    html += `<tr><td>Decisor</td><td>${r.a.decisor}</td><td>${r.b.decisor}</td></tr>`;
    html += `<tr><td>Status</td><td>${r.a.status}</td><td>${r.b.status}</td></tr>`;
    html += `<tr><td>Turno atual</td><td>${r.a.turno_atual}/${r.a.n_turnos}</td><td>${r.b.turno_atual}/${r.b.n_turnos}</td></tr>`;
    if (r.a.resultado && r.b.resultado) {
      html += `<tr><td>Vivos</td><td>${r.a.resultado.n_vivos}</td><td>${r.b.resultado.n_vivos}</td></tr>`;
      html += `<tr><td>Vidas</td><td>${r.a.resultado.soma_vidas}</td><td>${r.b.resultado.soma_vidas}</td></tr>`;
      html += `<tr><td>Estoque</td><td>${r.a.resultado.valor_estoque}</td><td>${r.b.resultado.valor_estoque}</td></tr>`;
    }
    html += "</table>";
    if (r.diferencas && Object.keys(r.diferencas).length > 0) {
      html += "<h4>Diferenças</h4><ul>";
      for (const [k, v] of Object.entries(r.diferencas)) {
        html += `<li><strong>${k}</strong>: A=${v.a}, B=${v.b}</li>`;
      }
      html += "</ul>";
    }
    div.innerHTML = html;
  } catch (e) { div.innerHTML = "Erro: " + e.message; }
});
