# LocalAI Studio

**Plataforma de inteligência artificial local — 100% offline, para Windows, Linux e macOS.**

Converse com modelos de linguagem rodando no seu próprio computador, indexe seus
documentos, crie agentes com memória e estenda tudo com plugins. Nada sai da sua
máquina: não há telemetria, nem chamada de API externa, nem dependência de nuvem.

---

## Sumário

- [O que já funciona](#o-que-já-funciona)
- [Instalação rápida](#instalação-rápida)
- [Primeiro modelo](#primeiro-modelo)
- [Arquitetura](#arquitetura)
- [Dependências opcionais](#dependências-opcionais)
- [Docker](#docker)
- [Configuração](#configuração)
- [API](#api)
- [Testes](#testes)
- [Documentação](#documentação)

---

## O que já funciona

### Chat
Conversas ilimitadas com streaming token a token via WebSocket, Markdown renderizado,
realce de sintaxe, cópia de blocos de código, edição de mensagem com regeneração,
regeneração de resposta, exportação (Markdown, JSON, texto), busca global no histórico,
fixação e arquivamento de conversas.

### Modelos
Importação de GGUF, safetensors e ONNX; leitura dos metadados técnicos direto do
cabeçalho GGUF (arquitetura, quantização, contagem de parâmetros, janela de contexto)
sem carregar os pesos; download por URL com progresso e retomada; carga e descarga
sob demanda com cache LRU; controle de temperatura, top-p, top-k, semente,
penalidade de repetição e tamanho máximo de resposta.

### RAG
Importação de **PDF, DOCX, TXT, HTML, Markdown, CSV e JSON**; divisão recursiva em
trechos com sobreposição; embeddings automáticos; índice vetorial FAISS, ChromaDB
ou NumPy; busca semântica com citação da fonte (documento e página) na resposta;
coleções para separar bases por assunto; reconstrução do índice a partir do banco.

### Agentes
Persona, avatar, instruções de sistema, parâmetros próprios, modelo padrão,
memória permanente entre conversas e ferramentas (calculadora com avaliação segura
por AST, data/hora, busca na base de documentos, informações do sistema, listagem
de modelos).

### Plugins
Instalação por `.zip` ou pasta, ativação e desativação a quente, marketplace local
em arquivo, cinco ganchos (`on_startup`, `on_shutdown`, `on_message`, `on_response`,
`on_document`). Um plugin com defeito é isolado e registrado — nunca derruba o servidor.

### Painel e monitor
CPU (total e por núcleo), memória, swap, disco, GPU (NVML, PyTorch ou `nvidia-smi`),
temperatura, tempo de atividade e contagens de conteúdo. Gráficos em tempo real via
WebSocket.

### Segurança
JWT com sessões revogáveis individualmente, hash de senha com bcrypt, proteção CSRF
(double submit cookie assinado), rate limit por IP em janela deslizante, CSP restrita,
cabeçalhos anti-XSS e anti-clickjacking, chaves de API com escopo, papéis de usuário,
backup automático com restauração reversível.

### Extras
OCR, transcrição de voz, texto para voz, geração de imagens local e aplicativo
desktop — todos com dependências opcionais e degradação elegante quando ausentes.

---

## Instalação rápida

**Requisitos:** Python 3.10 ou superior.

```bash
python install.py
```

O instalador cria o ambiente virtual, instala o núcleo, pergunta quais recursos
opcionais você quer e inicializa o banco. **Anote a senha do administrador exibida
ao final** — ela é gerada aleatoriamente e mostrada uma única vez.

```bash
.venv/bin/python start.py          # Linux e macOS
.venv\Scripts\python start.py      # Windows
```

Abra <http://127.0.0.1:8080>.

### Modos de execução

```bash
python start.py                 # servidor local (padrão)
python start.py --navegador     # abre o navegador automaticamente
python start.py --desktop       # janela nativa (requer PySide6)
python start.py --host 0.0.0.0  # acessível na rede local
python start.py --sem-auth      # usuário único, sem login (uso local)
python start.py --portatil      # modo portátil
python start.py --reload        # desenvolvimento
```

---

## Primeiro modelo

O sistema sobe e funciona sem nenhum modelo instalado — o chat responde em **modo
diagnóstico**, o que permite validar toda a cadeia antes de baixar gigabytes.

Para conversar de verdade:

```bash
# 1. Instale o motor de inferência
.venv/bin/pip install llama-cpp-python

# 2. Coloque um arquivo .gguf na pasta models/
cp ~/Downloads/meu-modelo.Q4_K_M.gguf models/
```

Depois, em **Modelos → Reexaminar**, selecione o modelo no seletor abaixo da caixa
de mensagem e converse.

> Modelos quantizados em `Q4_K_M` costumam ser o melhor equilíbrio entre qualidade
> e memória para uso em CPU.

---

## Arquitetura

```
LocalAIStudio/
├── backend/
│   ├── main.py                 # aplicação FastAPI, middlewares e ciclo de vida
│   ├── config.py               # configuração (env > settings.yaml > padrão)
│   ├── api/
│   │   ├── deps.py             # autenticação (JWT, API key, cookie) e paginação
│   │   ├── routes/             # auth, chat, models, rag, agents, plugins, system, extras
│   │   └── ws/                 # WebSocket de chat e de métricas
│   ├── core/                   # segurança, middlewares, exceções, logging
│   ├── database/               # ORM (14 tabelas), sessão, seed
│   ├── schemas/                # contratos Pydantic de entrada e saída
│   └── services/
│       ├── chat.py             # orquestra prompt + RAG + agente + modelo
│       ├── llm/                # backends, gerenciador LRU, leitor GGUF, downloads
│       ├── rag/                # carregadores, chunking, embeddings, índice, pipeline
│       ├── agents/             # serviço e ferramentas
│       ├── plugins/            # descoberta, instalação, ganchos, marketplace
│       ├── system/             # monitor de recursos
│       ├── backup/             # backup e restauração
│       └── extras/             # OCR, voz, imagens
├── frontend/                   # interface (HTML5, CSS3, JavaScript ES6, sem build)
├── desktop/                    # aplicativo PySide6
├── docker/                     # Dockerfile e docker-compose.yml
├── tests/                      # 118 testes automatizados
├── docs/                       # manuais e guias
├── models/ documents/ plugins/ database/ logs/ backups/ …
├── install.py  start.py  requirements.txt
```

### Decisões de projeto

**Sem CDN, sem etapa de build.** O requisito de operação offline é levado a sério:
Markdown, realce de sintaxe e gráficos são implementações próprias em
`frontend/js/`. Não há `npm install`, nem bundler, nem recurso remoto — a interface
é servida como arquivos estáticos e funciona em uma máquina sem rede.

**Dependências pesadas são opcionais e importadas sob demanda.** `llama-cpp-python`,
`torch`, `faiss`, `sentence-transformers` e afins são carregados apenas quando de
fato usados. O servidor sobe em segundos com o núcleo mínimo, e cada recurso
ausente informa exatamente o comando de instalação.

**Degradação elegante em vez de falha.** Sem modelo, o chat entra em modo
diagnóstico. Sem `sentence-transformers`, os embeddings caem para hashing de
n-gramas (busca lexical, sinalizada na interface). Sem FAISS, o índice usa NumPy.
O sistema sempre funciona; o que muda é a qualidade.

**O banco é a fonte da verdade do RAG.** O índice vetorial é sempre derivável da
tabela `embeddings` e pode ser reconstruído a qualquer momento — trocar de backend
vetorial ou recuperar de uma corrupção é uma operação de um clique.

---

## Dependências opcionais

| Recurso | Instalação |
|---|---|
| Modelos GGUF (llama.cpp) | `pip install llama-cpp-python` |
| Modelos HuggingFace | `pip install transformers torch safetensors` |
| Modelos ONNX | `pip install onnxruntime` |
| Embeddings semânticos | `pip install sentence-transformers` |
| Índice FAISS | `pip install faiss-cpu` |
| ChromaDB | `pip install chromadb` |
| Leitura de PDF | `pip install pypdf` |
| Leitura de DOCX | `pip install python-docx` |
| Leitura de HTML | `pip install beautifulsoup4` |
| OCR | `pip install pytesseract Pillow pdf2image` + binário `tesseract` |
| Transcrição de voz | `pip install faster-whisper` |
| Texto para voz | `pip install pyttsx3` |
| Geração de imagens | `pip install diffusers torch accelerate` |
| Aplicativo desktop | `pip install PySide6` |

O painel e a página de Configurações mostram, em tempo real, o que está disponível.

---

## Docker

```bash
docker compose -f docker/docker-compose.yml up -d --build
docker compose -f docker/docker-compose.yml logs localai   # senha do admin
```

A imagem já inclui `llama-cpp-python`, `sentence-transformers`, `faiss-cpu` e os
leitores de documento. Dados persistem em `docker/dados/`; a pasta `models/` do
projeto é montada diretamente.

---

## Configuração

Precedência: **variável de ambiente** > `config/settings.yaml` > padrão do código.
Todas as variáveis usam o prefixo `LAIS_`.

```bash
LAIS_PORT=9000
LAIS_N_GPU_LAYERS=35          # camadas descarregadas na GPU
LAIS_MAX_LOADED_MODELS=2      # modelos simultâneos em RAM
LAIS_CONTEXT_LENGTH=8192
LAIS_VECTOR_BACKEND=faiss     # faiss | chroma | numpy
LAIS_AUTH_REQUIRED=false      # usuário único, sem login
```

A chave JWT é gerada e persistida automaticamente em `config/settings.yaml` na
primeira execução, com permissão `600`.

---

## API

Documentação interativa em <http://127.0.0.1:8080/api/docs> (75 endpoints).

Principais rotas:

```
POST   /api/chat                 conversa (com streaming opcional via SSE)
POST   /api/generate             geração direta, sem persistência
GET    /api/models               modelos instalados
POST   /api/models/import        importar modelo
DELETE /api/models/{id}          remover modelo
POST   /api/embeddings           gerar embeddings
POST   /api/rag/search           busca semântica
POST   /api/upload               enviar e indexar documento
GET    /api/history              busca no histórico
POST   /api/agents               criar agente
GET    /api/plugins              plugins instalados
GET    /api/system               painel completo
WS     /ws/chat                  streaming token a token
WS     /ws/system                métricas em tempo real
```

Autenticação por `Authorization: Bearer <jwt>` ou `X-API-Key: lais_…`
(as chaves de API são criadas em **Configurações → Chaves de API**).

---

## Testes

```bash
.venv/bin/python -m pytest tests/ -q
```

118 testes cobrindo API, banco de dados, chat, streaming, embeddings, RAG,
modelos, agentes, ferramentas e plugins — incluindo casos de segurança
(travessia de diretório em pacotes de plugin, execução de código na calculadora,
isolamento entre usuários, obrigatoriedade de chaves estrangeiras).

---

## Documentação

| Documento | Conteúdo |
|---|---|
| [docs/instalacao.md](docs/instalacao.md) | Instalação em Linux, Windows, macOS e Docker |
| [docs/manual-do-usuario.md](docs/manual-do-usuario.md) | Guia completo da interface |
| [docs/api.md](docs/api.md) | Referência da API com exemplos |
| [docs/desenvolvedores.md](docs/desenvolvedores.md) | Arquitetura, extensão e criação de plugins |

---

## Licença

MIT.

Implementação original: código, arquitetura e identidade visual próprios. Modelos
de IA de terceiros mantêm suas respectivas licenças.
