/* Peças de formulário compartilhadas (Vip/Preparação e Regravações). Tudo aqui é melhoria: sem JavaScript, os campos
   comuns (listas, datas, arquivos) continuam funcionando e o servidor valida tudo de novo.

   VapForm.combo(formulario, opcoes)     busca digitando sobre uma lista (cliente, parceiro...)
   VapForm.cor(formulario)               pop-up de cores com amostras e o nome escrito
   VapForm.placa(formulario, mapa)       preenche o veículo a partir do cadastro (sem sobrescrever o digitado)
   VapForm.arquivos(formulario, opcoes)  prévia, redução de imagem no navegador e confirmação ao remover
   VapForm.rascunho(formulario, opcoes)  guarda o digitado ao ir cadastrar algo e restaura ao voltar */
(function () {
  function campo(formulario, nome) { return formulario.querySelector('[name="' + nome + '"]'); }

  /* ---------- Combobox (busca digitando) ---------- */
  function combo(formulario, o) {
    var bloco = formulario.querySelector(o.bloco);
    var select = campo(formulario, o.campo);
    if (!bloco || !select || select.disabled) return;

    var opcoes = Array.prototype.slice.call(select.options).filter(function (op) { return op.value; });
    var entrada = document.createElement("input");
    entrada.type = "text";
    entrada.autocomplete = "off";
    entrada.placeholder = o.placeholder;
    entrada.setAttribute("role", "combobox");
    entrada.setAttribute("aria-expanded", "false");
    entrada.setAttribute("aria-autocomplete", "list");
    entrada.setAttribute("aria-controls", o.idLista);
    entrada.setAttribute("aria-label", o.rotulo);
    var lista = document.createElement("ul");
    lista.id = o.idLista;
    lista.className = "combo__lista";
    lista.setAttribute("role", "listbox");
    lista.hidden = true;

    var caixa = document.createElement("div");
    caixa.className = "combo";
    caixa.appendChild(entrada);
    caixa.appendChild(lista);
    select.hidden = true;
    select.setAttribute("aria-hidden", "true");
    select.tabIndex = -1;
    select.parentNode.insertBefore(caixa, select.nextSibling);

    var marcado = -1;
    function selecionada() { return opcoes.filter(function (op) { return op.value === select.value; })[0]; }
    function mostrarNome() { var op = selecionada(); entrada.value = op ? op.text : ""; }

    function desenhar() {
      var termo = entrada.value.trim().toLowerCase();
      var achados = opcoes.filter(function (op) { return op.text.toLowerCase().indexOf(termo) !== -1; }).slice(0, 40);
      lista.innerHTML = "";
      marcado = -1;
      if (!achados.length) {
        var vazio = document.createElement("li");
        vazio.className = "combo__vazio";
        vazio.textContent = o.vazio;
        lista.appendChild(vazio);
      }
      achados.forEach(function (op, i) {
        var li = document.createElement("li");
        li.setAttribute("role", "option");
        li.id = o.idLista + "-op-" + i;
        li.textContent = op.text;
        li.addEventListener("mousedown", function (e) { e.preventDefault(); escolher(op); });
        lista.appendChild(li);
      });
      lista.hidden = false;
      entrada.setAttribute("aria-expanded", "true");
    }
    function fechar() { lista.hidden = true; entrada.setAttribute("aria-expanded", "false"); }
    function escolher(op) {
      select.value = op.value;
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
        var op = opcoes.filter(function (x) { return x.text === lista.querySelectorAll("[role=option]")[marcado].textContent; })[0];
        if (op) escolher(op);
      } else if (e.key === "Escape" && !lista.hidden) { fechar(); e.stopPropagation(); }
    });
    mostrarNome();
  }

  /* ---------- Cor: pop-up ---------- */
  function cor(formulario) {
    var bloco = formulario.querySelector("[data-cor-campo]");
    var select = campo(formulario, "cor");
    var botao = bloco && bloco.querySelector("[data-cor-botao]");
    var dialogo = document.getElementById("dialogo-cor");
    if (!botao || !select || !dialogo) return;
    var texto = botao.querySelector("[data-cor-texto]");
    var outraBloco = bloco.querySelector("[data-cor-outra-bloco]");
    var outra = campo(formulario, "cor_outra");
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
  }

  /* ---------- Placa: preenche a partir do cadastro de veículos ---------- */
  // mapa: { chave do JSON -> nome do campo do formulário }, ex.: { marca: "marca", ano: "ano", ... }
  function placa(formulario, mapa) {
    var entrada = campo(formulario, "placa");
    if (!entrada || !window.fetch) return;
    var aviso = document.createElement("div");
    aviso.className = "nota-preenchimento";
    aviso.setAttribute("role", "status");
    entrada.parentNode.appendChild(aviso);

    function vazio(nome) { var c = campo(formulario, nome); return c && !c.disabled && !c.value.trim(); }
    function preencher(nome, valor) {
      var c = campo(formulario, nome);
      if (c && valor && vazio(nome)) { c.value = valor; c.dispatchEvent(new Event("change", { bubbles: true })); return true; }
      return false;
    }
    entrada.addEventListener("blur", function () {
      var valor = entrada.value.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
      aviso.textContent = "";
      if (valor.length < 7) return;
      fetch(formulario.getAttribute("data-url-veiculo") + "?placa=" + encodeURIComponent(valor), { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : { encontrado: false }; })
        .then(function (d) {
          if (!d.encontrado) return;
          var mudou = Object.keys(mapa).map(function (chave) { return preencher(mapa[chave], d[chave]); });
          if (mudou.some(Boolean)) aviso.textContent = "Dados preenchidos a partir do cadastro de veículos. Confira.";
        })
        .catch(function () { /* sem rede: o usuário preenche à mão */ });
    });
  }

  /* ---------- Arquivos: prévia, redução e confirmação ao remover ---------- */
  function reduzir(arquivo, ladoMaximo) {
    // Devolve uma Promise com o File reduzido, ou o original se não der (PDF, HEIC no computador...).
    if (!window.createImageBitmap || !/^image\/(jpeg|png|webp)$/.test(arquivo.type)) return Promise.resolve(arquivo);
    return createImageBitmap(arquivo, { imageOrientation: "from-image" }).then(function (bitmap) {
      var escala = Math.min(1, ladoMaximo / Math.max(bitmap.width, bitmap.height));
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

  // opcoes: { entrada: "[data-foto]", cartao: "[data-foto-campo]", previa: "[data-previa]", remover: 'input[name^="remover_"]',
  //           lado: 1600, textoRemover: "...", rotulo: "foto" }
  function arquivos(formulario, o) {
    formulario.querySelectorAll(o.entrada).forEach(function (entrada) {
      entrada.addEventListener("change", function () {
        var arquivo = entrada.files && entrada.files[0];
        var cartao = entrada.closest(o.cartao);
        var previa = cartao && cartao.querySelector(o.previa);
        if (!arquivo) return;
        reduzir(arquivo, o.lado || 1600).then(function (final) {
          if (final !== arquivo && window.DataTransfer) {
            var pacote = new DataTransfer();
            pacote.items.add(final);
            entrada.files = pacote.files;
          }
          if (previa) {
            previa.innerHTML = "";
            if (/^image\//.test(final.type) && !/heic|heif/.test(final.type)) {
              var img = document.createElement("img");
              img.alt = "Prévia do arquivo escolhido";
              img.src = URL.createObjectURL(final);
              previa.appendChild(img);
            } else {
              previa.textContent = "Selecionado: " + final.name;
            }
          }
        });
      });
    });
    formulario.querySelectorAll(o.remover).forEach(function (caixa) {
      caixa.addEventListener("change", function () {
        if (caixa.checked && !window.confirm(o.textoRemover)) caixa.checked = false;
      });
    });
  }

  /* ---------- Rascunho: ir cadastrar cliente/parceiro/técnico sem perder o que foi digitado ---------- */
  // opcoes: { chave: "vip_rascunho", links: "[data-novo-cliente]", parametros: /[?&]cliente=/, ignorar: ["cliente"], eventos: ["cor"] }
  function rascunho(formulario, o) {
    var links = formulario.querySelectorAll(o.links);
    try {
      links.forEach(function (link) {
        link.addEventListener("click", function () {
          var dados = {};
          Array.prototype.forEach.call(formulario.elements, function (el) {
            if (el.name && el.type !== "file" && el.type !== "password" && el.name !== "csrfmiddlewaretoken") {
              dados[el.name] = (el.type === "checkbox" || el.type === "radio") ? (el.type === "radio" ? (el.checked ? el.value : dados[el.name]) : el.checked) : el.value;
            }
          });
          sessionStorage.setItem(o.chave, JSON.stringify(dados));
        });
      });
      var guardado = sessionStorage.getItem(o.chave);
      if (guardado && o.parametros.test(window.location.search)) {   // voltou do cadastro
        var salvo = JSON.parse(guardado);
        Object.keys(salvo).forEach(function (nome) {
          var elementos = formulario.querySelectorAll('[name="' + nome + '"]');
          if (!elementos.length || (o.ignorar || []).indexOf(nome) !== -1) return;
          elementos.forEach(function (el) {
            if (el.type === "checkbox") el.checked = salvo[nome];
            else if (el.type === "radio") el.checked = el.value === salvo[nome];
            else el.value = salvo[nome];
          });
        });
        (o.eventos || []).forEach(function (nome) { var el = campo(formulario, nome); if (el) el.dispatchEvent(new Event("change", { bubbles: true })); });
      }
      sessionStorage.removeItem(o.chave);
    } catch (erro) { /* navegação privada: segue sem rascunho */ }
  }

  window.VapForm = { combo: combo, cor: cor, placa: placa, arquivos: arquivos, rascunho: rascunho };
})();
