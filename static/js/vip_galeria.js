/* Galeria do detalhe do VIP/Preparação: ampliar a foto ao clicar e navegar com os botões ou as setas do teclado. */
(function () {
  var dialogo = document.getElementById("lightbox");
  if (!dialogo || typeof dialogo.showModal !== "function") return;
  var imagem = dialogo.querySelector("[data-lightbox-imagem]");
  var legenda = dialogo.querySelector("[data-lightbox-legenda]");
  var links = Array.prototype.slice.call(document.querySelectorAll("[data-galeria]"));
  var atual = 0;

  function mostrar(indice) {
    if (!links.length) return;
    atual = (indice + links.length) % links.length;
    var link = links[atual];
    imagem.src = link.getAttribute("href");
    imagem.alt = link.getAttribute("data-legenda");
    legenda.textContent = link.getAttribute("data-legenda") + " (" + (atual + 1) + " de " + links.length + ")";
  }

  links.forEach(function (link, indice) {
    link.addEventListener("click", function (evento) {
      evento.preventDefault();
      mostrar(indice);
      dialogo.showModal();
    });
  });
  dialogo.querySelector("[data-lightbox-anterior]").addEventListener("click", function () { mostrar(atual - 1); });
  dialogo.querySelector("[data-lightbox-proxima]").addEventListener("click", function () { mostrar(atual + 1); });
  dialogo.addEventListener("keydown", function (evento) {
    if (evento.key === "ArrowLeft") mostrar(atual - 1);
    if (evento.key === "ArrowRight") mostrar(atual + 1);
  });
  dialogo.addEventListener("close", function () { imagem.removeAttribute("src"); });
})();
