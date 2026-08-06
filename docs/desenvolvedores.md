# Guia para desenvolvedores

Arquitetura interna, convenções e como estender o LocalAI Studio.

---

## Ambiente de desenvolvimento

```bash
python install.py --completo
.venv/bin/python start.py --reload --debug
```

`--reload` reinicia o servidor a cada alteração no backend. O frontend não tem
etapa de build: basta recarregar o navegador (`Ctrl+Shift+R` para ignorar o cache).

```bash
.venv/bin/python -m pytest tests/ -q          # suíte completa
.venv/bin/python -m pytest tests/test_rag.py -v
```

---

## Estrutura em camadas

```
Rotas (api/routes)          contratos HTTP, validação, autorização
      ↓
Serviços (services)         regras de negócio, sem conhecer HTTP
      ↓
ORM (database/models)       persistência
```

Regras que a base segue:

- **Rotas não contêm lógica de negócio.** Elas validam entrada, chamam um serviço
  e serializam a saída. Se uma rota está ficando longa, a lógica pertence a um serviço.
- **Serviços não importam FastAPI.** Isso os mantém testáveis e reutilizáveis pelo
  WebSocket, por tarefas de fundo e pela CLI.
- **Dependências pesadas são importadas dentro da função que as usa**, nunca no topo
  do módulo. É o que permite ao servidor subir sem `torch` instalado.

### Instâncias únicas

Serviços com estado são exportados como instância única no fim do módulo:

```python
from backend.services.llm.manager import gerenciador
from backend.services.rag.pipeline import pipeline
from backend.services.plugins.manager import gerenciador_plugins
from backend.services.system.monitor import monitor
from backend.services.chat import servico_chat
```

---

## Sessões de banco

Dois padrões, conforme o contexto:

```python
# Dentro de uma rota — a dependência gerencia o ciclo de vida
from backend.api.deps import BancoDados

@router.get("/exemplo")
def exemplo(db: BancoDados):
    ...

# Fora do ciclo de requisição — commit ao sair, rollback em exceção
from backend.database.session import sessao

with sessao() as db:
    db.add(objeto)
```

> **Atenção com campos JSON.** O SQLAlchemy não detecta mutação em listas e dicts.
> Reatribua sempre: `agente.memory = nova_lista`, nunca `agente.memory.append(...)`.

---

## Adicionando um backend de inferência

Implemente `BackendLLM` em `backend/services/llm/backends.py`:

```python
class MeuBackend(BackendLLM):
    nome = "meu_backend"
    formatos = ("meuformato",)

    @classmethod
    def disponivel(cls) -> bool:
        """Verifica a dependência sem importá-la (find_spec)."""
        return find_spec("minha_lib") is not None

    def carregar(self) -> None:
        if self._carregado:
            return
        if not self.disponivel():
            raise BackendIndisponivel(
                "Requer minha_lib. Execute: pip install minha-lib"
            )
        import minha_lib          # import tardio, aqui dentro
        self._modelo = minha_lib.load(self.info.path)
        self._carregado = True

    def descarregar(self) -> None:
        self._modelo = None
        self._carregado = False

    def gerar(self, mensagens, params):
        self.carregar()
        for pedaco in self._modelo.stream(...):
            yield pedaco          # fragmentos de texto, não tokens brutos
```

Registre em `BACKENDS` e adicione o formato a `backend_para_formato`. O gerenciador
cuida do restante: cache LRU, contagem de uso, integração com o chat.

---

## Adicionando uma ferramenta de agente

```python
# backend/services/agents/tools.py

@ferramenta(
    "converter_unidade",
    "Converte entre unidades de medida.",
    {
        "valor": {"type": "number", "description": "Valor a converter"},
        "de": {"type": "string", "description": "Unidade de origem"},
        "para": {"type": "string", "description": "Unidade de destino"},
    },
)
def converter_unidade(valor: float, de: str, para: str) -> str:
    ...
    return f"{valor} {de} = {resultado} {para}"
```

A ferramenta aparece automaticamente no editor de agentes e em `GET /api/agents/tools`.

**Regras de segurança:** ferramentas nunca acessam a rede, nunca leem fora dos
diretórios do projeto e nunca executam código arbitrário. A calculadora é o
exemplo de referência — avalia expressões pela AST, com lista branca de operadores
e teto de expoente, em vez de `eval()`.

---

## Adicionando um formato de documento

```python
# backend/services/rag/loaders.py

def carregar_epub(caminho: Path) -> tuple[str, dict[str, Any]]:
    """Extrai o texto de um EPUB."""
    try:
        import ebooklib
    except ImportError as exc:
        raise ArquivoInvalido(
            "Leitura de EPUB requer 'ebooklib'. Execute: pip install ebooklib"
        ) from exc
    ...
    return texto, {"capitulos": n}

CARREGADORES[".epub"] = carregar_epub
```

Acrescente a extensão a `allowed_document_ext` em `config.py`.

---

## Escrevendo um plugin

Estrutura mínima:

```
plugins/meu_plugin/
├── plugin.json
└── __init__.py
```

```json
{
  "slug": "meu_plugin",
  "name": "Meu Plugin",
  "version": "1.0.0",
  "author": "Você",
  "description": "O que ele faz",
  "hooks": ["on_message", "on_response"],
  "permissions": []
}
```

