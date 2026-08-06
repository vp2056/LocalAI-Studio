/**
 * Cliente da API do LocalAI Studio.
 *
 * Centraliza autenticação (JWT + CSRF), tratamento de erros e o WebSocket de
 * chat. Todo o restante do frontend fala apenas com este módulo.
 */

const API = (() => {
  const BASE = "/api";
  const CHAVE_TOKEN = "lais_token";

  let token = localStorage.getItem(CHAVE_TOKEN) || null;

  /** Lê um cookie pelo nome (usado para o token CSRF). */
  function cookie(nome) {
    const achado = document.cookie
      .split("; ")
      .find((c) => c.startsWith(nome + "="));
    return achado ? decodeURIComponent(achado.split("=").slice(1).join("=")) : null;
  }

  /** Erro de API com o status HTTP preservado. */
  class ErroAPI extends Error {
    constructor(mensagem, status, dados) {
      super(mensagem);
      this.name = "ErroAPI";
      this.status = status;
      this.dados = dados || {};
    }
  }

  /** Executa uma requisição, tratando autenticação, CSRF e erros. */
  async function pedir(caminho, opcoes = {}) {
    const cabecalhos = { ...(opcoes.headers || {}) };

    if (token) cabecalhos["Authorization"] = `Bearer ${token}`;

    // O corpo pode ser FormData (upload); nesse caso o navegador define o
    // Content-Type com o boundary correto.
    const ehFormData = opcoes.body instanceof FormData;
    if (opcoes.body && !ehFormData && !cabecalhos["Content-Type"]) {
      cabecalhos["Content-Type"] = "application/json";
    }

    const csrf = cookie("lais_csrf");
    if (csrf) cabecalhos["X-CSRF-Token"] = csrf;

    const resposta = await fetch(BASE + caminho, {
      ...opcoes,
      headers: cabecalhos,
      credentials: "same-origin",
    });

    if (resposta.status === 204) return null;

    const tipo = resposta.headers.get("content-type") || "";
    const corpo = tipo.includes("application/json")
      ? await resposta.json().catch(() => ({}))
      : await resposta.text();

    if (!resposta.ok) {
      // 403 com token presente = sessão expirada: volta para o login.
      if (resposta.status === 403 && token && caminho !== "/auth/login") {
        const detalhe = (corpo && corpo.detail) || "";
        if (/sess|token|autentic/i.test(detalhe)) {
          definirToken(null);
          window.dispatchEvent(new CustomEvent("lais:sessao-expirada"));
        }
      }
      throw new ErroAPI(
        (corpo && corpo.detail) || `Erro ${resposta.status}`,
        resposta.status,
        corpo
      );
    }

    return corpo;
  }

  const get = (c, params) => {
    const q = params
      ? "?" +
        new URLSearchParams(
          Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
        )
      : "";
    return pedir(c + q);
  };
  const post = (c, dados) =>
    pedir(c, { method: "POST", body: dados ? JSON.stringify(dados) : undefined });
  const patch = (c, dados) =>
    pedir(c, { method: "PATCH", body: JSON.stringify(dados) });
  const put = (c, dados) => pedir(c, { method: "PUT", body: JSON.stringify(dados) });
  const remover = (c) => pedir(c, { method: "DELETE" });

  const enviarArquivo = (c, formData) =>
    pedir(c, { method: "POST", body: formData });

  function definirToken(novo) {
    token = novo;
    if (novo) localStorage.setItem(CHAVE_TOKEN, novo);
    else localStorage.removeItem(CHAVE_TOKEN);
  }

  // =====================================================================
  // WebSocket de chat
  // =====================================================================
  class ChatSocket {
    constructor() {
      this.ws = null;
      this.ouvintes = {};
      this.reconexoes = 0;
      this.fechandoDeProposito = false;
      this.fila = [];
    }

    conectar() {
      if (this.ws && this.ws.readyState <= WebSocket.OPEN) return;

      const protocolo = location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${protocolo}//${location.host}/ws/chat${
        token ? `?token=${encodeURIComponent(token)}` : ""
      }`;

      this.fechandoDeProposito = false;
      this.ws = new WebSocket(url);

      this.ws.onopen = () => {
        this.reconexoes = 0;
        this.emitir("aberto");
        // Reenvia o que ficou pendente enquanto a conexão estava caída.
        while (this.fila.length) this.ws.send(this.fila.shift());
      };

      this.ws.onmessage = (evento) => {
        try {
          const dados = JSON.parse(evento.data);
          this.emitir(dados.type, dados);
        } catch (e) {
          console.error("Mensagem inválida do WebSocket:", e);
        }
      };

      this.ws.onclose = () => {
        this.emitir("fechado");
        if (this.fechandoDeProposito || !token) return;

        // Reconexão com espera progressiva, limitada a 30 s.
        const espera = Math.min(1000 * 2 ** this.reconexoes, 30000);
        this.reconexoes += 1;
        setTimeout(() => this.conectar(), espera);
      };

      this.ws.onerror = () => this.emitir("erro-conexao");
    }

    enviar(dados) {
      const bruto = JSON.stringify(dados);
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(bruto);
      } else {
        this.fila.push(bruto);
        this.conectar();
      }
    }

    parar() {
      this.enviar({ type: "stop" });
    }

    desconectar() {
      this.fechandoDeProposito = true;
      if (this.ws) this.ws.close();
      this.ws = null;
    }

    em(evento, funcao) {
      (this.ouvintes[evento] ||= []).push(funcao);
      return this;
    }

    emitir(evento, dados) {
      (this.ouvintes[evento] || []).forEach((f) => {
        try {
          f(dados);
        } catch (e) {
          console.error(`Erro no ouvinte '${evento}':`, e);
        }
      });
    }
  }

  // =====================================================================
  // WebSocket do monitor de sistema
  // =====================================================================
  function monitorarSistema(aoReceber) {
    const protocolo = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(
      `${protocolo}//${location.host}/ws/system${
        token ? `?token=${encodeURIComponent(token)}` : ""
      }`
    );
    ws.onmessage = (e) => {
      try {
        const dados = JSON.parse(e.data);
        if (dados.type === "metrics") aoReceber(dados.data);
      } catch {
        /* payload inválido: ignora este tique */
      }
    };
    return ws;
  }

  // =====================================================================
  // Superfície pública
  // =====================================================================
  return {
    ErroAPI,
    get,
    post,
    patch,
    put,
    remover,
    enviarArquivo,
    definirToken,
    get token() {
      return token;
    },
    ChatSocket,
    monitorarSistema,

    auth: {
      login: (username, password) => post("/auth/login", { username, password }),
      registrar: (dados) => post("/auth/register", dados),
      sair: () => post("/auth/logout"),
      eu: () => get("/auth/me"),
      atualizarPerfil: (dados) => patch("/auth/me", dados),
      trocarSenha: (senha_atual, senha_nova) =>
        post("/auth/senha", { senha_atual, senha_nova }),
      csrf: () => get("/auth/csrf"),
      chaves: () => get("/auth/api-keys"),
      criarChave: (name) => post("/auth/api-keys", { name }),
      removerChave: (id) => remover(`/auth/api-keys/${id}`),
    },

    chat: {
      enviar: (dados) => post("/chat", dados),
      gerar: (dados) => post("/generate", dados),
      conversas: (params) => get("/conversations", params),
      criarConversa: (dados) => post("/conversations", dados || {}),
      conversa: (id) => get(`/conversations/${id}`),
      atualizarConversa: (id, dados) => patch(`/conversations/${id}`, dados),
      removerConversa: (id) => remover(`/conversations/${id}`),
      urlExport: (id, formato) =>
        `${BASE}/conversations/${id}/export?formato=${formato}`,
      mensagens: (id, params) => get(`/conversations/${id}/messages`, params),
      editarMensagem: (id, content, regenerar = true) =>
        patch(`/messages/${id}`, { content, regenerar }),
      regenerar: (id) => post(`/messages/${id}/regenerate`),
      removerMensagem: (id) => remover(`/messages/${id}`),
      historico: (params) => get("/history", params),
    },

    modelos: {
      listar: (params) => get("/models", params),
      escanear: () => post("/models/scan"),
      estado: () => get("/models/status"),
      obter: (id) => get(`/models/${id}`),
      atualizar: (id, dados) => patch(`/models/${id}`, dados),
      importar: (dados) => post("/models/import", dados),
      remover: (id, apagar) => remover(`/models/${id}?apagar_arquivo=${!!apagar}`),
      carregar: (id) => post(`/models/${id}/load`),
      descarregar: (id) => post(`/models/${id}/unload`),
      baixar: (url, nome_arquivo) => post("/models/download", { url, nome_arquivo }),
      downloads: () => get("/models/downloads/list"),
      cancelarDownload: (id) => post(`/models/downloads/${id}/cancel`),
      enviar: (formData) => enviarArquivo("/models/upload", formData),
    },

    documentos: {
      listar: (params) => get("/documents", params),
      obter: (id) => get(`/documents/${id}`),
      enviar: (formData) => enviarArquivo("/upload", formData),
      remover: (id, apagar) =>
        remover(`/documents/${id}?apagar_arquivo=${!!apagar}`),
      reindexar: (id) => post(`/documents/${id}/reindex`),
      colecoes: () => get("/documents/collections/list"),
      buscar: (dados) => post("/rag/search", dados),
      estatisticas: () => get("/rag/stats"),
      reconstruir: () => post("/rag/rebuild"),
      importarPasta: (caminho, colecao) =>
        post(
          `/rag/import-folder?caminho=${encodeURIComponent(caminho)}&colecao=${encodeURIComponent(colecao)}`
        ),
      embeddings: (textos) => post("/embeddings", { textos }),
    },

    agentes: {
      listar: (params) => get("/agents", params),
      criar: (dados) => post("/agents", dados),
      obter: (id) => get(`/agents/${id}`),
      atualizar: (id, dados) => patch(`/agents/${id}`, dados),
      remover: (id) => remover(`/agents/${id}`),
      duplicar: (id) => post(`/agents/${id}/duplicate`),
      ferramentas: () => get("/agents/tools"),
      lembrar: (id, fato) => post(`/agents/${id}/memory`, { fato }),
      esquecer: (id, indice) =>
        remover(`/agents/${id}/memory${indice != null ? `?indice=${indice}` : ""}`),
    },

    plugins: {
      listar: () => get("/plugins"),
      escanear: () => post("/plugins/scan"),
      marketplace: () => get("/plugins/marketplace"),
      estado: () => get("/plugins/status"),
      instalar: (formData) => enviarArquivo("/plugins/install", formData),
      habilitar: (slug) => post(`/plugins/${slug}/enable`),
      desabilitar: (slug) => post(`/plugins/${slug}/disable`),
      configurar: (slug, config) => patch(`/plugins/${slug}/config`, config),
      remover: (slug) => remover(`/plugins/${slug}`),
    },

    sistema: {
      info: () => get("/system"),
      monitor: (completo) => get("/system/monitor", { completo }),
      contagens: () => get("/system/stats"),
      configuracoes: (categoria) => get("/settings", { categoria }),
      gravarConfiguracao: (chave, value) => put(`/settings/${chave}`, { value }),
      configuracaoRuntime: () => get("/settings/runtime/config"),
      logs: (params) => get("/logs", params),
      limparLogs: () => remover("/logs"),
      favoritos: (tipo) => get("/favorites", { tipo }),
      favoritar: (dados) => post("/favorites", dados),
      desfavoritar: (id) => remover(`/favorites/${id}`),
      backups: () => get("/backup"),
      criarBackup: (incluir_documentos, rotulo) =>
        post(
          `/backup?incluir_documentos=${incluir_documentos !== false}${
            rotulo ? `&rotulo=${encodeURIComponent(rotulo)}` : ""
          }`
        ),
      urlBackup: (nome) => `${BASE}/backup/${encodeURIComponent(nome)}/download`,
      restaurarBackup: (nome) =>
        post(`/backup/${encodeURIComponent(nome)}/restore`),
      removerBackup: (nome) => remover(`/backup/${encodeURIComponent(nome)}`),
    },

    extras: {
      estado: () => get("/extras/status"),
      ocr: (formData) => enviarArquivo("/extras/ocr", formData),
      transcrever: (formData) => enviarArquivo("/extras/transcribe", formData),
      vozes: () => get("/extras/tts/voices"),
      gerarImagem: (dados) => post("/extras/images/generate", dados),
      modelosImagem: () => get("/extras/images/models"),
      urlImagem: (nome) => `${BASE}/extras/images/${encodeURIComponent(nome)}`,
    },
  };
})();
