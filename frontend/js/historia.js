// historia.js — Gera narrativa lúdica da partida a partir dos dados de análise
// Não substitui analise.js — é uma página nova que conta a história

document.getElementById("btn-carregar").addEventListener("click", async () => {
  const pid = parseInt(document.getElementById("f-pid").value);
  await carregarHistoria(pid);
});

(async () => {
  const params = new URLSearchParams(location.search);
  const pid = params.get("pid");
  if (pid) {
    document.getElementById("f-pid").value = pid;
    await carregarHistoria(parseInt(pid));
  }
})();

// === Catálogo de descrições ludicas ===
const ACAO_DESC = {
  cacar:           { verbo: "foi caçar",          icone: "🏹", obj: "carne" },
  pescar:          { verbo: "foi pescar",         icone: "🎣", obj: "peixe" },
  coletar_trigo:   { verbo: "colheu trigo",       icone: "🌾", obj: "trigo" },
  coletar_erva:    { verbo: "colheu ervas",       icone: "🌿", obj: "erva" },
  coletar_madeira: { verbo: "coletou madeira",    icone: "🪵", obj: "madeira" },
  forragear:       { verbo: "foi forragear",      icone: "🍃", obj: "alimento" },
  assar_carne:     { verbo: "assou carne",        icone: "🔥", obj: "carne_assada" },
  assar_peixe:     { verbo: "assou peixe",        icone: "🔥", obj: "peixe_assado" },
  fazer_pao:       { verbo: "fez pão",            icone: "🍞", obj: "pão" },
  preparar_remedio:{ verbo: "preparou remédio",   icone: "⚗️", obj: "remédio" },
  curar:           { verbo: "curou um colega",    icone: "💊", obj: "vida" },
  passar:          { verbo: "ficou parado",       icone: "⏸", obj: "nada" },
};

const VALORES = {
  trigo: 3, peixe: 4, carne: 6, pao: 18, peixe_assado: 22, carne_assada: 26,
  madeira: 2, erva: 2, remedio: 8,
};

const NOMES_ACOES_HUMANO = {
  cacar: "caçar", pescar: "pescar", coletar_trigo: "colher trigo",
  coletar_erva: "colher ervas", coletar_madeira: "coletar madeira",
  forragear: "forragear", assar_carne: "assar carne", assar_peixe: "assar peixe",
  fazer_pao: "fazer pão", preparar_remedio: "preparar remédio",
  curar: "curar", passar: "esperar",
};

// === Função principal ===
async function carregarHistoria(pid) {
  const div = document.getElementById("historia");
  const loading = document.getElementById("loading");
  div.hidden = true;
  loading.hidden = false;

  try {
    const [partida, eventos, conversas, decisoes, ganhosPerdas, vidas, estoqueSnap] = await Promise.all([
      API.obterPartida(pid),
      API.analise(pid, "eventos"),
      API.analise(pid, "conversas"),
      API.analise(pid, "decisoes"),
      API.analise(pid, "ganhos-perdas"),
      API.analise(pid, "vidas"),
      API.analise(pid, "estoque"),
    ]);

    loading.hidden = true;
    div.hidden = false;
    div.innerHTML = "";

    // === Hero ===
    div.appendChild(gerarHero(partida));

    // === Prólogo ===
    div.appendChild(gerarPrologo(partida, eventos));

    // === Capítulos (um por turno) ===
    eventos.turnos.forEach(t => {
      const cap = gerarCapitulo(t, {
        conversas: conversas.mensagens.filter(m => m.turno === t.numero),
        decisoes: decisoes.decisoes.filter(d => d.turno === t.numero && d.oficial),
        movimentos: (ganhosPerdas.turnos.find(g => g.turno === t.numero) || {}).movimentos || [],
        vidasEventos: vidas.eventos.filter(v => v.turno === t.numero),
        estoque: estoqueSnap.turnos.find(e => e.turno === t.numero),
        proximoEstoque: estoqueSnap.turnos.find(e => e.turno === t.numero + 1),
      }, partida);
      div.appendChild(cap);
    });

    // === Epílogo ===
    div.appendChild(await gerarEpilogo(partida, eventos, vidas));

    // === Pontuação final (card) ===
    div.appendChild(await gerarPontuacao(partida));

  } catch (e) {
    loading.hidden = true;
    div.hidden = false;
    div.innerHTML = `<div class="card" style="border-color: var(--danger)">
      <h3>⚠ Erro</h3>
      <p class="text-sm">${e.message}</p>
    </div>`;
  }
}

