/**
 * Gráficos em canvas — implementação própria, sem bibliotecas externas.
 *
 * Cobre o que o painel do LocalAI Studio precisa: séries temporais de recursos
 * (CPU/RAM/GPU), barras comparativas e um medidor radial. Todo o desenho
 * respeita o devicePixelRatio para ficar nítido em telas de alta densidade e lê
 * as cores das variáveis CSS, acompanhando a troca de tema automaticamente.
 */

const Graficos = (() => {
  /** Lê uma variável CSS do tema atual. */
  function cor(nome, alternativa) {
    const valor = getComputedStyle(document.documentElement)
      .getPropertyValue(nome)
      .trim();
    return valor || alternativa;
  }

  /** Prepara o canvas para a densidade de pixels do dispositivo. */
  function preparar(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const largura = canvas.clientWidth || canvas.parentElement.clientWidth || 300;
    const altura = canvas.clientHeight || 160;

    canvas.width = Math.round(largura * dpr);
    canvas.height = Math.round(altura * dpr);

    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, largura, altura);
    return { ctx, largura, altura };
  }

  /** Converte "#rrggbb" em "rgba(r,g,b,alfa)". */
  function comAlfa(hex, alfa) {
    const limpo = hex.replace("#", "");
    const cheio =
      limpo.length === 3
        ? limpo
            .split("")
            .map((c) => c + c)
            .join("")
        : limpo;
    const n = parseInt(cheio, 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alfa})`;
  }

  // =====================================================================
  // Gráfico de linhas (série temporal)
  // =====================================================================
  class Linha {
    /**
     * @param {HTMLCanvasElement} canvas
     * @param {object} opcoes  { series: [{rotulo, cor}], maximo, pontos }
     */
    constructor(canvas, opcoes = {}) {
      this.canvas = canvas;
      this.maximo = opcoes.maximo ?? 100;
      this.limitePontos = opcoes.pontos ?? 60;
      this.series = (opcoes.series || [{ rotulo: "valor" }]).map((s) => ({
        rotulo: s.rotulo,
        cor: s.cor || cor("--marca", "#7c6cff"),
        dados: [],
      }));
      this.sufixo = opcoes.sufixo ?? "%";
      window.addEventListener("resize", () => this.desenhar());
    }

    /** Acrescenta um ponto a cada série (na ordem informada). */
    empurrar(valores) {
      const lista = Array.isArray(valores) ? valores : [valores];
      this.series.forEach((serie, i) => {
        serie.dados.push(Number(lista[i]) || 0);
        if (serie.dados.length > this.limitePontos) serie.dados.shift();
      });
      this.desenhar();
    }

    desenhar() {
      const { ctx, largura, altura } = preparar(this.canvas);
      const margem = { esq: 34, dir: 8, topo: 10, base: 18 };
      const l = largura - margem.esq - margem.dir;
      const a = altura - margem.topo - margem.base;
      if (l <= 0 || a <= 0) return;

      const corGrade = cor("--borda", "#262c3d");
      const corTexto = cor("--txt-3", "#6f7a93");

      // Grade horizontal + rótulos do eixo Y.
      ctx.strokeStyle = corGrade;
      ctx.fillStyle = corTexto;
      ctx.lineWidth = 1;
      ctx.font = "10px system-ui, sans-serif";
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";

      for (let i = 0; i <= 4; i++) {
        const y = margem.topo + (a * i) / 4;
        ctx.beginPath();
        // O deslocamento de 0.5 alinha a linha ao pixel, evitando borrão.
        ctx.moveTo(margem.esq, Math.round(y) + 0.5);
        ctx.lineTo(margem.esq + l, Math.round(y) + 0.5);
        ctx.stroke();
        ctx.fillText(
          `${Math.round(this.maximo - (this.maximo * i) / 4)}${this.sufixo}`,
          margem.esq - 6,
          y
        );
      }

      const pontos = Math.max(...this.series.map((s) => s.dados.length), 0);
      if (pontos < 2) return;

      const passo = l / (this.limitePontos - 1);

      this.series.forEach((serie) => {
        if (serie.dados.length < 2) return;

        // Alinha a série à direita: o dado mais recente fica na borda.
        const deslocamento = this.limitePontos - serie.dados.length;
        const pos = (i) => ({
          x: margem.esq + (deslocamento + i) * passo,
          y:
            margem.topo +
            a -
            (Math.min(serie.dados[i], this.maximo) / this.maximo) * a,
        });

        // Área preenchida sob a curva.
        ctx.beginPath();
        ctx.moveTo(pos(0).x, margem.topo + a);
        serie.dados.forEach((_, i) => {
          const p = pos(i);
          ctx.lineTo(p.x, p.y);
        });
        ctx.lineTo(pos(serie.dados.length - 1).x, margem.topo + a);
        ctx.closePath();

        const gradiente = ctx.createLinearGradient(0, margem.topo, 0, margem.topo + a);
        gradiente.addColorStop(0, comAlfa(serie.cor, 0.26));
        gradiente.addColorStop(1, comAlfa(serie.cor, 0));
        ctx.fillStyle = gradiente;
        ctx.fill();

        // Curva.
        ctx.beginPath();
        serie.dados.forEach((_, i) => {
          const p = pos(i);
          if (i === 0) ctx.moveTo(p.x, p.y);
          else ctx.lineTo(p.x, p.y);
        });
        ctx.strokeStyle = serie.cor;
        ctx.lineWidth = 1.8;
        ctx.lineJoin = "round";
        ctx.stroke();

        // Marcador do valor mais recente.
        const ultimo = pos(serie.dados.length - 1);
        ctx.beginPath();
        ctx.arc(ultimo.x, ultimo.y, 3, 0, Math.PI * 2);
        ctx.fillStyle = serie.cor;
        ctx.fill();
      });
    }
  }

  // =====================================================================
  // Gráfico de barras
  // =====================================================================
  class Barras {
    constructor(canvas, opcoes = {}) {
      this.canvas = canvas;
      this.horizontal = opcoes.horizontal ?? false;
      this.cor = opcoes.cor || cor("--marca", "#7c6cff");
      this.dados = [];
      window.addEventListener("resize", () => this.desenhar());
    }

    definir(dados) {
      this.dados = dados || [];
      this.desenhar();
    }

    desenhar() {
      const { ctx, largura, altura } = preparar(this.canvas);
      if (!this.dados.length) return;

      const maximo = Math.max(...this.dados.map((d) => d.valor), 1);
      const corTexto = cor("--txt-3", "#6f7a93");
      const corTexto1 = cor("--txt-1", "#eef1f7");
      ctx.font = "11px system-ui, sans-serif";

      if (this.horizontal) {
        const alturaItem = Math.min(30, altura / this.dados.length);
        const rotuloL = 96;

        this.dados.forEach((item, i) => {
          const y = i * alturaItem + alturaItem / 2;
          const comprimento = ((largura - rotuloL - 46) * item.valor) / maximo;

          ctx.fillStyle = corTexto;
          ctx.textAlign = "right";
          ctx.textBaseline = "middle";
          ctx.fillText(_truncar(ctx, item.rotulo, rotuloL - 10), rotuloL - 8, y);

          ctx.fillStyle = comAlfa(item.cor || this.cor, 0.85);
          _retanguloArredondado(
            ctx,
            rotuloL,
            y - alturaItem * 0.28,
            Math.max(comprimento, 2),
            alturaItem * 0.56,
            3
          );
          ctx.fill();

          ctx.fillStyle = corTexto1;
          ctx.textAlign = "left";
          ctx.fillText(_formatar(item.valor), rotuloL + comprimento + 8, y);
        });
        return;
      }

      const larguraItem = largura / this.dados.length;
      this.dados.forEach((item, i) => {
        const h = ((altura - 30) * item.valor) / maximo;
        const x = i * larguraItem + larguraItem * 0.22;
        const l = larguraItem * 0.56;

        ctx.fillStyle = comAlfa(item.cor || this.cor, 0.85);
        _retanguloArredondado(ctx, x, altura - 20 - h, l, Math.max(h, 2), 3);
        ctx.fill();

        ctx.fillStyle = corTexto;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillText(
          _truncar(ctx, item.rotulo, larguraItem - 4),
          x + l / 2,
          altura - 15
        );

        ctx.fillStyle = corTexto1;
        ctx.textBaseline = "bottom";
        ctx.fillText(_formatar(item.valor), x + l / 2, altura - 24 - h);
      });
    }
  }

  // =====================================================================
  // Medidor radial
  // =====================================================================
  class Medidor {
    constructor(canvas, opcoes = {}) {
      this.canvas = canvas;
      this.rotulo = opcoes.rotulo || "";
      this.sufixo = opcoes.sufixo ?? "%";
      this.valor = 0;
      window.addEventListener("resize", () => this.desenhar());
    }

    definir(valor) {
      this.valor = Math.max(0, Math.min(100, Number(valor) || 0));
      this.desenhar();
    }

    desenhar() {
      const { ctx, largura, altura } = preparar(this.canvas);
      const cx = largura / 2;
      const cy = altura / 2 + 8;
      const raio = Math.min(largura, altura * 1.6) / 2 - 14;
      if (raio <= 0) return;

      const inicio = Math.PI * 0.75;
      const varredura = Math.PI * 1.5;

      // Trilho.
      ctx.beginPath();
      ctx.arc(cx, cy, raio, inicio, inicio + varredura);
      ctx.strokeStyle = cor("--sup-3", "#212636");
      ctx.lineWidth = 9;
      ctx.lineCap = "round";
      ctx.stroke();

      // Faixa preenchida — a cor comunica o nível de pressão do recurso.
      const corAtual =
        this.valor > 90
          ? cor("--erro", "#f2637b")
          : this.valor > 70
            ? cor("--alerta", "#f2b544")
            : cor("--marca", "#7c6cff");

      ctx.beginPath();
      ctx.arc(cx, cy, raio, inicio, inicio + (varredura * this.valor) / 100);
      ctx.strokeStyle = corAtual;
      ctx.lineWidth = 9;
      ctx.stroke();

      ctx.textAlign = "center";
      ctx.fillStyle = cor("--txt-1", "#eef1f7");
      ctx.font = "600 21px system-ui, sans-serif";
      ctx.textBaseline = "alphabetic";
      ctx.fillText(`${Math.round(this.valor)}${this.sufixo}`, cx, cy + 4);

      if (this.rotulo) {
        ctx.fillStyle = cor("--txt-3", "#6f7a93");
        ctx.font = "11px system-ui, sans-serif";
        ctx.fillText(this.rotulo, cx, cy + 21);
      }
    }
  }

  // -------------------------------------------------------------- auxiliares
  function _retanguloArredondado(ctx, x, y, l, a, r) {
    const raio = Math.min(r, l / 2, a / 2);
    ctx.beginPath();
    ctx.moveTo(x + raio, y);
    ctx.arcTo(x + l, y, x + l, y + a, raio);
    ctx.arcTo(x + l, y + a, x, y + a, raio);
    ctx.arcTo(x, y + a, x, y, raio);
    ctx.arcTo(x, y, x + l, y, raio);
    ctx.closePath();
  }

  function _truncar(ctx, texto, larguraMax) {
    let t = String(texto);
    if (ctx.measureText(t).width <= larguraMax) return t;
    while (t.length > 1 && ctx.measureText(t + "…").width > larguraMax) {
      t = t.slice(0, -1);
    }
    return t + "…";
  }

  function _formatar(n) {
    if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
    return String(Math.round(n * 10) / 10);
  }

  return { Linha, Barras, Medidor, cor };
})();
