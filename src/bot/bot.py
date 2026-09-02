import logging
from typing import List, Dict, Any, Optional
from telegram import Bot
from telegram.constants import ParseMode
from telegram.ext import Application, ApplicationBuilder, CommandHandler

from src.config import settings
from src.database.models import Usuario, Edicao
from src.database.session import get_db
from src.services.alert_engine import AlertMatch
from src.bot.messages import format_alert_message, split_long_message
from src.bot.handlers import (
    start_command,
    help_command,
    ultimo_command,
    monitorar_command,
    listar_command,
    remover_command,
    status_command,
    verificar_command,
)

logger = logging.getLogger(__name__)


def create_bot_app() -> Optional[Application]:
    """Cria e configura a instância do Bot do Telegram."""
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN não foi informado. O bot do Telegram não iniciará polling interativo.")
        return None

    app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()

    # Registro dos comandos
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler(["ajuda", "help"], help_command))
    app.add_handler(CommandHandler(["ultimo", "resumo"], ultimo_command))
    app.add_handler(CommandHandler("monitorar", monitorar_command))
    app.add_handler(CommandHandler("listar", listar_command))
    app.add_handler(CommandHandler("remover", remover_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("verificar", verificar_command))

    return app


async def send_alert_to_user(bot: Bot, chat_id: int, match: AlertMatch, edicao: Edicao) -> None:
    """Envia mensagem de alerta prioritário para um usuário específico."""
    texto_alerta = format_alert_message(
        match=match,
        numero_edicao=edicao.numero,
        data_edicao=edicao.data_publicacao,
        url_download=edicao.url_download
    )
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=texto_alerta,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
        logger.info(f"🚨 Alerta enviado com sucesso para o chat_id={chat_id} (Termo: {match.termo})")
    except Exception as e:
        logger.error(f"Falha ao enviar alerta para chat_id={chat_id}: {e}")


async def broadcast_edition_summary(bot: Bot, edicao: Edicao) -> None:
    """Envia o resumo da nova edição para todos os usuários ativos."""
    with get_db() as db:
        usuarios = db.query(Usuario).filter(Usuario.ativo == True).all()
        chat_ids = [u.chat_id for u in usuarios]

    # Se o admin estiver configurado mas não cadastrado ainda no banco, incluir
    if settings.TELEGRAM_ADMIN_CHAT_ID and settings.TELEGRAM_ADMIN_CHAT_ID not in chat_ids:
        chat_ids.append(settings.TELEGRAM_ADMIN_CHAT_ID)

    if not chat_ids:
        logger.warning("Nenhum usuário ativo para receber o resumo diário.")
        return

    resumo_texto = edicao.resumo or "Nova edição publicada da ALETO."
    chunks = split_long_message(resumo_texto)
    pdf_info = f"\n\n📥 **Download do PDF Original:** [Diário nº {edicao.numero} ({edicao.data_publicacao})]({edicao.url_download})"

    for chat_id in set(chat_ids):
        try:
            for chunk in chunks:
                await bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True
                )
            # Mensagem final com link de download
            await bot.send_message(
                chat_id=chat_id,
                text=pdf_info,
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"Resumo da edição nº {edicao.numero} entregue para chat_id={chat_id}")
        except Exception as e:
            logger.error(f"Erro ao entregar resumo para chat_id={chat_id}: {e}")
