// Cliente da API
const API = (() => {
  const BASE = "";  // mesma origem
  async function req(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const r = await fetch(BASE + path, opts);
    if (!r.ok) {
      let detalhe;
      try { detalhe = await r.json(); } catch { detalhe = await r.text(); }
      throw new Error(`${r.status} ${r.statusText}: ${JSON.stringify(detalhe)}`);
    }
    return await r.json();
  }
  return {
    listarPartidas: () => req("GET", "/partidas"),
    obterPartida: (id) => req("GET", `/partidas/${id}`),
    criarPartida: (dados) => req("POST", "/partidas", dados),
    iniciar: (id) => req("POST", `/partidas/${id}/iniciar`),
    turno: (id) => req("POST", `/partidas/${id}/turno`),
    encerrar: (id) => req("POST", `/partidas/${id}/encerrar`),
    retomar: (id) => req("POST", `/partidas/${id}/retomar`),
    estado: (id) => req("GET", `/partidas/${id}/estado`),
    obterPrompt: (pid, aid) => req("GET", `/partidas/${pid}/agentes/${aid}/prompt`),
    editarPrompt: (pid, aid, texto) => req("PUT", `/partidas/${pid}/agentes/${aid}/prompt`, { texto }),
    configAgente: (pid, aid, dados) => req("PUT", `/partidas/${pid}/agentes/${aid}/config`, dados),
    catalogoTools: () => req("GET", "/catalogo/tools"),
    skillsPadrao: () => req("GET", "/catalogo/skills-padrao"),
    configLlm: () => req("GET", "/config/llm"),
    salvarLlm: (dados) => req("PUT", "/config/llm", dados),
    ativarPerfilLlm: (nome) => req("POST", "/config/llm/perfil-ativo", { nome }),
    criarPerfilLlm: (nome) => req("POST", "/config/llm/perfis", { nome }),
    excluirPerfilLlm: (nome) => req("DELETE", `/config/llm/perfis/${encodeURIComponent(nome)}`),
    configLbm: () => req("GET", "/config/lbm"),
    salvarLbm: (dados) => req("PUT", "/config/lbm", dados),
    perfisLbm: () => req("GET", "/config/lbm/perfis"),
    testarLbm: () => req("POST", "/config/lbm/testar"),
    analise: (pid, tipo) => req("GET", `/partidas/${pid}/analise/${tipo}`),
    comparar: (a, b) => req("GET", `/comparar?a=${a}&b=${b}`),
  };
})();
