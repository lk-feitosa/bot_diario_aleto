import asyncio
import logging
import signal
import sys
from rich.logging import RichHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.config import settings
from src.database.session import init_db
from src.bot.bot import create_bot_app
from src.scheduler.job import run_daily_check_pipeline

# Configuração de Logging elegante
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, show_path=False)]
)
logger = logging.getLogger("diario_aleto")


async def main() -> None:
    logger.info("🚀 Iniciando o Bot do Diário Oficial da ALETO...")

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
    logger.info(
        f"⏰ Agendador iniciado: checagens a cada {settings.CHECK_INTERVAL_MINUTES} minutos "
        f"(Timezone: {settings.TIMEZONE})."
    )

    # 4. Dispara uma checagem inicial assíncrona após a inicialização
    asyncio.create_task(run_daily_check_pipeline(app))

    # 5. Inicia o Polling do Bot do Telegram se o token foi configurado
    if app:
        logger.info("🤖 Iniciando polling interativo do bot no Telegram...")
        async with app:
            await app.start()
            await app.updater.start_polling()

            # Mantém a aplicação rodando até receber sinal de parada
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
    else:
        logger.warning("⚠️ Bot rodando em MODO SOMENTE-SERVIÇO (Sem polling do Telegram).")
        logger.info("Para ativar o bot no Telegram, preencha o TELEGRAM_BOT_TOKEN no seu arquivo .env.")
        
        # Mantém processo vivo para o agendador
        while True:
            await asyncio.sleep(3600)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Aplicação finalizada pelo usuário.")
        sys.exit(0)
