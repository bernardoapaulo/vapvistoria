/* Dashboard: desenha os gráficos (Chart.js) e mostra "De/Até" só no período personalizado.
   Os dados vêm em <script type="application/json" id="g-..."> (json_script) e as cores das
   variáveis CSS (--cor-<chave>), então o visual se muda só em static/css/tokens.css. */
(function () {
  function cor(chave) {
    var valor = getComputedStyle(document.documentElement).getPropertyValue("--cor-" + chave).trim();
    return valor || "#888888";
  }

  function formatar(valor, formato) {
    if (formato === "moeda") return valor.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
    if (formato === "percentual") return valor.toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + "%";
    return valor.toLocaleString("pt-BR");
  }

  function datasets(series, tipo) {
    return series.map(function (s) {
      var fundo = s.cores ? s.cores.map(cor) : cor(s.cor);
      return { label: s.rotulo, data: s.dados, backgroundColor: fundo, borderColor: tipo === "doughnut" ? cor("superficie") : fundo, borderRadius: tipo === "doughnut" ? 0 : 4 };
    });
  }

  function opcoes(cfg, empilhado) {
    var rosca = cfg.tipo === "doughnut";
    var opc = {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: rosca || empilhado, position: "bottom", labels: { color: cor("texto-suave") } },
        tooltip: {
          callbacks: {
            label: function (ctx) {
              var v = rosca ? ctx.parsed : (cfg.tipo === "barh" ? ctx.parsed.x : ctx.parsed.y);
              return (ctx.dataset.label ? ctx.dataset.label + ": " : "") + formatar(v, cfg.formato);
            }
          }
        }
      }
    };
    if (!rosca) {
      var eixoValor = { beginAtZero: true, stacked: empilhado, ticks: { color: cor("texto-suave"), precision: 0 }, grid: { color: cor("borda") } };
      var eixoRotulo = { stacked: empilhado, ticks: { color: cor("texto-suave") }, grid: { display: false } };
      if (cfg.tipo === "barh") { opc.indexAxis = "y"; opc.scales = { x: eixoValor, y: eixoRotulo }; }
      else { opc.scales = { x: eixoRotulo, y: eixoValor }; }
    }
    return opc;
  }

  function desenhar(canvas) {
    var id = canvas.getAttribute("data-grafico");
    var cfg = JSON.parse(document.getElementById(id).textContent);
    var tipo = cfg.tipo === "doughnut" ? "doughnut" : "bar";
    var grafico = new Chart(canvas, {
      type: tipo,
      data: { labels: cfg.labels, datasets: datasets(cfg.series, cfg.tipo) },
      options: opcoes(cfg, false)
    });

    // "Empilhar por categoria" (só nos gráficos mensais)
    var opcao = document.querySelector('input[data-empilhar="' + id + '"]');
    if (opcao && cfg.series_empilhadas) {
      opcao.addEventListener("change", function () {
        var empilhar = opcao.checked;
        grafico.data.datasets = datasets(empilhar ? cfg.series_empilhadas : cfg.series, cfg.tipo);
        grafico.options = opcoes(cfg, empilhar);
        grafico.update();
      });
    }
  }

  function filtroPersonalizado() {
    var periodo = document.getElementById("id_periodo");
    var campos = document.querySelectorAll("[data-personalizado]");
    if (!periodo) return;
    function atualizar() {
      campos.forEach(function (c) { c.hidden = periodo.value !== "personalizado"; });
    }
    periodo.addEventListener("change", atualizar);
    atualizar();
  }

  document.addEventListener("DOMContentLoaded", function () {
    filtroPersonalizado();
    if (typeof Chart === "undefined") return;
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.color = cor("texto-suave");
    document.querySelectorAll("canvas[data-grafico]").forEach(desenhar);
  });
})();
