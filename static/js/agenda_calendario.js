/* Calendário da agenda (FullCalendar). As cores dos eventos vêm do CSS (modulos.css),
   pela classe "evento-status-<status>" que o servidor coloca em cada evento.
   Em tela pequena, a visão inicial é a lista do dia. */
document.addEventListener("DOMContentLoaded", function () {
  var elemento = document.getElementById("calendario");
  if (!elemento || typeof FullCalendar === "undefined") return;

  var telaPequena = window.matchMedia("(max-width: 800px)");
  var visaoInicial = function () { return telaPequena.matches ? "listDay" : "dayGridMonth"; };
  var barra = function () {
    return telaPequena.matches
      ? { left: "prev,next today", center: "title", right: "listDay,listWeek,dayGridMonth" }
      : { left: "prev,next today", center: "title", right: "dayGridMonth,timeGridWeek,timeGridDay,listWeek" };
  };

  var calendario = new FullCalendar.Calendar(elemento, {
    locale: "pt-br",
    initialView: visaoInicial(),
    headerToolbar: barra(),
    buttonText: { today: "Hoje", month: "Mês", week: "Semana", day: "Dia", list: "Lista", listDay: "Dia (lista)", listWeek: "Semana (lista)" },
    height: "auto",
    nowIndicator: true,
    navLinks: true,
    slotMinTime: "07:00:00",
    slotMaxTime: "21:00:00",
    eventTimeFormat: { hour: "2-digit", minute: "2-digit", hour12: false },
    noEventsText: "Nenhum agendamento neste período",
    events: elemento.getAttribute("data-eventos"),
  });
  calendario.render();

  // Se o usuário girar o celular / redimensionar a janela, troca a visão e a barra.
  telaPequena.addEventListener("change", function () {
    calendario.setOption("headerToolbar", barra());
    calendario.changeView(visaoInicial());
  });
});
