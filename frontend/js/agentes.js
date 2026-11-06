// agentes.js — editor de prompts
let partidaId = null;
let agenteIndice = null;

document.getElementById("btn-carregar").addEventListener("click", async () => {
  partidaId = parseInt(document.getElementById("f-pid").value);
  try {
    const estado = await API.estado(partidaId);
    const div = document.getElementById("agentes-lista");
    div.innerHTML = estado.agentes.map(a => `
      <button onclick="carregarPrompt(${a.indice})">${a.indice} ${a.nome}</button>
    `).join("");
  } catch (e) { alert(e.message); }
});

window.carregarPrompt = async (indice) => {
  agenteIndice = indice;
  try {
    const r = await API.obterPrompt(partidaId, indice);
    document.getElementById("e-agente").textContent = indice;
    document.getElementById("e-texto").value = r.texto || "";
    document.getElementById("editor").hidden = false;
  } catch (e) { alert(e.message); }
};

document.getElementById("btn-salvar").addEventListener("click", async () => {
  const texto = document.getElementById("e-texto").value;
  try {
    await API.editarPrompt(partidaId, agenteIndice, texto);
    alert("Prompt salvo. Vale a partir do próximo turno.");
  } catch (e) { alert(e.message); }
});
