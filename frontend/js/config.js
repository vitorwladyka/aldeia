// config.js — configuração de LLM e LBM
async function carregarLlm() {
  try {
    const c = await API.configLlm();
    document.getElementById("llm-provedor").value = c.provedor || "groq";
    document.getElementById("llm-url").value = c.base_url || "";
    document.getElementById("llm-model").value =
      (c.provedor === "groq" && c.model) ? c.model : "qwen/qwen3-27b";
    document.getElementById("llm-model-openai").value =
      (c.provedor === "openai" && c.model) ? c.model : "";
    document.getElementById("llm-model-anthropic").value =
      (c.provedor === "anthropic" && c.model) ? c.model : "claude-haiku-4-5-20251001";
    document.getElementById("llm-temp").value = c.temperature ?? 0.7;
    document.getElementById("llm-modo").value = c.modo || "tools";
    document.getElementById("llm-modo-openai").value = c.modo || "json";
    document.getElementById("llm-key-status").textContent =
      c.api_key_configured ? "✓ definida no .env" : "✗ não definida no .env";
    // Perfis: seletor + resumo do ativo
    const selPerfil = document.getElementById("llm-perfil");
    selPerfil.innerHTML = (c.perfis || [])
      .map(p => `<option value="${p.nome}">${p.nome}</option>`).join("");
    selPerfil.value = c.perfil_ativo;
    document.getElementById("llm-perfil-info").textContent =
      `${c.provedor} · ${c.model || "?"}`;
    // Avançado (vazio = padrão do sistema)
    document.getElementById("llm-timeout").value = c.timeout_s ?? "";
    document.getElementById("llm-maxtok").value = c.max_tokens ?? "";
    document.getElementById("llm-reasoning").value = c.reasoning_effort ?? "";
    document.getElementById("llm-tpm").value = c.tpm_limite ?? "";
    alternarCamposProvedor();
  } catch (e) { alert(e.message); }
}

// Campo numérico/texto opcional: "" faz o servidor REMOVER a chave do perfil.
function valorOpcional(id, numero) {
  const v = document.getElementById(id).value.trim();
  return v === "" ? "" : (numero ? Number(v) : v);
}

document.getElementById("llm-perfil").addEventListener("change", async (e) => {
  try { await API.ativarPerfilLlm(e.target.value); }
  catch (err) { alert(err.message); }
  await carregarLlm();   // mostra o perfil agora ativo (ou volta ao anterior em caso de erro)
});

document.getElementById("btn-perfil-novo").addEventListener("click", async () => {
  const nome = prompt("Nome do novo perfil (será uma cópia do atual):");
  if (!nome || !nome.trim()) return;
  try { await API.criarPerfilLlm(nome.trim()); await carregarLlm(); }
  catch (err) { alert(err.message); }
});

document.getElementById("btn-perfil-excluir").addEventListener("click", async () => {
  const nome = document.getElementById("llm-perfil").value;
  if (!confirm(`Excluir o perfil "${nome}"?`)) return;
  try { await API.excluirPerfilLlm(nome); await carregarLlm(); }
  catch (err) { alert(err.message); }
});

function alternarCamposProvedor() {
  const provedor = document.getElementById("llm-provedor").value;
  document.getElementById("campos-groq").hidden = (provedor !== "groq");
  document.getElementById("campos-openai").hidden = (provedor !== "openai");
  document.getElementById("campos-anthropic").hidden = (provedor !== "anthropic");
  // A variável da chave no .env depende do provedor.
  document.getElementById("llm-key-var").textContent =
    provedor === "anthropic" ? "ANTHROPIC_API_KEY" : "GROQ_API_KEY";
}

document.getElementById("llm-provedor").addEventListener("change", alternarCamposProvedor);

