/* Formulário de atendimento: apenas conveniências de tela.
   As regras valem de verdade no servidor (models.py / forms.py). */
(function () {
  var cliente = document.getElementById("id_cliente");
  var tipo = document.getElementById("id_tipo_servico");
  var veiculo = document.getElementById("id_veiculo");
  var aluno = document.getElementById("id_aluno");
  var valor = document.getElementById("id_valor_cobrado"); // não existe para funcionário
  if (!cliente || !tipo || !veiculo || !aluno) return;

  var boxVeiculo = document.querySelector('[data-campo="veiculo"]');
  var boxAluno = document.querySelector('[data-campo="aluno"]');

  // Mostra só os veículos do cliente escolhido.
  function filtrarVeiculos() {
    Array.prototype.forEach.call(veiculo.options, function (op) {
      if (!op.value) return;
      var visivel = !cliente.value || op.dataset.cliente === cliente.value;
      op.hidden = !visivel;
      op.disabled = !visivel;
      if (!visivel && op.selected) veiculo.value = "";
    });
  }

  // Mostra veículo ou aluno conforme a categoria do serviço.
  function atualizarCamposDoServico() {
    var op = tipo.options[tipo.selectedIndex];
    var exige = op ? op.dataset.exige : "";
    boxVeiculo.hidden = exige !== "veiculo";
    boxAluno.hidden = exige !== "aluno";
    if (boxVeiculo.hidden) veiculo.value = "";
    if (boxAluno.hidden) aluno.value = "";
  }

  cliente.addEventListener("change", filtrarVeiculos);

  tipo.addEventListener("change", function () {
    atualizarCamposDoServico();
    var op = tipo.options[tipo.selectedIndex];
    if (valor && op && op.dataset.valor) valor.value = op.dataset.valor; // valor padrão do serviço
  });

  // Aluno com cliente vinculado: sugere o cliente (se ainda não escolhido).
  aluno.addEventListener("change", function () {
    var op = aluno.options[aluno.selectedIndex];
    if (op && op.dataset.cliente && !cliente.value) {
      cliente.value = op.dataset.cliente;
      filtrarVeiculos();
    }
  });

  filtrarVeiculos();
  atualizarCamposDoServico();
  if (valor && !valor.value) {
    var op = tipo.options[tipo.selectedIndex];
    if (op && op.dataset.valor) valor.value = op.dataset.valor;
  }
})();
