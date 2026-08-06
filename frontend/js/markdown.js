/**
 * Renderizador de Markdown e realce de sintaxe — implementação própria.
 *
 * O sistema precisa funcionar totalmente offline, sem CDN nem pacotes de
 * terceiros; por isso Markdown e realce são implementados aqui, cobrindo o que
 * modelos de linguagem de fato produzem: cabeçalhos, listas, tabelas, citações,
 * ênfase, links e blocos de código.
 *
 * Segurança: todo texto é escapado ANTES de qualquer substituição por HTML.
 * Nenhum caminho do renderizador injeta conteúdo bruto do modelo no DOM.
 */

const Markdown = (() => {
  // =====================================================================
  // Realce de sintaxe
  // =====================================================================
  const PALAVRAS = {
    python:
      "def class return if elif else for while in not and or is None True False import from as try except finally raise with lambda yield global nonlocal assert del pass break continue async await match case",
    javascript:
      "function return if else for while do const let var class new this typeof instanceof import from export default try catch finally throw switch case break continue async await yield of in delete void null undefined true false extends static get set",
    typescript:
      "function return if else for while const let var class new this typeof import from export default try catch finally throw switch case break continue async await interface type enum implements extends public private protected readonly namespace declare as satisfies null undefined true false",
    java:
      "public private protected class interface extends implements return if else for while do new this static final void int long double float boolean char String try catch finally throw throws import package abstract synchronized enum instanceof null true false",
    csharp:
      "public private protected internal class interface struct return if else for foreach while do new this static readonly void int long double float bool string var try catch finally throw using namespace async await null true false override virtual",
    go: "func package import return if else for range var const type struct interface map chan go defer select switch case break continue nil true false make new",
    rust: "fn let mut const struct enum impl trait pub use mod return if else for while loop match in as dyn ref move Some None Ok Err true false self Self where async await",
    sql:
      "SELECT FROM WHERE INSERT UPDATE DELETE CREATE TABLE ALTER DROP JOIN LEFT RIGHT INNER OUTER ON GROUP BY ORDER HAVING LIMIT OFFSET AS AND OR NOT NULL PRIMARY KEY FOREIGN REFERENCES INDEX UNION DISTINCT COUNT SUM AVG MIN MAX CASE WHEN THEN END",
    bash:
      "if then else elif fi for while do done case esac function return export local source echo cd ls mkdir rm cp mv cat grep sed awk sudo apt pip python git chmod chown",
    css: "important media supports keyframes import charset font-face root hover focus active before after",
    html: "",
    json: "true false null",
    yaml: "true false null yes no on off",
  };

  const ALIAS = {
    py: "python",
    js: "javascript",
    jsx: "javascript",
    ts: "typescript",
    tsx: "typescript",
    sh: "bash",
    shell: "bash",
    zsh: "bash",
    console: "bash",
    "c#": "csharp",
    cs: "csharp",
    golang: "go",
    rs: "rust",
    yml: "yaml",
    htm: "html",
    xml: "html",
  };

  /**
   * Aplica realce em um trecho de código já escapado.
   *
   * Trabalha em uma única passagem com uma expressão combinada, evitando o
   * problema clássico de substituições encadeadas corromperem tags já geradas.
   */
  function realcar(codigoEscapado, linguagem) {
    const lang = ALIAS[(linguagem || "").toLowerCase()] || (linguagem || "").toLowerCase();

    if (lang === "html") return realcarMarcacao(codigoEscapado);

    const palavras = PALAVRAS[lang];
    if (palavras === undefined) return codigoEscapado; // linguagem desconhecida

    const conjunto = new Set(palavras.split(/\s+/).filter(Boolean));
    const conjuntoMaiusculo = new Set([...conjunto].map((p) => p.toUpperCase()));
    const semDistincao = lang === "sql";

    // Ordem importa: strings e comentários primeiro, para que palavras dentro
    // deles não sejam realçadas.
    const padrao = new RegExp(
      [
        // Comentários
        "(#[^\\n]*|//[^\\n]*|/\\*[\\s\\S]*?\\*/|--[^\\n]*)",
        // Strings (aspas triplas, duplas, simples e crase)
        "(\"\"\"[\\s\\S]*?\"\"\"|'''[\\s\\S]*?'''|\"(?:[^\"\\\\\\n]|\\\\.)*\"|'(?:[^'\\\\\\n]|\\\\.)*'|`(?:[^`\\\\]|\\\\.)*`)",
        // Números
        "\\b(0[xXbBoO][0-9a-fA-F_]+|\\d[\\d_]*\\.?[\\d_]*(?:[eE][+-]?\\d+)?)\\b",
        // Chamada de função: identificador seguido de parêntese
        "\\b([A-Za-z_$][\\w$]*)(?=\\s*\\()",
        // Identificadores
        "\\b([A-Za-z_$][\\w$]*)\\b",
      ].join("|"),
      "g"
    );

    return codigoEscapado.replace(
      padrao,
      (todo, comentario, texto, numero, funcao, ident) => {
        if (comentario) return `<span class="tk-comentario">${comentario}</span>`;
        if (texto) return `<span class="tk-texto">${texto}</span>`;
        if (numero) return `<span class="tk-numero">${numero}</span>`;

        if (funcao) {
          const chave = semDistincao ? funcao.toUpperCase() : funcao;
          if (conjunto.has(chave) || (semDistincao && conjuntoMaiusculo.has(chave))) {
            return `<span class="tk-palavra">${funcao}</span>`;
          }
          return `<span class="tk-funcao">${funcao}</span>`;
        }

        if (ident) {
          const chave = semDistincao ? ident.toUpperCase() : ident;
          if (conjunto.has(chave) || (semDistincao && conjuntoMaiusculo.has(chave))) {
            return `<span class="tk-palavra">${ident}</span>`;
          }
          // Convenção: identificadores em PascalCase são tipos/classes.
          if (/^[A-Z][a-z]/.test(ident)) {
            return `<span class="tk-tipo">${ident}</span>`;
          }
          // CONSTANTES em maiúsculas.
          if (/^[A-Z][A-Z0-9_]{2,}$/.test(ident)) {
            return `<span class="tk-const">${ident}</span>`;
          }
        }
        return todo;
      }
    );
  }

  /** Realce específico para HTML/XML (tags, atributos e valores). */
  function realcarMarcacao(codigo) {
    return codigo
      .replace(/(&lt;!--[\s\S]*?--&gt;)/g, '<span class="tk-comentario">$1</span>')
      .replace(
        /(&lt;\/?)([\w-]+)/g,
        '$1<span class="tk-marcacao">$2</span>'
      )
      .replace(
        /([\w-]+)(=)(&quot;[^&]*?&quot;|"[^"]*")/g,
        '<span class="tk-atributo">$1</span><span class="tk-operador">$2</span><span class="tk-texto">$3</span>'
      );
  }

  // =====================================================================
  // Markdown
  // =====================================================================
  // Marcador usado para proteger trechos de codigo inline durante as demais
  // substituicoes. Fica na area de uso privado do Unicode: nao ocorre em texto
  // real, e o conteudo ja escapado nunca o contem.
  const SENTINELA = "\uE000";
  const RE_SENTINELA = /\uE000(\d+)\uE000/g;

  function escapar(texto) {
    return String(texto)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  /** Aplica formatação de linha: código, negrito, itálico, riscado, links. */
  function inline(texto) {
    // O código inline é extraído primeiro e reinserido no fim, para que o
    // conteúdo dentro de crases não sofra as demais transformações.
    const trechos = [];
    let saida = texto.replace(/`([^`]+)`/g, (_, codigo) => {
      trechos.push(`<code>${codigo}</code>`);
      return SENTINELA + (trechos.length - 1) + SENTINELA;
    });

    saida = saida
      // Imagens antes dos links (sintaxe é um superconjunto).
      .replace(
        /!\[([^\]]*)\]\(([^)\s]+)\)/g,
        '<img src="$2" alt="$1" style="max-width:100%;border-radius:8px">'
      )
      .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, rotulo, destino) => {
        // Bloqueia esquemas perigosos (javascript:, data:) em links.
        const seguro = /^(https?:|mailto:|\/|#)/i.test(destino);
        return seguro
          ? `<a href="${destino}" target="_blank" rel="noopener noreferrer">${rotulo}</a>`
          : rotulo;
      })
      .replace(/\*\*\*([^*]+)\*\*\*/g, "<strong><em>$1</em></strong>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(?<![\w*])\*([^*\n]+)\*(?![\w*])/g, "<em>$1</em>")
      .replace(/(?<![\w_])_([^_\n]+)_(?![\w_])/g, "<em>$1</em>")
      .replace(/~~([^~]+)~~/g, "<del>$1</del>");

    return saida.replace(RE_SENTINELA, (_, i) => trechos[Number(i)]);
  }

  /**
   * Converte Markdown em HTML.
   *
   * @param {string} texto  Markdown de origem.
   * @param {boolean} parcial  Em streaming, um bloco de código ainda aberto é
   *                           renderizado mesmo sem a cerca de fechamento.
   */
  function renderizar(texto, parcial = false) {
    if (!texto) return "";

    const linhas = escapar(texto).split("\n");
    const saida = [];
    let i = 0;

    while (i < linhas.length) {
      const linha = linhas[i];

      // ---------------------------------------------------- bloco de código
      const cerca = linha.match(/^\s*```+\s*([\w#+.-]*)\s*$/);
      if (cerca) {
        const linguagem = cerca[1] || "";
        const corpo = [];
        i += 1;
        let fechado = false;

        while (i < linhas.length) {
          if (/^\s*```+\s*$/.test(linhas[i])) {
            fechado = true;
            i += 1;
            break;
          }
          corpo.push(linhas[i]);
          i += 1;
        }

        // Bloco não fechado só é renderizado durante o streaming.
        if (!fechado && !parcial) {
          saida.push(`<p>${inline(linha)}</p>`);
          corpo.forEach((l) => saida.push(`<p>${inline(l)}</p>`));
          continue;
        }

        const codigo = corpo.join("\n");
        const rotulo = linguagem || "texto";
        saida.push(
          `<pre><div class="bloco-codigo-topo">` +
            `<span class="bloco-codigo-lang">${escapar(rotulo)}</span>` +
            `<button class="bloco-codigo-copiar" data-copiar-codigo>` +
            `${Icones.copiar(12)} copiar</button></div>` +
            `<code>${realcar(codigo, linguagem)}</code></pre>`
        );
        continue;
      }

      // ------------------------------------------------------------ tabela
      if (
        linha.includes("|") &&
        i + 1 < linhas.length &&
        /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(linhas[i + 1])
      ) {
        const celulas = (l) =>
          l
            .trim()
            .replace(/^\||\|$/g, "")
            .split("|")
            .map((c) => c.trim());

        const cabecalho = celulas(linha);
        i += 2;

        const corpo = [];
        while (i < linhas.length && linhas[i].includes("|") && linhas[i].trim()) {
          corpo.push(celulas(linhas[i]));
          i += 1;
        }

        saida.push(
          "<table><thead><tr>" +
            cabecalho.map((c) => `<th>${inline(c)}</th>`).join("") +
            "</tr></thead><tbody>" +
            corpo
              .map(
                (linhaCelulas) =>
                  "<tr>" +
                  linhaCelulas.map((c) => `<td>${inline(c)}</td>`).join("") +
                  "</tr>"
              )
              .join("") +
            "</tbody></table>"
        );
        continue;
      }

      // ---------------------------------------------------------- cabeçalho
      const cabecalho = linha.match(/^(#{1,6})\s+(.*)$/);
      if (cabecalho) {
        const nivel = Math.min(cabecalho[1].length, 4);
        saida.push(`<h${nivel}>${inline(cabecalho[2])}</h${nivel}>`);
        i += 1;
        continue;
      }

      // ----------------------------------------------------- régua horizontal
      if (/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(linha)) {
        saida.push("<hr>");
        i += 1;
        continue;
      }

      // ------------------------------------------------------------- citação
      if (/^\s*&gt;\s?/.test(linha)) {
        const trechos = [];
        while (i < linhas.length && /^\s*&gt;\s?/.test(linhas[i])) {
          trechos.push(linhas[i].replace(/^\s*&gt;\s?/, ""));
          i += 1;
        }
        saida.push(`<blockquote>${renderizar(desescapar(trechos.join("\n")), parcial)}</blockquote>`);
        continue;
      }

      // --------------------------------------------------------------- lista
      const marcador = linha.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
      if (marcador) {
        const ordenada = /\d/.test(marcador[2]);
        const itens = [];

        while (i < linhas.length) {
          const atual = linhas[i].match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
          if (!atual) {
            // Linha de continuação recuada pertence ao item anterior.
            if (itens.length && /^\s{2,}\S/.test(linhas[i])) {
              itens[itens.length - 1] += " " + linhas[i].trim();
              i += 1;
              continue;
            }
            break;
          }
          if (/\d/.test(atual[2]) !== ordenada) break;
          itens.push(atual[3]);
          i += 1;
        }

        const tag = ordenada ? "ol" : "ul";
        saida.push(
          `<${tag}>` +
            itens.map((item) => `<li>${inline(item)}</li>`).join("") +
            `</${tag}>`
        );
        continue;
      }

      // ------------------------------------------------------------ parágrafo
      if (!linha.trim()) {
        i += 1;
        continue;
      }

      const paragrafo = [];
      while (i < linhas.length && linhas[i].trim() && !ehBlocoNovo(linhas[i])) {
        paragrafo.push(linhas[i]);
        i += 1;
      }
      saida.push(`<p>${inline(paragrafo.join("<br>"))}</p>`);
    }

    return saida.join("\n");
  }

  /** Indica se a linha inicia um bloco (encerrando o parágrafo corrente). */
  function ehBlocoNovo(linha) {
    return (
      /^\s*```/.test(linha) ||
      /^#{1,6}\s/.test(linha) ||
      /^\s*&gt;\s?/.test(linha) ||
      /^(\s*)([-*+]|\d+[.)])\s+/.test(linha) ||
      /^\s*([-*_])\s*\1\s*\1/.test(linha)
    );
  }

  /** Desfaz o escape (necessário na recursão de citações). */
  function desescapar(texto) {
    return texto
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&amp;/g, "&");
  }

  return { renderizar, realcar, escapar, inline };
})();
