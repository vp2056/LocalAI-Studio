# Manual de instalação

Guia completo de instalação do LocalAI Studio em Linux, Windows, macOS e Docker.

---

## Requisitos

| Item | Mínimo | Recomendado |
|---|---|---|
| Python | 3.10 | 3.12 |
| RAM | 4 GB | 16 GB |
| Disco | 2 GB (sem modelos) | 50 GB |
| CPU | 2 núcleos | 8 núcleos com AVX2 |
| GPU | — | NVIDIA com 8 GB+ de VRAM |

O consumo real depende do modelo: um modelo de 7 bilhões de parâmetros
quantizado em `Q4_K_M` ocupa cerca de 4,5 GB de RAM; um de 13 B, cerca de 8 GB.

---

## Instalação guiada (todas as plataformas)

```bash
cd LocalAIStudio
python install.py
```

O instalador:

1. verifica a versão do Python;
2. cria a árvore de diretórios de trabalho;
3. cria o ambiente virtual em `.venv/`;
4. instala as dependências obrigatórias;
5. pergunta quais recursos opcionais instalar;
6. cria o banco e o usuário administrador.

> **Anote a senha exibida ao final.** Ela é aleatória e mostrada uma única vez.
> Se você a perder, apague `database/localai_studio.db` e execute
> `python -m backend.database.init_db` para gerar outra — as conversas serão perdidas.

Modos não interativos:

```bash
python install.py --minimo      # só o núcleo
python install.py --completo    # núcleo + todos os extras
python install.py --sem-venv    # instala no Python atual
```

---

## Linux

### Debian / Ubuntu

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip build-essential cmake git

# Opcionais, conforme os recursos que você for usar:
sudo apt install -y tesseract-ocr tesseract-ocr-por   # OCR
sudo apt install -y poppler-utils                     # OCR em PDF
sudo apt install -y espeak-ng                         # texto para voz
sudo apt install -y ffmpeg                            # transcrição de áudio

cd LocalAIStudio
python3 install.py
```

### Fedora / RHEL

```bash
sudo dnf install -y python3 python3-pip gcc gcc-c++ cmake git
sudo dnf install -y tesseract tesseract-langpack-por poppler-utils espeak-ng ffmpeg
python3 install.py
```

### Arch Linux

```bash
sudo pacman -S python python-pip base-devel cmake git tesseract tesseract-data-por poppler espeak-ng ffmpeg
python install.py
```

### Serviço systemd

Para iniciar o servidor junto com o sistema, crie
`/etc/systemd/system/localai-studio.service`:

```ini
[Unit]
Description=LocalAI Studio
After=network.target

[Service]
Type=simple
User=SEU_USUARIO
WorkingDirectory=/caminho/para/LocalAIStudio
ExecStart=/caminho/para/LocalAIStudio/.venv/bin/python start.py --host 0.0.0.0
Restart=on-failure
RestartSec=10

# Endurecimento: o serviço só precisa escrever na própria pasta.
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/caminho/para/LocalAIStudio

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now localai-studio
sudo journalctl -u localai-studio -f
```

---

## Windows

1. Instale o Python 3.12 de <https://www.python.org/downloads/>, marcando
   **“Add Python to PATH”** na primeira tela do instalador.
2. Instale o **Visual Studio Build Tools** com a carga de trabalho
   “Desenvolvimento para desktop com C++” — necessária para compilar
   `llama-cpp-python`.
3. No PowerShell:

```powershell
cd LocalAIStudio
python install.py
.venv\Scripts\python start.py
```

### Opcionais no Windows

- **OCR:** instale o Tesseract de
  <https://github.com/UB-Mannheim/tesseract/wiki> e adicione a pasta de
  instalação ao `PATH`.
- **Texto para voz:** funciona nativamente via `pyttsx3` (SAPI5).
- **Atalho na área de trabalho:** crie um atalho apontando para
  `.venv\Scripts\pythonw.exe start.py --desktop` — `pythonw` evita a janela
  de console.

---

## macOS

```bash
# Homebrew, se ainda não tiver
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install python@3.12 cmake
brew install tesseract tesseract-lang poppler ffmpeg   # opcionais

cd LocalAIStudio
python3 install.py
```

### Aceleração por GPU (Apple Silicon)

O `llama-cpp-python` compila com suporte a Metal quando instruído:

```bash
CMAKE_ARGS="-DGGML_METAL=on" .venv/bin/pip install --force-reinstall --no-cache-dir llama-cpp-python
```

Depois, defina `LAIS_N_GPU_LAYERS=999` para descarregar todas as camadas na GPU.

---

## Aceleração por GPU NVIDIA

```bash
# Requer o CUDA Toolkit instalado
CMAKE_ARGS="-DGGML_CUDA=on" .venv/bin/pip install --force-reinstall --no-cache-dir llama-cpp-python
```

Configure quantas camadas vão para a placa:

```bash
export LAIS_N_GPU_LAYERS=35    # ajuste conforme a VRAM disponível
```

Comece com um valor conservador e aumente até o limite da memória da GPU. O
painel do Monitor mostra o uso de VRAM em tempo real.

---

## Docker

```bash
docker compose -f docker/docker-compose.yml up -d --build

# Senha do administrador (primeira execução)
docker compose -f docker/docker-compose.yml logs localai | grep -A2 "PRIMEIRO ACESSO"
```

A imagem já traz `llama-cpp-python`, `sentence-transformers`, `faiss-cpu`, `pypdf`,
`python-docx` e `beautifulsoup4`.

**Volumes:** os dados persistem em `docker/dados/`. A pasta `models/` do projeto é
montada no contêiner — coloque seus arquivos `.gguf` ali.

**GPU:** instale o `nvidia-container-toolkit` e descomente o bloco `deploy.resources`
do `docker-compose.yml`.

---

## Verificação

```bash
# O servidor responde?
curl http://127.0.0.1:8080/api/health
# {"status":"ok","version":"1.0.0"}

# A suíte de testes passa?
.venv/bin/python -m pytest tests/ -q
# 118 passed
```

---

## Problemas comuns

**`llama-cpp-python` falha ao compilar**
Faltam ferramentas de build. Linux: `build-essential cmake`. Windows: Visual Studio
Build Tools com C++. macOS: `xcode-select --install`.

**“Porta 8080 ocupada”**
O `start.py` procura a próxima porta livre automaticamente e informa qual usou.
Para fixar outra: `python start.py --port 9000`.

**Modelo carrega mas responde muito devagar**
Verifique se o modelo cabe na RAM (Monitor → Memória). Se estiver usando swap, o
desempenho cai drasticamente — use uma quantização menor (`Q4_K_M` em vez de `Q8_0`).

**“A busca não encontra nada relevante”**
Sem `sentence-transformers`, a busca é lexical. Instale-o e reindexe:
`pip install sentence-transformers`, depois **Documentos → Reconstruir índice** e
reindexe cada documento.

**Esqueci a senha do administrador**
Não há recuperação por design (não há e-mail nem serviço externo). Com outra conta
de administrador é possível criar um novo usuário; caso contrário, apague
`database/localai_studio.db` — o histórico será perdido, mas modelos e documentos
permanecem.

**Permissão negada ao gravar em `config/`**
O arquivo `config/settings.yaml` guarda a chave JWT e recebe permissão `600`.
Rode o servidor com o mesmo usuário que executou a instalação.
