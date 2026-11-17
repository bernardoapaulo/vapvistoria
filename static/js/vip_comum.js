/* Vip/Preparação: pop-ups nativos (<dialog>) e o pop-up de conclusão.
   [data-abrir-dialogo="id"] abre; [data-fechar-dialogo] fecha; Esc e clique no fundo também fecham.
   O foco já fica preso dentro do <dialog> aberto (showModal) e volta ao botão que o abriu. */
(function () {
  var ultimoBotao = null;

  function abrir(dialogo, botao) {
    if (!dialogo || typeof dialogo.showModal !== "function") return;
    ultimoBotao = botao || null;
    dialogo.showModal();
  }

  document.addEventListener("click", function (evento) {
    var abrirBotao = evento.target.closest("[data-abrir-dialogo]");
    if (abrirBotao) {
      abrir(document.getElementById(abrirBotao.getAttribute("data-abrir-dialogo")), abrirBotao);
      return;
    }
    var fechar = evento.target.closest("[data-fechar-dialogo]");
    if (fechar) {
      fechar.closest("dialog").close();
      return;
    }
    // clique no fundo escurecido (o próprio <dialog>, fora do conteúdo)
    if (evento.target.tagName === "DIALOG") {
      var r = evento.target.getBoundingClientRect();
      var fora = evento.clientX < r.left || evento.clientX > r.right || evento.clientY < r.top || evento.clientY > r.bottom;
      if (fora) evento.target.close();
    }
  });

  document.addEventListener("close", function (evento) {
    if (evento.target.tagName === "DIALOG" && ultimoBotao && document.body.contains(ultimoBotao)) ultimoBotao.focus();
  }, true);

  // Conclusão: um só pop-up na página; cada botão [data-concluir] informa a ação, a placa e o valor
  document.addEventListener("click", function (evento) {
    var botao = evento.target.closest("[data-concluir]");
    if (!botao) return;
    var dialogo = document.getElementById("dialogo-concluir");
    if (!dialogo) return;
    dialogo.querySelector("[data-concluir-form]").setAttribute("action", botao.getAttribute("data-url"));
    dialogo.querySelector("[data-concluir-placa]").textContent = botao.getAttribute("data-placa");
    dialogo.querySelector("#concluir-valor").value = botao.getAttribute("data-valor");
    // lista de serviços do registro (nome e valor de cada um), só texto
    var itens = dialogo.querySelector("[data-concluir-itens]");
    itens.innerHTML = "";
    try {
      JSON.parse(botao.getAttribute("data-itens") || "[]").forEach(function (i) {
        var li = document.createElement("li");
        li.textContent = i.nome + " — " + Number(i.valor).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
        itens.appendChild(li);
      });
    } catch (erro) { /* sem a lista, o total continua valendo */ }
    abrir(dialogo, botao);
  });
})();
