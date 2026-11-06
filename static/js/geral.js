/* Comportamentos gerais: confirmação em formulários marcados com data-confirmar e gaveta do menu no celular. */
document.addEventListener("submit", function (evento) {
  var mensagem = evento.target.getAttribute("data-confirmar");
  if (mensagem && !window.confirm(mensagem)) evento.preventDefault();
});

(function () {
  var botao = document.querySelector("[data-menu-botao]");
  var fundo = document.querySelector("[data-menu-fundo]");
  if (!botao) return;

  function alternar(abrir) {
    document.body.classList.toggle("menu-aberto", abrir);
    botao.setAttribute("aria-expanded", abrir ? "true" : "false");
    botao.setAttribute("aria-label", abrir ? "Fechar menu" : "Abrir menu");
  }

  botao.addEventListener("click", function () { alternar(!document.body.classList.contains("menu-aberto")); });
  if (fundo) fundo.addEventListener("click", function () { alternar(false); });
  document.addEventListener("keydown", function (evento) {
    if (evento.key === "Escape" && document.body.classList.contains("menu-aberto")) {
      alternar(false);
      botao.focus();
    }
  });
})();
