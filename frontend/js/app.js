/**
 * Orquestração da aplicação: autenticação, navegação, tema e atalhos.
 */

const App = (() => {
  const { $, $$ } = UI;

  const PAGINAS = {
    chat: { titulo: "Chat" },
    painel: { titulo: "Painel", modulo: () => Paginas.Painel, caixa: "#corpo-painel" },
    modelos: { titulo: "Modelos", modulo: () => Paginas.Modelos, caixa: "#corpo-modelos" },
    documentos: { titulo: "Documentos e RAG", modulo: () => Paginas.Documentos, caixa: "#corpo-documentos" },
    agentes: { titulo: "Agentes", modulo: () => Paginas.Agentes, caixa: "#corpo-agentes" },
    plugins: { titulo: "Plugins", modulo: () => Paginas.Plugins, caixa: "#corpo-plugins" },
    sistema: { titulo: "Monitor do sistema", modulo: () => Paginas.Sistema, caixa: "#corpo-sistema" },
    logs: { titulo: "Logs", modulo: () => Paginas.Logs, caixa: "#corpo-logs" },
    config: { titulo: "Configurações", modulo: () => Paginas.Config, caixa: "#corpo-config" },
    ajuda: { titulo: "Ajuda", modulo: () => Paginas.Ajuda, caixa: "#corpo-ajuda" },
  };

  let usuario = null;
  let paginaAtual = "chat";
  let modoLogin = "entrar";

  // =====================================================================
  // Inicialização
  // =====================================================================
  async function iniciar() {
    aplicarTemaSalvo();
    aplicarFonteSalva();
    UI.aplicarIcones();
    ligarEventosGlobais();

    // Garante o cookie CSRF antes de qualquer POST.
    try {
      await API.auth.csrf();
    } catch {
      /* servidor pode estar iniciando; o middleware emite o cookie depois */
    }

    if (API.token) {
      try {
        usuario = await API.auth.eu();
        return entrarNoApp();
      } catch {
        API.definirToken(null);
      }
    }
    mostrarLogin();
  }

  function ligarEventosGlobais() {
    // ------------------------------------------------------------ login
    $$("[data-aba-login]").forEach((aba) =>
      aba.addEventListener("click", () => {
        modoLogin = aba.dataset.abaLogin;
        $$("[data-aba-login]").forEach((a) =>
          a.classList.toggle("ativa", a === aba)
        );
        const criando = modoLogin === "criar";
        $(".campo-nome").classList.toggle("oculto", !criando);
        $(".campo-dica-senha").classList.toggle("oculto", !criando);
        $("#login-enviar").textContent = criando ? "Criar conta" : "Entrar";
        $("#login-senha").autocomplete = criando ? "new-password" : "current-password";
        esconderErroLogin();
      })
    );

    $("#form-login").addEventListener("submit", enviarLogin);

    // -------------------------------------------------------- navegação
    $$("[data-pagina]").forEach((item) =>
      item.addEventListener("click", () => irPara(item.dataset.pagina))
    );

    $("#btn-menu").addEventListener("click", alternarLateral);
    $("#btn-tema").addEventListener("click", () =>
      definirTema(document.documentElement.dataset.tema === "escuro" ? "claro" : "escuro")
    );
    $("#btn-sair").addEventListener("click", sair);

    // ------------------------------------------------------------ modal
    $$("[data-fechar-modal]").forEach((botao) =>
      botao.addEventListener("click", UI.fecharModal)
    );
    $("#sobreposicao").addEventListener("click", (e) => {
      if (e.target.id === "sobreposicao") UI.fecharModal();
    });

    // -------------------------------------------------------- atalhos
    document.addEventListener("keydown", (e) => {
      const cmd = e.ctrlKey || e.metaKey;

      if (e.key === "Escape") {
        if ($("#sobreposicao").classList.contains("aberta")) UI.fecharModal();
        else if (Chat.estado.gerando) Chat.socket.parar();
        return;
      }

      if (!cmd) return;

      if (e.key === "k") {
        e.preventDefault();
        $("#busca-conversas").focus();
      } else if (e.key === "n") {
        e.preventDefault();
        Chat.novaConversa();
      } else if (e.key === "b") {
        e.preventDefault();
        alternarLateral();
      }
    });

    // Sessão expirada em qualquer requisição.
    window.addEventListener("lais:sessao-expirada", () => {
      UI.alerta("Sua sessão expirou. Entre novamente.");
      mostrarLogin();
    });

    // Fecha a lateral ao navegar no celular.
    window.addEventListener("resize", () => {
      if (window.innerWidth > 900) {
        $("#app").classList.remove("lateral-visivel");
      }
    });
  }

  // =====================================================================
  // Autenticação
  // =====================================================================
  async function enviarLogin(evento) {
    evento.preventDefault();
    esconderErroLogin();

    const botao = $("#login-enviar");
    const usuarioNome = $("#login-usuario").value.trim();
    const senha = $("#login-senha").value;

    botao.disabled = true;
    botao.textContent = "Aguarde…";

    try {
      const resposta =
        modoLogin === "criar"
          ? await API.auth.registrar({
              username: usuarioNome,
              password: senha,
              full_name: $("#login-nome").value.trim() || null,
            })
          : await API.auth.login(usuarioNome, senha);

      API.definirToken(resposta.access_token);
      usuario = resposta.user;
      entrarNoApp();
    } catch (e) {
      mostrarErroLogin(e.message || "Não foi possível entrar.");
    } finally {
      botao.disabled = false;
      botao.textContent = modoLogin === "criar" ? "Criar conta" : "Entrar";
    }
  }

  function mostrarErroLogin(mensagem) {
    const caixa = $("#login-erro");
    caixa.textContent = mensagem;
    caixa.classList.add("visivel");
  }

  function esconderErroLogin() {
    $("#login-erro").classList.remove("visivel");
  }

  function mostrarLogin() {
    $("#app").hidden = true;
    $("#tela-login").hidden = false;
    $("#login-usuario").focus();
  }

  async function entrarNoApp() {
    $("#tela-login").hidden = true;
    $("#app").hidden = false;

    $("#usuario-nome").textContent = usuario.full_name || usuario.username;
    $("#usuario-papel").textContent =
      usuario.role === "admin" ? "Administrador" : "Usuário";
    $("#usuario-avatar").textContent = (usuario.username[0] || "?").toUpperCase();

    Chat.iniciar();
    await Promise.all([
      Chat.carregarConversas(),
      Chat.carregarSeletores(),
      atualizarContadores(),
    ]);

    Chat.novaConversa();
    UI.aplicarIcones();
  }

  async function sair() {
    try {
      await API.auth.sair();
    } catch {
      /* mesmo sem resposta do servidor, encerramos localmente */
    }
    if (Chat.socket) Chat.socket.desconectar();
    API.definirToken(null);
    usuario = null;
    location.reload();
  }

  // =====================================================================
  // Navegação
  // =====================================================================
  let moduloAtual = null;

  async function irPara(nome) {
    const pagina = PAGINAS[nome];
    if (!pagina) return;

    // Libera timers/sockets da página que está saindo.
    if (moduloAtual?.sair) moduloAtual.sair();
    moduloAtual = null;

    paginaAtual = nome;

    $$(".pagina").forEach((p) =>
      p.classList.toggle("ativa", p.id === `pagina-${nome}`)
    );
    $$("[data-pagina]").forEach((i) =>
      i.classList.toggle("ativo", i.dataset.pagina === nome)
    );

    $("#topo-titulo").textContent = pagina.titulo;
    $("#app").classList.remove("lateral-visivel");

    if (pagina.modulo) {
      const modulo = pagina.modulo();
      moduloAtual = modulo;
      try {
        await modulo.render($(pagina.caixa));
      } catch (e) {
        console.error(`Falha ao renderizar "${nome}":`, e);
        $(pagina.caixa).innerHTML = UI.vazio(
          "!",
          "Falha ao carregar a página",
          e.message || "Erro desconhecido"
        );
      }
    }

    if (nome !== "chat") atualizarContadores();
  }

  /** Re-renderiza a página atual (após uma ação que mudou os dados). */
  function recarregarPagina() {
    if (paginaAtual !== "chat") irPara(paginaAtual);
    atualizarContadores();
  }

  async function atualizarContadores() {
    try {
      const c = await API.sistema.contagens();
      $("#contador-modelos").textContent = c.models || "";
      $("#contador-documentos").textContent = c.documents || "";
      $("#contador-agentes").textContent = c.agents || "";
    } catch {
      /* contadores são informativos: falha silenciosa é aceitável */
    }
  }

  function alternarLateral() {
    const app = $("#app");
    if (window.innerWidth <= 900) app.classList.toggle("lateral-visivel");
    else app.classList.toggle("lateral-oculta");
  }

  // =====================================================================
  // Tema e preferências
  // =====================================================================
  function definirTema(tema) {
    document.documentElement.dataset.tema = tema;
    localStorage.setItem("lais_tema", tema);
    $("#btn-tema").innerHTML = tema === "escuro" ? Icones.sol(16) : Icones.lua(16);
    // Os gráficos leem cores do CSS: precisam ser redesenhados na troca.
    window.dispatchEvent(new Event("resize"));
  }

  function aplicarTemaSalvo() {
    const salvo = localStorage.getItem("lais_tema");
    const preferido = window.matchMedia?.("(prefers-color-scheme: light)").matches
      ? "claro"
      : "escuro";
    definirTema(salvo || preferido);
  }

  function aplicarFonteSalva() {
    const px = localStorage.getItem("lais_fonte");
    if (px) $("#chat-lista").style.fontSize = `${px}px`;
  }

  // =====================================================================
  document.addEventListener("DOMContentLoaded", iniciar);

  return {
    irPara,
    recarregarPagina,
    atualizarContadores,
    definirTema,
    sair,
    get usuario() {
      return usuario;
    },
    get paginaAtual() {
      return paginaAtual;
    },
  };
})();
