import asyncio
import logging
import json
import signal
import sys
import os
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from rich.logging import RichHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.config import settings
from src.database.session import init_db
from src.bot.bot import create_bot_app
from src.scheduler.job import run_daily_check_pipeline

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "ok", "service": "diario_aleto_bot"}\n')

    def log_message(self, format, *args):
        # Silencia logs repetitivos de health check
        return

def start_health_check_server():
    """Inicia um servidor HTTP em thread separada para plataformas que exigem porta aberta (ex: Render)."""
    port = int(os.getenv("PORT", "8080"))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        token = settings.TELEGRAM_BOT_TOKEN or ""
        mask_token = f"{token[:12]}..." if token and len(token) >= 12 else "***"
        logger.info(f"🌐 Servidor de Health Check ativo na porta {port} (Render/Cloud compatível). Token protegido: {mask_token}")
    except Exception as e:
        logger.warning(f"Não foi possível iniciar servidor de health check na porta {port}: {e}")

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

if os.getenv("RENDER") or os.getenv("JSON_LOGS"):
    handler = logging.StreamHandler(sys.stdout)
    formatter = JsonFormatter()
else:
    handler = logging.StreamHandler()
    formatter = None

if formatter:
    handler.setFormatter(formatter)

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[handler]
)

# Import anônimo do bot somente após mexer em app
logger = logging.getLogger("diario_aleto")

async def main() -> None:
    logger.info("🚀 Iniciando o Bot do Diário Oficial da ALETO...")

    # Inicia health check HTTP para Render/Cloud
    start_health_check_server()

    # 1. Inicializa o banco de dados e diretórios
    init_db()
    logger.info("📦 Banco de dados SQLite inicializado com sucesso.")

    # 2. Constrói a aplicação do Telegram Bot
    app = create_bot_app()

    # 3. Configura o Agendador de Tarefas (APScheduler)
    scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)
    scheduler.add_job(
        run_daily_check_pipeline,
        trigger="interval",
        minutes=settings.CHECK_INTERVAL_MINUTES,
        args=[app],
        id="check_aleto_diario",
        name="Checagem Periódica de Diários ALETO",
        replace_existing=True
    )
    scheduler.start()
    logger.info(f"⏰ Agendador iniciado: checagens a cada {settings.CHECK_INTERVAL_MINUTES} minutos "
                f"(Timezone: {settings.TIMEZONE}).")

    # 4. Dispara uma checagem inicial assíncrona após a inicialização
    asyncio.create_task(run_daily_check_pipeline(app))

    # 5. Verifica se o bot está configurado corretamente antes de iniciar polling
    token = settings.TELEGRAM_BOT_TOKEN or ""
    if not token:
        logger.warning("⚠️ Bot não configurado (TELEGRAM_BOT_TOKEN não informado). Rodando em MODO PASSIVO (sem polling do Telegram).")
        # Mantém processo vivo para o agendador
        while True:
            await asyncio.sleep(3600)
        return

    # Validação preventiva: verificar se o bot existe e responde
    # Isso garante que não tentamos inicializar com um token inválido
    # e evitamos exposição do token completo em logs
    try:
        bot = await app.bot.initialize()
        logger.info("✅ Bot Telegram inicializado com sucesso. Iniciando polling...")
    except Exception as e_token:
        logger.warning(f"⚠️ Token Telegram inválido ou bot inalcançável: {e_token}")
        logger.warning("Verifique se TELEGRAM_BOT_TOKEN no arquivo .env (ou Render Config) está correto.")
        # Mantém processo vivo para o agendador
        while True:
            await asyncio.sleep(3600)
        return

    logger.info("🤖 Iniciando polling interativo do bot no Telegram...")

    async with app:
        await app.start()
        await app.updater.start_polling()

        stop_event = asyncio.Event()

        def signal_handler():
            logger.info("🛑 Sinal de encerramento recebido...")
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                asyncio.get_event_loop().add_signal_handler(sig, signal_handler)
            except NotImplementedError:
                pass

        await stop_event.wait()
        logger.info("Encerrando bot do Telegram e agendador...")
        await app.updater.stop()
        await app.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Aplicação finalizada pelo usuário.")
        sys.exit(0)