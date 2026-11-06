// config.js — configuração de LLM e LBM
async function carregarLlm() {
  try {
    const c = await API.configLlm();
    document.getElementById("llm-provedor").value = c.provedor || "groq";
    document.getElementById("llm-url").value = c.base_url || "";
    document.getElementById("llm-model").value = c.model || "qwen/qwen3-27b";
    document.getElementById("llm-model-openai").value = c.model || "";
    document.getElementById("llm-temp").value = c.temperature ?? 0.7;
    document.getElementById("llm-modo").value = c.modo || "tools";
    document.getElementById("llm-modo-openai").value = c.modo || "json";
    document.getElementById("llm-key-status").textContent =
      c.api_key_configured ? "✓ definida no .env" : "✗ não definida — defina GROQ_API_KEY no .env";
    alternarCamposProvedor();
  } catch (e) { alert(e.message); }
}

function alternarCamposProvedor() {
  const provedor = document.getElementById("llm-provedor").value;
  document.getElementById("campos-groq").hidden = (provedor !== "groq");
  document.getElementById("campos-openai").hidden = (provedor !== "openai");
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
  if (provedor === "groq") {
    dados.model = document.getElementById("llm-model").value;
    dados.modo = document.getElementById("llm-modo").value;
  } else {
    dados.base_url = document.getElementById("llm-url").value;
    dados.model = document.getElementById("llm-model-openai").value;
    dados.modo = document.getElementById("llm-modo-openai").value;
  }
  try { await API.salvarLlm(dados); await carregarLlm(); alert("LLM salvo."); }
  catch (e) { alert(e.message); }
});

document.getElementById("btn-testar-llm").addEventListener("click", async () => {
  const div = document.getElementById("llm-teste-resultado");
  div.textContent = "Testando...";
  const provedor = document.getElementById("llm-provedor").value;
  const body = { provedor };
  if (provedor === "groq") {
    body.model = document.getElementById("llm-model").value;
    body.modo = document.getElementById("llm-modo").value;
  } else {
    body.base_url = document.getElementById("llm-url").value;
    body.model = document.getElementById("llm-model-openai").value;
    body.modo = document.getElementById("llm-modo-openai").value;
  }
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