// === HERO ===
function gerarHero(partida) {
  // PartidaDetalhe retorna campos diretos (id, nome, seed, n_agentes, n_turnos, decisor, ...)
  const p = partida.partida || partida;
  const div = document.createElement("div");
  div.className = "hero";
  div.innerHTML = `
    <h1 class="hero-titulo">🏔️ A Saga da Aldeia</h1>
    <p class="hero-subtitulo">
      Partida #${p.id} — ${p.nome || "sem nome"} • ${p.n_agentes} aldeões enfrentaram ${p.n_turnos} turnos
    </p>
    <div class="hero-meta">
      <span>🌱 <strong>Seed:</strong> ${p.seed}</span>
      <span>🧭 <strong>Decisor:</strong> ${p.decisor}</span>
      <span>💬 <strong>Conselho:</strong> ${p.rodadas_conselho || 1} rodada(s)</span>
      <span>📊 <strong>Status:</strong> ${p.status}</span>
    </div>
  `;
  return div;
}

// === PRÓLOGO ===
function gerarPrologo(partida, eventos) {
  const p = partida.partida || partida;
  const div = document.createElement("div");
  div.className = "narrativa-capitulo";
  const nTurnos = eventos.turnos.length;
  div.innerHTML = `
    <div class="capitulo-num">Prólogo</div>
    <h2 class="capitulo-titulo">🌅 O Início</h2>
    <p class="narrativa-texto">
      Era uma vez, numa <span class="destaque">aldeia cooperativa</span> de ${p.n_agentes} habitantes,
      um desafio: sobreviver por <span class="destaque">${p.n_turnos} turnos</span> até o fim dos tempos.
      O inverno chegaria no turno <span class="destaque-alerta">16</span>, trazendo frio e fome triplicada.
      A cada turno, cada aldeão precisaria pagar <span class="destaque">1 alimento</span> de basal
      (ou <span class="destaque-ruim">3 no inverno</span>) só para continuar vivo.
    </p>
    <p class="narrativa-texto">
      A decisão de cada ação seria tomada por <span class="destaque">${p.decisor}</span>
      ${p.decisor === 'lbm' ? ' — o híbrido Laya + LLM' : ''}.
      ${p.rodadas_conselho > 0
        ? `Antes de cada turno, os aldeões se reuniriam por <span class="destaque">${p.rodadas_conselho} rodada(s)</span> de conselho.`
        : `Sem conselho — cada um por si.`
      }
    </p>
    ${nTurnos === 0 ? `
      <p class="narrativa-texto">
        <span class="destaque-alerta">Mas a história ainda não foi escrita.</span>
        Inicie a partida e execute alguns turnos para ver a narrativa.
      </p>
    ` : `
      <p class="narrativa-texto">
        Vamos acompanhar essa história através de <span class="destaque">${nTurnos} turno(s)</span>...
      </p>
    `}
  `;
  return div;
}

