/* Regravações: pop-up "Concluir / receber" (lista e detalhe). Cada botão [data-concluir-reg] informa a ação e os valores
   atuais; o pop-up é o mesmo. Fechar com Esc ou clique fora vem de vip_comum.js (pop-ups nativos <dialog>). */
(function () {
  var dialogo = document.getElementById("dialogo-concluir-reg");
  if (!dialogo) return;
  var form = dialogo.querySelector("[data-reg-form]");
  var recebido = dialogo.querySelector("[data-reg-recebido]");

  function campo(nome) { return form.querySelector('[name="' + nome + '"]'); }
  function atualizarRecebimento() {
    var marcado = form.querySelector('[name="situacao"]:checked');
    recebido.hidden = !(marcado && marcado.value === "recebido");
  }
  form.querySelectorAll('[name="situacao"]').forEach(function (r) { r.addEventListener("change", atualizarRecebimento); });

  document.addEventListener("click", function (evento) {
    var botao = evento.target.closest("[data-concluir-reg]");
    if (!botao || typeof dialogo.showModal !== "function") return;
    form.setAttribute("action", botao.getAttribute("data-url"));
    campo("voltar").value = botao.getAttribute("data-voltar") || "";
    dialogo.querySelector("[data-reg-placa]").textContent = botao.getAttribute("data-placa");
    campo("data_concluida").value = botao.getAttribute("data-concluida");
    campo("tecnico").value = botao.getAttribute("data-tecnico");
    campo("forma").value = botao.getAttribute("data-forma");
    campo("data_recebimento").value = botao.getAttribute("data-recebimento");
    form.querySelectorAll('[name="situacao"]').forEach(function (r) { r.checked = r.value === botao.getAttribute("data-situacao"); });
    atualizarRecebimento();
    dialogo.showModal();
  });
})();
