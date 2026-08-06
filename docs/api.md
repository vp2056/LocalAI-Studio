# Documentação da API

Referência da API REST e WebSocket do LocalAI Studio.

Base: `http://127.0.0.1:8080/api`
Documentação interativa: <http://127.0.0.1:8080/api/docs>

---

## Autenticação

Três formas, verificadas nesta ordem:

| Método | Cabeçalho | Uso |
|---|---|---|
| Chave de API | `X-API-Key: lais_…` | Integrações e scripts |
| Token JWT | `Authorization: Bearer <jwt>` | Clientes e a própria interface |
| Cookie | `lais_token` (HttpOnly) | Navegador |

Com `LAIS_AUTH_REQUIRED=false` (modo de usuário único) a autenticação é dispensada.

### Obtendo um token

```bash
curl -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"SUA_SENHA"}'
```

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_at": "2026-08-10T17:24:00Z",
  "user": { "id": 1, "username": "admin", "role": "admin" }
}
```

### Chave de API

Crie em **Configurações → Chaves de API** ou via `POST /api/auth/api-keys`. A chave
é retornada **uma única vez**; o servidor guarda apenas o hash. Chaves não sofrem
verificação CSRF, por não dependerem de cookie.

### CSRF

Requisições que alteram estado e se autenticam por cookie precisam do cabeçalho
`X-CSRF-Token`, com o valor do cookie `lais_csrf`. Clientes que usam `Bearer` ou
`X-API-Key` estão isentos.

---

## Convenções

**Respostas paginadas** usam o envelope:

```json
{ "items": [], "total": 120, "page": 1, "per_page": 50, "pages": 3 }
```

**Erros** seguem o formato:

```json
{ "detail": "Modelo 'llama-3' não está registrado.", "code": "modelo_nao_encontrado" }
```

| Código HTTP | Significado |
|---|---|
| `403` | Não autenticado, sessão expirada ou sem permissão |
| `404` | Recurso não encontrado |
| `409` | Conflito de estado (ex.: nenhum modelo carregado) |
| `422` | Dados inválidos — inclui a lista `errors` com campo e motivo |
| `429` | Rate limit — veja o cabeçalho `Retry-After` |
| `503` | Dependência opcional ausente — a mensagem traz o comando de instalação |

**Rate limit:** 240 requisições por minuto por IP, por padrão. Cada resposta traz
`X-RateLimit-Limit` e `X-RateLimit-Remaining`.

---

## Chat

### `POST /api/chat`

Envia uma mensagem e recebe a resposta.

```json
{
  "mensagem": "Explique o que é RAG.",
  "conversation_id": 12,
  "modelo": "llama-3-8b-instruct.Q4_K_M",
  "agent_id": 3,
  "usar_rag": true,
  "stream": false,
  "params": { "temperature": 0.7, "max_tokens": 1024 }
}
```

Apenas `mensagem` é obrigatório. Sem `conversation_id`, uma conversa nova é criada.

```json
{
  "content": "RAG combina busca em documentos com geração de texto…",
  "model": "llama-3-8b-instruct.Q4_K_M",
  "conversation_id": 12,
  "user_message_id": 45,
  "assistant_message_id": 46,
  "tokens": 187,
  "duration_ms": 4210,
  "tokens_per_second": 44.4,
  "sources": [
    { "index": 1, "document_id": 3, "title": "manual.pdf",
      "score": 0.82, "page": 14, "excerpt": "A recuperação aumentada…" }
  ]
}
```

Com `"stream": true`, a resposta é **Server-Sent Events**:

```
data: {"type":"sources","sources":[…]}
data: {"type":"start","message_id":46,"model":"llama-3"}
data: {"type":"token","content":"RAG"}
data: {"type":"token","content":" combina"}
data: {"type":"done","tokens":187,"tokens_per_second":44.4}
data: [DONE]
```

### `POST /api/generate`

Geração direta, sem conversa nem persistência.

```json
{ "prompt": "Resuma em uma frase: …", "system": "Você é conciso.",
  "modelo": "llama-3", "params": { "temperature": 0.2 } }
```

### Conversas

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/conversations` | Lista (aceita `busca`, `arquivadas`, `fixadas`, `page`, `per_page`) |
| `POST` | `/conversations` | Cria |
| `GET` | `/conversations/{id}` | Detalhe com todas as mensagens |
| `PATCH` | `/conversations/{id}` | Renomeia, fixa, arquiva, reconfigura |
| `DELETE` | `/conversations/{id}` | Exclui (cascata nas mensagens) |
| `GET` | `/conversations/{id}/export` | Exporta (`formato`: `markdown`, `json`, `txt`) |
| `GET` | `/conversations/{id}/messages` | Mensagens (cursor: `antes_de`, `limite`) |

