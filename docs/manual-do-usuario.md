# Manual do usuário

Guia completo da interface do LocalAI Studio.

---

## Primeiro acesso

Abra <http://127.0.0.1:8080> e entre com as credenciais exibidas no console do
servidor durante a instalação. Troque a senha em **Configurações → Trocar senha**;
isso encerra todas as outras sessões.

A aba **Criar conta** registra novos usuários. O primeiro usuário do sistema é
automaticamente administrador; os demais são usuários comuns e não podem gerenciar
plugins nem backups.

---

## Chat

### Conversando

Escreva na caixa inferior e pressione **Enter** (use **Shift+Enter** para quebrar
linha). A resposta aparece palavra por palavra conforme o modelo gera.

Abaixo da caixa há quatro controles:

- **Seletor de modelo** — qual modelo responde. Vazio significa que nenhum modelo
  está instalado e o chat opera em modo diagnóstico.
- **Seletor de agente** — aplica uma persona com parâmetros e ferramentas próprios.
- **RAG** — quando ligado, cada pergunta consulta seus documentos indexados antes
  de ir ao modelo, e a resposta cita as fontes usadas.
- **Parâmetros** — ajusta temperatura, top-p, top-k, tokens máximos, penalidade de
  repetição e semente para esta conversa.

Durante a geração, o botão de envio vira **parar**; clique nele (ou pressione
**Esc**) para interromper. O texto já gerado é preservado.

### Parâmetros de geração

| Parâmetro | O que faz | Quando ajustar |
|---|---|---|
| **Temperatura** | Aleatoriedade da escolha de palavras | `0.1–0.3` para código e fatos; `0.7–1.0` para texto criativo |
| **Top-P** | Considera só os tokens que somam esta probabilidade | Deixe em `0.95`; reduza para respostas mais focadas |
| **Top-K** | Limita às K palavras mais prováveis | `40` é um bom padrão; `0` desativa |
| **Tokens máximos** | Tamanho máximo da resposta | Aumente para textos longos; reduza para economizar tempo |
| **Penalidade de repetição** | Desestimula repetir trechos | Acima de `1.1` se o modelo ficar repetitivo |
| **Semente** | Torna a geração reproduzível | Fixe um número para obter sempre a mesma resposta |

### Ações sobre mensagens

Passe o mouse sobre uma mensagem para revelar as ações:

- **Copiar** — copia o texto integral.
- **Editar** (suas mensagens) — corrige a pergunta e regenera a resposta,
  descartando tudo o que veio depois.
- **Regenerar** (respostas) — descarta a resposta e gera outra.
- **Excluir** — remove a mensagem.

Blocos de código têm um botão **copiar** próprio no cabeçalho.

### Gerenciando conversas

A lista lateral mostra suas conversas, com as fixadas no topo. Passe o mouse sobre
uma para **fixar**, **renomear** ou **excluir**.

O campo de pesquisa procura tanto nos títulos quanto no conteúdo das mensagens.

Para exportar, abra a conversa e use o endereço
`/api/conversations/{id}/export?formato=markdown` (também aceita `json` e `txt`).

---

## Modelos

### Instalando

Três caminhos:

1. **Copiar o arquivo** para a pasta `models/` e clicar em **Reexaminar**.
2. **Importar** — informe o caminho no disco. Desligue “Copiar para a pasta models/”
   para apenas referenciar o arquivo onde ele já está (útil para arquivos grandes
   em outra partição).
3. **Baixar por URL** — o download roda em segundo plano, mostra progresso e é
   retomado automaticamente se a conexão cair.

Formatos aceitos: `.gguf` (llama.cpp), `.safetensors` e pastas HuggingFace
(Transformers), `.onnx` (ONNX Runtime).

### Entendendo a tabela

- **Parâmetros** — tamanho do modelo (7B, 13B…). Mais parâmetros geralmente
  significam respostas melhores e mais consumo de memória.
- **Quantização** — precisão dos pesos. `Q4_K_M` equilibra qualidade e tamanho;
  `Q8_0` é mais preciso e ocupa o dobro; `F16` é o modelo sem compressão.
- **Contexto** — quantos tokens o modelo consegue considerar de uma vez, incluindo
  o histórico da conversa e o contexto do RAG.

O botão de **olho** abre os metadados técnicos completos, lidos direto do cabeçalho
do arquivo.

### Carregar, descarregar e padrão

- **Carregar** coloca o modelo em memória antecipadamente, eliminando a espera da
  primeira resposta.
- **Descarregar** libera a RAM.
- O ícone de **estrela** define o modelo padrão para novas conversas.

Por padrão apenas um modelo fica em memória; ao usar outro, o menos recente é
descarregado. Ajuste com `LAIS_MAX_LOADED_MODELS`.

---

## Documentos e RAG

**RAG** (geração aumentada por recuperação) permite que o assistente responda com
base nos seus arquivos, citando de onde tirou cada informação.

### Como funciona

Ao enviar um documento, o sistema extrai o texto, divide em trechos com
sobreposição, converte cada trecho em um vetor numérico e indexa. Quando você
pergunta algo com o RAG ligado, a pergunta também vira vetor, os trechos mais
próximos são recuperados e entram no prompt como contexto.

### Enviando

**Documentos → Enviar documento.** Aceita PDF, DOCX, TXT, HTML, Markdown, CSV e
JSON; vários arquivos de uma vez. A indexação é automática.

**Coleções** separam bases por assunto — por exemplo, `contratos`, `manuais`,
`pesquisa`. Um agente pode ser restrito a coleções específicas.

### Usando

