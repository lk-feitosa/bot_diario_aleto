import logging
from datetime import datetime
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src.database.session import get_db
from src.database.models import Usuario, TermoMonitorado, Edicao
from src.bot.messages import format_welcome_message, split_long_message

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Registra o usuário e envia mensagem de boas-vindas."""
    user = update.effective_user
    chat_id = update.effective_chat.id

    with get_db() as db:
        usuario = db.query(Usuario).filter(Usuario.chat_id == chat_id).first()
        if not usuario:
            usuario = Usuario(
                chat_id=chat_id,
                username=user.username,
                first_name=user.first_name,
                ativo=True,
                criado_em=datetime.utcnow()
            )
            db.add(usuario)
            db.commit()
            logger.info(f"Novo usuário registrado no bot: {user.first_name} (@{user.username}, ID: {chat_id})")
        else:
            if not usuario.ativo:
                usuario.ativo = True
                db.commit()

    msg = format_welcome_message(user.first_name)
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe instruções de uso do bot."""
    msg = format_welcome_message(update.effective_user.first_name)
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


async def ultimo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Retorna o resumo da última edição do diário processada."""
    with get_db() as db:
        edicao = db.query(Edicao).order_by(Edicao.id.desc()).first()

    if not edicao:
        await update.message.reply_text(
            "ℹ️ Nenhuma edição foi processada ainda no banco de dados.\n"
            "Use o comando `/verificar` para realizar a primeira busca agora mesmo!",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    resumo_texto = edicao.resumo or "Resumo não disponível para esta edição."
    chunks = split_long_message(resumo_texto)

    for i, chunk in enumerate(chunks):
        await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

    await update.message.reply_text(
        f"📥 **Download do PDF Original:** [Diário nº {edicao.numero} ({edicao.data_publicacao})]({edicao.url_download})",
        parse_mode=ParseMode.MARKDOWN
    )


async def monitorar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Adiciona um nome ou termo à lista de monitoramento do usuário."""
    chat_id = update.effective_chat.id
    termo = " ".join(context.args).strip() if context.args else ""
    # Remove automaticamente delimitadores como < >, [ ], " ou ' que possam ter sido digitados por engano
    termo = termo.strip("<>\"'[] ")

    if not termo:
        await update.message.reply_text(
            "⚠️ **Uso incorreto.** Informe o nome que deseja monitorar.\n\n"
            "Exemplo: `/monitorar João da Silva` ou `/monitorar Concurso`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    with get_db() as db:
        usuario = db.query(Usuario).filter(Usuario.chat_id == chat_id).first()
        if not usuario:
            usuario = Usuario(
                chat_id=chat_id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name,
                ativo=True
            )
            db.add(usuario)
            db.flush()

        existente = db.query(TermoMonitorado).filter(
            TermoMonitorado.usuario_id == usuario.id,
            TermoMonitorado.termo.ilike(termo)
        ).first()

        if existente:
            if not existente.ativo:
                existente.ativo = True
                db.commit()
                await update.message.reply_text(f"✅ O termo `{termo}` foi reativado para monitoramento!", parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(f"ℹ️ O termo `{termo}` já está ativo no seu monitoramento.", parse_mode=ParseMode.MARKDOWN)
            return

        novo_termo = TermoMonitorado(
            usuario_id=usuario.id,
            termo=termo,
            ativo=True,
            criado_em=datetime.utcnow()
        )
        db.add(novo_termo)
        db.commit()

    await update.message.reply_text(
        f"✅ **Nome monitorado com sucesso!**\n\n"
        f"🔍 Termo adicionado: `{termo}`\n"
        f"🚨 Você receberá um alerta prioritário com o trecho exato sempre que este nome for publicado no Diário da ALETO.",
        parse_mode=ParseMode.MARKDOWN
    )


async def listar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lista todos os termos que o usuário está monitorando."""
    chat_id = update.effective_chat.id

    with get_db() as db:
        usuario = db.query(Usuario).filter(Usuario.chat_id == chat_id).first()
        if not usuario:
            termos_usuario = []
        else:
            termos_usuario = db.query(TermoMonitorado).filter(
                TermoMonitorado.usuario_id == usuario.id,
                TermoMonitorado.ativo == True
            ).all()

        # Termos globais (configurados via .env)
        termos_globais = db.query(TermoMonitorado).filter(
            TermoMonitorado.usuario_id.is_(None),
            TermoMonitorado.ativo == True
        ).all()

    linhas = ["📋 **SEUS NOMES E TERMOS MONITORADOS:**\n"]
    
    if termos_usuario:
        linhas.append("👤 **Termos Pessoais:**")
        for t in termos_usuario:
            linhas.append(f"• `{t.termo}` (desde {t.criado_em.strftime('%d/%m/%Y')})")
    else:
        linhas.append("ℹ️ Você ainda não adicionou nenhum termo pessoal. Use `/monitorar <nome>`")

    if termos_globais:
        linhas.append("\n🌐 **Termos Globais do Sistema:**")
        for g in termos_globais:
            linhas.append(f"• `{g.termo}`")

    linhas.append("\n💡 *Para remover um termo pessoal, use:* `/remover <nome>`")
    await update.message.reply_text("\n".join(linhas), parse_mode=ParseMode.MARKDOWN)


async def remover_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove um nome da lista de monitoramento do usuário."""
    chat_id = update.effective_chat.id
    termo = " ".join(context.args).strip() if context.args else ""
    termo = termo.strip("<>\"'[] ")

    if not termo:
        await update.message.reply_text(
            "⚠️ Informe o nome que deseja remover.\nExemplo: `/remover João da Silva`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    with get_db() as db:
        usuario = db.query(Usuario).filter(Usuario.chat_id == chat_id).first()
        if not usuario:
            await update.message.reply_text("ℹ️ Nenhum termo encontrado.", parse_mode=ParseMode.MARKDOWN)
            return

        termo_db = db.query(TermoMonitorado).filter(
            TermoMonitorado.usuario_id == usuario.id,
            TermoMonitorado.termo.ilike(termo)
        ).first()

        if not termo_db:
            await update.message.reply_text(f"❌ O termo `{termo}` não foi encontrado na sua lista.", parse_mode=ParseMode.MARKDOWN)
            return

        db.delete(termo_db)
        db.commit()

    await update.message.reply_text(f"🗑️ Termo `{termo}` removido do seu monitoramento.", parse_mode=ParseMode.MARKDOWN)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe estatísticas e status do bot."""
    with get_db() as db:
        total_edicoes = db.query(Edicao).count()
        total_usuarios = db.query(Usuario).filter(Usuario.ativo == True).count()
        total_termos = db.query(TermoMonitorado).filter(TermoMonitorado.ativo == True).count()
        ultima_edicao = db.query(Edicao).order_by(Edicao.id.desc()).first()

    ultima_info = (
        f"Nº {ultima_edicao.numero} ({ultima_edicao.data_publicacao})"
        if ultima_edicao else "Nenhuma ainda"
    )

    msg = (
        f"📊 **STATUS DO BOT DO DIÁRIO OFICIAL ALETO**\n\n"
        f"🟢 **Status:** Operacional e Monitorando\n"
        f"📰 **Total de Edições Catalogadas:** {total_edicoes}\n"
        f"📅 **Última Edição Processada:** {ultima_info}\n"
        f"👥 **Usuários Ativos:** {total_usuarios}\n"
        f"🔍 **Termos Monitorados:** {total_termos}\n"
        f"🕒 **Hora do Servidor:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def verificar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dispara uma verificação manual forçada de novas edições."""
    from src.scheduler.job import run_daily_check_pipeline

    await update.message.reply_text("🔄 **Iniciando verificação manual no portal da ALETO...**\nAguarde alguns instantes.")
    try:
        resultado = await run_daily_check_pipeline(context.application)
        if resultado.get("novas_edicoes", 0) > 0:
            await update.message.reply_text(f"✅ Verificação finalizada! {resultado['novas_edicoes']} nova(s) edição(ões) processada(s).")
        else:
            await update.message.reply_text("✅ Verificação finalizada! Nenhuma nova edição encontrada no momento.")
    except Exception as e:
        logger.error(f"Erro na verificação manual: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ocorreu um erro durante a verificação: `{e}`", parse_mode=ParseMode.MARKDOWN)
