/* Formulário de Regravações. Melhoria sobre o formulário comum (sem JavaScript tudo continua funcionando e o servidor
   valida de novo). As peças compartilhadas (busca, cor, placa, arquivos, rascunho) vêm de vap_form.js. */
(function () {
  var formulario = document.querySelector("[data-reg-formulario]");
  if (!formulario) return;

  function campo(nome) { return formulario.querySelector('[name="' + nome + '"]'); }

  VapForm.combo(formulario, { bloco: "[data-cliente-campo]", campo: "cliente", rotulo: "Cliente indicado",
                              placeholder: "Digite o nome do cliente", vazio: "Nenhum cliente encontrado", idLista: "lista-clientes" });
  VapForm.combo(formulario, { bloco: "[data-parceiro-campo]", campo: "parceiro", rotulo: "Parceiro indicador",
                              placeholder: "Digite o nome do parceiro (opcional)", vazio: "Nenhum parceiro encontrado", idLista: "lista-parceiros" });
  VapForm.cor(formulario);
  VapForm.placa(formulario, { marca: "marca", modelo: "modelo", ano_modelo: "ano_modelo", chassi: "chassi", cor: "cor", cor_outra: "cor_outra" });
  VapForm.arquivos(formulario, { entrada: "[data-anexo]", cartao: "[data-anexo-campo]", previa: "[data-previa]",
                                 remover: 'input[name^="remover_anexo_"]', lado: 2000,
                                 textoRemover: "Remover este arquivo ao salvar? Esta ação não pode ser desfeita." });
  var nomesNaUrl = ["cliente", "parceiro", "tecnico"].filter(function (n) { return new RegExp("[?&]" + n + "=").test(window.location.search); });
  VapForm.rascunho(formulario, { chave: "regravacao_rascunho", links: "[data-novo-cliente], [data-novo-parceiro], [data-novo-tecnico]",
                                 parametros: /[?&](cliente|parceiro|tecnico)=/, ignorar: nomesNaUrl, eventos: ["cor", "proprietario_e_cliente"] });

  /* "O proprietário é o próprio cliente": preenche com o nome do cliente e trava o campo */
  (function () {
    var marca = campo("proprietario_e_cliente");
    var proprietario = campo("proprietario");
    var cliente = campo("cliente");
    if (!marca || !proprietario || !cliente) return;
    function nomeDoCliente() { var op = cliente.value ? cliente.options[cliente.selectedIndex] : null; return op ? op.text : ""; }
    function atualizar() {
      if (marca.checked) {
        proprietario.value = nomeDoCliente();
        proprietario.readOnly = true;
      } else {
        proprietario.readOnly = false;
      }
    }
    marca.addEventListener("change", atualizar);
    cliente.addEventListener("change", function () { if (marca.checked) atualizar(); });
    atualizar();
  })();

  /* Autorizações exigidas conforme o serviço marcado */
  (function () {
    var motor = campo("servico_motor"), chassi = campo("servico_chassi");
    if (!motor || !chassi) return;
    function atualizar() {
      var exigidas = { autorizacao_motor: motor.checked, autorizacao_chassi: chassi.checked };
      formulario.querySelectorAll("[data-anexo-campo]").forEach(function (cartao) {
        var etiqueta = cartao.querySelector("[data-anexo-exigido]");
        var tipo = cartao.getAttribute("data-tipo-anexo");
        if (etiqueta && tipo in exigidas) etiqueta.hidden = !exigidas[tipo];
      });
    }
    motor.addEventListener("change", atualizar);
    chassi.addEventListener("change", atualizar);
    atualizar();
  })();

  /* Recebimento: forma e data só aparecem quando "Recebido" */
  (function () {
    var radios = formulario.querySelectorAll('input[name="recebimento_situacao"]');
    var forma = campo("forma_pagamento"), data = campo("data_recebimento");
    if (!radios.length || !forma || !data) return;
    var blocos = [forma.closest(".campo"), data.closest(".campo")];
    function atualizar() {
      var marcado = formulario.querySelector('input[name="recebimento_situacao"]:checked');
      var recebido = marcado && marcado.value === "recebido";
      blocos.forEach(function (b) { if (b) b.hidden = !recebido; });
    }
    radios.forEach(function (r) { r.addEventListener("change", atualizar); });
    atualizar();
  })();
})();
