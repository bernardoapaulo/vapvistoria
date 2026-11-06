/* Formulário de agendamento: ao escolher o início, o fim vira início + 1 hora
   (se estiver vazio ou antes do início). O servidor repete essa regra. */
document.addEventListener("DOMContentLoaded", function () {
  var inicio = document.getElementById("id_inicio");
  var fim = document.getElementById("id_fim");
  if (!inicio || !fim) return;

  function doisDigitos(n) { return (n < 10 ? "0" : "") + n; }
  function formatar(d) {
    return d.getFullYear() + "-" + doisDigitos(d.getMonth() + 1) + "-" + doisDigitos(d.getDate()) +
      "T" + doisDigitos(d.getHours()) + ":" + doisDigitos(d.getMinutes());
  }

  inicio.addEventListener("change", function () {
    if (!inicio.value) return;
    var ini = new Date(inicio.value);
    if (!fim.value || new Date(fim.value) <= ini) {
      fim.value = formatar(new Date(ini.getTime() + 60 * 60 * 1000));
    }
  });
});
