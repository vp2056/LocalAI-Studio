/**
 * Ícones SVG embutidos.
 *
 * Desenhados como paths inline em vez de uma fonte de ícones: mantém tudo
 * offline, elimina o "flash" de carregamento e permite herdar a cor do texto.
 * Traçado de 1.75 para casar com o peso tipográfico da interface.
 */

const Icones = (() => {
  const svg = (conteudo, tamanho = 17) =>
    `<svg class="ico" width="${tamanho}" height="${tamanho}" viewBox="0 0 24 24" ` +
    `fill="none" stroke="currentColor" stroke-width="1.75" ` +
    `stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${conteudo}</svg>`;

  return {
    chat: (t) =>
      svg('<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 9 9 0 0 1-4-.9L3 21l1.9-5a8.4 8.4 0 0 1-.9-4 8.4 8.4 0 0 1 8.4-8.4h.5A8.4 8.4 0 0 1 21 11v.5z"/>', t),

    painel: (t) =>
      svg('<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>', t),

    cubo: (t) =>
      svg('<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>', t),

    documento: (t) =>
      svg('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M8 13h8M8 17h5"/>', t),

    busca: (t) => svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>', t),

    robo: (t) =>
      svg('<rect x="4" y="8" width="16" height="12" rx="2.5"/><path d="M12 8V4M9 4h6"/><circle cx="9" cy="14" r="1.1"/><circle cx="15" cy="14" r="1.1"/><path d="M2 13v3M22 13v3"/>', t),

    plugue: (t) =>
      svg('<path d="M9 2v6M15 2v6"/><path d="M6 8h12v4a6 6 0 0 1-12 0V8z"/><path d="M12 18v4"/>', t),

    monitor: (t) =>
      svg('<rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4"/><path d="m6 12 2.5-3 2 2.5L13 8l2 3.5"/>', t),

    lista: (t) =>
      svg('<path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>', t),

    engrenagem: (t) =>
      svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6h.09A1.7 1.7 0 0 0 10 3.05V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9v.09a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>', t),

    escudo: (t) =>
      svg('<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>', t),

    ajuda: (t) =>
      svg('<circle cx="12" cy="12" r="9"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>', t),

    mais: (t) => svg('<path d="M12 5v14M5 12h14"/>', t),

    enviar: (t) => svg('<path d="M4 12h15M13 6l6 6-6 6"/>', t),

    parar: (t) => svg('<rect x="7" y="7" width="10" height="10" rx="1.5"/>', t),

    copiar: (t) =>
      svg('<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>', t),

    lapis: (t) =>
      svg('<path d="M17 3a2.5 2.5 0 0 1 3.5 3.5L7 20l-4 1 1-4z"/><path d="m15 5 4 4"/>', t),

    lixeira: (t) =>
      svg('<path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M10 11v6M14 11v6"/>', t),

    recarregar: (t) =>
      svg('<path d="M3 12a9 9 0 0 1 15.5-6.2L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15.5 6.2L3 16"/><path d="M3 21v-5h5"/>', t),

    baixar: (t) =>
      svg('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5M12 15V3"/>', t),

    enviarArquivo: (t) =>
      svg('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5M12 3v12"/>', t),

    alfinete: (t) =>
      svg('<path d="M12 17v5"/><path d="M9 3h6l-1 5 3 3v2H7v-2l3-3z"/>', t),

    estrela: (t) =>
      svg('<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1-5.4-2.9L6.6 20l1-6.1L3.2 9.5l6.1-.9z"/>', t),

    sair: (t) =>
      svg('<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5M21 12H9"/>', t),

    menu: (t) => svg('<path d="M3 6h18M3 12h18M3 18h18"/>', t),

    fechar: (t) => svg('<path d="M18 6 6 18M6 6l12 12"/>', t),

    sol: (t) =>
      svg('<circle cx="12" cy="12" r="4.2"/><path d="M12 2v2M12 20v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M2 12h2M20 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/>', t),

    lua: (t) => svg('<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>', t),

    raio: (t) => svg('<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>', t),

    pasta: (t) =>
      svg('<path d="M4 20a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2z"/>', t),

    banco: (t) =>
      svg('<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>', t),

    check: (t) => svg('<path d="m5 12.5 5 5L19 6"/>', t),

    alerta: (t) =>
      svg('<path d="M12 3 2.5 20h19z"/><path d="M12 9v5M12 17h.01"/>', t),

    microfone: (t) =>
      svg('<rect x="9" y="2" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v4"/>', t),

    som: (t) =>
      svg('<path d="M11 5 6 9H2v6h4l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/>', t),

    imagem: (t) =>
      svg('<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.6"/><path d="m21 15-5-5L5 21"/>', t),

    olho: (t) =>
      svg('<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>', t),
  };
})();
