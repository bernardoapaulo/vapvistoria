/* Formulário do VIP/Preparação. Tudo aqui é melhoria: sem JavaScript, os campos comuns (listas, datas, arquivos)
   continuam funcionando e o servidor valida tudo de novo.

   - Cliente: busca digitando (combobox) sobre a lista de clientes.
   - Cor e serviço: pop-ups; o serviço preenche o valor.
   - Placa: preenche marca, modelo, ano, cor e chassi a partir do cadastro de veículos (sem sobrescrever o digitado).
   - Fotos: prévia na hora, redução no navegador (lado maior 1600 px, JPEG) para enviar menos dados do celular,
     e confirmação ao remover. Fotos HEIC do iPhone passam direto: o servidor converte.
   - "Cadastrar novo cliente": guarda o que foi digitado e restaura ao voltar. */
(function () {
  var formulario = document.querySelector("[data-vip-form]");
  if (!formulario) return;
  var CHAVE_RASCUNHO = "vip_rascunho";
  var LADO_MAXIMO = 1600;

  function campo(nome) { return formulario.querySelector('[name="' + nome + '"]'); }

  /* ---------- Cliente: combobox ---------- */
  (function () {
    var bloco = formulario.querySelector("[data-cliente-campo]");
    var select = campo("cliente");
    if (!bloco || !select || select.disabled) return;

    var opcoes = Array.prototype.slice.call(select.options).filter(function (o) { return o.value; });
    var entrada = document.createElement("input");
    entrada.type = "text";
    entrada.autocomplete = "off";
    entrada.placeholder = "Digite o nome do cliente";
    entrada.setAttribute("role", "combobox");
    entrada.setAttribute("aria-expanded", "false");
    entrada.setAttribute("aria-autocomplete", "list");
    entrada.setAttribute("aria-controls", "lista-clientes");
    entrada.setAttribute("aria-label", "Cliente");
    var lista = document.createElement("ul");
    lista.id = "lista-clientes";
    lista.className = "combo__lista";
    lista.setAttribute("role", "listbox");
    lista.hidden = true;

    var combo = document.createElement("div");
    combo.className = "combo";
    combo.appendChild(entrada);
    combo.appendChild(lista);
    select.hidden = true;
    select.setAttribute("aria-hidden", "true");
    select.tabIndex = -1;
    select.parentNode.insertBefore(combo, select.nextSibling);

    var marcado = -1;
    function selecionada() { return opcoes.filter(function (o) { return o.value === select.value; })[0]; }
    function mostrarNome() { var o = selecionada(); entrada.value = o ? o.text : ""; }

    function desenhar() {
      var termo = entrada.value.trim().toLowerCase();
      var achados = opcoes.filter(function (o) { return o.text.toLowerCase().indexOf(termo) !== -1; }).slice(0, 40);
      lista.innerHTML = "";
      marcado = -1;
      if (!achados.length) {
        var vazio = document.createElement("li");
        vazio.className = "combo__vazio";
        vazio.textContent = "Nenhum cliente encontrado";
        lista.appendChild(vazio);
      }
      achados.forEach(function (o, i) {
        var li = document.createElement("li");
        li.setAttribute("role", "option");
        li.id = "cliente-op-" + i;
        li.textContent = o.text;
        li.addEventListener("mousedown", function (e) { e.preventDefault(); escolher(o); });
        lista.appendChild(li);
      });
      lista.hidden = false;
      entrada.setAttribute("aria-expanded", "true");
    }
    function fechar() { lista.hidden = true; entrada.setAttribute("aria-expanded", "false"); }
    function escolher(o) {
      select.value = o.value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      mostrarNome();
      fechar();
    }
    function destacar(delta) {
      var itens = lista.querySelectorAll("[role=option]");
      if (!itens.length) return;
      if (marcado >= 0) itens[marcado].setAttribute("aria-selected", "false");
      marcado = (marcado + delta + itens.length) % itens.length;
      itens[marcado].setAttribute("aria-selected", "true");
      itens[marcado].scrollIntoView({ block: "nearest" });
      entrada.setAttribute("aria-activedescendant", itens[marcado].id);
    }

    entrada.addEventListener("input", function () { select.value = ""; desenhar(); });
    entrada.addEventListener("focus", function () { entrada.select(); desenhar(); });
    entrada.addEventListener("blur", function () { fechar(); mostrarNome(); });
    entrada.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); if (lista.hidden) desenhar(); destacar(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); destacar(-1); }
      else if (e.key === "Enter" && !lista.hidden && marcado >= 0) {
        e.preventDefault();
        var o = opcoes.filter(function (x) { return x.text === lista.querySelectorAll("[role=option]")[marcado].textContent; })[0];
        if (o) escolher(o);
      } else if (e.key === "Escape" && !lista.hidden) { fechar(); e.stopPropagation(); }
    });
    mostrarNome();
  })();

  /* ---------- Cor: pop-up ---------- */
  (function () {
    var bloco = formulario.querySelector("[data-cor-campo]");
    var select = campo("cor");
    var botao = bloco && bloco.querySelector("[data-cor-botao]");
    var dialogo = document.getElementById("dialogo-cor");
    if (!botao || !select || !dialogo) return;
    var texto = botao.querySelector("[data-cor-texto]");
    var outraBloco = bloco.querySelector("[data-cor-outra-bloco]");
    var outra = campo("cor_outra");
    select.hidden = true;
    select.setAttribute("aria-hidden", "true");
    select.tabIndex = -1;
    botao.hidden = false;

    function atualizar() {
      var valor = select.value;
      var nome = valor ? select.options[select.selectedIndex].text : "";
      if (valor === "outra" && outra && outra.value.trim()) nome = "Outra: " + outra.value.trim();
      botao.classList.toggle("seletor-botao--vazio", !valor);
      texto.innerHTML = "";
      if (valor) {
        var amostra = document.createElement("span");
        amostra.className = "amostra amostra--" + valor;
        amostra.setAttribute("aria-hidden", "true");
        texto.appendChild(amostra);
      }
      texto.appendChild(document.createTextNode(nome || "Escolher a cor"));
      outraBloco.hidden = valor !== "outra";
      dialogo.querySelectorAll("[data-cor-opcao]").forEach(function (b) {
        b.setAttribute("aria-pressed", b.getAttribute("data-cor-opcao") === valor ? "true" : "false");
      });
    }
    dialogo.addEventListener("click", function (e) {
      var b = e.target.closest("[data-cor-opcao]");
      if (!b) return;
      select.value = b.getAttribute("data-cor-opcao");
      atualizar();
      dialogo.close();
      if (select.value === "outra" && outra) outra.focus();
    });
    if (outra) outra.addEventListener("input", atualizar);
    select.addEventListener("change", atualizar);
    atualizar();
  })();

  /* ---------- Serviço: pop-up com busca; preenche o valor ---------- */
  (function () {
    var select = campo("servico");
    var botao = formulario.querySelector("[data-servico-botao]");
    var dialogo = document.getElementById("dialogo-servico");
    var valor = campo("valor");
    if (!select || !botao || !dialogo) return;
    var texto = botao.querySelector("[data-servico-texto]");
    var busca = dialogo.querySelector("[data-busca-servico]");
    select.hidden = true;
    select.setAttribute("aria-hidden", "true");
    select.tabIndex = -1;
    botao.hidden = false;

    function atualizar() {
      var op = select.value ? select.options[select.selectedIndex] : null;
      botao.classList.toggle("seletor-botao--vazio", !op);
      texto.textContent = op ? op.text : "Escolher o serviço";
      dialogo.querySelectorAll("[data-servico-opcao]").forEach(function (b) {
        b.setAttribute("aria-pressed", b.getAttribute("data-servico-opcao") === select.value ? "true" : "false");
      });
    }
    dialogo.addEventListener("click", function (e) {
      var b = e.target.closest("[data-servico-opcao]");
      if (!b) return;
      select.value = b.getAttribute("data-servico-opcao");
      if (valor) valor.value = b.getAttribute("data-valor");   // o servidor ignora o valor de quem não pode alterá-lo
      atualizar();
      dialogo.close();
    });
    busca.addEventListener("input", function () {
      var termo = busca.value.trim().toLowerCase();
      dialogo.querySelectorAll(".lista-servicos li").forEach(function (li) {
        li.hidden = termo && li.textContent.toLowerCase().indexOf(termo) === -1;
      });
    });
    dialogo.addEventListener("close", function () { busca.value = ""; busca.dispatchEvent(new Event("input")); });
    atualizar();
  })();

  /* ---------- Placa: preenche a partir do cadastro de veículos ---------- */
  (function () {
    var placa = campo("placa");
    if (!placa || !window.fetch) return;
    var aviso = document.createElement("div");
    aviso.className = "nota-preenchimento";
    aviso.setAttribute("role", "status");
    placa.parentNode.appendChild(aviso);

    function vazio(nome) { var c = campo(nome); return c && !c.disabled && !c.value.trim(); }
    function preencher(nome, valor) {
      var c = campo(nome);
      if (c && valor && vazio(nome)) { c.value = valor; c.dispatchEvent(new Event("change", { bubbles: true })); return true; }
      return false;
    }
    placa.addEventListener("blur", function () {
      var valor = placa.value.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
      aviso.textContent = "";
      if (valor.length < 7) return;
      fetch(formulario.getAttribute("data-url-veiculo") + "?placa=" + encodeURIComponent(valor), { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : { encontrado: false }; })
        .then(function (d) {
          if (!d.encontrado) return;
          var mudou = [preencher("marca", d.marca), preencher("modelo", d.modelo), preencher("ano", d.ano),
                       preencher("chassi", d.chassi), preencher("cor", d.cor), preencher("cor_outra", d.cor_outra)];
          if (mudou.some(Boolean)) aviso.textContent = "Dados preenchidos a partir do cadastro de veículos. Confira.";
        })
        .catch(function () { /* sem rede: o usuário preenche à mão */ });
    });
  })();

  /* ---------- Fotos: prévia, redução e confirmação ao remover ---------- */
  function reduzir(arquivo) {
    // Devolve uma Promise com o File reduzido, ou o original se não der para reduzir (ex.: HEIC no computador).
    if (!window.createImageBitmap || !/^image\/(jpeg|png|webp)$/.test(arquivo.type)) return Promise.resolve(arquivo);
    return createImageBitmap(arquivo, { imageOrientation: "from-image" }).then(function (bitmap) {
      var escala = Math.min(1, LADO_MAXIMO / Math.max(bitmap.width, bitmap.height));
      var tela = document.createElement("canvas");
      tela.width = Math.round(bitmap.width * escala);
      tela.height = Math.round(bitmap.height * escala);
      tela.getContext("2d").drawImage(bitmap, 0, 0, tela.width, tela.height);
      return new Promise(function (resolver) {
        tela.toBlob(function (blob) {
          if (!blob || blob.size >= arquivo.size) return resolver(arquivo);
          resolver(new File([blob], arquivo.name.replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" }));
        }, "image/jpeg", 0.82);
      });
    }).catch(function () { return arquivo; });
  }

  formulario.querySelectorAll("[data-foto]").forEach(function (entrada) {
    entrada.addEventListener("change", function () {
      var arquivo = entrada.files && entrada.files[0];
      var cartao = entrada.closest("[data-foto-campo]");
      var previa = cartao && cartao.querySelector("[data-previa]");
      if (!arquivo) return;
      reduzir(arquivo).then(function (final) {
        if (final !== arquivo && window.DataTransfer) {
          var pacote = new DataTransfer();
          pacote.items.add(final);
          entrada.files = pacote.files;
        }
        if (previa) {
          previa.innerHTML = "";
          if (/^image\//.test(final.type) && !/heic|heif/.test(final.type)) {
            var img = document.createElement("img");
            img.alt = "Prévia da foto escolhida";
            img.src = URL.createObjectURL(final);
            previa.appendChild(img);
          } else {
            previa.textContent = "Foto selecionada: " + final.name;
          }
        }
      });
    });
  });
  formulario.querySelectorAll('input[name^="remover_"]').forEach(function (caixa) {
    caixa.addEventListener("change", function () {
      if (caixa.checked && !window.confirm("Remover esta foto ao salvar? Esta ação não pode ser desfeita.")) caixa.checked = false;
    });
  });

  /* ---------- Cadastrar novo cliente sem perder o que foi digitado ---------- */
  var linkCliente = formulario.querySelector("[data-novo-cliente]");
  try {
    if (linkCliente) {
      linkCliente.addEventListener("click", function () {
        var dados = {};
        Array.prototype.forEach.call(formulario.elements, function (el) {
          if (el.name && el.type !== "file" && el.type !== "password" && el.name !== "csrfmiddlewaretoken") {
            dados[el.name] = el.type === "checkbox" ? el.checked : el.value;
          }
        });
        sessionStorage.setItem(CHAVE_RASCUNHO, JSON.stringify(dados));
      });
    }
    var guardado = sessionStorage.getItem(CHAVE_RASCUNHO);
    if (guardado && /[?&]cliente=/.test(window.location.search)) {   // voltou do cadastro do cliente
      var rascunho = JSON.parse(guardado);
      Object.keys(rascunho).forEach(function (nome) {
        var el = campo(nome);
        if (!el || nome === "cliente") return;
        if (el.type === "checkbox") el.checked = rascunho[nome]; else el.value = rascunho[nome];
      });
      ["cor", "servico"].forEach(function (nome) { var el = campo(nome); if (el) el.dispatchEvent(new Event("change", { bubbles: true })); });
    }
    sessionStorage.removeItem(CHAVE_RASCUNHO);
  } catch (erro) { /* navegação privada: segue sem rascunho */ }
})();