### Mensagens

| Método | Rota | Descrição |
|---|---|---|
| `PATCH` | `/messages/{id}` | Edita; com `regenerar: true` descarta o que veio depois |
| `POST` | `/messages/{id}/regenerate` | Gera outra resposta |
| `DELETE` | `/messages/{id}` | Exclui |
| `GET` | `/history` | Busca global em todas as mensagens |

---

## Modelos

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/models` | Lista (`incluir_indisponiveis`) |
| `POST` | `/models/scan` | Reexamina a pasta `models/` |
| `GET` | `/models/status` | Modelos em memória e motores disponíveis |
| `GET` | `/models/{id}` | Metadados técnicos completos |
| `PATCH` | `/models/{id}` | Edita descrição, contexto, padrão |
| `POST` | `/models/import` | Importa por caminho no disco |
| `POST` | `/models/upload` | Envia arquivo (multipart) |
| `DELETE` | `/models/{id}` | Remove (`apagar_arquivo`) |
| `POST` | `/models/{id}/load` | Carrega em memória |
| `POST` | `/models/{id}/unload` | Descarrega |
| `POST` | `/models/download` | Baixa por URL (assíncrono) |
| `GET` | `/models/downloads/list` | Progresso dos downloads |
| `POST` | `/models/downloads/{id}/cancel` | Cancela |

```bash
curl -X POST http://127.0.0.1:8080/api/models/import \
  -H "X-API-Key: lais_…" -H 'Content-Type: application/json' \
  -d '{"caminho":"/dados/modelos/llama-3-8b.Q4_K_M.gguf","copiar":false}'
```

---

## RAG e documentos

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/upload` | Envia e indexa (multipart: `arquivo`, `colecao`, `indexar`) |
| `GET` | `/documents` | Lista (`colecao`, `status`, `busca`) |
| `GET` | `/documents/{id}` | Detalhe |
| `POST` | `/documents/{id}/reindex` | Reprocessa |
| `DELETE` | `/documents/{id}` | Remove documento e vetores |
| `GET` | `/documents/collections/list` | Coleções com contagens |
| `POST` | `/rag/search` | Busca semântica |
| `POST` | `/rag/rebuild` | Reconstrói o índice a partir do banco |
| `POST` | `/rag/import-folder` | Importa uma pasta inteira |
| `GET` | `/rag/stats` | Estatísticas da base |
| `POST` | `/embeddings` | Gera vetores para textos |

```bash
curl -X POST http://127.0.0.1:8080/api/upload \
  -H "X-API-Key: lais_…" \
  -F "arquivo=@manual.pdf" -F "colecao=manuais"
```

```bash
curl -X POST http://127.0.0.1:8080/api/rag/search \
  -H "X-API-Key: lais_…" -H 'Content-Type: application/json' \
  -d '{"consulta":"política de backup","k":5,"colecoes":["manuais"]}'
```

```json
[
  { "embedding_id": 812, "score": 0.78, "content": "O backup automático…",
    "document_id": 3, "document_title": "manual.pdf",
    "collection": "manuais", "meta": { "page": 14 } }
]
```

---