Ligue o botão **RAG** no chat e pergunte normalmente. Abaixo da resposta aparece o
bloco **Fontes**, com o documento, a página (em PDFs) e a pontuação de relevância
de cada trecho utilizado.

**Testar busca** permite consultar o índice diretamente, sem passar pelo modelo —
útil para verificar se um documento foi bem indexado.

### Modo lexical vs. semântico

Se aparecer um aviso de que a busca está em **modo lexical**, significa que o
modelo de embeddings não está instalado. A busca ainda funciona (encontra termos
parecidos), mas não entende sinônimos. Instale `sentence-transformers`, clique em
**Reconstruir índice** e reindexe os documentos.

### Manutenção

- **Reindexar** (por documento) reprocessa o arquivo — necessário após trocar o
  modelo de embeddings.
- **Reconstruir índice** recria o índice vetorial a partir do banco. Use após
  trocar o backend vetorial ou se a busca começar a se comportar de forma estranha.

---

## Agentes

Um agente é um conjunto salvo de persona, parâmetros, ferramentas e memória.

### Criando

**Agentes → Novo agente.** Os campos:

- **Ícone e nome** — identificação visual.
- **Instruções do sistema** — o mais importante. Define quem o agente é, como
  responde e o que não deve fazer. Seja específico: *“Você é um revisor de código
  Python. Aponte bugs, problemas de segurança e violações de PEP 8. Seja direto e
  cite o número da linha.”*
- **Modelo padrão** — deixe vazio para usar o modelo da conversa.
- **Temperatura e tokens máximos** — parâmetros próprios do agente.
- **Ferramentas** — capacidades que o agente pode acionar.
- **Memória permanente** — quando ligada, o agente lembra de fatos entre conversas.

### Ferramentas disponíveis

| Ferramenta | O que faz |
|---|---|
| `calculadora` | Avalia expressões matemáticas com segurança |
| `data_hora` | Informa a data e hora atuais |
| `busca_documentos` | Consulta a base RAG |
| `info_sistema` | Relata CPU, memória e disco |
| `listar_modelos` | Lista os modelos instalados |

O agente aciona uma ferramenta escrevendo `[[ferramenta:nome(argumento=valor)]]`,
e o resultado é inserido na resposta. Ferramentas não habilitadas para o agente são
recusadas.

### Memória

O ícone de **banco de dados** no cartão do agente abre a memória. Adicione fatos
que devem persistir entre conversas — preferências, contexto do projeto,
convenções da equipe. Eles são incluídos nas instruções de sistema a cada conversa.

### Agentes pré-configurados

- **Assistente Geral** — equilibrado, para o dia a dia.
- **Programador** — temperatura baixa, focado em código correto e comentado.
- **Analista de Documentos** — responde apenas com base no contexto RAG e cita as
  fontes.

---

## Plugins

Plugins estendem o sistema interceptando eventos.

**Instalação:** coloque a pasta do plugin em `plugins/` e clique em **Reexaminar**,
ou use **Instalar .zip**. Depois clique em **Ativar**.

> Plugins executam código Python no mesmo processo do servidor. Instale apenas
> pacotes de origem confiável.

O **marketplace local** lê `plugins/_marketplace/catalogo.json` — um arquivo que
você mantém, sem qualquer acesso à rede.

Um plugin que falhe ao carregar é automaticamente desativado, e o erro aparece no
seu cartão.

---

## Painel e Monitor

O **Painel** resume o estado do sistema: uso de CPU, memória, disco e GPU, gráfico
de recursos em tempo real, contagens de conteúdo, motores de inferência instalados
e situação dos recursos extras.

O **Monitor** aprofunda: medidores radiais, histórico dos últimos 60 segundos, uso
por núcleo de CPU, detalhes de memória e swap, temperatura e informações das placas
gráficas.

---

## Logs

Registra eventos do servidor com filtros por nível, origem e texto. Útil para
entender por que um documento falhou ao indexar ou por que um plugin não carregou.

Apenas administradores podem limpar os logs.

---

## Configurações

- **Aparência** — tema escuro ou claro e tamanho da fonte do chat.
- **Conta** — troca de senha e chaves de API.
- **Backup** — criação, download, restauração e exclusão.
- **Servidor** e **Recursos extras** — informações de diagnóstico.

### Chaves de API

Para integrar suas próprias ferramentas com o LocalAI Studio, crie uma chave em
**Configurações → Chaves de API**. Use-a no cabeçalho `X-API-Key`. A chave completa
é exibida **uma única vez** — o servidor guarda apenas o hash.

### Backup

Um backup contém banco, configurações, plugins e documentos — modelos ficam de fora
por serem grandes e re-obteníveis. Backups automáticos rodam a cada 24 horas e os
10 mais recentes são mantidos.

**Restaurar substitui o estado atual.** Antes de fazê-lo, o sistema cria
automaticamente um backup de segurança, e o servidor precisa ser reiniciado depois.

---

## Atalhos de teclado

| Atalho | Ação |
|---|---|
| `Enter` | Enviar mensagem |
| `Shift + Enter` | Quebrar linha |
| `Ctrl/Cmd + K` | Focar na pesquisa de conversas |
| `Ctrl/Cmd + N` | Nova conversa |
| `Ctrl/Cmd + B` | Mostrar/ocultar a barra lateral |
| `Esc` | Fechar modal · interromper geração |

---

## Privacidade

Nada sai do seu computador. Modelos, documentos, conversas e embeddings ficam no
disco local. Não há telemetria nem chamadas a serviços externos — a única conexão
de rede possível é o download de um modelo, e apenas quando você o solicita
explicitamente.
