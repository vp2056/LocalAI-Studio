PROMPT COMPLETO – LocalAI Studio
Objetivo
Crie um projeto completo chamado LocalAI Studio, uma plataforma de Inteligência Artificial totalmente offline para Linux desktop, web site, app moblie android . O sistema deve possuir uma interface web moderna para conversar com modelos de IA locais, gerenciar modelos, documentos e agentes, inspirando-se nas funcionalidades de ferramentas populares de IA local, mas com identidade visual, arquitetura, código e interface originais.

Requisitos Gerais
Desenvolva um projeto completo e profissional.
O código deve ser organizado, documentado e modular.
Todo o sistema deve funcionar sem Internet após a instalação.
Arquitetura escalável.
Código limpo.
Comentários em português.
Sistema preparado para milhares de conversas.

Tecnologias
Backend
    • Python 3.12+
    • FastAPI
    • Uvicorn
    • SQLAlchemy
    • SQLite3
    • WebSocket
    • JWT
    • Pydantic
    • aiofiles
    • requests
    • psutil
    • watchdog
IA
    • llama.cpp
    • Transformers
    • GGUF
    • safetensors
    • ONNX Runtime
    • Sentence Transformers
Banco Vetorial
    • FAISS
    • ChromaDB
Frontend
    • HTML5
    • CSS3
    • JavaScript ES6
    • Bootstrap ou Tailwind
    • Markdown
    • Highlight.js
    • Chart.js

Estrutura
LocalAIStudio/

backend/
frontend/
database/
models/
documents/
plugins/
logs/
config/
uploads/
downloads/
temp/
backups/
tests/
docker/

README.md
requirements.txt
install.py
start.py

Funcionalidades
Chat
    • Chat ilimitado
    • Markdown
    • Código destacado
    • Streaming
    • Copiar resposta
    • Editar mensagem
    • Regenerar resposta
    • Exportar conversa
    • Pesquisar conversas
    • Fixar chats

Modelos
    • Importar GGUF
    • Importar safetensors
    • Baixar modelos
    • Excluir modelos
    • Atualizar modelos
    • Informações técnicas
    • Uso de RAM
    • Uso de GPU
    • Tokens
    • Contexto
    • Temperatura
    • Top-P
    • Top-K
    • Seed

RAG
Importar:
    • PDF
    • DOCX
    • TXT
    • HTML
    • Markdown
    • CSV
    • JSON
Criar embeddings automaticamente.
Pesquisa semântica.
Indexação automática.

Agentes
Criar agentes personalizados.
Cada agente possui:
    • Nome
    • Avatar
    • Prompt
    • Memória
    • Ferramentas
    • Temperatura
    • Modelo padrão

Plugins
Sistema completo.
Instalar.
Remover.
Atualizar.
Ativar.
Desativar.
Marketplace local.

API
POST /chat
POST /generate
GET /models
POST /models/import
DELETE /models
POST /embeddings
POST /rag/search
POST /upload
GET /history
POST /agents
GET /plugins
GET /system

Banco SQLite
Criar automaticamente:
users
models
agents
messages
conversations
embeddings
documents
plugins
downloads
settings
logs
sessions
api_keys
favorites

Interface
Menu lateral.
Página inicial.
Chat.
Gerenciador de modelos.
Documentos.
RAG.
Agentes.
Plugins.
Monitor do sistema.
Logs.
Configurações.
Backup.
Ajuda.

Dashboard
Mostrar:
Uso da CPU
Uso da RAM
Uso da GPU
Temperatura
Espaço em disco
Quantidade de modelos
Conversas
Documentos
Embeddings
Plugins

Segurança
JWT
Hash de senha
Permissões
Backup automático
Logs
Proteção CSRF
Proteção XSS
Rate Limit

Recursos Extras
OCR
Reconhecimento de voz
Texto para voz
Imagem para texto
Gerador de imagens com modelos locais
Editor de Prompt
Memória permanente
Importação de modelos
Exportação completa
Sincronização LAN
Modo servidor
Modo desktop
Modo portátil

Desktop
Criar versão usando:
    • PySide6 ou Electron

Docker
Criar:
Dockerfile
docker-compose.yml
Instalação automática.

Instalador
Criar scripts para:

Linux
Instalar dependências automaticamente.

Documentação
Gerar:
README.md
Manual de instalação
Manual do usuário
Documentação da API
Guia para desenvolvedores

Testes
Criar testes automatizados para:
API
Banco de dados
Chat
Embeddings
Plugins
Modelos
RAG

Resultado Esperado
O projeto deve ser completo, modular, responsivo, offline, bem documentado e pronto para evolução futura, utilizando apenas implementações originais e sem copiar código, interface ou identidade visual de softwares existentes. Deve oferecer uma experiência moderna para execução e gerenciamento de modelos de IA locais.

Build the executable
linux desktop .deb 
web site
app moblie android . apk 