// === CAPÍTULO POR TURNO ===
function gerarCapitulo(turno, dados, partida) {
  const div = document.createElement("div");

  // Define classe do capítulo
  let cls = "narrativa-capitulo";
  if (turno.estacao === "inverno") cls += " inverno";
  const houveMorte = dados.vidasEventos.some(v => v.vida_depois === 0);
  if (houveMorte) cls += " crise";
  if (turno.fartura) cls += " fartura";
  div.className = cls;

  const estacaoTag = `<span class="estacao-tag ${turno.estacao}">${turno.estacao === "inverno" ? "❄️ inverno" : "☀️ normal"}</span>`;

  // === Texto narrativo do turno ===
  const paragrafos = [];

  // 1. Contexto do turno
  let ctx = `Turno <span class="destaque">${turno.numero}</span>${estacaoTag}. `;
  if (turno.estacao === "inverno") {
    ctx += `O inverno apertava — basal subiu para <span class="destaque-ruim">3 alimentos por agente</span>. `;
  }
  // Clima
  const climaBits = [];
  if (turno.tempestade) climaBits.push("⛈️ uma <span class='destaque-ruim'>tempestade</span> bloqueou a pesca");
  if (turno.fartura) climaBits.push("🌾 uma <span class='destaque-bom'>fartura</span> animou as coletas (+1)");
  if (turno.doenca) climaBits.push("🤒 a <span class='destaque-ruim'>doença</span> rondou a aldeia");
  if (turno.praga) climaBits.push("🐛 uma <span class='destaque-ruim'>praga</span> ameaçou os estoques");
  if (climaBits.length > 0) {
    ctx += `${climaBits.join(", ")}. `;
  } else if (turno.estacao !== "inverno") {
    ctx += `Clima tranquilo, sem incidentes. `;
  }
  paragrafos.push(ctx);

  // 2. O que cada agente fez
  if (dados.decisoes.length > 0) {
    const acoesPorAgente = dados.decisoes.map(d => {
      let acao = "?", alvo = null;
      try { const a = JSON.parse(d.acao_json); acao = a.acao; alvo = a.alvo; } catch {}
      return { ...d, acao, alvo };
    });

    // Agrupa por ação para narrativa mais fluida
    const grupos = {};
    acoesPorAgente.forEach(d => {
      if (!grupos[d.acao]) grupos[d.acao] = [];
      grupos[d.acao].push(d);
    });

    let frase = "";
    const gruposArr = Object.entries(grupos);
    if (gruposArr.length === 1) {
      // Todos fizeram a mesma coisa
      const [acao, agentes] = gruposArr[0];
      const desc = ACAO_DESC[acao] || { verbo: acao, icone: "•" };
      const nomes = agentes.map(d => nomeAgente(d.indice, partida)).join(", ");
      frase = `<span class="agente-nome">${nomes}</span> ${desc.verbo}`;
      if (acao === "curar" && agentes[0].alvo != null) {
        frase += ` <span class="agente-nome">${nomeAgente(agentes[0].alvo, partida)}</span>`;
      }
      frase += ` <span class="acao-nome">${desc.icone} ${NOMES_ACOES_HUMANO[acao] || acao}</span>. `;
      if (agentes.length > 2) {
        frase += `<span class="destaque-alerta">Todos na mesma ação — desperdício (max 2 por local)!</span> `;
      }
    } else {
      const partes = gruposArr.map(([acao, agentes]) => {
        const desc = ACAO_DESC[acao] || { verbo: acao, icone: "•" };
        const nomes = agentes.map(d => nomeAgente(d.indice, partida)).join(" e ");
        let s = `<span class="agente-nome">${nomes}</span> ${desc.verbo}`;
        if (acao === "curar" && agentes[0].alvo != null) {
          s += ` <span class="agente-nome">${nomeAgente(agentes[0].alvo, partida)}</span>`;
        }
        return s;
      });
      frase = partes.join(", ") + ". ";
    }
    paragrafos.push(frase);

    // 3. Decisões interessantes: quem foi escalado para o LLM?
    const escalados = acoesPorAgente.filter(d => {
      if (!d.resposta_bruta) return false;
      try {
        const rb = JSON.parse(d.resposta_bruta);
        return rb.decidido_por === "llm";
      } catch { return false; }
    });
    if (escalados.length > 0) {
      const nomesEsc = escalados.map(d => nomeAgente(d.indice, partida)).join(", ");
      paragrafos.push(
        `<span class="destaque-alerta">🧠 O LLM assumiu para ${nomesEsc}</span> — ` +
        `Laya não tinha confiança suficiente nessa decisão.`
      );
    }
  }

  // 4. Movimentos do turno (ganhos/perdas)
  if (dados.movimentos.length > 0) {
    const porTipo = {};
    dados.movimentos.forEach(m => {
      if (!porTipo[m.tipo]) porTipo[m.tipo] = [];
      porTipo[m.tipo].push(m);
    });

    // Só narra tipos interessantes
    const tiposNarraveis = ["coleta", "preparo", "cura", "forragem", "praga"];
    const frasesMov = [];

    if (porTipo.coleta) {
      const gains = porTipo.coleta.filter(m => m.delta > 0);
      if (gains.length > 0) {
        const lista = gains.map(m => `<span class="destaque-bom">+${m.delta} ${m.item}</span>`).join(", ");
        frasesMov.push(`Coletas renderam: ${lista}.`);
      }
    }
    if (porTipo.preparo) {
      const gains = porTipo.preparo.filter(m => m.delta > 0);
      if (gains.length > 0) {
        const lista = gains.map(m => `<span class="destaque-bom">+${m.delta} ${m.item}</span>`).join(", ");
        frasesMov.push(`Transformações geraram: ${lista}.`);
      }
    }
    if (porTipo.cura) {
      frasesMov.push(`<span class="destaque-bom">💊 Cura aplicada — vida recuperada.</span>`);
    }
    if (porTipo.forragem) {
      const gains = porTipo.forragem.filter(m => m.delta > 0);
      const losses = porTipo.forragem.filter(m => m.delta < 0);
      if (gains.length > 0) {
        frasesMov.push(`Forrageio rendeu <span class="destaque-bom">+${gains[0].delta} alimento</span>.`);
      }
    }
    if (porTipo.praga) {
      const losses = porTipo.praga.filter(m => m.delta < 0);
      if (losses.length > 0) {
        const lista = losses.map(m => `<span class="destaque-ruim">${m.delta} ${m.item}</span>`).join(", ");
        frasesMov.push(`<span class="destaque-ruim">🐛 Praga destruiu: ${lista}.</span>`);
      }
    }
    // Basal sempre
    const basal = porTipo.basal || porTipo.pagamento;
    if (basal && basal.length > 0) {
      const total = basal.reduce((s, m) => s + Math.abs(m.delta), 0);
      frasesMov.push(`Custo de vida basal: <span class="destaque-ruim">-${total} alimentos</span>.`);
    }
    if (frasesMov.length > 0) {
      paragrafos.push(frasesMov.join(" "));
    }
  }

  // 5. Eventos de vida (mortes e perdas)
  if (dados.vidasEventos.length > 0) {
    const mortes = dados.vidasEventos.filter(v => v.vida_depois === 0);
    const perdas = dados.vidasEventos.filter(v => v.vida_depois > 0 && v.vida_depois < v.vida_antes);

    if (perdas.length > 0) {
      const lista = perdas.map(v =>
        `<span class="agente-nome">${nomeAgente(v.indice, partida)}</span> ` +
        `(<span class="destaque-ruim">${v.vida_antes}→${v.vida_depois}</span>, ${v.motivo})`
      ).join(", ");
      paragrafos.push(`💔 ${lista} perdeu vida.`);
    }
    if (mortes.length > 0) {
      const lista = mortes.map(v =>
        `<span class="agente-nome">${nomeAgente(v.indice, partida)}</span> (${v.motivo})`
      ).join(", ");
      paragrafos.push(`<span class="destaque-ruim">💀 MORTE: ${lista} não resistiu.</span>`);
    }
  }

  // === Citacoes dos agentes (conselho) ===
  let citacoesHtml = "";
  if (dados.conversas.length > 0) {
    citacoesHtml = `<div class="citacoes">
      <div class="dados-box-titulo">💬 Conselho</div>
      ${dados.conversas.map(m => {
        const agenteIdx = m.agente ?? m.indice ?? '?';
        return `<div class="citacao">
          <span class="quem">${nomeAgente(agenteIdx, partida)} (R${m.rodada}):</span>
          "${m.texto}"
          ${m.intencao_declarada ? `<span class="intencao">${m.intencao_declarada}</span>` : ""}
        </div>`;
      }).join("")}
    </div>`;
  }

  // === Box de dados do turno ===
  const estoqueDepois = dados.proximoEstoque?.itens || dados.estoque?.itens || {};
  const alimentoSolto = estoqueDepois.alimento_solto ?? 0;
  const alimentoDisp = calcularAlimentoDisponivel(estoqueDepois);

  let dadoCls = "";
  if (alimentoDisp < 5) dadoCls = "ruim";
  else if (alimentoDisp < 10) dadoCls = "alerta";
  else dadoCls = "bom";

  const dadosHtml = `<div class="dados-box">
    <div class="dados-box-titulo">📊 Situação ao final do turno</div>
    <div class="dados-grid">
      <div class="dado-item">
        <span class="dado-label">Alimento disponível</span>
        <span class="dado-valor ${dadoCls}">${alimentoDisp}</span>
      </div>
      <div class="dado-item">
        <span class="dado-label">Alimento solto</span>
        <span class="dado-valor">${alimentoSolto}</span>
      </div>
      <div class="dado-item">
        <span class="dado-label">Ações executadas</span>
        <span class="dado-valor">${dados.decisoes.length}</span>
      </div>
      ${estoqueDepois.trigo ? `<div class="dado-item"><span class="dado-label">🌾 Trigo</span><span class="dado-valor">${estoqueDepois.trigo}</span></div>` : ''}
      ${estoqueDepois.peixe ? `<div class="dado-item"><span class="dado-label">🐟 Peixe</span><span class="dado-valor">${estoqueDepois.peixe}</span></div>` : ''}
      ${estoqueDepois.carne ? `<div class="dado-item"><span class="dado-label">🥩 Carne</span><span class="dado-valor">${estoqueDepois.carne}</span></div>` : ''}
      ${estoqueDepois.pao ? `<div class="dado-item"><span class="dado-label">🍞 Pão</span><span class="dado-valor">${estoqueDepois.pao}</span></div>` : ''}
      ${estoqueDepois.madeira ? `<div class="dado-item"><span class="dado-label">🪵 Madeira</span><span class="dado-valor">${estoqueDepois.madeira}</span></div>` : ''}
      ${estoqueDepois.erva ? `<div class="dado-item"><span class="dado-label">🌿 Erva</span><span class="dado-valor">${estoqueDepois.erva}</span></div>` : ''}
      ${estoqueDepois.remedio ? `<div class="dado-item"><span class="dado-label">💊 Remédio</span><span class="dado-valor">${estoqueDepois.remedio}</span></div>` : ''}
    </div>
  </div>`;

  // === Monta o capítulo ===
  div.innerHTML = `
    <div class="capitulo-num">Capítulo ${turno.numero}</div>
    <h2 class="capitulo-titulo">${tituloCapitulo(turno, dados)} ${estacaoTag}</h2>
    ${paragrafos.map(p => `<p class="narrativa-texto">${p}</p>`).join("")}
    ${citacoesHtml}
    ${dadosHtml}
  `;
  return div;
}

