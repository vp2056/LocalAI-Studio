/**
 * Renderização das páginas: painel, modelos, documentos, agentes, plugins,
 * monitor, logs, configurações e ajuda.
 *
 * Cada página expõe `render(container)` e, opcionalmente, `sair()` para
 * liberar temporizadores e sockets ao trocar de tela.
 */

const Paginas = (() => {
  const { $, $$, el, esc } = UI;

  // ===================================================================
  // Painel
  // ===================================================================
  const Painel = {
    async render(caixa) {
      caixa.innerHTML = '<div class="carregando-tela"><div class="girando"></div></div>';

      let info;
      try {
        info = await API.sistema.info();
      } catch (e) {
        caixa.innerHTML = UI.vazio("!", "Falha ao carregar", e.message);
        return;
      }

      const r = info.resources;
      const c = info.counts;
      const gpu = r.gpu.devices[0];

      caixa.innerHTML = `
        <div class="cabecalho-secao">
          <div>
            <h2>Painel</h2>
            <p>Visão geral do ${esc(info.app.name)} v${esc(info.app.version)} —
               modo ${esc(info.app.mode)} · ativo há ${UI.duracao(r.uptime_seconds)}</p>
          </div>
        </div>

        <div class="grade grade-4 mb-20">
          ${cartaoMetrica("CPU", `${r.cpu.percent.toFixed(0)}%`,
            `${r.cpu.cores} núcleos${r.cpu.frequency_mhz ? ` · ${(r.cpu.frequency_mhz / 1000).toFixed(1)} GHz` : ""}`,
            r.cpu.percent)}
          ${cartaoMetrica("Memória", `${r.memory.percent.toFixed(0)}%`,
            `${r.memory.used_gb} de ${r.memory.total_gb} GB`, r.memory.percent)}
          ${cartaoMetrica("Disco", `${r.disk.percent.toFixed(0)}%`,
            `${r.disk.free_gb} GB livres`, r.disk.percent)}
          ${gpu
            ? cartaoMetrica("GPU", `${gpu.utilization_percent ?? "—"}${gpu.utilization_percent != null ? "%" : ""}`,
                `${esc(gpu.name)} · ${gpu.memory_used_gb}/${gpu.memory_total_gb} GB`,
                gpu.memory_percent)
            : cartaoMetrica("GPU", "—", "Nenhuma GPU detectada", 0)}
        </div>

        <div class="grade grade-2 mb-20">
          <div class="cartao">
            <div class="cartao-titulo"><span data-icone="monitor" data-tamanho="15"></span> Recursos em tempo real</div>
            <div class="grafico-caixa"><canvas id="grafico-painel"></canvas></div>
            <div class="legenda">
              <span class="legenda-item"><span class="legenda-cor" style="background:var(--marca)"></span> CPU</span>
              <span class="legenda-item"><span class="legenda-cor" style="background:var(--acento)"></span> Memória</span>
            </div>
          </div>

          <div class="cartao">
            <div class="cartao-titulo"><span data-icone="banco" data-tamanho="15"></span> Conteúdo</div>
            <div class="grafico-caixa"><canvas id="grafico-conteudo"></canvas></div>
          </div>
        </div>

        <div class="grade grade-4 mb-20">
          ${cartaoSimples("Modelos", c.models, "cubo")}
          ${cartaoSimples("Conversas", c.conversations, "chat")}
          ${cartaoSimples("Mensagens", c.messages, "lista")}
          ${cartaoSimples("Documentos", c.documents, "documento")}
          ${cartaoSimples("Embeddings", c.embeddings, "banco")}
          ${cartaoSimples("Agentes", c.agents, "robo")}
          ${cartaoSimples("Plugins ativos", c.plugins, "plugue")}
          ${cartaoSimples("Índice vetorial", info.rag.index_size, "busca")}
        </div>

        <div class="grade grade-2">
          <div class="cartao">
            <div class="cartao-titulo"><span data-icone="cubo" data-tamanho="15"></span> Motores de inferência</div>
            ${Object.entries(info.models.backends)
              .map(
                ([nome, disponivel]) => `
                <div class="flex-centro gap-10" style="padding:6px 0">
                  <span class="etiqueta ${disponivel ? "ok" : ""}">${disponivel ? "instalado" : "ausente"}</span>
                  <span class="mono pequeno">${esc(nome)}</span>
                </div>`
              )
              .join("")}
            <div class="campo-dica mt-14">
              Modelo padrão: <strong>${esc(info.models.default_model || "nenhum")}</strong> ·
              carregados: ${info.models.loaded.length}/${info.models.max_loaded}
            </div>
          </div>

          <div class="cartao">
            <div class="cartao-titulo"><span data-icone="raio" data-tamanho="15"></span> Recursos extras</div>
            ${Object.entries(info.extras)
              .map(
                ([nome, e]) => `
                <div class="flex-centro gap-10" style="padding:6px 0">
                  <span class="etiqueta ${e.available ? "ok" : ""}">${e.available ? "pronto" : "não instalado"}</span>
                  <span class="pequeno">${esc(rotuloExtra(nome))}</span>
                </div>`
              )
              .join("")}
            <div class="campo-dica mt-14">
              Embeddings: <strong>${esc(info.rag.embedder.provider)}</strong>
              (${info.rag.embedder.dimension}d,
              ${info.rag.embedder.semantic ? "semântico" : "lexical"})
            </div>
          </div>
        </div>`;

      UI.aplicarIcones(caixa);

      // Série temporal alimentada pelo WebSocket do monitor.
      const grafico = new Graficos.Linha($("#grafico-painel"), {
        series: [
          { rotulo: "CPU", cor: Graficos.cor("--marca", "#7c6cff") },
          { rotulo: "Memória", cor: Graficos.cor("--acento", "#2fd4c4") },
        ],
        pontos: 50,
      });

      this._socket = API.monitorarSistema((m) => {
        grafico.empurrar([m.cpu_percent, m.memory_percent]);
      });

      new Graficos.Barras($("#grafico-conteudo"), { horizontal: true }).definir([
        { rotulo: "Conversas", valor: c.conversations },
        { rotulo: "Mensagens", valor: c.messages },
        { rotulo: "Documentos", valor: c.documents },
        { rotulo: "Embeddings", valor: c.embeddings },
        { rotulo: "Modelos", valor: c.models },
      ]);
    },

    sair() {
      if (this._socket) {
        this._socket.close();
        this._socket = null;
      }
    },
  };

  function cartaoMetrica(rotulo, valor, sub, percentual) {
    return `
      <div class="metrica">
        <div class="metrica-rotulo">${esc(rotulo)}</div>
        <div class="metrica-valor">${esc(valor)}</div>
        <div class="metrica-sub">${esc(sub)}</div>
        ${UI.barra(percentual)}
      </div>`;
  }

  function cartaoSimples(rotulo, valor, icone) {
    return `
      <div class="metrica">
        <div class="flex-centro gap-10">
          <span data-icone="${icone}" data-tamanho="15" class="txt-3"></span>
          <div class="metrica-rotulo" style="margin:0">${esc(rotulo)}</div>
        </div>
        <div class="metrica-valor" style="margin-top:8px">${UI.numero(valor)}</div>
      </div>`;
  }

  function rotuloExtra(nome) {
    return (
      {
        ocr: "OCR (imagem/PDF para texto)",
        stt: "Reconhecimento de voz",
        tts: "Texto para voz",
        image_generation: "Geração de imagens",
      }[nome] || nome
    );
  }

  // ===================================================================
  // Modelos
  // ===================================================================
  const Modelos = {
    async render(caixa) {
      caixa.innerHTML = '<div class="carregando-tela"><div class="girando"></div></div>';

      const [modelos, estado, downloads] = await Promise.all([
        API.modelos.listar({ incluir_indisponiveis: true }),
        API.modelos.estado(),
        API.modelos.downloads().catch(() => []),
      ]);

      const carregados = new Set(estado.loaded.map((m) => m.name));
      const ativos = downloads.filter((d) =>
        ["pending", "downloading"].includes(d.status)
      );

      caixa.innerHTML = `
        <div class="cabecalho-secao">
          <div>
            <h2>Modelos</h2>
            <p>${modelos.length} registrado(s) · ${estado.loaded.length} em memória</p>
          </div>
          <span class="espaco"></span>
          <button class="btn btn-secundario" id="btn-escanear"><span data-icone="recarregar" data-tamanho="14"></span> Reexaminar</button>
          <button class="btn btn-secundario" id="btn-baixar-modelo"><span data-icone="baixar" data-tamanho="14"></span> Baixar por URL</button>
          <button class="btn btn-primario" id="btn-importar-modelo"><span data-icone="mais" data-tamanho="14"></span> Importar</button>
        </div>

        ${ativos.length ? blocoDownloads(ativos) : ""}

        ${
          modelos.length
            ? `<div class="cartao" style="padding:0">
                 <div class="tabela-rolagem">
                   <table class="tabela">
                     <thead><tr>
                       <th>Modelo</th><th>Formato</th><th>Parâmetros</th>
                       <th>Quantização</th><th>Contexto</th><th>Tamanho</th>
                       <th>Usos</th><th class="direita">Ações</th>
                     </tr></thead>
                     <tbody>${modelos.map((m) => linhaModelo(m, carregados)).join("")}</tbody>
                   </table>
                 </div>
               </div>`
            : UI.vazio(
                "📦",
                "Nenhum modelo instalado",
                "Coloque arquivos .gguf na pasta models/ e clique em Reexaminar, ou importe um modelo pelo botão acima.",
                '<button class="btn btn-primario" id="btn-importar-vazio">Importar modelo</button>'
              )
        }`;

      UI.aplicarIcones(caixa);
      this.ligar(caixa);
    },

    ligar(caixa) {
      $("#btn-escanear")?.addEventListener("click", async (e) => {
        e.currentTarget.disabled = true;
        const achados = await API.modelos.escanear();
        UI.sucesso(`Varredura concluída: ${achados.length} modelo(s).`);
        App.recarregarPagina();
      });

      const abrirImportar = () => this.dialogoImportar();
      $("#btn-importar-modelo")?.addEventListener("click", abrirImportar);
      $("#btn-importar-vazio")?.addEventListener("click", abrirImportar);
      $("#btn-baixar-modelo")?.addEventListener("click", () => this.dialogoBaixar());

      $$("[data-acao-modelo]", caixa).forEach((botao) => {
        botao.addEventListener("click", async () => {
          const { acaoModelo: acao, id, nome } = botao.dataset;
          botao.disabled = true;
          try {
            if (acao === "carregar") {
              await API.modelos.carregar(id);
              UI.sucesso(`Modelo "${nome}" carregado.`);
            } else if (acao === "descarregar") {
              await API.modelos.descarregar(id);
              UI.sucesso("Modelo descarregado.");
            } else if (acao === "padrao") {
              await API.modelos.atualizar(id, { is_default: true });
              UI.sucesso(`"${nome}" agora é o modelo padrão.`);
            } else if (acao === "detalhes") {
              return this.dialogoDetalhes(id);
            } else if (acao === "remover") {
              const ok = await UI.confirmar(
                `Remover "${nome}" do catálogo? O arquivo em disco será preservado.`,
                { titulo: "Remover modelo", perigoso: true }
              );
              if (!ok) return;
              await API.modelos.remover(id, false);
              UI.sucesso("Modelo removido.");
            }
            App.recarregarPagina();
          } catch (e) {
            UI.erro(e.message);
          } finally {
            botao.disabled = false;
          }
        });
      });
    },

    dialogoImportar() {
      const corpo = el("div", {
        html: `
          <div class="campo">
            <label class="campo-rotulo" for="imp-caminho">Caminho do arquivo ou pasta</label>
            <input class="entrada" id="imp-caminho" placeholder="/home/usuario/modelos/llama-3-8b.Q4_K_M.gguf" />
            <div class="campo-dica">Aceita .gguf, .safetensors, .onnx ou uma pasta no formato HuggingFace.</div>
          </div>
          <div class="campo">
            <label class="campo-rotulo" for="imp-nome">Nome (opcional)</label>
            <input class="entrada" id="imp-nome" placeholder="Deixe vazio para usar o nome do arquivo" />
          </div>
          <div class="campo flex-centro gap-10">
            <div class="interruptor ligado" id="imp-copiar"></div>
            <div>
              <div class="pequeno negrito">Copiar para a pasta models/</div>
              <div class="campo-dica" style="margin:0">Desligue para apenas referenciar o arquivo onde ele está.</div>
            </div>
          </div>
          <hr style="border:none;border-top:1px solid var(--borda);margin:18px 0">
          <div class="campo">
            <label class="campo-rotulo" for="imp-arquivo">Ou envie um arquivo pelo navegador</label>
            <input class="entrada" type="file" id="imp-arquivo" accept=".gguf,.safetensors,.onnx,.bin" />
            <div class="campo-dica">Modelos grandes são mais rápidos pelo caminho no disco.</div>
          </div>`,
      });

      corpo
        .querySelector("#imp-copiar")
        .addEventListener("click", (e) => e.currentTarget.classList.toggle("ligado"));

      UI.modal({
        titulo: "Importar modelo",
        corpo,
        acoes: [
          { rotulo: "Cancelar", classe: "btn-fantasma" },
          {
            rotulo: "Importar",
            classe: "btn-primario",
            aoClicar: async () => {
              const arquivo = corpo.querySelector("#imp-arquivo").files[0];
              try {
                if (arquivo) {
                  const fd = new FormData();
                  fd.append("arquivo", arquivo);
                  UI.aviso("Enviando modelo… isso pode demorar.", "info", 8000);
                  await API.modelos.enviar(fd);
                } else {
                  const caminho = corpo.querySelector("#imp-caminho").value.trim();
                  if (!caminho) {
                    UI.alerta("Informe um caminho ou selecione um arquivo.");
                    return false;
                  }
                  await API.modelos.importar({
                    caminho,
                    nome: corpo.querySelector("#imp-nome").value.trim() || null,
                    copiar: corpo.querySelector("#imp-copiar").classList.contains("ligado"),
                  });
                }
                UI.sucesso("Modelo importado.");
                App.recarregarPagina();
                Chat.carregarSeletores();
              } catch (e) {
                UI.erro(e.message);
                return false;
              }
            },
          },
        ],
      });
    },

    dialogoBaixar() {
      const corpo = el("div", {
        html: `
          <div class="campo">
            <label class="campo-rotulo" for="dl-url">URL do modelo</label>
            <input class="entrada" id="dl-url" placeholder="https://exemplo.com/modelo.gguf" />
            <div class="campo-dica">O download roda em segundo plano e pode ser retomado se cair.</div>
          </div>
          <div class="campo">
            <label class="campo-rotulo" for="dl-nome">Nome do arquivo (opcional)</label>
            <input class="entrada" id="dl-nome" />
          </div>`,
      });

      UI.modal({
        titulo: "Baixar modelo",
        corpo,
        acoes: [
          { rotulo: "Cancelar", classe: "btn-fantasma" },
          {
            rotulo: "Iniciar download",
            classe: "btn-primario",
            aoClicar: async () => {
              const url = corpo.querySelector("#dl-url").value.trim();
              if (!url) {
                UI.alerta("Informe a URL.");
                return false;
              }
              try {
                await API.modelos.baixar(
                  url,
                  corpo.querySelector("#dl-nome").value.trim() || null
                );
                UI.sucesso("Download iniciado.");
                App.recarregarPagina();
              } catch (e) {
                UI.erro(e.message);
                return false;
              }
            },
          },
        ],
      });
    },

    async dialogoDetalhes(id) {
      const m = await API.modelos.obter(id);
      const meta = m.meta || {};

      const linhas = [
        ["Nome", m.name],
        ["Caminho", m.path],
        ["Formato", m.format],
        ["Motor", m.backend],
        ["Finalidade", m.kind],
        ["Tamanho", UI.bytes(m.size_bytes)],
        ["Arquitetura", m.architecture || "—"],
        ["Parâmetros", m.parameters || "—"],
        ["Quantização", m.quantization || "—"],
        ["Contexto", `${UI.numero(m.context_length)} tokens`],
        ["Camadas", meta.block_count ?? "—"],
        ["Cabeças de atenção", meta.head_count ?? "—"],
        ["Dimensão do embedding", meta.embedding_length ?? "—"],
        ["Template de chat", meta.chat_template ? "sim" : "não"],
        ["Usos", UI.numero(m.usage_count)],
        ["Último uso", UI.dataHora(m.last_used_at)],
      ];

      UI.modal({
        titulo: m.name,
        largo: true,
        corpo: `<div class="tabela-rolagem"><table class="tabela"><tbody>${linhas
          .map(
            ([k, v]) =>
              `<tr><td style="width:200px"><strong>${esc(k)}</strong></td><td class="quebra mono pequeno">${esc(v)}</td></tr>`
          )
          .join("")}</tbody></table></div>`,
        acoes: [{ rotulo: "Fechar", classe: "btn-secundario" }],
      });
    },
  };

  function linhaModelo(m, carregados) {
    const carregado = carregados.has(m.name);
    return `
      <tr>
        <td>
          <strong>${esc(m.name)}</strong>
          ${m.is_default ? '<span class="etiqueta marca" style="margin-left:6px">padrão</span>' : ""}
          ${carregado ? '<span class="etiqueta ok" style="margin-left:6px">em memória</span>' : ""}
          ${!m.is_available ? '<span class="etiqueta erro" style="margin-left:6px">arquivo ausente</span>' : ""}
        </td>
        <td><span class="etiqueta">${esc(m.format)}</span></td>
        <td class="num">${esc(m.parameters || "—")}</td>
        <td class="mono pequeno">${esc(m.quantization || "—")}</td>
        <td class="num">${UI.numero(m.context_length)}</td>
        <td class="num">${UI.bytes(m.size_bytes)}</td>
        <td class="num">${UI.numero(m.usage_count)}</td>
        <td class="direita">
          <div class="item-acoes" style="justify-content:flex-end">
            <button class="btn btn-pequeno btn-fantasma" data-acao-modelo="detalhes" data-id="${m.id}" title="Detalhes técnicos">${Icones.olho(13)}</button>
            ${
              carregado
                ? `<button class="btn btn-pequeno btn-secundario" data-acao-modelo="descarregar" data-id="${m.id}" data-nome="${esc(m.name)}">Descarregar</button>`
                : `<button class="btn btn-pequeno btn-secundario" data-acao-modelo="carregar" data-id="${m.id}" data-nome="${esc(m.name)}" ${!m.is_available ? "disabled" : ""}>Carregar</button>`
            }
            ${!m.is_default ? `<button class="btn btn-pequeno btn-fantasma" data-acao-modelo="padrao" data-id="${m.id}" data-nome="${esc(m.name)}" title="Definir como padrão">${Icones.estrela(13)}</button>` : ""}
            <button class="btn btn-pequeno btn-fantasma" data-acao-modelo="remover" data-id="${m.id}" data-nome="${esc(m.name)}" title="Remover">${Icones.lixeira(13)}</button>
          </div>
        </td>
      </tr>`;
  }

  function blocoDownloads(ativos) {
    return `
      <div class="cartao mb-20">
        <div class="cartao-titulo"><span data-icone="baixar" data-tamanho="15"></span> Downloads em andamento</div>
        ${ativos
          .map(
            (d) => `
          <div style="padding:8px 0">
            <div class="flex-centro gap-10 mb-8">
              <span class="pequeno negrito">${esc(d.filename)}</span>
              <span class="espaco"></span>
              <span class="pequeno txt-3 num">${d.progress.toFixed(1)}% ·
                ${UI.bytes(d.downloaded_bytes)} / ${UI.bytes(d.total_bytes)} ·
                ${UI.bytes(d.speed_bps)}/s</span>
            </div>
            ${UI.barra(d.progress)}
          </div>`
          )
          .join("")}
      </div>`;
  }

  // ===================================================================
  // Documentos / RAG
  // ===================================================================
  const Documentos = {
    async render(caixa) {
      caixa.innerHTML = '<div class="carregando-tela"><div class="girando"></div></div>';

      const [dados, stats, colecoes] = await Promise.all([
        API.documentos.listar({ per_page: 100 }),
        API.documentos.estatisticas(),
        API.documentos.colecoes(),
      ]);

      caixa.innerHTML = `
        <div class="cabecalho-secao">
          <div>
            <h2>Documentos e RAG</h2>
            <p>${stats.documents} documento(s) · ${UI.numero(stats.embeddings)} trechos indexados ·
               índice ${esc(stats.index_backend)}</p>
          </div>
          <span class="espaco"></span>
          <button class="btn btn-secundario" id="btn-buscar-rag"><span data-icone="busca" data-tamanho="14"></span> Testar busca</button>
          <button class="btn btn-secundario" id="btn-reconstruir"><span data-icone="recarregar" data-tamanho="14"></span> Reconstruir índice</button>
          <button class="btn btn-primario" id="btn-enviar-doc"><span data-icone="enviarArquivo" data-tamanho="14"></span> Enviar documento</button>
        </div>

        ${
          !stats.embedder.semantic
            ? `<div class="cartao mb-20" style="border-color:var(--alerta)">
                 <div class="flex-centro gap-10">
                   <span class="etiqueta alerta">atenção</span>
                   <div class="pequeno">
                     A busca está em modo <strong>lexical</strong> (provedor
                     <span class="mono">${esc(stats.embedder.provider)}</span>).
                     Para busca semântica de verdade, instale:
                     <span class="mono">pip install sentence-transformers</span>
                   </div>
                 </div>
               </div>`
            : ""
        }

        <div class="grade grade-4 mb-20">
          ${cartaoSimples("Documentos", stats.documents, "documento")}
          ${cartaoSimples("Indexados", stats.indexed, "check")}
          ${cartaoSimples("Trechos", stats.embeddings, "banco")}
          ${cartaoSimples("Coleções", colecoes.length, "pasta")}
        </div>

        ${
          dados.items.length
            ? `<div class="cartao" style="padding:0">
                 <div class="tabela-rolagem">
                   <table class="tabela">
                     <thead><tr>
                       <th>Documento</th><th>Tipo</th><th>Coleção</th>
                       <th>Situação</th><th>Trechos</th><th>Tamanho</th>
                       <th>Enviado</th><th class="direita">Ações</th>
                     </tr></thead>
                     <tbody>${dados.items.map(linhaDocumento).join("")}</tbody>
                   </table>
                 </div>
               </div>`
            : UI.vazio(
                "📄",
                "Nenhum documento indexado",
                "Envie PDF, DOCX, TXT, HTML, Markdown, CSV ou JSON para que o assistente possa consultá-los durante a conversa.",
                '<button class="btn btn-primario" id="btn-enviar-vazio">Enviar documento</button>'
              )
        }`;

      UI.aplicarIcones(caixa);
      this.ligar(caixa, colecoes);
    },

    ligar(caixa, colecoes) {
      const abrirEnvio = () => this.dialogoEnviar(colecoes);
      $("#btn-enviar-doc")?.addEventListener("click", abrirEnvio);
      $("#btn-enviar-vazio")?.addEventListener("click", abrirEnvio);
      $("#btn-buscar-rag")?.addEventListener("click", () => this.dialogoBuscar());

      $("#btn-reconstruir")?.addEventListener("click", async (e) => {
        e.currentTarget.disabled = true;
        try {
          const r = await API.documentos.reconstruir();
          UI.sucesso(r.detail);
        } catch (err) {
          UI.erro(err.message);
        } finally {
          e.currentTarget.disabled = false;
        }
      });

      $$("[data-acao-doc]", caixa).forEach((botao) => {
        botao.addEventListener("click", async () => {
          const { acaoDoc: acao, id, nome } = botao.dataset;
          botao.disabled = true;
          try {
            if (acao === "reindexar") {
              await API.documentos.reindexar(id);
              UI.sucesso("Documento reindexado.");
            } else if (acao === "remover") {
              const ok = await UI.confirmar(
                `Remover "${nome}" e seus ${botao.dataset.trechos} trecho(s) do índice?`,
                { titulo: "Remover documento", perigoso: true }
              );
              if (!ok) return;
              await API.documentos.remover(id, false);
              UI.sucesso("Documento removido.");
            }
            App.recarregarPagina();
          } catch (e) {
            UI.erro(e.message);
          } finally {
            botao.disabled = false;
          }
        });
      });
    },

    dialogoEnviar(colecoes) {
      const opcoes = [...new Set(["default", ...colecoes.map((c) => c.name)])];

      const corpo = el("div", {
        html: `
          <div class="campo">
            <label class="campo-rotulo" for="doc-arquivo">Arquivo</label>
            <input class="entrada" type="file" id="doc-arquivo"
                   accept=".pdf,.docx,.txt,.html,.htm,.md,.csv,.json" multiple />
            <div class="campo-dica">Aceita PDF, DOCX, TXT, HTML, Markdown, CSV e JSON. Vários arquivos de uma vez.</div>
          </div>
          <div class="campo">
            <label class="campo-rotulo" for="doc-colecao">Coleção</label>
            <input class="entrada" id="doc-colecao" list="lista-colecoes" value="default" />
            <datalist id="lista-colecoes">${opcoes.map((c) => `<option value="${esc(c)}">`).join("")}</datalist>
            <div class="campo-dica">Coleções separam bases de conhecimento por assunto ou projeto.</div>
          </div>
          <div id="doc-progresso"></div>`,
      });

      UI.modal({
        titulo: "Enviar documentos",
        corpo,
        acoes: [
          { rotulo: "Cancelar", classe: "btn-fantasma" },
          {
            rotulo: "Enviar e indexar",
            classe: "btn-primario",
            aoClicar: async () => {
              const arquivos = [...corpo.querySelector("#doc-arquivo").files];
              if (!arquivos.length) {
                UI.alerta("Selecione ao menos um arquivo.");
                return false;
              }

              const colecao = corpo.querySelector("#doc-colecao").value.trim() || "default";
              const progresso = corpo.querySelector("#doc-progresso");
              let ok = 0;

              for (const arquivo of arquivos) {
                progresso.innerHTML = `<div class="flex-centro gap-10 pequeno txt-2"><span class="girando"></span> Indexando ${esc(arquivo.name)}…</div>`;
                const fd = new FormData();
                fd.append("arquivo", arquivo);
                fd.append("colecao", colecao);
                try {
                  await API.documentos.enviar(fd);
                  ok += 1;
                } catch (e) {
                  UI.erro(`${arquivo.name}: ${e.message}`);
                }
              }

              if (ok) UI.sucesso(`${ok} documento(s) indexado(s).`);
              App.recarregarPagina();
            },
          },
        ],
      });
    },

    dialogoBuscar() {
      const corpo = el("div", {
        html: `
          <div class="campo">
            <label class="campo-rotulo" for="rag-consulta">O que procurar</label>
            <input class="entrada" id="rag-consulta" placeholder="Digite e pressione Enter…" />
          </div>
          <div id="rag-resultados"></div>`,
      });

      const executar = async () => {
        const consulta = corpo.querySelector("#rag-consulta").value.trim();
        const alvo = corpo.querySelector("#rag-resultados");
        if (!consulta) return;

        alvo.innerHTML = '<div class="carregando-tela"><div class="girando"></div></div>';
        try {
          const resultados = await API.documentos.buscar({ consulta, k: 8 });
          alvo.innerHTML = resultados.length
            ? resultados
                .map(
                  (r, i) => `
                <div class="cartao mb-8" style="padding:12px">
                  <div class="flex-centro gap-10 mb-8">
                    <span class="etiqueta marca">${i + 1}</span>
                    <span class="pequeno negrito">${esc(r.document_title || "documento")}</span>
                    ${r.meta?.page ? `<span class="pequeno txt-3">p. ${r.meta.page}</span>` : ""}
                    <span class="espaco"></span>
                    <span class="etiqueta ${r.score > 0.5 ? "ok" : ""}">${r.score.toFixed(3)}</span>
                  </div>
                  <div class="pequeno txt-2">${esc(r.content.slice(0, 420))}${r.content.length > 420 ? "…" : ""}</div>
                </div>`
                )
                .join("")
            : '<div class="vazio"><div class="vazio-texto">Nenhum trecho relevante encontrado.</div></div>';
        } catch (e) {
          alvo.innerHTML = `<div class="msg-erro">${esc(e.message)}</div>`;
        }
      };

      corpo.querySelector("#rag-consulta").addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          executar();
        }
      });

      UI.modal({
        titulo: "Testar busca semântica",
        largo: true,
        corpo,
        acoes: [
          { rotulo: "Buscar", classe: "btn-secundario", fechar: false, aoClicar: executar },
          { rotulo: "Fechar", classe: "btn-fantasma" },
        ],
      });
    },
  };

  function linhaDocumento(d) {
    const cores = { indexed: "ok", processing: "info", pending: "", failed: "erro" };
    const rotulos = {
      indexed: "indexado",
      processing: "processando",
      pending: "pendente",
      failed: "falhou",
    };
    return `
      <tr>
        <td>
          <strong>${esc(d.title)}</strong>
          ${d.error ? `<div class="pequeno" style="color:var(--erro)">${esc(d.error.slice(0, 110))}</div>` : ""}
        </td>
        <td><span class="etiqueta">${esc(d.filetype)}</span></td>
        <td class="pequeno">${esc(d.collection)}</td>
        <td><span class="etiqueta ${cores[d.status] || ""}">${rotulos[d.status] || d.status}</span></td>
        <td class="num">${UI.numero(d.chunk_count)}</td>
        <td class="num">${UI.bytes(d.size_bytes)}</td>
        <td class="pequeno txt-3">${UI.quando(d.created_at)}</td>
        <td class="direita">
          <div class="item-acoes" style="justify-content:flex-end">
            <button class="btn btn-pequeno btn-fantasma" data-acao-doc="reindexar" data-id="${d.id}" title="Reindexar">${Icones.recarregar(13)}</button>
            <button class="btn btn-pequeno btn-fantasma" data-acao-doc="remover" data-id="${d.id}" data-nome="${esc(d.title)}" data-trechos="${d.chunk_count}" title="Remover">${Icones.lixeira(13)}</button>
          </div>
        </td>
      </tr>`;
  }

  // ===================================================================
  // Agentes
  // ===================================================================
  const Agentes = {
    async render(caixa) {
      caixa.innerHTML = '<div class="carregando-tela"><div class="girando"></div></div>';

      const [agentes, ferramentas, modelos] = await Promise.all([
        API.agentes.listar(),
        API.agentes.ferramentas(),
        API.modelos.listar(),
      ]);

      this._ferramentas = ferramentas;
      this._modelos = modelos;

      caixa.innerHTML = `
        <div class="cabecalho-secao">
          <div>
            <h2>Agentes</h2>
            <p>${agentes.length} agente(s) · ${ferramentas.length} ferramenta(s) disponível(is)</p>
          </div>
          <span class="espaco"></span>
          <button class="btn btn-primario" id="btn-novo-agente"><span data-icone="mais" data-tamanho="14"></span> Novo agente</button>
        </div>

        ${
          agentes.length
            ? `<div class="grade grade-2">${agentes.map(cartaoAgente).join("")}</div>`
            : UI.vazio("🤖", "Nenhum agente", "Agentes combinam uma persona, parâmetros, ferramentas e memória permanente.")
        }`;

      UI.aplicarIcones(caixa);
      this.ligar(caixa);
    },

    ligar(caixa) {
      $("#btn-novo-agente")?.addEventListener("click", () => this.editor(null));

      $$("[data-acao-agente]", caixa).forEach((botao) => {
        botao.addEventListener("click", async () => {
          const { acaoAgente: acao, id, nome } = botao.dataset;
          try {
            if (acao === "editar") {
              const agente = await API.agentes.obter(id);
              this.editor(agente);
            } else if (acao === "duplicar") {
              await API.agentes.duplicar(id);
              UI.sucesso("Agente duplicado.");
              App.recarregarPagina();
            } else if (acao === "usar") {
              Chat.novaConversa();
              $("#seletor-agente").value = id;
              $("#seletor-agente").dispatchEvent(new Event("change"));
              UI.sucesso(`Conversando com "${nome}".`);
            } else if (acao === "memoria") {
              const agente = await API.agentes.obter(id);
              this.dialogoMemoria(agente);
            } else if (acao === "remover") {
              const ok = await UI.confirmar(`Excluir o agente "${nome}"?`, {
                titulo: "Excluir agente",
                perigoso: true,
              });
              if (!ok) return;
              await API.agentes.remover(id);
              UI.sucesso("Agente excluído.");
              App.recarregarPagina();
            }
          } catch (e) {
            UI.erro(e.message);
          }
        });
      });
    },

    editor(agente) {
      const a = agente || {
        name: "",
        avatar: "🤖",
        description: "",
        system_prompt: "",
        model_name: "",
        temperature: 0.7,
        top_p: 0.95,
        top_k: 40,
        max_tokens: 1024,
        tools: [],
        rag_collections: [],
        memory_enabled: true,
      };

      const corpo = el("div", {
        html: `
          <div class="flex gap-10 mb-14">
            <div class="campo" style="width:88px;margin:0">
              <label class="campo-rotulo" for="ag-avatar">Ícone</label>
              <input class="entrada centro" id="ag-avatar" value="${esc(a.avatar || "🤖")}" maxlength="4" />
            </div>
            <div class="campo" style="flex:1;margin:0">
              <label class="campo-rotulo" for="ag-nome">Nome</label>
              <input class="entrada" id="ag-nome" value="${esc(a.name)}" placeholder="Revisor Técnico" />
            </div>
          </div>

          <div class="campo">
            <label class="campo-rotulo" for="ag-descricao">Descrição</label>
            <input class="entrada" id="ag-descricao" value="${esc(a.description || "")}" placeholder="Para que serve este agente" />
          </div>

          <div class="campo">
            <label class="campo-rotulo" for="ag-prompt">Instruções do sistema</label>
            <textarea class="area" id="ag-prompt" rows="6" placeholder="Você é um especialista em…">${esc(a.system_prompt)}</textarea>
            <div class="campo-dica">Define a persona, o tom e as regras que o modelo deve seguir.</div>
          </div>

          <div class="campo">
            <label class="campo-rotulo" for="ag-modelo">Modelo padrão</label>
            <select class="selecao" id="ag-modelo">
              <option value="">Usar o modelo da conversa</option>
              ${this._modelos
                .map(
                  (m) =>
                    `<option value="${esc(m.name)}" ${m.name === a.model_name ? "selected" : ""}>${esc(m.name)}</option>`
                )
                .join("")}
            </select>
          </div>

          <div class="campo">
            <div class="campo-linha">
              <label class="campo-rotulo" style="margin:0">Temperatura</label>
              <span class="campo-valor" id="ag-valor-temp">${a.temperature}</span>
            </div>
            <input class="deslizante" type="range" id="ag-temperatura" min="0" max="2" step="0.05" value="${a.temperature}" />
          </div>

          <div class="campo">
            <div class="campo-linha">
              <label class="campo-rotulo" style="margin:0">Tokens máximos</label>
              <span class="campo-valor" id="ag-valor-tokens">${a.max_tokens}</span>
            </div>
            <input class="deslizante" type="range" id="ag-max-tokens" min="64" max="8192" step="64" value="${a.max_tokens}" />
          </div>

          <div class="campo">
            <label class="campo-rotulo">Ferramentas</label>
            <div class="grade" style="grid-template-columns:1fr 1fr;gap:8px">
              ${this._ferramentas
                .map(
                  (f) => `
                <label class="flex-centro gap-10 pequeno" style="cursor:pointer">
                  <input type="checkbox" class="ag-ferramenta" value="${esc(f.name)}" ${(a.tools || []).includes(f.name) ? "checked" : ""} />
                  <span title="${esc(f.description)}">${esc(f.name)}</span>
                </label>`
                )
                .join("")}
            </div>
          </div>

          <div class="campo flex-centro gap-10">
            <div class="interruptor ${a.memory_enabled ? "ligado" : ""}" id="ag-memoria"></div>
            <div>
              <div class="pequeno negrito">Memória permanente</div>
              <div class="campo-dica" style="margin:0">O agente lembra de fatos entre conversas diferentes.</div>
            </div>
          </div>`,
      });

      corpo
        .querySelector("#ag-memoria")
        .addEventListener("click", (e) => e.currentTarget.classList.toggle("ligado"));

      corpo.querySelector("#ag-temperatura").addEventListener("input", (e) => {
        corpo.querySelector("#ag-valor-temp").textContent = e.target.value;
      });
      corpo.querySelector("#ag-max-tokens").addEventListener("input", (e) => {
        corpo.querySelector("#ag-valor-tokens").textContent = e.target.value;
      });

      UI.modal({
        titulo: agente ? `Editar "${agente.name}"` : "Novo agente",
        largo: true,
        corpo,
        acoes: [
          { rotulo: "Cancelar", classe: "btn-fantasma" },
          {
            rotulo: agente ? "Salvar" : "Criar agente",
            classe: "btn-primario",
            aoClicar: async () => {
              const dados = {
                name: corpo.querySelector("#ag-nome").value.trim(),
                avatar: corpo.querySelector("#ag-avatar").value.trim() || "🤖",
                description: corpo.querySelector("#ag-descricao").value.trim(),
                system_prompt: corpo.querySelector("#ag-prompt").value.trim(),
                model_name: corpo.querySelector("#ag-modelo").value || null,
                temperature: parseFloat(corpo.querySelector("#ag-temperatura").value),
                max_tokens: parseInt(corpo.querySelector("#ag-max-tokens").value, 10),
                tools: [...corpo.querySelectorAll(".ag-ferramenta:checked")].map((c) => c.value),
                memory_enabled: corpo.querySelector("#ag-memoria").classList.contains("ligado"),
              };

              if (!dados.name) {
                UI.alerta("Informe o nome do agente.");
                return false;
              }

              try {
                if (agente) await API.agentes.atualizar(agente.id, dados);
                else await API.agentes.criar(dados);
                UI.sucesso(agente ? "Agente atualizado." : "Agente criado.");
                App.recarregarPagina();
                Chat.carregarSeletores();
              } catch (e) {
                UI.erro(e.message);
                return false;
              }
            },
          },
        ],
      });
    },

    dialogoMemoria(agente) {
      const memoria = agente.memory || [];

      const corpo = el("div", {
        html: `
          <div class="campo">
            <label class="campo-rotulo" for="mem-novo">Novo fato</label>
            <div class="flex gap-10">
              <input class="entrada" id="mem-novo" placeholder="O usuário prefere respostas curtas." />
              <button class="btn btn-secundario" id="mem-adicionar">Adicionar</button>
            </div>
          </div>
          <div id="mem-lista">
            ${
              memoria.length
                ? memoria
                    .map(
                      (m, i) => `
                <div class="item-lista mb-8" style="padding:9px 12px">
                  <div class="item-info">
                    <div class="pequeno">${esc(m.fact)}</div>
                    <div class="item-detalhe">${esc(m.source || "—")} · ${UI.quando(m.at)}</div>
                  </div>
                  <button class="btn btn-pequeno btn-fantasma" data-esquecer="${i}">${Icones.lixeira(13)}</button>
                </div>`
                    )
                    .join("")
                : '<div class="vazio" style="padding:24px"><div class="vazio-texto">Nenhum fato memorizado.</div></div>'
            }
          </div>`,
      });

      const adicionar = async () => {
        const campo = corpo.querySelector("#mem-novo");
        const fato = campo.value.trim();
        if (!fato) return;
        await API.agentes.lembrar(agente.id, fato);
        UI.sucesso("Fato memorizado.");
        UI.fecharModal();
        this.dialogoMemoria(await API.agentes.obter(agente.id));
      };

      corpo.querySelector("#mem-adicionar").addEventListener("click", adicionar);
      corpo.querySelector("#mem-novo").addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          adicionar();
        }
      });

      corpo.querySelectorAll("[data-esquecer]").forEach((botao) => {
        botao.addEventListener("click", async () => {
          await API.agentes.esquecer(agente.id, Number(botao.dataset.esquecer));
          UI.fecharModal();
          this.dialogoMemoria(await API.agentes.obter(agente.id));
        });
      });

      UI.modal({
        titulo: `Memória de "${agente.name}"`,
        largo: true,
        corpo,
        acoes: [
          {
            rotulo: "Limpar tudo",
            classe: "btn-perigo",
            aoClicar: async () => {
              const ok = await UI.confirmar("Apagar toda a memória deste agente?", {
                perigoso: true,
              });
              if (!ok) return false;
              await API.agentes.esquecer(agente.id);
              UI.sucesso("Memória apagada.");
            },
          },
          { rotulo: "Fechar", classe: "btn-secundario" },
        ],
      });
    },
  };

  function cartaoAgente(a) {
    return `
      <div class="cartao">
        <div class="flex gap-14 mb-14">
          <div class="item-icone" style="font-size:20px">${esc(a.avatar || "🤖")}</div>
          <div class="item-info">
            <div class="item-nome">${esc(a.name)}</div>
            <div class="item-detalhe">${esc(a.description || "Sem descrição")}</div>
          </div>
        </div>

        <div class="flex gap-6 mb-14" style="flex-wrap:wrap">
          <span class="etiqueta">temp ${a.temperature}</span>
          <span class="etiqueta">${a.max_tokens} tokens</span>
          ${a.model_name ? `<span class="etiqueta marca">${esc(a.model_name)}</span>` : ""}
          ${a.memory_enabled ? `<span class="etiqueta info">memória: ${(a.memory || []).length}</span>` : ""}
          ${(a.tools || []).map((t) => `<span class="etiqueta ok">${esc(t)}</span>`).join("")}
        </div>

        <div class="item-acoes">
          <button class="btn btn-pequeno btn-primario" data-acao-agente="usar" data-id="${a.id}" data-nome="${esc(a.name)}">Conversar</button>
          <button class="btn btn-pequeno btn-secundario" data-acao-agente="editar" data-id="${a.id}">Editar</button>
          <button class="btn btn-pequeno btn-fantasma" data-acao-agente="memoria" data-id="${a.id}" title="Memória">${Icones.banco(13)}</button>
          <button class="btn btn-pequeno btn-fantasma" data-acao-agente="duplicar" data-id="${a.id}" title="Duplicar">${Icones.copiar(13)}</button>
          <button class="btn btn-pequeno btn-fantasma" data-acao-agente="remover" data-id="${a.id}" data-nome="${esc(a.name)}" title="Excluir">${Icones.lixeira(13)}</button>
        </div>
      </div>`;
  }

  // ===================================================================
  // Plugins
  // ===================================================================
  const Plugins = {
    async render(caixa) {
      caixa.innerHTML = '<div class="carregando-tela"><div class="girando"></div></div>';

      const [plugins, mercado] = await Promise.all([
        API.plugins.listar(),
        API.plugins.marketplace().catch(() => []),
      ]);

      caixa.innerHTML = `
        <div class="cabecalho-secao">
          <div>
            <h2>Plugins</h2>
            <p>${plugins.length} instalado(s) · ${plugins.filter((p) => p.enabled).length} ativo(s)</p>
          </div>
          <span class="espaco"></span>
          <button class="btn btn-secundario" id="btn-escanear-plugins"><span data-icone="recarregar" data-tamanho="14"></span> Reexaminar</button>
          <button class="btn btn-primario" id="btn-instalar-plugin"><span data-icone="mais" data-tamanho="14"></span> Instalar .zip</button>
        </div>

        ${
          plugins.length
            ? `<div class="grade grade-2 mb-20">${plugins.map(cartaoPlugin).join("")}</div>`
            : UI.vazio(
                "🧩",
                "Nenhum plugin instalado",
                "Plugins estendem o sistema com ganchos em mensagens, respostas e documentos. Coloque a pasta do plugin em plugins/ ou instale um .zip."
              )
        }

        ${
          mercado.length
            ? `<div class="cabecalho-secao"><div><h2>Marketplace local</h2>
                 <p>Catálogo offline definido em plugins/_marketplace/catalogo.json</p></div></div>
               <div class="grade grade-2">${mercado.map(cartaoMercado).join("")}</div>`
            : ""
        }`;

      UI.aplicarIcones(caixa);
      this.ligar(caixa);
    },

    ligar(caixa) {
      $("#btn-escanear-plugins")?.addEventListener("click", async () => {
        await API.plugins.escanear();
        UI.sucesso("Pasta de plugins reexaminada.");
        App.recarregarPagina();
      });

      $("#btn-instalar-plugin")?.addEventListener("click", () => {
        const corpo = el("div", {
          html: `
            <div class="campo">
              <label class="campo-rotulo" for="plug-arquivo">Pacote do plugin (.zip)</label>
              <input class="entrada" type="file" id="plug-arquivo" accept=".zip" />
              <div class="campo-dica">
                O pacote precisa conter um <span class="mono">plugin.json</span> com
                slug, name e version.
              </div>
            </div>
            <div class="cartao pequeno txt-2" style="background:var(--sup-2)">
              <strong>Atenção:</strong> plugins executam código Python no mesmo
              processo do servidor. Instale apenas pacotes de origem confiável.
            </div>`,
        });

        UI.modal({
          titulo: "Instalar plugin",
          corpo,
          acoes: [
            { rotulo: "Cancelar", classe: "btn-fantasma" },
            {
              rotulo: "Instalar",
              classe: "btn-primario",
              aoClicar: async () => {
                const arquivo = corpo.querySelector("#plug-arquivo").files[0];
                if (!arquivo) {
                  UI.alerta("Selecione um arquivo .zip.");
                  return false;
                }
                const fd = new FormData();
                fd.append("arquivo", arquivo);
                try {
                  await API.plugins.instalar(fd);
                  UI.sucesso("Plugin instalado. Ative-o para carregar.");
                  App.recarregarPagina();
                } catch (e) {
                  UI.erro(e.message);
                  return false;
                }
              },
            },
          ],
        });
      });

      $$("[data-acao-plugin]", caixa).forEach((botao) => {
        botao.addEventListener("click", async () => {
          const { acaoPlugin: acao, slug } = botao.dataset;
          botao.disabled = true;
          try {
            if (acao === "habilitar") {
              await API.plugins.habilitar(slug);
              UI.sucesso("Plugin ativado.");
            } else if (acao === "desabilitar") {
              await API.plugins.desabilitar(slug);
              UI.sucesso("Plugin desativado.");
            } else if (acao === "remover") {
              const ok = await UI.confirmar(
                `Desinstalar "${slug}" e apagar seus arquivos?`,
                { titulo: "Desinstalar plugin", perigoso: true }
              );
              if (!ok) return;
              await API.plugins.remover(slug);
              UI.sucesso("Plugin desinstalado.");
            }
            App.recarregarPagina();
          } catch (e) {
            UI.erro(e.message);
          } finally {
            botao.disabled = false;
          }
        });
      });
    },
  };

  function cartaoPlugin(p) {
    return `
      <div class="cartao">
        <div class="flex gap-14 mb-14">
          <div class="item-icone">${Icones.plugue(18)}</div>
          <div class="item-info">
            <div class="item-nome">${esc(p.name)} <span class="txt-3 pequeno">v${esc(p.version)}</span></div>
            <div class="item-detalhe">${esc(p.description || "Sem descrição")}</div>
          </div>
          <span class="etiqueta ${p.enabled ? "ok" : ""}">${p.enabled ? "ativo" : "inativo"}</span>
        </div>

        ${p.error ? `<div class="msg-erro mb-14">${esc(p.error.slice(0, 200))}</div>` : ""}

        <div class="flex gap-6 mb-14" style="flex-wrap:wrap">
          ${p.author ? `<span class="etiqueta">${esc(p.author)}</span>` : ""}
          ${(p.hooks || []).map((h) => `<span class="etiqueta info mono">${esc(h)}</span>`).join("")}
        </div>

        <div class="item-acoes">
          ${
            p.enabled
              ? `<button class="btn btn-pequeno btn-secundario" data-acao-plugin="desabilitar" data-slug="${esc(p.slug)}">Desativar</button>`
              : `<button class="btn btn-pequeno btn-primario" data-acao-plugin="habilitar" data-slug="${esc(p.slug)}" ${!p.installed ? "disabled" : ""}>Ativar</button>`
          }
          <button class="btn btn-pequeno btn-fantasma" data-acao-plugin="remover" data-slug="${esc(p.slug)}" title="Desinstalar">${Icones.lixeira(13)}</button>
        </div>
      </div>`;
  }

  function cartaoMercado(item) {
    return `
      <div class="cartao">
        <div class="flex gap-14 mb-8">
          <div class="item-icone">${Icones.plugue(18)}</div>
          <div class="item-info">
            <div class="item-nome">${esc(item.name || item.slug)}</div>
            <div class="item-detalhe">${esc(item.description || "")}</div>
          </div>
          ${item.installed ? '<span class="etiqueta ok">instalado</span>' : ""}
        </div>
        ${item.url ? `<div class="pequeno txt-3 quebra mono">${esc(item.url)}</div>` : ""}
      </div>`;
  }

  // ===================================================================
  // Monitor do sistema
  // ===================================================================
  const Sistema = {
    async render(caixa) {
      caixa.innerHTML = '<div class="carregando-tela"><div class="girando"></div></div>';
      const r = await API.sistema.monitor(true);

      caixa.innerHTML = `
        <div class="cabecalho-secao">
          <div>
            <h2>Monitor do sistema</h2>
            <p>${esc(r.platform.system)} ${esc(r.platform.release)} ·
               ${esc(r.platform.machine)} · Python ${esc(r.platform.python)} ·
               ${esc(r.platform.hostname)}</p>
          </div>
        </div>

        <div class="grade grade-4 mb-20">
          <div class="cartao"><div class="grafico-caixa" style="height:120px"><canvas id="med-cpu"></canvas></div></div>
          <div class="cartao"><div class="grafico-caixa" style="height:120px"><canvas id="med-ram"></canvas></div></div>
          <div class="cartao"><div class="grafico-caixa" style="height:120px"><canvas id="med-disco"></canvas></div></div>
          <div class="cartao"><div class="grafico-caixa" style="height:120px"><canvas id="med-gpu"></canvas></div></div>
        </div>

        <div class="cartao mb-20">
          <div class="cartao-titulo"><span data-icone="monitor" data-tamanho="15"></span> Histórico (últimos 60 s)</div>
          <div class="grafico-caixa" style="height:200px"><canvas id="graf-historico"></canvas></div>
          <div class="legenda">
            <span class="legenda-item"><span class="legenda-cor" style="background:var(--marca)"></span> CPU</span>
            <span class="legenda-item"><span class="legenda-cor" style="background:var(--acento)"></span> Memória</span>
            <span class="legenda-item"><span class="legenda-cor" style="background:var(--info)"></span> GPU</span>
          </div>
        </div>

        <div class="grade grade-2">
          <div class="cartao">
            <div class="cartao-titulo">Processador</div>
            <div class="tabela-rolagem"><table class="tabela"><tbody>
              ${linhaInfo("Uso total", `${r.cpu.percent}%`)}
              ${linhaInfo("Núcleos lógicos", r.cpu.cores)}
              ${linhaInfo("Núcleos físicos", r.cpu.physical_cores)}
              ${linhaInfo("Frequência", r.cpu.frequency_mhz ? `${r.cpu.frequency_mhz} MHz` : "—")}
              ${linhaInfo("Carga média", r.cpu.load_average ? r.cpu.load_average.join("  ") : "—")}
              ${linhaInfo("Temperatura", r.temperature.cpu_c ? `${r.temperature.cpu_c} °C` : "não disponível")}
            </tbody></table></div>
            <div class="mt-14">
              <div class="campo-rotulo">Uso por núcleo</div>
              <div class="grafico-caixa" style="height:130px"><canvas id="graf-nucleos"></canvas></div>
            </div>
          </div>

          <div class="cartao">
            <div class="cartao-titulo">Memória e armazenamento</div>
            <div class="tabela-rolagem"><table class="tabela"><tbody>
              ${linhaInfo("RAM total", `${r.memory.total_gb} GB`)}
              ${linhaInfo("RAM em uso", `${r.memory.used_gb} GB (${r.memory.percent}%)`)}
              ${linhaInfo("RAM disponível", `${r.memory.available_gb} GB`)}
              ${linhaInfo("Swap", `${r.swap.used_gb} / ${r.swap.total_gb} GB`)}
              ${linhaInfo("Disco total", `${r.disk.total_gb} GB`)}
              ${linhaInfo("Disco livre", `${r.disk.free_gb} GB`)}
              ${linhaInfo("Processo", `${r.process.memory_mb} MB · ${r.process.threads} threads · PID ${r.process.pid}`)}
            </tbody></table></div>
          </div>
        </div>

        ${
          r.gpu.devices.length
            ? `<div class="cartao mt-14">
                 <div class="cartao-titulo">Placas gráficas</div>
                 <div class="tabela-rolagem"><table class="tabela">
                   <thead><tr><th>#</th><th>Modelo</th><th>Memória</th><th>Uso</th><th>Temp.</th><th>Fonte</th></tr></thead>
                   <tbody>${r.gpu.devices
                     .map(
                       (g) => `<tr>
                         <td class="num">${g.index}</td>
                         <td><strong>${esc(g.name)}</strong></td>
                         <td class="num">${g.memory_used_gb} / ${g.memory_total_gb} GB</td>
                         <td class="num">${g.utilization_percent ?? "—"}${g.utilization_percent != null ? "%" : ""}</td>
                         <td class="num">${g.temperature_c ?? "—"}${g.temperature_c != null ? " °C" : ""}</td>
                         <td class="pequeno mono">${esc(g.source)}</td>
                       </tr>`
                     )
                     .join("")}</tbody>
                 </table></div>
               </div>`
            : ""
        }`;

      UI.aplicarIcones(caixa);

      const medidores = {
        cpu: new Graficos.Medidor($("#med-cpu"), { rotulo: "CPU" }),
        ram: new Graficos.Medidor($("#med-ram"), { rotulo: "Memória" }),
        disco: new Graficos.Medidor($("#med-disco"), { rotulo: "Disco" }),
        gpu: new Graficos.Medidor($("#med-gpu"), { rotulo: "GPU" }),
      };

      const historico = new Graficos.Linha($("#graf-historico"), {
        series: [
          { rotulo: "CPU", cor: Graficos.cor("--marca", "#7c6cff") },
          { rotulo: "Memória", cor: Graficos.cor("--acento", "#2fd4c4") },
          { rotulo: "GPU", cor: Graficos.cor("--info", "#56a8f5") },
        ],
        pontos: 60,
      });

      const nucleos = new Graficos.Barras($("#graf-nucleos"));
      nucleos.definir(
        r.cpu.per_core.map((v, i) => ({ rotulo: `${i}`, valor: v }))
      );

      medidores.cpu.definir(r.cpu.percent);
      medidores.ram.definir(r.memory.percent);
      medidores.disco.definir(r.disk.percent);
      medidores.gpu.definir(r.gpu.devices[0]?.memory_percent ?? 0);

      this._socket = API.monitorarSistema((m) => {
        medidores.cpu.definir(m.cpu_percent);
        medidores.ram.definir(m.memory_percent);
        medidores.disco.definir(m.disk_percent);
        medidores.gpu.definir(m.gpu_memory_percent ?? 0);
        historico.empurrar([
          m.cpu_percent,
          m.memory_percent,
          m.gpu_percent ?? 0,
        ]);
      });

      // Uso por núcleo vem apenas da coleta completa; atualizamos com menos
      // frequência para não pesar.
      this._intervalo = setInterval(async () => {
        try {
          const dados = await API.sistema.monitor(true);
          nucleos.definir(
            dados.cpu.per_core.map((v, i) => ({ rotulo: `${i}`, valor: v }))
          );
        } catch {
          /* servidor reiniciando: tenta de novo no próximo ciclo */
        }
      }, 3000);
    },

    sair() {
      if (this._socket) {
        this._socket.close();
        this._socket = null;
      }
      clearInterval(this._intervalo);
    },
  };

  function linhaInfo(rotulo, valor) {
    return `<tr><td style="width:52%"><strong>${esc(rotulo)}</strong></td><td class="num">${esc(valor)}</td></tr>`;
  }

  // ===================================================================
  // Logs
  // ===================================================================
  const Logs = {
    async render(caixa) {
      caixa.innerHTML = `
        <div class="cabecalho-secao">
          <div><h2>Logs</h2><p>Eventos registrados pelo servidor</p></div>
          <span class="espaco"></span>
          <select class="seletor-inline" id="log-nivel">
            <option value="">Todos os níveis</option>
            <option value="ERROR">Erros</option>
            <option value="WARNING">Alertas</option>
            <option value="INFO">Informações</option>
          </select>
          <input class="busca-conversas" id="log-busca" placeholder="Filtrar mensagem…" style="max-width:240px" />
          <button class="btn btn-secundario" id="log-recarregar"><span data-icone="recarregar" data-tamanho="14"></span></button>
          <button class="btn btn-perigo" id="log-limpar">Limpar</button>
        </div>
        <div id="log-conteudo"><div class="carregando-tela"><div class="girando"></div></div></div>`;

      UI.aplicarIcones(caixa);

      const carregar = async () => {
        const alvo = $("#log-conteudo");
        try {
          const dados = await API.sistema.logs({
            nivel: $("#log-nivel").value,
            busca: $("#log-busca").value,
            per_page: 150,
          });

          alvo.innerHTML = dados.items.length
            ? `<div class="cartao" style="padding:0"><div class="tabela-rolagem">
                 <table class="tabela">
                   <thead><tr><th>Quando</th><th>Nível</th><th>Origem</th><th>Mensagem</th></tr></thead>
                   <tbody>${dados.items
                     .map(
                       (l) => `<tr>
                         <td class="pequeno txt-3" style="white-space:nowrap">${UI.dataHora(l.created_at)}</td>
                         <td><span class="etiqueta ${
                           { ERROR: "erro", WARNING: "alerta", INFO: "info" }[l.level] || ""
                         }">${esc(l.level)}</span></td>
                         <td class="mono pequeno">${esc(l.source)}</td>
                         <td class="pequeno quebra">${esc(l.message)}</td>
                       </tr>`
                     )
                     .join("")}</tbody>
                 </table></div></div>
               <div class="pequeno txt-3 mt-14">${dados.total} registro(s) no total.</div>`
            : UI.vazio("📋", "Nenhum log", "Nada foi registrado com os filtros atuais.");
        } catch (e) {
          alvo.innerHTML = `<div class="msg-erro">${esc(e.message)}</div>`;
        }
      };

      $("#log-nivel").addEventListener("change", carregar);
      $("#log-busca").addEventListener("input", UI.esperar(carregar, 350));
      $("#log-recarregar").addEventListener("click", carregar);
      $("#log-limpar").addEventListener("click", async () => {
        const ok = await UI.confirmar("Apagar todos os logs do banco?", {
          perigoso: true,
        });
        if (!ok) return;
        const r = await API.sistema.limparLogs();
        UI.sucesso(r.detail);
        carregar();
      });

      carregar();
    },
  };

  // ===================================================================
  // Configurações
  // ===================================================================
  const Config = {
    async render(caixa) {
      caixa.innerHTML = '<div class="carregando-tela"><div class="girando"></div></div>';

      const [configuracoes, runtime, backups, extras] = await Promise.all([
        API.sistema.configuracoes(),
        API.sistema.configuracaoRuntime(),
        API.sistema.backups().catch(() => []),
        API.extras.estado().catch(() => ({})),
      ]);

      caixa.innerHTML = `
        <div class="cabecalho-secao"><div><h2>Configurações</h2>
          <p>Preferências da interface, backups e informações do servidor</p></div></div>

        <div class="grade grade-2 mb-20">
          <div class="cartao">
            <div class="cartao-titulo"><span data-icone="engrenagem" data-tamanho="15"></span> Aparência</div>
            <div class="campo">
              <label class="campo-rotulo" for="cfg-tema">Tema</label>
              <select class="selecao" id="cfg-tema">
                <option value="escuro">Escuro</option>
                <option value="claro">Claro</option>
              </select>
            </div>
            <div class="campo">
              <div class="campo-linha">
                <label class="campo-rotulo" style="margin:0">Tamanho da fonte do chat</label>
                <span class="campo-valor" id="cfg-valor-fonte">15px</span>
              </div>
              <input class="deslizante" type="range" id="cfg-fonte" min="12" max="20" step="1" value="15" />
            </div>
          </div>

          <div class="cartao">
            <div class="cartao-titulo"><span data-icone="escudo" data-tamanho="15"></span> Conta</div>
            <div class="campo">
              <label class="campo-rotulo">Usuário</label>
              <input class="entrada" value="${esc(App.usuario?.username || "")}" disabled />
            </div>
            <button class="btn btn-secundario" id="cfg-trocar-senha">Trocar senha</button>
            <button class="btn btn-fantasma" id="cfg-chaves">Chaves de API</button>
          </div>
        </div>

        <div class="cartao mb-20">
          <div class="cartao-titulo"><span data-icone="banco" data-tamanho="15"></span> Backup</div>
          <div class="flex gap-10 mb-14" style="flex-wrap:wrap">
            <button class="btn btn-primario" id="cfg-criar-backup">Criar backup agora</button>
            <div class="pequeno txt-3 flex-centro">
              Inclui banco, configurações, plugins e documentos. Modelos não entram.
            </div>
          </div>
          ${
            backups.length
              ? `<div class="tabela-rolagem"><table class="tabela">
                   <thead><tr><th>Arquivo</th><th>Criado</th><th>Tamanho</th><th>Documentos</th><th class="direita">Ações</th></tr></thead>
                   <tbody>${backups
                     .map(
                       (b) => `<tr>
                         <td class="mono pequeno">${esc(b.filename)}</td>
                         <td class="pequeno txt-3">${UI.dataHora(b.created_at)}</td>
                         <td class="num">${b.size_mb} MB</td>
                         <td>${b.includes_documents ? '<span class="etiqueta ok">sim</span>' : '<span class="etiqueta">não</span>'}</td>
                         <td class="direita"><div class="item-acoes" style="justify-content:flex-end">
                           <a class="btn btn-pequeno btn-fantasma" href="${API.sistema.urlBackup(b.filename)}" title="Baixar">${Icones.baixar(13)}</a>
                           <button class="btn btn-pequeno btn-secundario" data-backup-restaurar="${esc(b.filename)}">Restaurar</button>
                           <button class="btn btn-pequeno btn-fantasma" data-backup-remover="${esc(b.filename)}" title="Excluir">${Icones.lixeira(13)}</button>
                         </div></td>
                       </tr>`
                     )
                     .join("")}</tbody>
                 </table></div>`
              : '<div class="pequeno txt-3">Nenhum backup ainda.</div>'
          }
        </div>

        <div class="grade grade-2">
          <div class="cartao">
            <div class="cartao-titulo">Servidor</div>
            <div class="tabela-rolagem"><table class="tabela"><tbody>
              ${linhaInfo("Versão", runtime.version)}
              ${linhaInfo("Modo", runtime.mode)}
              ${linhaInfo("Endereço", `${runtime.host}:${runtime.port}`)}
              ${linhaInfo("Autenticação", runtime.auth_required ? "obrigatória" : "desativada")}
              ${linhaInfo("Proteção CSRF", runtime.csrf_enabled ? "ativa" : "desativada")}
              ${linhaInfo("Limite de requisições", `${runtime.rate_limit_requests} / ${runtime.rate_limit_window_seconds}s`)}
              ${linhaInfo("Contexto padrão", `${UI.numero(runtime.context_length)} tokens`)}
              ${linhaInfo("Modelos em memória", runtime.max_loaded_models)}
              ${linhaInfo("Índice vetorial", runtime.vector_backend)}
              ${linhaInfo("Upload máximo", `${runtime.max_upload_mb} MB`)}
            </tbody></table></div>
          </div>

          <div class="cartao">
            <div class="cartao-titulo">Recursos extras</div>
            <div class="tabela-rolagem"><table class="tabela"><tbody>
              ${Object.entries(extras)
                .map(
                  ([nome, e]) =>
                    `<tr><td><strong>${esc(rotuloExtra(nome))}</strong></td>
                     <td><span class="etiqueta ${e.available ? "ok" : ""}">${e.available ? "disponível" : "não instalado"}</span></td></tr>`
                )
                .join("")}
            </tbody></table></div>
            <div class="campo-dica mt-14">
              Recursos ausentes indicam dependências opcionais não instaladas.
              Veja a Ajuda para os comandos de instalação.
            </div>
          </div>
        </div>

        <div class="cartao mt-14">
          <div class="cartao-titulo">Configurações persistidas</div>
          <div class="tabela-rolagem"><table class="tabela">
            <thead><tr><th>Chave</th><th>Valor</th><th>Descrição</th></tr></thead>
            <tbody>${configuracoes
              .map(
                (c) => `<tr>
                  <td class="mono pequeno">${esc(c.key)}</td>
                  <td class="mono pequeno">${esc(JSON.stringify(c.value))}</td>
                  <td class="pequeno txt-3">${esc(c.description || "")}</td>
                </tr>`
              )
              .join("")}</tbody>
          </table></div>
        </div>`;

      UI.aplicarIcones(caixa);
      this.ligar();
    },

    ligar() {
      const seletorTema = $("#cfg-tema");
      seletorTema.value = document.documentElement.dataset.tema;
      seletorTema.addEventListener("change", (e) => App.definirTema(e.target.value));

      const fonte = $("#cfg-fonte");
      fonte.value = parseInt(localStorage.getItem("lais_fonte") || "15", 10);
      $("#cfg-valor-fonte").textContent = `${fonte.value}px`;
      fonte.addEventListener("input", (e) => {
        const px = e.target.value;
        $("#cfg-valor-fonte").textContent = `${px}px`;
        document.documentElement.style.setProperty("--fonte-chat", `${px}px`);
        $("#chat-lista").style.fontSize = `${px}px`;
        localStorage.setItem("lais_fonte", px);
      });

      $("#cfg-trocar-senha").addEventListener("click", () => this.dialogoSenha());
      $("#cfg-chaves").addEventListener("click", () => this.dialogoChaves());

      $("#cfg-criar-backup").addEventListener("click", async (e) => {
        e.currentTarget.disabled = true;
        try {
          const r = await API.sistema.criarBackup(true);
          UI.sucesso(`Backup criado: ${r.filename} (${r.size_mb} MB).`);
          App.recarregarPagina();
        } catch (err) {
          UI.erro(err.message);
        } finally {
          e.currentTarget.disabled = false;
        }
      });

      $$("[data-backup-restaurar]").forEach((botao) =>
        botao.addEventListener("click", async () => {
          const nome = botao.dataset.backupRestaurar;
          const ok = await UI.confirmar(
            `Restaurar "${nome}"? O estado atual será substituído — um backup de segurança é criado automaticamente antes. O servidor precisará ser reiniciado.`,
            { titulo: "Restaurar backup", perigoso: true }
          );
          if (!ok) return;
          try {
            const r = await API.sistema.restaurarBackup(nome);
            UI.alerta(r.detail);
          } catch (e) {
            UI.erro(e.message);
          }
        })
      );

      $$("[data-backup-remover]").forEach((botao) =>
        botao.addEventListener("click", async () => {
          const nome = botao.dataset.backupRemover;
          const ok = await UI.confirmar(`Excluir o backup "${nome}"?`, {
            perigoso: true,
          });
          if (!ok) return;
          await API.sistema.removerBackup(nome);
          UI.sucesso("Backup excluído.");
          App.recarregarPagina();
        })
      );
    },

    dialogoSenha() {
      const corpo = el("div", {
        html: `
          <div class="campo">
            <label class="campo-rotulo" for="sen-atual">Senha atual</label>
            <input class="entrada" type="password" id="sen-atual" autocomplete="current-password" />
          </div>
          <div class="campo">
            <label class="campo-rotulo" for="sen-nova">Nova senha</label>
            <input class="entrada" type="password" id="sen-nova" autocomplete="new-password" />
            <div class="campo-dica">Mínimo de 8 caracteres. Todas as sessões serão encerradas.</div>
          </div>
          <div class="campo">
            <label class="campo-rotulo" for="sen-conf">Confirmar nova senha</label>
            <input class="entrada" type="password" id="sen-conf" autocomplete="new-password" />
          </div>`,
      });

      UI.modal({
        titulo: "Trocar senha",
        corpo,
        acoes: [
          { rotulo: "Cancelar", classe: "btn-fantasma" },
          {
            rotulo: "Trocar senha",
            classe: "btn-primario",
            aoClicar: async () => {
              const atual = corpo.querySelector("#sen-atual").value;
              const nova = corpo.querySelector("#sen-nova").value;
              const conf = corpo.querySelector("#sen-conf").value;

              if (nova.length < 8) {
                UI.alerta("A nova senha precisa ter ao menos 8 caracteres.");
                return false;
              }
              if (nova !== conf) {
                UI.alerta("A confirmação não confere.");
                return false;
              }

              try {
                await API.auth.trocarSenha(atual, nova);
                UI.sucesso("Senha alterada. Entre novamente.");
                setTimeout(() => App.sair(), 1400);
              } catch (e) {
                UI.erro(e.message);
                return false;
              }
            },
          },
        ],
      });
    },

    async dialogoChaves() {
      const chaves = await API.auth.chaves();

      const corpo = el("div", {
        html: `
          <div class="campo">
            <label class="campo-rotulo" for="chave-nome">Nova chave</label>
            <div class="flex gap-10">
              <input class="entrada" id="chave-nome" placeholder="Nome da integração" />
              <button class="btn btn-secundario" id="chave-criar">Gerar</button>
            </div>
            <div class="campo-dica">Use no cabeçalho <span class="mono">X-API-Key</span>. A chave aparece uma única vez.</div>
          </div>
          ${
            chaves.length
              ? `<div class="tabela-rolagem"><table class="tabela">
                   <thead><tr><th>Nome</th><th>Prefixo</th><th>Último uso</th><th></th></tr></thead>
                   <tbody>${chaves
                     .map(
                       (c) => `<tr>
                         <td><strong>${esc(c.name)}</strong></td>
                         <td class="mono pequeno">${esc(c.prefix)}…</td>
                         <td class="pequeno txt-3">${c.last_used_at ? UI.quando(c.last_used_at) : "nunca"}</td>
                         <td class="direita"><button class="btn btn-pequeno btn-fantasma" data-chave-remover="${c.id}">${Icones.lixeira(13)}</button></td>
                       </tr>`
                     )
                     .join("")}</tbody>
                 </table></div>`
              : '<div class="pequeno txt-3">Nenhuma chave criada.</div>'
          }`,
      });

      corpo.querySelector("#chave-criar").addEventListener("click", async () => {
        const nome = corpo.querySelector("#chave-nome").value.trim();
        if (!nome) {
          UI.alerta("Informe um nome.");
          return;
        }
        const r = await API.auth.criarChave(nome);
        UI.fecharModal();
        UI.modal({
          titulo: "Chave criada",
          corpo: `<p class="txt-2 mb-14">${esc(r.aviso)}</p>
                  <div class="cartao mono quebra" style="background:var(--sup-2)">${esc(r.key)}</div>`,
          acoes: [
            {
              rotulo: "Copiar",
              classe: "btn-secundario",
              fechar: false,
              aoClicar: () => UI.copiar(r.key),
            },
            { rotulo: "Pronto", classe: "btn-primario" },
          ],
        });
      });

      corpo.querySelectorAll("[data-chave-remover]").forEach((botao) =>
        botao.addEventListener("click", async () => {
          await API.auth.removerChave(botao.dataset.chaveRemover);
          UI.sucesso("Chave revogada.");
          UI.fecharModal();
          this.dialogoChaves();
        })
      );

      UI.modal({
        titulo: "Chaves de API",
        largo: true,
        corpo,
        acoes: [{ rotulo: "Fechar", classe: "btn-secundario" }],
      });
    },
  };

  // ===================================================================
  // Ajuda
  // ===================================================================
  const Ajuda = {
    async render(caixa) {
      caixa.innerHTML = `
        <div class="cabecalho-secao"><div><h2>Ajuda</h2>
          <p>Primeiros passos, atalhos e instalação de recursos opcionais</p></div></div>

        <div class="grade grade-2 mb-20">
          <div class="cartao">
            <div class="cartao-titulo"><span data-icone="raio" data-tamanho="15"></span> Começando</div>
            <ol style="padding-left:20px;line-height:2;font-size:13.5px" class="txt-2">
              <li>Instale o motor de inferência:<br>
                  <span class="mono pequeno">pip install llama-cpp-python</span></li>
              <li>Coloque um arquivo <span class="mono">.gguf</span> em
                  <span class="mono">models/</span> ou use <strong>Modelos → Importar</strong>.</li>
              <li>Clique em <strong>Reexaminar</strong> para registrá-lo.</li>
              <li>Selecione o modelo abaixo da caixa de mensagem e converse.</li>
            </ol>
          </div>

          <div class="cartao">
            <div class="cartao-titulo"><span data-icone="documento" data-tamanho="15"></span> Usando o RAG</div>
            <ol style="padding-left:20px;line-height:2;font-size:13.5px" class="txt-2">
              <li>Instale o modelo de embeddings:<br>
                  <span class="mono pequeno">pip install sentence-transformers faiss-cpu</span></li>
              <li>Em <strong>Documentos</strong>, envie PDFs, DOCX, TXT ou Markdown.</li>
              <li>Ligue o botão <strong>RAG</strong> na barra do chat.</li>
              <li>As respostas passam a citar os trechos usados como fonte.</li>
            </ol>
          </div>
        </div>

        <div class="cartao mb-20">
          <div class="cartao-titulo">Atalhos de teclado</div>
          <div class="tabela-rolagem"><table class="tabela"><tbody>
            ${[
              ["Enter", "Enviar mensagem"],
              ["Shift + Enter", "Quebrar linha"],
              ["Ctrl/Cmd + K", "Focar na pesquisa de conversas"],
              ["Ctrl/Cmd + N", "Nova conversa"],
              ["Ctrl/Cmd + B", "Mostrar/ocultar a barra lateral"],
              ["Esc", "Fechar modal · interromper geração"],
            ]
              .map(
                ([tecla, acao]) =>
                  `<tr><td style="width:220px"><span class="mono etiqueta">${esc(tecla)}</span></td><td>${esc(acao)}</td></tr>`
              )
              .join("")}
          </tbody></table></div>
        </div>

        <div class="cartao mb-20">
          <div class="cartao-titulo">Dependências opcionais</div>
          <div class="tabela-rolagem"><table class="tabela">
            <thead><tr><th>Recurso</th><th>Comando</th></tr></thead>
            <tbody>
              ${[
                ["Modelos GGUF (llama.cpp)", "pip install llama-cpp-python"],
                ["Modelos HuggingFace", "pip install transformers torch"],
                ["Modelos ONNX", "pip install onnxruntime"],
                ["Embeddings semânticos", "pip install sentence-transformers"],
                ["Índice FAISS", "pip install faiss-cpu"],
                ["ChromaDB", "pip install chromadb"],
                ["Leitura de PDF", "pip install pypdf"],
                ["Leitura de DOCX", "pip install python-docx"],
                ["Leitura de HTML", "pip install beautifulsoup4"],
                ["OCR", "pip install pytesseract Pillow  (+ binário tesseract)"],
                ["Reconhecimento de voz", "pip install faster-whisper"],
                ["Texto para voz", "pip install pyttsx3"],
                ["Geração de imagens", "pip install diffusers torch accelerate"],
                ["Aplicativo desktop", "pip install PySide6"],
              ]
                .map(
                  ([recurso, comando]) =>
                    `<tr><td><strong>${esc(recurso)}</strong></td><td class="mono pequeno">${esc(comando)}</td></tr>`
                )
                .join("")}
            </tbody>
          </table></div>
        </div>

        <div class="grade grade-2">
          <div class="cartao">
            <div class="cartao-titulo">API</div>
            <p class="pequeno txt-2 mb-14">
              Toda a interface usa a mesma API REST documentada, disponível para
              suas próprias integrações.
            </p>
            <a class="btn btn-secundario" href="/api/docs" target="_blank">Abrir documentação interativa</a>
          </div>

          <div class="cartao">
            <div class="cartao-titulo">Privacidade</div>
            <p class="pequeno txt-2">
              Nada sai do seu computador. Modelos, documentos, conversas e
              embeddings ficam no disco local; o sistema não faz chamadas de rede
              exceto quando você pede explicitamente o download de um modelo.
            </p>
          </div>
        </div>`;

      UI.aplicarIcones(caixa);
    },
  };

  return { Painel, Modelos, Documentos, Agentes, Plugins, Sistema, Logs, Config, Ajuda };
})();
