/**
 * Módulo de chat: histórico, streaming via WebSocket e ações de mensagem.
 */

const Chat = (() => {
  const { $, el, esc } = UI;

  const estado = {
    conversaId: null,
    conversas: [],
    gerando: false,
    usarRag: false,
    agenteId: null,
    modelo: null,
    params: {},
    nodoStreaming: null,
    bufferStreaming: "",
    fontesPendentes: [],
  };

  let socket = null;

  // =====================================================================
  // Inicialização
  // =====================================================================
  function iniciar() {
    socket = new API.ChatSocket();

    socket
      .em("conversation", (e) => {
        estado.conversaId = e.conversation_id;
        carregarConversas();
      })
      .em("sources", (e) => {
        estado.fontesPendentes = e.sources || [];
      })
      .em("start", () => iniciarBolhaResposta())
      .em("token", (e) => acrescentarToken(e.content))
      .em("done", (e) => concluir(e))
      .em("stopped", () => {
        definirStatus("Interrompido.");
        finalizarGeracao();
      })
      .em("error", (e) => {
        UI.erro(e.error || "Falha na geração.");
        finalizarGeracao();
      })
      .em("fechado", () => {
        if (estado.gerando) {
          definirStatus("Conexão perdida — reconectando…");
          finalizarGeracao();
        }
      });

    socket.conectar();
    ligarEventos();
  }

  function ligarEventos() {
    const entrada = $("#entrada");

    entrada.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        enviar();
      }
    });

    // Textarea que cresce com o conteúdo, até o teto definido no CSS.
    entrada.addEventListener("input", () => {
      entrada.style.height = "auto";
      entrada.style.height = Math.min(entrada.scrollHeight, 220) + "px";
    });

    $("#btn-enviar").addEventListener("click", () => {
      if (estado.gerando) socket.parar();
      else enviar();
    });

    $("#btn-nova-conversa").addEventListener("click", () => novaConversa());

    $("#alt-rag").addEventListener("click", (e) => {
      estado.usarRag = !estado.usarRag;
      e.currentTarget.classList.toggle("ligado", estado.usarRag);
      if (estado.usarRag && estado.conversaId) {
        aplicarRagNaConversa();
      }
    });

    $("#alt-params").addEventListener("click", abrirParametros);

    $("#seletor-modelo").addEventListener("change", (e) => {
      estado.modelo = e.target.value || null;
    });

    $("#seletor-agente").addEventListener("change", (e) => {
      estado.agenteId = e.target.value ? Number(e.target.value) : null;
    });

    $("#busca-conversas").addEventListener(
      "input",
      UI.esperar((e) => carregarConversas(e.target.value), 300)
    );

    // Delegação: botões "copiar" dos blocos de código gerados pelo Markdown.
    $("#chat-lista").addEventListener("click", (e) => {
      const botao = e.target.closest("[data-copiar-codigo]");
      if (!botao) return;
      const codigo = botao.closest("pre")?.querySelector("code");
      if (codigo) UI.copiar(codigo.textContent);
    });
  }

  // =====================================================================
  // Conversas
  // =====================================================================
  async function carregarConversas(busca = "") {
    try {
      const dados = await API.chat.conversas({ busca, per_page: 80 });
      estado.conversas = dados.items;
      renderizarListaConversas();
    } catch (e) {
      console.error("Falha ao listar conversas:", e);
    }
  }

  function renderizarListaConversas() {
    const lista = $("#lista-conversas");
    lista.innerHTML = "";

    if (!estado.conversas.length) {
      lista.innerHTML =
        '<div class="pequeno txt-3 centro" style="padding:16px">Nenhuma conversa ainda.</div>';
      return;
    }

    estado.conversas.forEach((conversa) => {
      const item = el("div", {
        classe: `conversa-item ${conversa.id === estado.conversaId ? "ativa" : ""}`,
        title: `${conversa.title}\n${conversa.message_count} mensagens · ${UI.quando(
          conversa.last_message_at || conversa.created_at
        )}`,
      });

      if (conversa.pinned) {
        item.append(
          el("span", { classe: "fixado", html: Icones.alfinete(12) })
        );
      }

      item.append(el("span", { classe: "conversa-titulo", texto: conversa.title }));

      const acoes = el("div", { classe: "conversa-acoes" });

      acoes.append(
        el("button", {
          html: Icones.alfinete(13),
          title: conversa.pinned ? "Desafixar" : "Fixar",
          onclick: async (e) => {
            e.stopPropagation();
            await API.chat.atualizarConversa(conversa.id, { pinned: !conversa.pinned });
            carregarConversas($("#busca-conversas").value);
          },
        }),
        el("button", {
          html: Icones.lapis(13),
          title: "Renomear",
          onclick: async (e) => {
            e.stopPropagation();
            const novo = await UI.perguntar("Título da conversa", conversa.title, {
              titulo: "Renomear conversa",
            });
            if (novo) {
              await API.chat.atualizarConversa(conversa.id, { title: novo });
              carregarConversas($("#busca-conversas").value);
            }
          },
        }),
        el("button", {
          html: Icones.lixeira(13),
          title: "Excluir",
          onclick: async (e) => {
            e.stopPropagation();
            const ok = await UI.confirmar(
              `Excluir "${conversa.title}" e todas as suas mensagens?`,
              { titulo: "Excluir conversa", perigoso: true }
            );
            if (!ok) return;
            await API.chat.removerConversa(conversa.id);
            if (estado.conversaId === conversa.id) novaConversa();
            carregarConversas($("#busca-conversas").value);
            UI.sucesso("Conversa excluída.");
          },
        })
      );

      item.append(acoes);
      item.addEventListener("click", () => abrirConversa(conversa.id));
      lista.append(item);
    });
  }

  async function abrirConversa(id) {
    try {
      const conversa = await API.chat.conversa(id);
      estado.conversaId = id;
      estado.modelo = conversa.model_name;
      estado.agenteId = conversa.agent_id;
      estado.usarRag = (conversa.rag_collections || []).length > 0;
      estado.params = conversa.params || {};

      $("#seletor-modelo").value = conversa.model_name || "";
      $("#seletor-agente").value = conversa.agent_id || "";
      $("#alt-rag").classList.toggle("ligado", estado.usarRag);

      renderizarMensagens(conversa.messages);
      renderizarListaConversas();
      App.irPara("chat");
    } catch (e) {
      UI.erro("Não foi possível abrir a conversa.");
    }
  }

  function novaConversa() {
    estado.conversaId = null;
    estado.fontesPendentes = [];
    renderizarBoasVindas();
    renderizarListaConversas();
    App.irPara("chat");
    $("#entrada").focus();
  }

  async function aplicarRagNaConversa() {
    try {
      const colecoes = await API.documentos.colecoes();
      await API.chat.atualizarConversa(estado.conversaId, {
        rag_collections: colecoes.map((c) => c.name),
      });
    } catch {
      /* sem coleções ainda: o RAG simplesmente não encontra contexto */
    }
  }

  // =====================================================================
  // Renderização de mensagens
  // =====================================================================
  function renderizarBoasVindas() {
    $("#chat-lista").innerHTML = `
      <div class="boas-vindas">
        <div class="boas-vindas-sinal">AI</div>
        <h2>Como posso ajudar?</h2>
        <p>Converse com modelos de IA rodando inteiramente no seu computador.</p>
        <div class="sugestoes">
          <button class="sugestao" data-sugestao="Explique como funciona o RAG (geração aumentada por recuperação) em termos simples.">
            <div class="sugestao-titulo">Entender o RAG</div>
            <div class="sugestao-texto">Como a busca em documentos melhora as respostas</div>
          </button>
          <button class="sugestao" data-sugestao="Escreva uma função Python que leia um CSV grande em blocos e calcule a média de uma coluna.">
            <div class="sugestao-titulo">Escrever código</div>
            <div class="sugestao-texto">Processar um CSV grande em Python</div>
          </button>
          <button class="sugestao" data-sugestao="Resuma os pontos principais dos documentos que eu indexei.">
            <div class="sugestao-titulo">Resumir documentos</div>
            <div class="sugestao-texto">Requer documentos indexados e o RAG ligado</div>
          </button>
          <button class="sugestao" data-sugestao="Quais modelos de IA estão instalados e quanto de memória cada um usa?">
            <div class="sugestao-titulo">Consultar o sistema</div>
            <div class="sugestao-texto">Modelos instalados e uso de recursos</div>
          </button>
        </div>
      </div>`;

    UI.$$(".sugestao").forEach((botao) =>
      botao.addEventListener("click", () => {
        $("#entrada").value = botao.dataset.sugestao;
        $("#entrada").dispatchEvent(new Event("input"));
        enviar();
      })
    );
  }

  function renderizarMensagens(mensagens) {
    const lista = $("#chat-lista");
    lista.innerHTML = "";

    const visiveis = (mensagens || []).filter((m) =>
      ["user", "assistant"].includes(m.role)
    );

    if (!visiveis.length) {
      renderizarBoasVindas();
      return;
    }

    visiveis.forEach((m) => lista.append(criarBolha(m)));
    rolarParaFim(true);
  }

  function criarBolha(mensagem) {
    const ehUsuario = mensagem.role === "user";

    const conteudo = el("div", {
      classe: "msg-conteudo md",
      html: ehUsuario
        ? `<p>${esc(mensagem.content).replace(/\n/g, "<br>")}</p>`
        : Markdown.renderizar(mensagem.content),
    });

    const cabecalho = el("div", { classe: "msg-cabecalho" }, [
      el("span", { classe: "msg-autor", texto: ehUsuario ? "Você" : "Assistente" }),
      el("span", { classe: "msg-meta", texto: metaDe(mensagem) }),
    ]);

    const corpo = el("div", { classe: "msg-corpo" }, [cabecalho, conteudo]);

    // Fontes RAG usadas na resposta.
    const fontes = mensagem.meta?.sources;
    if (fontes?.length) corpo.append(criarFontes(fontes));

    if (mensagem.error) {
      corpo.append(
        el("div", { classe: "msg-erro", texto: `Erro: ${mensagem.error}` })
      );
    }

    if (mensagem.id) corpo.append(criarAcoes(mensagem));

    const bolha = el(
      "div",
      {
        classe: `msg ${ehUsuario ? "usuario" : "assistente"}`,
        dados: { id: mensagem.id || "" },
      },
      [
        el("div", {
          classe: "msg-avatar",
          texto: ehUsuario ? (App.usuario?.username?.[0] || "V").toUpperCase() : "",
          html: ehUsuario ? undefined : Icones.robo(16),
        }),
        corpo,
      ]
    );

    return bolha;
  }

  function metaDe(mensagem) {
    const partes = [];
    if (mensagem.model_name) partes.push(mensagem.model_name);
    if (mensagem.tokens) partes.push(`${mensagem.tokens} tokens`);
    if (mensagem.tokens_per_second) {
      partes.push(`${mensagem.tokens_per_second.toFixed(1)} tok/s`);
    }
    if (mensagem.edited) partes.push("editada");
    return partes.join(" · ");
  }

  function criarFontes(fontes) {
    const caixa = el("div", { classe: "fontes" }, [
      el("div", { classe: "fontes-titulo", texto: `Fontes (${fontes.length})` }),
    ]);

    fontes.forEach((f) => {
      caixa.append(
        el("div", { classe: "fonte" }, [
          el("span", { classe: "fonte-num", texto: `[${f.index}]` }),
          el("span", {
            texto: `${f.title || "documento"}${f.page ? `, p. ${f.page}` : ""} — ${
              (f.excerpt || "").slice(0, 130)
            }…`,
          }),
          el("span", {
            classe: "fonte-score",
            texto: (f.score ?? 0).toFixed(2),
          }),
        ])
      );
    });

    return caixa;
  }

  function criarAcoes(mensagem) {
    const acoes = el("div", { classe: "msg-acoes" });

    acoes.append(
      el("button", {
        classe: "msg-acao",
        html: `${Icones.copiar(12)} Copiar`,
        onclick: () => UI.copiar(mensagem.content),
      })
    );

    if (mensagem.role === "user") {
      acoes.append(
        el("button", {
          classe: "msg-acao",
          html: `${Icones.lapis(12)} Editar`,
          onclick: () => editarMensagem(mensagem),
        })
      );
    } else {
      acoes.append(
        el("button", {
          classe: "msg-acao",
          html: `${Icones.recarregar(12)} Regenerar`,
          onclick: () => regenerar(mensagem.id),
        })
      );
    }

    acoes.append(
      el("button", {
        classe: "msg-acao",
        html: `${Icones.lixeira(12)} Excluir`,
        onclick: async () => {
          const ok = await UI.confirmar("Excluir esta mensagem?", {
            perigoso: true,
          });
          if (!ok) return;
          await API.chat.removerMensagem(mensagem.id);
          abrirConversa(estado.conversaId);
        },
      })
    );

    return acoes;
  }

  // =====================================================================
  // Envio e streaming
  // =====================================================================
  async function enviar() {
    const entrada = $("#entrada");
    const texto = entrada.value.trim();
    if (!texto || estado.gerando) return;

    // Cria a conversa antes de enviar, para que o agente selecionado valha
    // já na primeira mensagem.
    if (!estado.conversaId) {
      try {
        const colecoes = estado.usarRag ? await API.documentos.colecoes() : [];
        const conversa = await API.chat.criarConversa({
          model_name: estado.modelo,
          agent_id: estado.agenteId,
          rag_collections: colecoes.map((c) => c.name),
        });
        estado.conversaId = conversa.id;
        $("#chat-lista").innerHTML = "";
      } catch (e) {
        UI.erro("Não foi possível criar a conversa.");
        return;
      }
    }

    entrada.value = "";
    entrada.style.height = "auto";

    $("#chat-lista").append(
      criarBolha({ role: "user", content: texto, meta: {} })
    );
    rolarParaFim();

    estado.gerando = true;
    estado.fontesPendentes = [];
    atualizarBotaoEnviar();
    definirStatus("Gerando…");

    socket.enviar({
      type: "chat",
      mensagem: texto,
      conversation_id: estado.conversaId,
      modelo: estado.modelo,
      usar_rag: estado.usarRag,
      params: estado.params,
    });
  }

  function iniciarBolhaResposta() {
    estado.bufferStreaming = "";

    const conteudo = el("div", {
      classe: "msg-conteudo md",
      html: '<span class="cursor-digitando"></span>',
    });

    const bolha = el("div", { classe: "msg assistente" }, [
      el("div", { classe: "msg-avatar", html: Icones.robo(16) }),
      el("div", { classe: "msg-corpo" }, [
        el("div", { classe: "msg-cabecalho" }, [
          el("span", { classe: "msg-autor", texto: "Assistente" }),
          el("span", { classe: "msg-meta", texto: estado.modelo || "" }),
        ]),
        conteudo,
      ]),
    ]);

    estado.nodoStreaming = conteudo;
    $("#chat-lista").append(bolha);
    rolarParaFim();
  }

  function acrescentarToken(texto) {
    if (!estado.nodoStreaming) iniciarBolhaResposta();

    estado.bufferStreaming += texto;

    // `parcial=true` faz o Markdown renderizar blocos de código ainda abertos,
    // evitando que o código apareça como texto solto durante a digitação.
    estado.nodoStreaming.innerHTML =
      Markdown.renderizar(estado.bufferStreaming, true) +
      '<span class="cursor-digitando"></span>';

    rolarParaFim();
  }

  function concluir(evento) {
    if (estado.nodoStreaming) {
      estado.nodoStreaming.innerHTML = Markdown.renderizar(estado.bufferStreaming);

      const corpo = estado.nodoStreaming.parentElement;
      corpo.querySelector(".msg-meta").textContent = metaDe({
        model_name: evento.model,
        tokens: evento.tokens,
        tokens_per_second: evento.tokens_per_second,
      });

      const fontes = evento.sources || estado.fontesPendentes;
      if (fontes?.length) corpo.append(criarFontes(fontes));

      if (evento.error) {
        corpo.append(
          el("div", { classe: "msg-erro", texto: `Erro: ${evento.error}` })
        );
      }

      corpo.append(
        criarAcoes({
          id: evento.message_id,
          role: "assistant",
          content: estado.bufferStreaming,
        })
      );
    }

    definirStatus(
      evento.tokens
        ? `${evento.tokens} tokens · ${(evento.duration_ms / 1000).toFixed(1)}s · ${
            evento.tokens_per_second
          } tok/s`
        : ""
    );

    finalizarGeracao();
    carregarConversas($("#busca-conversas").value);
    rolarParaFim();
  }

  function finalizarGeracao() {
    estado.gerando = false;
    estado.nodoStreaming = null;
    atualizarBotaoEnviar();
  }

  function atualizarBotaoEnviar() {
    const botao = $("#btn-enviar");
    botao.innerHTML = estado.gerando ? Icones.parar(16) : Icones.enviar(16);
    botao.classList.toggle("parar", estado.gerando);
    botao.title = estado.gerando ? "Interromper" : "Enviar";
  }

  function definirStatus(texto) {
    $("#status-chat").textContent = texto || "";
  }

  function rolarParaFim(imediato = false) {
    const caixa = $("#chat-mensagens");
    // Só acompanha automaticamente se o usuário já estava perto do fim —
    // caso contrário ele está lendo mensagens antigas.
    const perto =
      caixa.scrollHeight - caixa.scrollTop - caixa.clientHeight < 180;
    if (imediato || perto) {
      caixa.scrollTo({
        top: caixa.scrollHeight,
        behavior: imediato ? "auto" : "smooth",
      });
    }
  }

  // =====================================================================
  // Ações de mensagem
  // =====================================================================
  async function editarMensagem(mensagem) {
    const novo = await UI.perguntar("Mensagem", mensagem.content, {
      titulo: "Editar e regenerar",
      multilinha: true,
    });
    if (!novo || novo === mensagem.content) return;

    definirStatus("Regenerando…");
    try {
      await API.chat.editarMensagem(mensagem.id, novo, true);
      await abrirConversa(estado.conversaId);
      definirStatus("");
    } catch (e) {
      UI.erro(e.message);
      definirStatus("");
    }
  }

  async function regenerar(mensagemId) {
    definirStatus("Regenerando…");
    try {
      await API.chat.regenerar(mensagemId);
      await abrirConversa(estado.conversaId);
      definirStatus("");
    } catch (e) {
      UI.erro(e.message);
      definirStatus("");
    }
  }

  // =====================================================================
  // Parâmetros de geração
  // =====================================================================
  function abrirParametros() {
    const p = {
      temperature: 0.7,
      top_p: 0.95,
      top_k: 40,
      max_tokens: 1024,
      repeat_penalty: 1.1,
      seed: -1,
      ...estado.params,
    };

    const deslizante = (chave, rotulo, min, max, passo, dica) => `
      <div class="campo">
        <div class="campo-linha">
          <label class="campo-rotulo" style="margin:0">${rotulo}</label>
          <span class="campo-valor" id="valor-${chave}">${p[chave]}</span>
        </div>
        <input class="deslizante" type="range" id="param-${chave}"
               min="${min}" max="${max}" step="${passo}" value="${p[chave]}" />
        <div class="campo-dica">${dica}</div>
      </div>`;

    const corpo = el("div", {
      html:
        deslizante("temperature", "Temperatura", 0, 2, 0.05,
          "Mais baixo = respostas previsíveis; mais alto = criativas.") +
        deslizante("top_p", "Top-P", 0, 1, 0.01,
          "Considera apenas os tokens que somam esta probabilidade.") +
        deslizante("top_k", "Top-K", 0, 200, 1,
          "Limita a escolha aos K tokens mais prováveis. 0 desativa.") +
        deslizante("max_tokens", "Tokens máximos", 64, 8192, 64,
          "Tamanho máximo da resposta.") +
        deslizante("repeat_penalty", "Penalidade de repetição", 1, 2, 0.05,
          "Acima de 1 desestimula a repetição de trechos.") +
        `<div class="campo">
           <label class="campo-rotulo" for="param-seed">Semente</label>
           <input class="entrada" type="number" id="param-seed" value="${p.seed}" />
           <div class="campo-dica">-1 gera resposta diferente a cada vez. Um valor fixo torna a geração reproduzível.</div>
         </div>`,
    });

    // Reflete o valor do deslizante enquanto arrasta.
    corpo.querySelectorAll(".deslizante").forEach((entrada) => {
      entrada.addEventListener("input", () => {
        const chave = entrada.id.replace("param-", "");
        corpo.querySelector(`#valor-${chave}`).textContent = entrada.value;
      });
    });

    UI.modal({
      titulo: "Parâmetros de geração",
      corpo,
      acoes: [
        {
          rotulo: "Restaurar padrões",
          classe: "btn-fantasma",
          fechar: false,
          aoClicar: () => {
            estado.params = {};
            $("#alt-params").classList.remove("ligado");
            UI.fecharModal();
            UI.sucesso("Parâmetros restaurados.");
          },
        },
        {
          rotulo: "Aplicar",
          classe: "btn-primario",
          aoClicar: async () => {
            const lidos = {};
            ["temperature", "top_p", "repeat_penalty"].forEach((k) => {
              lidos[k] = parseFloat(corpo.querySelector(`#param-${k}`).value);
            });
            ["top_k", "max_tokens", "seed"].forEach((k) => {
              lidos[k] = parseInt(corpo.querySelector(`#param-${k}`).value, 10);
            });

            estado.params = lidos;
            $("#alt-params").classList.add("ligado");

            if (estado.conversaId) {
              await API.chat.atualizarConversa(estado.conversaId, { params: lidos });
            }
            UI.sucesso("Parâmetros aplicados.");
          },
        },
      ],
    });
  }

  // =====================================================================
  // Seletores de modelo e agente
  // =====================================================================
  async function carregarSeletores() {
    try {
      const [modelos, agentes] = await Promise.all([
        API.modelos.listar(),
        API.agentes.listar({ apenas_ativos: true }),
      ]);

      const seletorModelo = $("#seletor-modelo");
      seletorModelo.innerHTML = modelos.length
        ? modelos
            .filter((m) => m.kind === "chat")
            .map(
              (m) =>
                `<option value="${esc(m.name)}" ${m.is_default ? "selected" : ""}>${esc(
                  m.name
                )}</option>`
            )
            .join("")
        : '<option value="">Nenhum modelo instalado</option>';

      if (!estado.modelo && seletorModelo.value) estado.modelo = seletorModelo.value;

      $("#seletor-agente").innerHTML =
        '<option value="">Sem agente</option>' +
        agentes
          .map(
            (a) =>
              `<option value="${a.id}">${esc(a.avatar || "")} ${esc(a.name)}</option>`
          )
          .join("");
    } catch (e) {
      console.error("Falha ao carregar seletores:", e);
    }
  }

  return {
    iniciar,
    carregarConversas,
    carregarSeletores,
    novaConversa,
    abrirConversa,
    get estado() {
      return estado;
    },
    get socket() {
      return socket;
    },
  };
})();