// === EPÍLOGO ===
async function gerarEpilogo(partida, eventos, vidas) {
  const p = partida.partida || partida;
  const div = document.createElement("div");
  div.className = "narrativa-capitulo epilogo";

  const totalTurnos = eventos.turnos.length;
  const ultimoTurno = eventos.turnos[eventos.turnos.length - 1];

  // Conta vivos e mortos — USA O ESTADO REAL DA PARTIDA (mais confiável)
  // Bug anterior: usava só vidas.eventos que pode não ter todas as mortes
  // (especialmente se a partida encerrou por "todos mortos" sem registrar evento)
  let nMortos = 0;
  let nVivos = p.n_agentes;
  let indicesMortosUnicos = [];
  let mortos = [];

  try {
    // Busca estado atual via API
    const r = await fetch(`/partidas/${p.id}/estado`);
    if (r.ok) {
      const estado = await r.json();
      const agentes = estado.agentes || [];
      nVivos = agentes.filter(a => a.status === "vivo").length;
      nMortos = agentes.filter(a => a.status === "morto").length;
      indicesMortosUnicos = agentes.filter(a => a.status === "morto").map(a => a.indice);
    }
  } catch (e) {
    console.warn("Não foi possível buscar estado, usando vidas.eventos como fallback", e);
  }

  // Fallback: se não conseguiu via API, usa vidas.eventos
  if (nMortos === 0 && nVivos === p.n_agentes && vidas.eventos.length > 0) {
    const todosMortesEventos = vidas.eventos.filter(v => v.vida_depois === 0);
    indicesMortosUnicos = [...new Set(todosMortesEventos.map(v => v.indice))];
    nMortos = indicesMortosUnicos.length;
    nVivos = p.n_agentes - nMortos;
  }

  // Para listar mortes, pega o evento de cada agente morto (com motivo real)
  if (indicesMortosUnicos.length > 0) {
    const todosMortesEventos = vidas.eventos.filter(v => v.vida_depois === 0);
    mortos = indicesMortosUnicos.map(idx => {
      const eventosAgente = todosMortesEventos.filter(v => v.indice === idx);
      return eventosAgente.find(v => v.motivo && v.motivo !== "morte") || eventosAgente[0]
        || { indice: idx, turno: "?", motivo: "desconhecido" };
    });
  }

  // Status da partida
  const encerrada = p.status === "ENCERRADA";

  // Total de alimento coletado/comido
  const todosMovimentos = []; // não temos acesso fácil aqui, usar estimativa
  const totalTurnosExecutados = totalTurnos;

  // Estoque final (do último snapshot)
  // Não temos acesso fácil ao último snapshot aqui, mas podemos usar eventos
  const ultimoEvento = eventos.turnos[eventos.turnos.length - 1];

  let veredito = "";
  if (nMortos === 0 && encerrada) {
    veredito = `<span class="destaque-bom">Todos sobreviveram!</span> A aldeia cumpriu seu objetivo — ninguém morreu em ${totalTurnosExecutados} turnos de desafio. Vitória completa.`;
  } else if (nMortos === 0 && !encerrada) {
    veredito = `Até agora, <span class="destaque-bom">todos vivos</span>. A saga continua...`;
  } else if (nMortos < p.n_agentes / 2) {
    veredito = `A aldeia sobreviveu, mas perdeu <span class="destaque-ruim">${nMortos} dos seus</span>: ${indicesMortosUnicos.map(i => nomeAgente(i, partida)).join(", ")}. Uma vitória parcial.`;
  } else if (nMortos < p.n_agentes) {
    veredito = `<span class="destaque-ruim">Catástrofe parcial</span>: ${nMortos} de ${p.n_agentes} aldeões morreram (${indicesMortosUnicos.map(i => nomeAgente(i, partida)).join(", ")}). Apenas ${nVivos} restaram.`;
  } else {
    veredito = `<span class="destaque-ruim">Todos morreram.</span> A aldeia foi extinta antes do turno ${p.n_turnos}.`;
  }

  div.innerHTML = `
    <div class="capitulo-num">Epílogo</div>
    <h2 class="capitulo-titulo">🏁 O Fim</h2>
    <p class="narrativa-texto">
      Após <span class="destaque">${totalTurnosExecutados} turno(s)</span> de luta,
      a saga chegou ao fim. Dos <span class="destaque">${p.n_agentes}</span> aldeões originais,
      <span class="destaque-bom">${nVivos} permaneceram vivos</span>
      ${nMortos > 0 ? `e <span class="destaque-ruim">${nMortos} partiram</span>` : ''}.
    </p>
    <p class="narrativa-texto">
      ${veredito}
    </p>
    ${nMortos > 0 ? `
      <p class="narrativa-texto">
        <strong>Mortes registradas:</strong>
      </p>
      <ul class="narrativa-texto" style="padding-left: 24px">
        ${mortos.map(m => `<li><span class="agente-nome">${nomeAgente(m.indice, partida)}</span> morreu no turno ${m.turno} (${m.motivo})</li>`).join("")}
      </ul>
    ` : ''}
    <p class="narrativa-texto" style="margin-top: 16px; color: var(--text-muted); font-style: italic;">
      Fim da partida #${p.id}. Para ver os dados completos, consulte a
      <a href="analise.html?pid=${p.id}" style="color: var(--accent)">página de análise</a>.
    </p>
  `;
  return div;
}