## Agentes

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/agents` | Lista (`apenas_ativos`) |
| `POST` | `/agents` | Cria |
| `GET` | `/agents/tools` | Catálogo de ferramentas |
| `GET` | `/agents/{id}` | Detalhe |
| `PATCH` | `/agents/{id}` | Edita |
| `DELETE` | `/agents/{id}` | Exclui |
| `POST` | `/agents/{id}/duplicate` | Duplica |
| `POST` | `/agents/{id}/memory` | Memoriza um fato |
| `DELETE` | `/agents/{id}/memory` | Esquece (`indice` ou tudo) |

---

## Plugins

| Método | Rota | Permissão |
|---|---|---|
| `GET` | `/plugins` | usuário |
| `POST` | `/plugins/scan` | administrador |
| `GET` | `/plugins/marketplace` | usuário |
| `GET` | `/plugins/status` | usuário |
| `POST` | `/plugins/install` | administrador |
| `POST` | `/plugins/{slug}/enable` | administrador |
| `POST` | `/plugins/{slug}/disable` | administrador |
| `PATCH` | `/plugins/{slug}/config` | administrador |
| `DELETE` | `/plugins/{slug}` | administrador |

---

## Sistema

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/health` | Disponibilidade (sem autenticação) |
| `GET` | `/system` | Painel completo |
| `GET` | `/system/monitor` | Recursos (`completo=true` para detalhes) |
| `GET` | `/system/stats` | Contagens |
| `GET` | `/settings` | Configurações persistidas |
| `PUT` | `/settings/{chave}` | Grava uma configuração |
| `GET` | `/settings/runtime/config` | Configuração efetiva (sem segredos) |
| `GET` | `/logs` | Logs (`nivel`, `origem`, `busca`) |
| `DELETE` | `/logs` | Limpa (administrador) |
| `GET` | `/favorites` | Favoritos |
| `POST` | `/favorites` | Favorita |
| `DELETE` | `/favorites/{id}` | Desfavorita |
| `GET` | `/backup` | Lista backups |
| `POST` | `/backup` | Cria (administrador) |
| `GET` | `/backup/{nome}/download` | Baixa (administrador) |
| `POST` | `/backup/{nome}/restore` | Restaura (administrador) |
| `DELETE` | `/backup/{nome}` | Exclui (administrador) |

---

## Extras

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/extras/status` | Disponibilidade de cada recurso |
| `POST` | `/extras/ocr` | Texto de imagem ou PDF digitalizado |
| `POST` | `/extras/transcribe` | Transcreve áudio |
| `POST` | `/extras/tts` | Texto para voz (devolve `.wav`) |
| `GET` | `/extras/tts/voices` | Vozes disponíveis |
| `POST` | `/extras/images/generate` | Gera imagem |
| `GET` | `/extras/images/models` | Modelos de difusão instalados |

Recursos não instalados respondem `503` com o comando de instalação na mensagem.

---

## WebSocket

### `/ws/chat?token=<jwt>`

O navegador não permite cabeçalhos no handshake, então o token vai na query string.

**Cliente envia:**

```json
{ "type": "chat", "mensagem": "…", "conversation_id": 12,
  "modelo": "llama-3", "usar_rag": true, "params": {} }
{ "type": "stop" }
{ "type": "ping" }
```

**Servidor envia:**

| Evento | Conteúdo |
|---|---|
| `conversation` | `conversation_id` da conversa recém-criada |
| `sources` | Trechos RAG recuperados |
| `start` | `message_id`, `user_message_id`, `model` |
| `token` | `content` — fragmento de texto |
| `done` | `tokens`, `duration_ms`, `tokens_per_second`, `title` |
| `stopped` | Geração interrompida pelo cliente |
| `error` | `error` — mensagem de falha |
| `pong` | Resposta ao `ping` |

### `/ws/system?token=<jwt>`

Emite métricas a cada segundo:

```json
{ "type": "metrics", "data": {
    "cpu_percent": 34.2, "memory_percent": 61.8, "memory_used_gb": 9.9,
    "disk_percent": 42.1, "gpu_percent": 78, "gpu_memory_percent": 65,
    "temperature_c": 58.0, "uptime_seconds": 8412 } }
```

---

## Exemplo em Python

```python
import requests

BASE = "http://127.0.0.1:8080/api"
CABECALHOS = {"X-API-Key": "lais_sua_chave_aqui"}

# Indexa um documento
with open("manual.pdf", "rb") as f:
    requests.post(
        f"{BASE}/upload",
        headers=CABECALHOS,
        files={"arquivo": f},
        data={"colecao": "manuais"},
    ).raise_for_status()

# Pergunta com RAG
resposta = requests.post(
    f"{BASE}/chat",
    headers=CABECALHOS,
    json={"mensagem": "Qual é a política de backup?", "usar_rag": True},
).json()

print(resposta["content"])
for fonte in resposta["sources"]:
    print(f"  [{fonte['index']}] {fonte['title']} p.{fonte['page']} ({fonte['score']})")
```

## Exemplo de streaming em Python

```python
import json
import requests

with requests.post(
    "http://127.0.0.1:8080/api/chat",
    headers={"X-API-Key": "lais_sua_chave_aqui"},
    json={"mensagem": "Escreva um haicai sobre servidores.", "stream": True},
    stream=True,
) as fluxo:
    for linha in fluxo.iter_lines(decode_unicode=True):
        if not linha or not linha.startswith("data: "):
            continue
        bruto = linha[6:]
        if bruto == "[DONE]":
            break
        evento = json.loads(bruto)
        if evento["type"] == "token":
            print(evento["content"], end="", flush=True)
```
