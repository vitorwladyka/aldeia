// index.js — lista partidas recentes + botão limpar
async function carregarPartidas() {
  try {
    const partidas = await API.listarPartidas();
    const div = document.getElementById("partidas");
    if (!partidas.length) {
      div.innerHTML = "<p>Nenhuma partida ainda.</p>";
      return;
    }
    const html = partidas.map(p => {
      const statusColor = p.status === "ENCERRADA" ? "#27ae60" :
                          p.status === "PAUSADA" ? "#e67e22" :
                          p.status === "EM_ANDAMENTO" ? "#2980b9" : "#888";
      return `
        <div class="card">
          <strong>#${p.id}</strong> ${p.nome || "(sem nome)"} —
          seed ${p.seed}, ${p.n_agentes} agentes, ${p.n_turnos} turnos,
          decisor=${p.decisor},
          <span style="color:${statusColor};font-weight:bold">${p.status}</span>,
          turno ${p.turno_atual}/${p.n_turnos}
          <a href="jogo.html?id=${p.id}" style="margin-left:8px">▶ abrir</a>
          <a href="analise.html?pid=${p.id}" style="margin-left:8px">📊 análise</a>
        </div>
      `;
    }).join("");
    div.innerHTML = html;
  } catch (e) {
    document.getElementById("partidas").innerHTML = `<p>Erro: ${e.message}</p>`;
  }
}

// Botão limpar histórico
document.getElementById("btn-limpar").addEventListener("click", async () => {
  if (!confirm("Apagar TODAS as partidas? Esta ação não pode ser desfeita.")) return;
  try {
    // Apaga o banco direto via endpoint
    const r = await fetch("/admin/limpar", {method: "POST"});
    if (r.ok) {
      alert("Histórico limpo!");
      await carregarPartidas();
    } else {
      alert("Erro: " + r.status);
    }
  } catch (e) {
    alert("Erro: " + e.message);
  }
});

carregarPartidas();