// === Helpers ===
function nomeAgente(indice, partida) {
  const p = partida.partida || partida;
  const nomes = ["Ana", "Bruno", "Carla", "Diego", "Eva", "Fábio", "Gabi", "Hugo"];
  return nomes[indice] || `Agente ${indice}`;
}

function calcularAlimentoDisponivel(estoque) {
  let total = estoque.alimento_solto || 0;
  const valores = { peixe: 4, carne: 6, pao: 18, peixe_assado: 22, carne_assada: 26 };
  for (const [item, valor] of Object.entries(valores)) {
    total += valor * (estoque[item] || 0);
  }
  return total;
}

function tituloCapitulo(turno, dados) {
  const n = turno.numero;
  // Títulos especiais baseados em eventos
  if (dados.vidasEventos.some(v => v.vida_depois === 0)) {
    return `💀 O Dia da Perda`;
  }
  if (turno.estacao === "inverno" && n === 16) {
    return `❄️ O Inverno Chega`;
  }
  if (turno.tempestade) return `⛈️ A Tempestade`;
  if (turno.fartura) return `🌾 Tempo de Fartura`;
  if (turno.doenca) return `🤒 A Doença`;
  if (turno.praga) return `🐛 A Praga`;
  if (n === 1) return `🌅 O Primeiro Dia`;
  if (n === turno.turnos_total || n === 20) return `🏁 O Último Turno`;
  return `📜 O Turno ${n}`;
}

