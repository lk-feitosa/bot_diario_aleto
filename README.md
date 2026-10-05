# 🤖 GhostWriter (Bot do Diário Oficial da ALETO)

Sistema autônomo que monitora diariamente as edições publicadas do Diário Oficial da **Assembleia Legislativa do Estado do Tocantins ([ALETO](https://www.al.to.leg.br/diario))**, processa os arquivos PDF com **PyMuPDF**, gera resumos completos e estruturados com inteligência artificial (**Google Gemini**) e dispara alertas prioritários imediatos caso seu nome ou termos de interesse sejam publicados.

---

## 🌟 Funcionalidades

- 🕒 **Monitoramento Automático:** Varredura periódica configurável (ex: a cada 30 min) no portal da ALETO.
- 📥 **Download e Extração Rápida:** Baixa e processa o PDF do diário preservando referências de páginas e atos.
- 🚨 **Alerta Nominal Imediato:** Detecta seu nome completo ou palavras-chave com exibição do **trecho exato**, **número do ato/decreto** e **página**.
- 🧠 **Resumo Inteligente por IA:** Gera um resumo executivo dividido em:
  - 🏛️ Atos Legislativos e Sessões Plenárias.
  - 👥 Recursos Humanos (Nomeações, Exonerações, Concessões).
  - 💼 Licitações, Contratos e Extratos.
  - 📑 Decretos e Portarias Administrativas.
- 💬 **Bot Interativo do Telegram:** Comandos para consultar resumos anteriores, adicionar/remover nomes monitorados e forçar verificação manual.
- 🐳 **Deploy Simplificado:** Pronto para rodar com Python local ou via Docker / Docker Compose.

---

## 🚀 Como Configurar e Rodar

### 1. Pré-requisitos
- Python 3.10+ (ou Docker)
- Token de Bot do Telegram (criado gratuitamente no [@BotFather](https://t.me/BotFather))
- Chave de API do Google Gemini (gratuita no [Google AI Studio](https://aistudio.google.com/app/apikey))

---

### 2. Configuração do Arquivo `.env`

Copie o modelo de variáveis de ambiente:
```bash
cp .env.example .env
```

Edite o arquivo `.env` com suas credenciais:
```env
# 1. Telegram
TELEGRAM_BOT_TOKEN="123456789:ABCdefGhIJKlmNoPQRstuVWXyz"
TELEGRAM_ADMIN_CHAT_ID=123456789  # Obtenha seu ID enviando mensagem para @userinfobot no Telegram

# 2. Google Gemini API
GEMINI_API_KEY="AIzaSyYourSecretGeminiKeyHere"
GEMINI_MODEL="gemini-2.5-flash"

# 3. Nomes ou Termos para Alerta Imediato
DEFAULT_WATCH_NAMES="Seu Nome Completo,Outro Nome Relevante"

# 4. Agendamento
CHECK_INTERVAL_MINUTES=30
TIMEZONE="America/Araguaina"
```

---

### 3. Executando Localmente com Python

1. **Crie e ative o ambiente virtual:**
```bash
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# ou venv\Scripts\activate no Windows
```

2. **Instale as dependências:**
```bash
pip install -r requirements.txt
```

3. **Inicie o robô:**
```bash
python -m src.main
```

---

### 4. Executando com Docker (ou Deploy no Render)

Se preferir rodar em um servidor (VPS, cloud) 24/7 de forma isolada:

```bash
docker compose up -d --build
```

Para acompanhar os logs:
```bash
docker compose logs -f
```

**Para Deploy no Render (Cloud):**
- O projeto contém um arquivo `render.yaml` pronto para deploy com Blueprint.
- Na plataforma Render, conecte o repositório e o Render configurará o serviço, incluindo o Healthcheck na porta 8080 e a montagem do disco persistente para o SQLite em `/app/data`.
- Lembre-se de configurar as variáveis de ambiente (como `TELEGRAM_BOT_TOKEN` e `GEMINI_API_KEY`) no dashboard do serviço.

---

## 📱 Comandos Disponíveis no Telegram

| Comando | Descrição |
| :--- | :--- |
| `/start` | Inicia o bot e cadastra o usuário para receber resumos |
| `/ultimo` | Exibe o resumo e link de download da última edição publicada |
| `/monitorar <nome>` | Adiciona um novo nome ou termo para receber alerta nominal |
| `/listar` | Lista todos os termos atualmente cadastrados para monitoramento |
| `/remover <nome>` | Remove um nome da sua lista de monitoramento |
| `/verificar` | Força uma varredura imediata no portal da ALETO |
| `/status` | Exibe o status da aplicação, total de edições e termos ativos |
| `/ajuda` | Mostra as instruções e lista de comandos |

---

## 📂 Estrutura do Código

```
diario_aleto/
├── .env.example              # Exemplo de configuração
├── requirements.txt          # Dependências Python
├── Dockerfile                # Imagem Docker
├── docker-compose.yml        # Docker Compose
├── data/                     # Diretório persistente (SQLite e PDFs)
└── src/
    ├── config.py             # Configurações com Pydantic
    ├── main.py               # Ponto de entrada e loop principal
    ├── database/             # Modelos e sessão do SQLite
    │   ├── models.py
    │   └── session.py
    ├── services/             # Lógica de negócio
    │   ├── scraper.py        # Coletor web da ALETO
    │   ├── pdf_processor.py  # Processamento de PDF (PyMuPDF)
    │   ├── alert_engine.py   # Busca e detecção de nomes/termos
    │   └── summarizer.py     # IA / Google Gemini API
    ├── bot/                  # Bot do Telegram
    │   ├── bot.py
    │   ├── handlers.py
    │   └── messages.py
    └── scheduler/            # Agendador de tarefas
        └── job.py
```

---

## 💡 Apêndice: Exemplos de Uso no Dia a Dia

Aqui estão alguns cenários de como o bot funciona na prática:

**Exemplo 1: Recebendo resumos diários**
> Ao receber a notificação automática ou enviar `/ultimo`, o bot devolverá uma mensagem dividida em seções claras (RH, Licitações, Atos), explicando exatamente o formato e contexto da publicação, sem que você precise abrir o PDF.

**Exemplo 2: Comandos experimentais / fluxo futuro**
> Comandos de fluxo avançado como `/alerts_quase_10` (serviços nas bifurcações-stream-tempo) não existem ativamente ainda, mas o bot já possui a arquitetura assíncrona base preparada para escalar com esse tipo de fluxo em novas atualizações.

> **Nota sobre Chaves e Acessos:** O bot é seguro e *server-side*. Fica claro aos usuários que as chaves da API (Gemini, Telegram) são atribuídas apenas no ambiente de *deployment* construído pelo administrador (no painel do Render/Docker), impossibilitando acesso cruzado de usuários finais.

---

## 📄 Licença
Projeto pessoal sob licença MIT.