```python
def on_startup(**contexto):
    """Servidor iniciando."""

def on_shutdown(**contexto):
    """Servidor encerrando."""

def on_message(texto: str, **contexto) -> str:
    """Transforma a entrada do usuário. Devolva o texto (ou None p/ manter)."""
    return texto.replace(":brb:", "volto já")

def on_response(texto: str, **contexto) -> str:
    """Transforma a resposta do modelo."""
    return texto

def on_document(documento, **contexto):
    """Chamado após um documento ser indexado."""
```

O `contexto` traz `conversa_id` nos ganchos de mensagem e resposta.

**Comportamento garantido:** exceções são capturadas e registradas; um plugin com
defeito é desativado automaticamente e nunca interrompe uma conversa. Ganchos
transformadores são encadeados na ordem de carregamento.

**Cuidados:** `on_message` roda no caminho crítico da resposta — evite trabalho
pesado ali. Plugins compartilham o processo do servidor: não há sandbox.

Veja `plugins/exemplo_saudacao/` para um exemplo completo e comentado.

---

## Frontend

Sem framework, sem build, sem dependências externas — requisito de operação offline.

| Arquivo | Responsabilidade |
|---|---|
| `api.js` | Cliente HTTP e WebSocket; único ponto que fala com o backend |
| `ui.js` | Avisos, modais, formatação, helpers de DOM |
| `markdown.js` | Renderizador de Markdown e realce de sintaxe |
| `graficos.js` | Gráficos em canvas (linha, barras, medidor) |
| `icones.js` | Ícones SVG inline |
| `chat.js` | Chat e streaming |
| `paginas.js` | Demais páginas |
| `app.js` | Navegação, tema, atalhos, autenticação |

### Adicionando uma página

1. Acrescente o item de navegação e a `<section class="pagina">` no `index.html`.
2. Crie o módulo em `paginas.js` com `render(caixa)` e, se necessário, `sair()`
   para liberar timers e sockets.
3. Registre em `PAGINAS`, no `app.js`.

### Segurança no frontend

Todo texto vindo da API passa por `UI.esc()` ou pela propriedade `texto` de
`UI.el()`. O renderizador de Markdown escapa a entrada **antes** de qualquer
substituição por HTML, e links com esquemas perigosos (`javascript:`, `data:`)
são degradados para texto puro.

A propriedade `html` de `UI.el()` só deve receber conteúdo gerado internamente.

---

## Padrões de código

**Backend**

- Python 3.10+, tipagem moderna (`str | None`, não `Optional[str]`).
- `from __future__ import annotations` no topo de cada módulo.
- Docstrings e comentários em português.
- Nomes de domínio em português (`gerenciador`, `sessao`, `carregar`); nomes de
  API e de campos JSON em inglês, por serem contrato externo.
- Exceções de domínio em `core/exceptions.py`, com `status_code` próprio.

**Comentários**

Comentários explicam **por que**, não **o que**. O código já diz o que faz.

```python
# Ruim: incrementa o contador
contador += 1

# Bom: SQLite ignora chaves estrangeiras por padrão; sem este PRAGMA as
# cascatas declaradas no ORM não seriam aplicadas.
cursor.execute("PRAGMA foreign_keys=ON")
```

**Frontend**

- JavaScript ES6+, sem transpilação. IIFE por módulo, expondo apenas a superfície
  pública.
- CSS com variáveis de tema; nada de valores mágicos espalhados.

---

## Testes

```
tests/
├── conftest.py             fixtures: app, cliente, autenticado, admin, temp_dir
├── test_api.py             saúde, autenticação, validação, segurança
├── test_banco.py           esquema, restrições, cascatas
├── test_chat.py            conversas, mensagens, streaming, exportação
├── test_rag.py             carregadores, chunking, embeddings, índice
├── test_modelos.py         backends, GGUF, gerenciador
└── test_agentes_plugins.py agentes, ferramentas, plugins
```

Cada sessão de teste usa um banco e um diretório temporários — a instalação real
do usuário nunca é tocada.

Ao adicionar uma funcionalidade, cubra: o caminho feliz, a entrada inválida e o
comportamento quando a dependência opcional está ausente.

---

## Migrações

O projeto usa `create_all`, que cria tabelas novas mas **não altera as existentes**.

- **Coluna nova opcional:** funciona automaticamente em bancos novos; para bancos
  existentes, aplique um `ALTER TABLE` manual.
- **Mudança destrutiva:** oriente o usuário a fazer backup, e considere adotar
  Alembic se as migrações se tornarem frequentes.

Sempre teste contra um banco existente, não apenas contra um recém-criado.

---

## Desempenho

- **Geração bloqueia.** O WebSocket consome o gerador em um executor para não travar
  o event loop. Qualquer novo caminho de geração precisa fazer o mesmo.
- **O SQLite está em modo WAL**, permitindo leitura concorrente com escrita — é o
  que possibilita o monitor rodar durante o streaming.
- **A varredura de modelos toca o disco.** Na inicialização ela roda em thread
  separada (`asyncio.to_thread`).
- **O índice NumPy é O(n) por busca.** Acima de ~100 mil vetores, use FAISS.
- **Cache do monitor:** as métricas completas são cacheadas por ~1 s; o painel
  atualiza a cada segundo sem custo de CPU significativo.