// === PONTUAÇÃO FINAL ===
async function gerarPontuacao(partida) {
  const p = partida.partida || partida;
  const div = document.createElement("div");
  div.className = "card";
  div.style.marginTop = "16px";
  div.style.borderColor = "var(--accent)";

  try {
    // Busca detalhes da pontuação via API
    const r = await fetch(`/ranking/partida/${p.id}`);
    if (!r.ok) {
      // Partida em andamento — não tem resultado ainda
      div.innerHTML = `
        <h3>📊 Pontuação</h3>
        <p class="text-sm text-muted">
          Partida ainda em andamento. Execute todos os turnos para ver a pontuação final.
        </p>
        <p class="text-sm">
          <a href="ranking.html" style="color: var(--accent)">Ver ranking de todas as partidas →</a>
        </p>
      `;
      return div;
    }
    const dados = await r.json();
    const resultado = dados.resultado || {};
    const nVivos = resultado.n_vivos || 0;
    const somaVidas = resultado.soma_vidas || 0;
    const valorEstoque = resultado.valor_estoque || 0;
    const pontuacaoTotal = resultado.pontuacao_total || 0;
    const detalhamento = resultado.detalhamento || {};
    const classificacao = dados.classificacao || "—";

    // Calcula breakdown
    const ptsVivos = nVivos * 1000;
    const ptsVidas = somaVidas * 100;
    const ptsEstoque = valorEstoque;

    // Detalhamento do estoque
    const comida = detalhamento.comida || { itens: {}, valor_total: 0 };
    const insumos = detalhamento.insumos || { itens: {}, valor_total: 0 };
    const alimentoSolto = detalhamento.alimento_solto || 0;

    const comidaItems = Object.entries(comida.itens || {})
      .map(([k, v]) => `${k}=${v}`).join(", ") || "—";
    const insumosItems = Object.entries(insumos.itens || {})
      .map(([k, v]) => `${k}=${v}`).join(", ") || "—";

    div.innerHTML = `
      <h3>📊 Pontuação Final</h3>
      <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:16px;margin-top:16px">
        <div>
          <div class="text-xs text-muted" style="text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px">Pontuação Total</div>
          <div style="font-size:32px;font-weight:700;color:var(--accent);font-family:'JetBrains Mono',monospace">
            ${pontuacaoTotal.toLocaleString('pt-BR')}
          </div>
          <div style="margin-top:8px">
            <span class="classificacao-badge" style="display:inline-block;padding:4px 12px;border-radius:12px;font-size:12px;font-weight:600;background:var(--accent-subtle);color:var(--accent)">
              ${classificacao}
            </span>
          </div>
        </div>
        <div>
          <div class="text-xs text-muted" style="text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px">Breakdown</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:13px;line-height:1.8">
            <div>👥 Agentes vivos: <strong style="color:var(--success)">+${ptsVivos.toLocaleString('pt-BR')}</strong> <span class="text-muted">(${nVivos}/${p.n_agentes} × 1000)</span></div>
            <div>❤️ Soma das vidas: <strong style="color:var(--info)">+${ptsVidas.toLocaleString('pt-BR')}</strong> <span class="text-muted">(${somaVidas}/${p.n_agentes * 3} × 100)</span></div>
            <div>📦 Valor do estoque: <strong style="color:var(--warning)">+${ptsEstoque.toLocaleString('pt-BR')}</strong></div>
          </div>
        </div>
      </div>

      <div style="margin-top:16px;padding-top:16px;border-top:1px solid var(--border)">
        <div class="text-xs text-muted" style="text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px">Detalhamento do Estoque</div>
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;font-size:12px">
          <div>
            <div style="color:var(--text-secondary);font-weight:600;margin-bottom:4px">🍽️ Comida</div>
            <div class="text-mono text-xs">${comidaItems}</div>
            <div class="text-mono" style="color:var(--success);margin-top:2px">valor: ${comida.valor_total || 0}</div>
          </div>
          <div>
            <div style="color:var(--text-secondary);font-weight:600;margin-bottom:4px">🪵 Insumos</div>
            <div class="text-mono text-xs">${insumosItems}</div>
            <div class="text-mono" style="color:var(--warning);margin-top:2px">valor: ${insumos.valor_total || 0}</div>
          </div>
          <div>
            <div style="color:var(--text-secondary);font-weight:600;margin-bottom:4px">🍚 Alimento solto</div>
            <div class="text-mono text-xs">${alimentoSolto} unidades</div>
            <div class="text-mono" style="color:var(--text);margin-top:2px">valor: ${alimentoSolto}</div>
          </div>
        </div>
      </div>

      <p class="text-sm" style="margin-top:16px;text-align:center">
        <a href="ranking.html" style="color: var(--accent)">🏆 Ver no ranking comparativo →</a>
      </p>
    `;
  } catch (e) {
    div.innerHTML = `
      <h3>📊 Pontuação</h3>
      <p class="text-sm text-muted">Não foi possível carregar pontuação: ${e.message}</p>
    `;
  }
  return div;
}
