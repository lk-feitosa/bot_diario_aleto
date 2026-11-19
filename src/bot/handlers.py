import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from src.config import settings
from src.database.session import get_db
from src.database.models import Usuario, TermoMonitorado, Edicao, InteracaoLog
from src.bot.messages import format_welcome_message, split_long_message

logger = logging.getLogger(__name__)


async def _reply_markdown_safe(
    target,
    text: str,
    disable_web_page_preview: bool = True,
) -> None:
    """Responde com ParseMode.MARKDOWN e faz fallback para texto puro se houver erro de formatação.
    Aceita tanto `Update` quanto `Message`.
    """
    message = getattr(target, "message", None) or target
    try:
        await message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=disable_web_page_preview,
        )
    except BadRequest as e:
        if "parse" in str(e).lower() or "entities" in str(e).lower():
            logger.warning(f"Falha ao interpretar Markdown na resposta; enviando texto puro: {e}")
            await message.reply_text(
                text,
                disable_web_page_preview=disable_web_page_preview,
            )
        else:
            raise


def _registrar_interacao(db, chat_id: int, comando: str, parametros: str = None) -> None:
    """Registra a interação no log e atualiza o ultimo_acesso do usuário."""
    # Log de interação
    log = InteracaoLog(
        chat_id=chat_id,
        comando=comando,
        parametros=parametros[:200] if parametros else None,
        executado_em=datetime.utcnow()
    )
    db.add(log)

    # Atualiza ultimo_acesso do usuário
    usuario = db.query(Usuario).filter(Usuario.chat_id == chat_id).first()
    if usuario:
        usuario.ultimo_acesso = datetime.utcnow()

    db.commit()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Registra o usuário e envia a edição do dia no primeiro acesso."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    primeiro_acesso = False

    with get_db() as db:
        usuario = db.query(Usuario).filter(Usuario.chat_id == chat_id).first()
        if not usuario:
            primeiro_acesso = True
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
                usuario.bloqueado_em = None  # Limpa flag de bloqueio ao retornar
                db.commit()

        _registrar_interacao(db, chat_id, "/start")

        edicao_inicial = None
        if primeiro_acesso:
            data_hoje = datetime.now(ZoneInfo(settings.TIMEZONE)).strftime("%d/%m/%Y")
            edicao_inicial = db.query(Edicao).filter(
                Edicao.data_publicacao == data_hoje,
                Edicao.resumo.isnot(None)
            ).order_by(Edicao.id.desc()).first()
            if not edicao_inicial:
                edicao_inicial = db.query(Edicao).filter(
                    Edicao.resumo.isnot(None)
                ).order_by(Edicao.id.desc()).first()

    msg = format_welcome_message(user.first_name)
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

    if primeiro_acesso:
        if not edicao_inicial:
            await update.message.reply_text(
                "Ainda não há um resumo disponível. A primeira edição será enviada assim que o processamento terminar.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        for chunk in split_long_message(edicao_inicial.resumo):
            await _reply_markdown_safe(update, chunk, disable_web_page_preview=True)
        await _reply_markdown_safe(
            update,
            f"📥 **Download do PDF Original:** [Diário nº {edicao_inicial.numero} ({edicao_inicial.data_publicacao})]({edicao_inicial.url_download})",
            disable_web_page_preview=False,
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe instruções de uso do bot."""
    chat_id = update.effective_chat.id
    with get_db() as db:
        _registrar_interacao(db, chat_id, "/ajuda")

    msg = format_welcome_message(update.effective_user.first_name)
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


async def ultimo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Retorna o resumo da última edição processada ou de uma edição específica (`/ultimo 4380`)."""
    chat_id = update.effective_chat.id
    numero_alvo = context.args[0].strip("#nº° ") if context.args else None

    with get_db() as db:
        _registrar_interacao(db, chat_id, "/ultimo", numero_alvo)
        if numero_alvo:
            edicao = db.query(Edicao).filter(Edicao.numero == numero_alvo).order_by(Edicao.id.desc()).first()
        else:
            edicao = db.query(Edicao).order_by(Edicao.numero.desc(), Edicao.id.desc()).first()

    if not edicao:
        if numero_alvo:
            await _reply_markdown_safe(
                update,
                f"ℹ️ A edição nº `{numero_alvo}` ainda não está salva no banco.\n"
                f"Use `/verificar {numero_alvo}` para baixar e gerar o resumo por IA dessa edição.",
            )
        else:
            await _reply_markdown_safe(
                update,
                "ℹ️ Nenhuma edição foi processada ainda no banco de dados.\n"
                "Use o comando `/verificar` para realizar a primeira busca agora mesmo!",
            )
        return

    resumo_texto = edicao.resumo or "Resumo não disponível para esta edição."
    chunks = split_long_message(resumo_texto)

    for chunk in chunks:
        await _reply_markdown_safe(update, chunk, disable_web_page_preview=True)

    await _reply_markdown_safe(
        update,
        f"📥 **Download do PDF Original:** [Diário nº {edicao.numero} ({edicao.data_publicacao})]({edicao.url_download})",
        disable_web_page_preview=False,
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

    try:
        with get_db() as db:
            _registrar_interacao(db, chat_id, "/monitorar", termo)

            usuario = db.query(Usuario).filter(Usuario.chat_id == chat_id).first()
            if not usuario:
                usuario = Usuario(
                    chat_id=chat_id,
                    username=update.effective_user.username,
                    first_name=update.effective_user.first_name,
                    ativo=True
                )
                db.add(usuario)
                db.commit()
                db.refresh(usuario)

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
    except Exception as e:
        logger.error(f"Erro ao executar /monitorar para chat_id={chat_id}: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ocorreu um erro ao salvar o nome: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def listar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lista todos os termos que o usuário está monitorando."""
    chat_id = update.effective_chat.id

    with get_db() as db:
        _registrar_interacao(db, chat_id, "/listar")

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
        _registrar_interacao(db, chat_id, "/remover", termo)

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
    chat_id = update.effective_chat.id

    with get_db() as db:
        _registrar_interacao(db, chat_id, "/status")

        total_edicoes = db.query(Edicao).count()
        total_usuarios = db.query(Usuario).filter(Usuario.ativo == True).count()
        total_termos = db.query(TermoMonitorado).filter(TermoMonitorado.ativo == True).count()
        ultima_edicao = db.query(Edicao).order_by(Edicao.id.desc()).first()

    ultima_info = (
        f"Nº {ultima_edicao.numero} ({ultima_edicao.data_publicacao})"
        if ultima_edicao else "Nenhuma ainda"
    )

    gemini_status = f"Ativo ({settings.GEMINI_MODEL})" if settings.GEMINI_API_KEY else "Não configurado"
    openai_status = f"Ativo ({settings.OPENAI_MODEL})" if settings.OPENAI_API_KEY else "Não configurado"

    msg = (
        f"📊 *STATUS DO BOT DO DIÁRIO OFICIAL ALETO*\n\n"
        f"🟢 *Status:* Operacional e Monitorando\n"
        f"📰 *Total de Edições Catalogadas:* {total_edicoes}\n"
        f"📅 *Última Edição Processada:* {ultima_info}\n"
        f"👥 *Usuários Ativos:* {total_usuarios}\n"
        f"🔍 *Termos Monitorados:* {total_termos}\n"
        f"🧠 *Gemini:* {gemini_status}\n"
        f"🤖 *OpenAI (fallback):* {openai_status}\n"
        f"🕒 *Hora do Servidor:* {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    )
    await _reply_markdown_safe(update, msg)


async def verificar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dispara uma verificação manual forçada de novas edições ou de uma edição específica (`/verificar 4380`)."""
    from src.scheduler.job import run_daily_check_pipeline

    chat_id = update.effective_chat.id
    numero_alvo = context.args[0].strip("#nº° ") if context.args else None
    with get_db() as db:
        _registrar_interacao(db, chat_id, "/verificar", numero_alvo)

    aviso = (
        f"🔄 *Gerando/atualizando resumo por IA da edição nº {numero_alvo}...*\nAguarde alguns instantes."
        if numero_alvo
        else "🔄 *Iniciando verificação manual no portal da ALETO...*\n"
             "Edições recentes sem resumo IA serão atualizadas automaticamente no banco."
    )
    await _reply_markdown_safe(update, aviso)
    try:
        resultado = await run_daily_check_pipeline(
            context.application, force_current=True, target_numero=numero_alvo
        )
        numeros_proc = resultado.get("edicoes_processadas", [])
        if resultado.get("novas_edicoes", 0) > 0:
            lista_str = ", ".join(f"nº {n}" for n in numeros_proc) if numeros_proc else str(resultado["novas_edicoes"])
            await update.message.reply_text(
                f"✅ Verificação finalizada! Edição(ões) processada(s)/atualizada(s): {lista_str}."
            )
            if not resultado.get("broadcasted", False):
                with get_db() as db:
                    if numeros_proc:
                        edicoes = (
                            db.query(Edicao)
                            .filter(Edicao.numero.in_(numeros_proc))
                            .order_by(Edicao.numero.asc())
                            .all()
                        )
                    else:
                        ed = db.query(Edicao).order_by(Edicao.numero.desc(), Edicao.id.desc()).first()
                        edicoes = [ed] if ed else []
                for edicao in edicoes:
                    resumo_texto = edicao.resumo or "Resumo não disponível para esta edição."
                    for chunk in split_long_message(resumo_texto):
                        await _reply_markdown_safe(update, chunk, disable_web_page_preview=True)
                    await _reply_markdown_safe(
                        update,
                        f"📥 *Download do PDF Original:* [Diário nº {edicao.numero} ({edicao.data_publicacao})]({edicao.url_download})",
                        disable_web_page_preview=False,
                    )
        else:
            await update.message.reply_text("✅ Verificação finalizada! Nenhuma nova edição encontrada no momento.")
    except Exception as e:
        logger.error(f"Erro na verificação manual: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ocorreu um erro durante a verificação: {e}")

