# 🎥 YT Downloader Pro (AI Generated)

![AI Generated](https://img.shields.io/badge/Code-Generated%20by%20AI-blueviolet)
![Python](https://img.shields.io/badge/Python-3.x-blue)
![Flask](https://img.shields.io/badge/Framework-Flask-green)

Este é um projeto de **Downloader de YouTube** com interface web moderna (Dark Mode), barra de progresso em tempo real e proteção contra bots via Cloudflare Turnstile.

> ⚠️ **DISCLAIMER: PROJETO GERADO POR IA**
>
> Este código foi inteiramente gerado através de interações com um Modelo de Linguagem Grande (LLM). Embora funcional, ele serve primariamente para fins educacionais e de prototipagem. Pode conter padrões que não seguem estritamente as melhores práticas de engenharia de software empresarial. Use por sua conta e risco.

---
## .env example
```bash
CF_SECRET_KEY=yourscretket
EXPECTED_HOSTNAME=example.com
FLASK_PORT=1234
FLASK_DEBUG=True
ADMIN_PASSWORD=my_password_secret
FLASK_SECRET_KEY=12345677898
```

## ✨ Funcionalidades

* **Downloads de Vídeo:** Suporte para 1080p, 720p e seleção automática da melhor qualidade.
* **Conversão de Áudio:** Extração e conversão automática para MP3.
* **Interface Moderna:** Design responsivo com tema escuro (Dark Mode) e Glassmorphism.
* **Barra de Progresso:** Feedback visual em tempo real do download e conversão.
* **Segurança:** Integração com **Cloudflare Turnstile** para evitar abuso por bots.
* **Manutenção Automática:** Sistema que atualiza o núcleo (`yt-dlp`) automaticamente a cada 24h.
* **Limpeza Automática:** Os arquivos são deletados do servidor logo após o download do usuário para economizar espaço.

---

## 🛠️ Pré-requisitos Obrigatórios

Para que o sistema funcione corretamente (especialmente áudio e 1080p), você precisa ter instalado no seu sistema:

1.  **Python 3.8+**
2.  **FFmpeg:** Essencial para juntar vídeo+áudio e converter para MP3.
    * *Windows:* Baixe o executável e adicione ao PATH.
    * *Linux:* `sudo apt install ffmpeg`
3.  **Node.js:** Necessário para o `yt-dlp` resolver desafios de segurança do YouTube.

---

## 🚀 Instalação e Configuração

### 1. Clone o projeto
Crie uma pasta e coloque os arquivos `app.py`, `templates/index.html` e este `README.md`.

### 2. Instale as dependências
Recomenda-se usar um ambiente virtual (`venv`).

```bash
pip install flask yt-dlp apscheduler requests python-dotenv
