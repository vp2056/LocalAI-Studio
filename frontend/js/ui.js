/**
 * Utilitários de interface: avisos, modais, formatação e helpers de DOM.
 */

const UI = (() => {
  // =====================================================================
  // Seletores e criação de elementos
  // =====================================================================
  const $ = (seletor, raiz = document) => raiz.querySelector(seletor);
  const $$ = (seletor, raiz = document) => [...raiz.querySelectorAll(seletor)];

  /**
   * Cria um elemento.
   *
   * `html` é atribuído via innerHTML e deve conter apenas conteúdo já
   * escapado ou gerado internamente — nunca texto bruto vindo da API.
   * Para texto de terceiros use a propriedade `texto`.
   */
  function el(tag, props = {}, filhos = []) {
    const nodo = document.createElement(tag);
    for (const [chave, valor] of Object.entries(props)) {
      // Propriedades indefinidas são ignoradas: atribuí-las gravaria a string
      // "undefined" no textContent/innerHTML.
      if (valor === undefined && ["texto", "html", "classe"].includes(chave)) continue;

      if (chave === "classe") nodo.className = valor;
      else if (chave === "texto") nodo.textContent = valor;
      else if (chave === "html") nodo.innerHTML = valor;
      else if (chave === "dados") Object.assign(nodo.dataset, valor);
      else if (chave.startsWith("on")) {
        nodo.addEventListener(chave.slice(2).toLowerCase(), valor);
      } else if (valor !== null && valor !== undefined && valor !== false) {
        nodo.setAttribute(chave, valor);
      }
    }
    (Array.isArray(filhos) ? filhos : [filhos])
      .filter(Boolean)
      .forEach((f) => nodo.append(f));
    return nodo;
  }

  /** Escapa texto para inserção segura em HTML. */
  const esc = (t) =>
    String(t ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");

  /** Substitui os elementos `data-icone` pelos SVGs correspondentes. */
  function aplicarIcones(raiz = document) {
    $$("[data-icone]", raiz).forEach((nodo) => {
      const nome = nodo.dataset.icone;
      const tamanho = Number(nodo.dataset.tamanho) || 17;
      if (Icones[nome]) {
        nodo.innerHTML = Icones[nome](tamanho);
        delete nodo.dataset.icone;
      }
    });
  }

  // =====================================================================
  // Avisos flutuantes
  // =====================================================================
  function aviso(mensagem, tipo = "info", duracao = 4200) {
    const caixa = $("#avisos");
    const nodo = el("div", { classe: `aviso ${tipo}` }, [
      el("div", { classe: "aviso-sinal" }),
      el("div", { classe: "aviso-texto", texto: mensagem }),
    ]);

    caixa.append(nodo);

    const remover = () => {
      nodo.classList.add("saindo");
      setTimeout(() => nodo.remove(), 220);
    };

    nodo.addEventListener("click", remover);
    if (duracao > 0) setTimeout(remover, duracao);
    return nodo;
  }

  const sucesso = (m) => aviso(m, "sucesso");
  const erro = (m) => aviso(m, "erro", 6500);
  const alerta = (m) => aviso(m, "alerta", 5500);

  // =====================================================================
  // Modal
  // =====================================================================
  let aoFecharModal = null;

  /**
   * Abre o modal.
   *
   * @param {object} opcoes {titulo, corpo (Node|string HTML), acoes:[{rotulo,
   *                         classe, aoClicar, fechar}], largo, aoFechar}
   */
  function modal({ titulo, corpo, acoes = [], largo = false, aoFechar = null }) {
    $("#modal-titulo").textContent = titulo || "";
    $("#modal").classList.toggle("largo", !!largo);

    const areaCorpo = $("#modal-corpo");
    areaCorpo.innerHTML = "";
    if (typeof corpo === "string") areaCorpo.innerHTML = corpo;
    else if (corpo) areaCorpo.append(corpo);

    const rodape = $("#modal-rodape");
    rodape.innerHTML = "";
    acoes.forEach((acao) => {
      rodape.append(
        el("button", {
          classe: `btn ${acao.classe || "btn-secundario"}`,
          texto: acao.rotulo,
          onclick: async (ev) => {
            const botao = ev.currentTarget;
            if (acao.aoClicar) {
              botao.disabled = true;
              try {
                const resultado = await acao.aoClicar();
                if (resultado === false) return; // ação cancelou o fechamento
              } finally {
                botao.disabled = false;
              }
            }
            if (acao.fechar !== false) fecharModal();
          },
        })
      );
    });

    aoFecharModal = aoFechar;
    $("#sobreposicao").classList.add("aberta");
    aplicarIcones(areaCorpo);

    // Foco no primeiro campo: evita que o usuário precise clicar.
    setTimeout(() => {
      const primeiro = areaCorpo.querySelector("input, textarea, select");
      if (primeiro) primeiro.focus();
    }, 60);
  }

  function fecharModal() {
    $("#sobreposicao").classList.remove("aberta");
    if (aoFecharModal) {
      const f = aoFecharModal;
      aoFecharModal = null;
      f();
    }
  }

  /** Modal de confirmação; resolve para true/false. */
  function confirmar(mensagem, { titulo = "Confirmar", perigoso = false } = {}) {
    return new Promise((resolve) => {
      let respondido = false;
      modal({
        titulo,
        corpo: el("p", { texto: mensagem, classe: "txt-2" }),
        acoes: [
          {
            rotulo: "Cancelar",
            classe: "btn-fantasma",
            aoClicar: () => {
              respondido = true;
              resolve(false);
            },
          },
          {
            rotulo: perigoso ? "Excluir" : "Confirmar",
            classe: perigoso ? "btn-perigo" : "btn-primario",
            aoClicar: () => {
              respondido = true;
              resolve(true);
            },
          },
        ],
        aoFechar: () => {
          // Fechar pelo X ou Esc conta como cancelamento.
          if (!respondido) resolve(false);
        },
      });
    });
  }

  /** Modal com um único campo de texto; resolve para o valor ou null. */
  function perguntar(rotulo, valorInicial = "", { titulo = "Editar", multilinha = false } = {}) {
    return new Promise((resolve) => {
      const campo = multilinha
        ? el("textarea", { classe: "area", rows: 4 })
        : el("input", { classe: "entrada" });
      campo.value = valorInicial;

      let respondido = false;
      const confirmarValor = () => {
        respondido = true;
        resolve(campo.value.trim() || null);
      };

      if (!multilinha) {
        campo.addEventListener("keydown", (e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            confirmarValor();
            fecharModal();
          }
        });
      }

      modal({
        titulo,
        corpo: el("div", { classe: "campo" }, [
          el("label", { classe: "campo-rotulo", texto: rotulo }),
          campo,
        ]),
        acoes: [
          {
            rotulo: "Cancelar",
            classe: "btn-fantasma",
            aoClicar: () => {
              respondido = true;
              resolve(null);
            },
          },
          { rotulo: "Salvar", classe: "btn-primario", aoClicar: confirmarValor },
        ],
        aoFechar: () => {
          if (!respondido) resolve(null);
        },
      });
    });
  }

  // =====================================================================
  // Formatação
  // =====================================================================
  function bytes(n) {
    if (!n) return "0 B";
    const unidades = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), unidades.length - 1);
    return `${(n / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${unidades[i]}`;
  }

  function numero(n) {
    return new Intl.NumberFormat("pt-BR").format(Math.round(Number(n) || 0));
  }

  function dataHora(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleString("pt-BR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  /** Data relativa ("há 5 min"), caindo para data absoluta acima de 7 dias. */
  function quando(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    const segundos = (Date.now() - d.getTime()) / 1000;

    if (segundos < 60) return "agora";
    if (segundos < 3600) return `há ${Math.floor(segundos / 60)} min`;
    if (segundos < 86400) return `há ${Math.floor(segundos / 3600)} h`;
    if (segundos < 604800) return `há ${Math.floor(segundos / 86400)} d`;

    return d.toLocaleDateString("pt-BR", {
      day: "2-digit",
      month: "short",
      year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric",
    });
  }

  function duracao(segundos) {
    const s = Math.floor(Number(segundos) || 0);
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (d) return `${d}d ${h}h`;
    if (h) return `${h}h ${m}min`;
    if (m) return `${m}min`;
    return `${s}s`;
  }

  /** Copia texto para a área de transferência, com alternativa para HTTP. */
  async function copiar(texto) {
    try {
      await navigator.clipboard.writeText(texto);
      sucesso("Copiado.");
      return true;
    } catch {
      // navigator.clipboard exige contexto seguro; em http:// usamos o método
      // legado, que continua funcionando.
      const area = el("textarea", {
        style: "position:fixed;opacity:0;top:0;left:0",
      });
      area.value = texto;
      document.body.append(area);
      area.select();
      const ok = document.execCommand("copy");
      area.remove();
      if (ok) sucesso("Copiado.");
      else erro("Não foi possível copiar.");
      return ok;
    }
  }

  /** Classe da barra conforme o nível de uso. */
  function nivelBarra(percentual) {
    if (percentual >= 90) return "critico";
    if (percentual >= 75) return "alerta";
    return "";
  }

  /** Componente de barra de progresso rotulada. */
  function barra(percentual, rotulo) {
    const p = Math.max(0, Math.min(100, Number(percentual) || 0));
    return `
      <div class="barra" title="${esc(rotulo || `${p.toFixed(1)}%`)}">
        <div class="barra-preenchida ${nivelBarra(p)}" style="width:${p}%"></div>
      </div>`;
  }

  /** Bloco de estado vazio. */
  function vazio(icone, titulo, texto, acaoHtml = "") {
    return `
      <div class="vazio">
        <div class="vazio-icone">${icone}</div>
        <div class="vazio-titulo">${esc(titulo)}</div>
        <div class="vazio-texto">${esc(texto)}</div>
        ${acaoHtml ? `<div class="mt-14">${acaoHtml}</div>` : ""}
      </div>`;
  }

  /** Adia a execução até o usuário parar de digitar. */
  function esperar(funcao, atraso = 320) {
    let temporizador;
    return (...args) => {
      clearTimeout(temporizador);
      temporizador = setTimeout(() => funcao(...args), atraso);
    };
  }

  return {
    $,
    $$,
    el,
    esc,
    aplicarIcones,
    aviso,
    sucesso,
    erro,
    alerta,
    modal,
    fecharModal,
    confirmar,
    perguntar,
    bytes,
    numero,
    dataHora,
    quando,
    duracao,
    copiar,
    barra,
    nivelBarra,
    vazio,
    esperar,
  };
})();
