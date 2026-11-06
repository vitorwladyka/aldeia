// ranking.js — Carrega e exibe ranking de partidas por pontuação

document.addEventListener("DOMContentLoaded", async () => {
  await carregarRanking();
});

async function carregarRanking() {
  try {
    const r = await fetch("/ranking");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const dados = await r.json();

    if (!dados.ranking || dados.ranking.length === 0) {
      document.getElementById("ranking-container").innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">🎮</div>
          <p>Nenhuma partida encontrada.</p>
          <p class="text-xs">Crie uma partida na página <a href="jogo.html" style="color: var(--accent)">Jogo</a> para vê-la aqui.</p>
        </div>
      `;
      document.getElementById("stats").innerHTML = "";
      return;
    }

    // === Stats agregadas ===
    const total = dados.ranking.length;
    const encerradas = dados.ranking.filter(p => p.status === "ENCERRADA").length;
    const todasVivos = dados.ranking.filter(p => p.n_vivos === p.n_agentes).length;
    const todasMortas = dados.ranking.filter(p => p.n_vivos === 0).length;
    const melhorPontuacao = Math.max(...dados.ranking.map(p => p.pontuacao_total));

    document.getElementById("stats").innerHTML = `
      <div class="stat-card">
        <div class="stat-label">Total de partidas</div>
        <div class="stat-value accent">${total}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Encerradas</div>
        <div class="stat-value">${encerradas}/${total}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Todos vivos</div>
        <div class="stat-value success">${todasVivos}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Melhor pontuação</div>
        <div class="stat-value warning">${melhorPontuacao.toLocaleString('pt-BR')}</div>
      </div>
    `;

    // === Tabela de ranking ===
    const html = `
      <table class="ranking-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Partida</th>
            <th>Decisor</th>
            <th>Status</th>
            <th>Turno</th>
            <th>Vivos</th>
            <th>Vidas</th>
            <th>Estoque</th>
            <th>Pontuação</th>
            <th>Classificação</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          ${dados.ranking.map((p, i) => {
            const pos = i + 1;
            const posClass = pos <= 3 ? `pos-${pos}` : "";
            const decisorClass = p.decisor || "bot";
            const statusClass = p.status === "ENCERRADA" ? "encerrada"
                              : p.status === "EM_ANDAMENTO" ? "andamento"
                              : "criada";
            const vivosClass = p.n_vivos === p.n_agentes ? "completo"
                             : p.n_vivos === 0 ? "nenhum"
                             : "parcial";
            const pontuacaoClass = p.pontuacao_total >= 3000 ? "alta"
                                  : p.pontuacao_total >= 1500 ? "media"
                                  : "baixa";
            const classificacaoClass = (p.classificacao || "").includes("Próspera") ? "prospera"
                                     : (p.classificacao || "").includes("Estável") ? "estavel"
                                     : (p.classificacao || "").includes("Sobrevivente") ? "sobrevivente"
                                     : (p.classificacao || "").includes("Risco") ? "risco"
                                     : "caida";

            return `
              <tr class="${posClass}">
                <td class="posicao">${pos}</td>
                <td>
                  <div style="font-weight:600;color:var(--text)">${p.nome}</div>
                  <div class="text-xs text-muted">seed: ${p.seed} • ${p.n_agentes} agentes</div>
                </td>
                <td><span class="decisor-tag ${decisorClass}">${p.decisor}</span></td>
                <td><span class="badge-status ${statusClass}">${p.status.replace('_', ' ')}</span></td>
                <td class="text-mono">${p.turno_atual}/${p.n_turnos}</td>
                <td class="vivos-cell ${vivosClass}">${p.n_vivos}/${p.n_agentes}</td>
                <td class="text-mono">${p.soma_vidas}/${p.n_agentes * 3}</td>
                <td class="text-mono">${p.valor_estoque}</td>
                <td class="pontuacao-cell ${pontuacaoClass}">${p.pontuacao_total.toLocaleString('pt-BR')}</td>
                <td><span class="classificacao-badge ${classificacaoClass}">${p.classificacao || '—'}</span></td>
                <td>
                  <a href="historia.html?pid=${p.id}" class="text-xs" style="color:var(--accent)">📜 história</a>
                  <a href="analise.html?pid=${p.id}" class="text-xs" style="color:var(--accent);margin-left:6px">📊 análise</a>
                </td>
              </tr>
            `;
          }).join("")}
        </tbody>
      </table>
    `;
    document.getElementById("ranking-container").innerHTML = html;

  } catch (e) {
    document.getElementById("ranking-container").innerHTML = `
      <div class="card" style="border-color: var(--danger)">
        <h3>⚠ Erro ao carregar ranking</h3>
        <p class="text-sm">${e.message}</p>
        <p class="text-xs text-muted">Verifique se o servidor está rodando.</p>
      </div>
    `;
  }
}
