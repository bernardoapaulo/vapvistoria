/* Formulário do VIP/Preparação. Tudo aqui é melhoria: sem JavaScript, os campos comuns (listas, datas, arquivos)
   continuam funcionando e o servidor valida tudo de novo. As peças compartilhadas com Regravações (busca de cliente,
   pop-up de cor, placa, arquivos e rascunho) ficam em vap_form.js; aqui só o que é do Vip: os itens de serviço.

   - Serviços: pop-up com caixas de seleção; cada serviço marcado vira uma linha com valor e total. */
(function () {
  var formulario = document.querySelector("[data-vip-form]");
  if (!formulario) return;

  function campo(nome) { return formulario.querySelector('[name="' + nome + '"]'); }

  VapForm.combo(formulario, { bloco: "[data-cliente-campo]", campo: "cliente", rotulo: "Cliente",
                              placeholder: "Digite o nome do cliente", vazio: "Nenhum cliente encontrado", idLista: "lista-clientes" });
  VapForm.cor(formulario);

  /* ---------- Serviços: vários itens; o pop-up marca vários de uma vez ---------- */
  (function () {
    var area = formulario.querySelector("[data-itens-campo]");
    var dialogo = document.getElementById("dialogo-servico");
    if (!area || !dialogo) return;
    var lista = area.querySelector("[data-itens-lista]");
    var modelo = area.querySelector("[data-item-modelo]");
    var total = area.querySelector("[data-itens-total]");
    var abrir = area.querySelector("[data-servicos-abrir]");
    var busca = dialogo.querySelector("[data-busca-servico]");
    var totalForms = area.querySelector('input[name="itens-TOTAL_FORMS"]');
    abrir.hidden = false;

    function linhas() { return Array.prototype.slice.call(lista.querySelectorAll("[data-item]")); }
    function removida(linha) { return linha.hidden; }
    function campoDe(linha, nome) { return linha.querySelector('[name$="-' + nome + '"]'); }

    function somar() {
      var soma = 0;
      linhas().forEach(function (l) {
        if (removida(l)) return;
        var v = parseFloat(campoDe(l, "valor").value);
        if (!isNaN(v)) soma += v;
      });
      total.textContent = soma.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
    }

    // Os índices do formset precisam ser 0..n-1 na ordem da tela (os itens que já existem vêm primeiro)
    function renumerar() {
      linhas().forEach(function (linha, i) {
        linha.querySelectorAll("[name], [id], [for]").forEach(function (el) {
          ["name", "id", "for"].forEach(function (a) {
            var v = el.getAttribute(a);
            if (v) el.setAttribute(a, v.replace(/itens-(\d+|__prefix__)-/, "itens-" + i + "-"));
          });
        });
      });
      totalForms.value = linhas().length;
    }

    function mostrarNome(linha) {
      var select = campoDe(linha, "servico");
      var nome = linha.querySelector("[data-item-nome]");
      var op = select.value ? select.options[select.selectedIndex] : null;
      select.hidden = true;
      linha.querySelector("label[for]").classList.add("so-leitor");
      nome.hidden = false;
      nome.textContent = op ? op.text.replace(/ — R\$.*$/, "") : "";
      var rotulo = nome.textContent;
      linha.querySelector("[data-item-remover]").setAttribute("aria-label", "Remover " + rotulo);
    }

    function ligar(linha) {
      mostrarNome(linha);
      campoDe(linha, "valor").addEventListener("input", somar);
      linha.querySelector("[data-item-remover]").addEventListener("click", function () {
        var existente = campoDe(linha, "id") && campoDe(linha, "id").value;
        if (existente) {                      // já gravado: marca para remover ao salvar
          campoDe(linha, "DELETE").checked = true;
          linha.hidden = true;
        } else {
          linha.remove();
        }
        renumerar();
        somar();
        abrir.focus();
      });
    }

    function adicionar(opcao) {
      var linha = modelo.content.firstElementChild.cloneNode(true);
      lista.appendChild(linha);
      var select = campoDe(linha, "servico");
      select.value = opcao.getAttribute("data-servico-opcao");
      var valor = campoDe(linha, "valor");
      valor.value = opcao.getAttribute("data-valor");      // o servidor recalcula o valor de quem não pode alterá-lo
      renumerar();
      ligar(linha);
    }

    // Linha vazia que o servidor oferece para quem está sem JavaScript: aqui o pop-up a substitui
    linhas().forEach(function (l) {
      var id = campoDe(l, "id");
      if (!campoDe(l, "servico").value && !(id && id.value)) l.remove(); else ligar(l);
    });
    renumerar();
    somar();

    dialogo.querySelector("[data-servicos-confirmar]").addEventListener("click", function () {
      var marcados = dialogo.querySelectorAll("[data-servico-opcao]:checked");
      marcados.forEach(function (c) { adicionar(c); c.checked = false; });
      somar();
      dialogo.close();
    });
    busca.addEventListener("input", function () {
      var termo = busca.value.trim().toLowerCase();
      dialogo.querySelectorAll(".lista-servicos li").forEach(function (li) {
        li.hidden = termo && li.textContent.toLowerCase().indexOf(termo) === -1;
      });
    });
    dialogo.addEventListener("close", function () { busca.value = ""; busca.dispatchEvent(new Event("input")); });
    formulario.addEventListener("submit", renumerar);
  })();

  VapForm.placa(formulario, { marca: "marca", modelo: "modelo", ano: "ano", chassi: "chassi", cor: "cor", cor_outra: "cor_outra" });
  VapForm.arquivos(formulario, { entrada: "[data-foto]", cartao: "[data-foto-campo]", previa: "[data-previa]",
                                 remover: 'input[name^="remover_"]', lado: 1600,
                                 textoRemover: "Remover esta foto ao salvar? Esta ação não pode ser desfeita." });
  VapForm.rascunho(formulario, { chave: "vip_rascunho", links: "[data-novo-cliente]", parametros: /[?&]cliente=/,
                                 ignorar: ["cliente"], eventos: ["cor"] });
})();