async function carregarLbm() {
  try {
    const [c, perfis] = await Promise.all([API.configLbm(), API.perfisLbm()]);
    document.getElementById("lbm-url").value = c.url || "";
    document.getElementById("lbm-timeout").value = c.timeout_s ?? 10;
    document.getElementById("lbm-instructions").value = c.instructions || "";
    // Carrega state_template (prompt do Laya)
    const ta = document.getElementById("lbm-state-template");
    if (ta) ta.value = c.state_template || "";
    const sel = document.getElementById("lbm-perfil");
    sel.innerHTML = perfis.perfis.map(p => `<option value="${p}">${p}</option>`).join("");
    sel.value = c.perfil || "laya_systemone";
  } catch (e) { alert(e.message); }
}

document.getElementById("btn-llm").addEventListener("click", async () => {
  const provedor = document.getElementById("llm-provedor").value;
  const dados = {
    provedor: provedor,
    temperature: parseFloat(document.getElementById("llm-temp").value),
  };
  if (provedor === "anthropic") {
    dados.model = document.getElementById("llm-model-anthropic").value;
    dados.base_url = "";  // o cliente da Anthropic não usa base_url
  } else if (provedor === "groq") {
    dados.model = document.getElementById("llm-model").value;
    dados.modo = document.getElementById("llm-modo").value;
  } else {
    dados.base_url = document.getElementById("llm-url").value;
    dados.model = document.getElementById("llm-model-openai").value;
    dados.modo = document.getElementById("llm-modo-openai").value;
  }
  dados.timeout_s = valorOpcional("llm-timeout", true);
  dados.max_tokens = valorOpcional("llm-maxtok", true);
  dados.reasoning_effort = valorOpcional("llm-reasoning", false);
  dados.tpm_limite = valorOpcional("llm-tpm", true);
  try { await API.salvarLlm(dados); await carregarLlm(); alert("Perfil salvo."); }
  catch (e) { alert(e.message); }
});

document.getElementById("btn-testar-llm").addEventListener("click", async () => {
  const div = document.getElementById("llm-teste-resultado");
  div.textContent = "Testando...";
  const provedor = document.getElementById("llm-provedor").value;
  const body = { provedor };
  if (provedor === "anthropic") {
    body.model = document.getElementById("llm-model-anthropic").value;
  } else if (provedor === "groq") {
    body.model = document.getElementById("llm-model").value;
    body.modo = document.getElementById("llm-modo").value;
  } else {
    body.base_url = document.getElementById("llm-url").value;
    body.model = document.getElementById("llm-model-openai").value;
    body.modo = document.getElementById("llm-modo-openai").value;
  }
  const tmo = document.getElementById("llm-timeout").value;
  if (tmo) body.timeout_s = Number(tmo);
  const rea = document.getElementById("llm-reasoning").value.trim();
  if (rea) body.reasoning_effort = rea;
  try {
    const r = await fetch("/config/llm/testar", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    }).then(r => r.json());
    if (r.ok) {
      div.innerHTML = `✓ OK — latência=${r.latencia_ms}ms, modelo=${r.modelo}<br>Resposta: <code>${(r.resposta || "").substring(0, 200)}</code>`;
    } else {
      div.innerHTML = `✗ Falhou: ${r.erro} (latência=${r.latencia_ms}ms)`;
    }
  } catch (e) { div.textContent = "Erro: " + e.message; }
});

document.getElementById("btn-lbm").addEventListener("click", async () => {
  const dados = {
    perfil: document.getElementById("lbm-perfil").value,
    url: document.getElementById("lbm-url").value,
    timeout_s: parseFloat(document.getElementById("lbm-timeout").value),
    instructions: document.getElementById("lbm-instructions").value,
    state_template: document.getElementById("lbm-state-template").value,
  };
  try { await API.salvarLbm(dados); await carregarLbm(); alert("LBM salvo (persistido em config_lbm.json)."); }
  catch (e) { alert(e.message); }
});

document.getElementById("btn-testar-lbm").addEventListener("click", async () => {
  try {
    const r = await API.testarLbm();
    document.getElementById("lbm-teste-resultado").textContent =
      `ok=${r.ok}, latência=${r.latencia_ms}ms, ${r.mensagem || ""}`;
  } catch (e) { alert(e.message); }
});

document.getElementById("btn-perfis").addEventListener("click", carregarLbm);

carregarLlm();
carregarLbm();
