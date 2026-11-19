import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from src.config import settings
from src.database.session import get_db
from src.database.models import Usuario, TermoMonitorado, Edicao, Alerta, InteracaoLog
from src.bot.messages import format_welcome_message, split_long_message, build_edition_keyboard

logger = logging.getLogger(__name__)


def _is_admin(chat_id: int) -> bool:
    """Retorna True se o chat_id pertence ao administrador configurado."""
    return bool(settings.TELEGRAM_ADMIN_CHAT_ID and chat_id == settings.TELEGRAM_ADMIN_CHAT_ID)


async def _require_admin(update: Update) -> bool:
    """Verifica permissão de administrador e responde caso não autorizado."""
    chat_id = update.effective_chat.id
    if _is_admin(chat_id):
        return True
    await _reply_markdown_safe(
        update,
        "🔒 *Acesso restrito.*\nEste comando é exclusivo do administrador do bot.",
    )
    return False


async def _reply_markdown_safe(
    target,
    text: str,
    disable_web_page_preview: bool = True,
    reply_markup=None,
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
            reply_markup=reply_markup,
        )
    except BadRequest as e:
        if "parse" in str(e).lower() or "entities" in str(e).lower():
            logger.warning(f"Falha ao interpretar Markdown na resposta; enviando texto puro: {e}")
            await message.reply_text(
                text,
                disable_web_page_preview=disable_web_page_preview,
                reply_markup=reply_markup,
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

    msg = format_welcome_message(user.first_name, is_admin=_is_admin(chat_id))
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
            reply_markup=build_edition_keyboard(edicao_inicial.url_download),
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe instruções de uso do bot."""
    chat_id = update.effective_chat.id
    with get_db() as db:
        _registrar_interacao(db, chat_id, "/ajuda")

    msg = format_welcome_message(update.effective_user.first_name, is_admin=_is_admin(chat_id))
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
        reply_markup=build_edition_keyboard(edicao.url_download),
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

        # Termos globais (visíveis apenas para o administrador)
        termos_globais = []
        if _is_admin(chat_id):
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
    """Exibe estatísticas e status do bot (exclusivo do administrador)."""
    if not await _require_admin(update):
        return

    chat_id = update.effective_chat.id

    with get_db() as db:
        _registrar_interacao(db, chat_id, "/status")

        total_edicoes = db.query(Edicao).count()
        total_usuarios = db.query(Usuario).filter(Usuario.ativo == True).count()
        total_termos = db.query(TermoMonitorado).filter(TermoMonitorado.ativo == True).count()
        ultima_edicao = db.query(Edicao).order_by(Edicao.numero.desc(), Edicao.id.desc()).first()

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
    if not await _require_admin(update):
        return

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
            ai_modelos = resultado.get("ai_modelos") or {}
            ai_erros = resultado.get("ai_erros") or {}
            partes_status = []
            for n in numeros_proc:
                modelo = ai_modelos.get(n, "desconhecido")
                tag = "⚠️ Fallback simples" if modelo == "fallback" else f"🧠 {modelo}"
                partes_status.append(f"nº {n} ({tag})")
            lista_str = ", ".join(partes_status) if partes_status else str(resultado["novas_edicoes"])
            msg_res = f"✅ Verificação finalizada! Edição(ões) processada(s)/atualizada(s): {lista_str}."
            if ai_erros:
                detalhes = []
                for n, errs in ai_erros.items():
                    detalhes.append(f"• Edição nº {n}:\n  - " + "\n  - ".join(errs[:3]))
                msg_res += "\n\n⚠️ Motivos da falha na IA:\n" + "\n".join(detalhes)
            await update.message.reply_text(msg_res)
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
                        reply_markup=build_edition_keyboard(edicao.url_download),
                    )
        else:
            await update.message.reply_text("✅ Verificação finalizada! Nenhuma nova edição encontrada no momento.")
    except Exception as e:
        logger.error(f"Erro na verificação manual: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ocorreu um erro durante a verificação: {e}")


def _build_edicoes_text(db) -> str:
    """Monta a listagem das últimas 10 edições catalogadas no banco."""
    edicoes = db.query(Edicao).order_by(Edicao.numero.desc(), Edicao.id.desc()).limit(10).all()
    if not edicoes:
        return "ℹ️ Nenhuma edição foi catalogada ainda no banco de dados."

    linhas = ["📚 *ÚLTIMAS EDIÇÕES CATALOGADAS NO BANCO:*\n"]
    for ed in edicoes:
        resumo = ed.resumo or ""
        is_fallback = (
            not resumo
            or "ATOS E MATÉRIAS IDENTIFICADOS NA EDIÇÃO" in resumo
            or "Resumo Automático Simplificado" in resumo
        )
        tag = "⚡ Resumo simples" if is_fallback else "🧠 Resumo IA"
        linhas.append(f"• *Nº {ed.numero}* ({ed.data_publicacao}) — {tag} | [PDF]({ed.url_download})")

    linhas.append("\n💡 *Para ler o resumo completo de uma edição, use:* `/ultimo <nº>`\nExemplo: `/ultimo 4380`")
    return "\n".join(linhas)


async def edicoes_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lista as últimas 10 edições salvas no banco de dados."""
    chat_id = update.effective_chat.id
    with get_db() as db:
        _registrar_interacao(db, chat_id, "/edicoes")
        texto = _build_edicoes_text(db)

    await _reply_markdown_safe(update, texto, disable_web_page_preview=True)


async def buscar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pesquisa um termo nos resumos e alertas salvos no banco de dados."""
    chat_id = update.effective_chat.id
    termo = " ".join(context.args).strip().strip("<>\"'[] ") if context.args else ""

    if len(termo) < 2:
        await _reply_markdown_safe(
            update,
            "⚠️ *Uso incorreto.* Informe pelo menos 2 caracteres para buscar.\n\n"
            "Exemplo: `/buscar Concurso` ou `/buscar João da Silva`",
        )
        return

    with get_db() as db:
        _registrar_interacao(db, chat_id, "/buscar", termo)
        like_pattern = f"%{termo}%"
        edicoes = (
            db.query(Edicao)
            .filter(Edicao.resumo.ilike(like_pattern))
            .order_by(Edicao.numero.desc(), Edicao.id.desc())
            .limit(5)
            .all()
        )
        alertas = (
            db.query(Alerta)
            .filter((Alerta.termo.ilike(like_pattern)) | (Alerta.trecho.ilike(like_pattern)))
            .order_by(Alerta.id.desc())
            .limit(5)
            .all()
        )

    if not edicoes and not alertas:
        await _reply_markdown_safe(
            update,
            f"🔍 Nenhum resultado encontrado para `{termo}` nos resumos e alertas salvos.",
        )
        return

    linhas = [f"🔍 *RESULTADOS DA BUSCA POR:* `{termo}`\n"]
    if edicoes:
        linhas.append("📰 *Nos Resumos das Edições:*")
        for ed in edicoes:
            resumo = ed.resumo or ""
            idx = resumo.lower().find(termo.lower())
            trecho = ""
            if idx != -1:
                ini = max(0, idx - 60)
                fim = min(len(resumo), idx + len(termo) + 90)
                trecho = resumo[ini:fim].replace("\n", " ").strip()
                if ini > 0:
                    trecho = "..." + trecho
                if fim < len(resumo):
                    trecho = trecho + "..."
            linhas.append(f"• *Edição nº {ed.numero}* ({ed.data_publicacao}) — [PDF]({ed.url_download})")
            if trecho:
                linhas.append(f"  _{trecho}_")

    if alertas:
        linhas.append("\n🚨 *Nos Alertas Registrados:*")
        vistos = set()
        for al in alertas:
            chave = (al.edicao_id, al.pagina, al.termo)
            if chave in vistos:
                continue
            vistos.add(chave)
            ed_num = al.edicao.numero if al.edicao else str(al.edicao_id)
            linhas.append(f"• *Edição nº {ed_num}* (Pág. {al.pagina}) — termo `{al.termo}`")

    linhas.append("\n💡 Use `/ultimo <nº>` para abrir o resumo completo da edição.")
    await _reply_markdown_safe(update, "\n".join(linhas), disable_web_page_preview=True)


def _build_notificacoes_payload(receber_resumos: bool):
    status_str = "📰 *Resumos Diários + Alertas*" if receber_resumos else "🚨 *Somente Alertas Nominais*"
    texto = (
        f"🔔 *PREFERÊNCIA DE NOTIFICAÇÕES*\n\n"
        f"Modo atual: {status_str}\n\n"
        f"• *Resumos Diários + Alertas:* você recebe o resumo completo de toda nova edição + alertas dos seus termos.\n"
        f"• *Somente Alertas Nominais:* você não recebe o resumo diário automático, apenas quando algum termo seu aparecer."
    )
    teclado = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📰 Resumos + Alertas", callback_data="notif:all"),
            InlineKeyboardButton("🚨 Somente Alertas", callback_data="notif:alerts"),
        ]
    ])
    return texto, teclado


async def notificacoes_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Permite escolher entre receber todos os resumos diários ou somente alertas nominais."""
    chat_id = update.effective_chat.id
    arg = context.args[0].lower().strip() if context.args else ""

    with get_db() as db:
        _registrar_interacao(db, chat_id, "/notificacoes", arg or None)
        usuario = db.query(Usuario).filter(Usuario.chat_id == chat_id).first()
        if not usuario:
            usuario = Usuario(
                chat_id=chat_id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name,
                ativo=True,
                receber_resumos=True,
            )
            db.add(usuario)
            db.commit()
            db.refresh(usuario)

        if arg in ("tudo", "resumos", "all", "sim"):
            usuario.receber_resumos = True
            db.commit()
        elif arg in ("alertas", "alerts", "nao", "não"):
            usuario.receber_resumos = False
            db.commit()

        receber = bool(getattr(usuario, "receber_resumos", True))

    texto, teclado = _build_notificacoes_payload(receber)
    await _reply_markdown_safe(update, texto, reply_markup=teclado)


async def usuarios_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lista usuários cadastrados e resumo de interações (exclusivo do administrador)."""
    if not await _require_admin(update):
        return

    chat_id = update.effective_chat.id
    with get_db() as db:
        _registrar_interacao(db, chat_id, "/usuarios")
        usuarios = db.query(Usuario).order_by(Usuario.ultimo_acesso.desc().nullslast(), Usuario.id.desc()).limit(25).all()
        total_ativos = db.query(Usuario).filter(Usuario.ativo == True).count()
        total_inativos = db.query(Usuario).filter(Usuario.ativo == False).count()
        total_resumos = db.query(Usuario).filter(Usuario.ativo == True, Usuario.receber_resumos == True).count()
        total_interacoes = db.query(InteracaoLog).count()

    linhas = [
        f"👥 *USUÁRIOS DO BOT*\n",
        f"• Ativos: *{total_ativos}* (recebem resumos: *{total_resumos}*)",
        f"• Bloqueados/Inativos: *{total_inativos}*",
        f"• Total de comandos registrados: *{total_interacoes}*\n",
    ]
    for u in usuarios:
        nome = u.first_name or "Sem nome"
        user_tag = f"@{u.username}" if u.username else f"`{u.chat_id}`"
        status_icon = "🟢" if u.ativo else "🔴"
        modo_icon = "📰" if getattr(u, "receber_resumos", True) else "🚨"
        acesso = u.ultimo_acesso.strftime("%d/%m %H:%M") if u.ultimo_acesso else "nunca"
        linhas.append(f"{status_icon}{modo_icon} *{nome}* ({user_tag}) — último acesso: {acesso}")

    await _reply_markdown_safe(update, "\n".join(linhas), disable_web_page_preview=True)


async def comunicado_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia um comunicado do administrador para todos os usuários ativos."""
    if not await _require_admin(update):
        return

    from src.bot.bot import send_markdown_safe

    chat_id = update.effective_chat.id
    mensagem = " ".join(context.args).strip() if context.args else ""
    if not mensagem:
        await _reply_markdown_safe(
            update,
            "⚠️ Informe a mensagem do comunicado.\nExemplo: `/comunicado Bot atualizado com novos comandos!`",
        )
        return

    with get_db() as db:
        _registrar_interacao(db, chat_id, "/comunicado", mensagem[:100])
        usuarios = db.query(Usuario).filter(Usuario.ativo == True).all()
        chat_ids = [u.chat_id for u in usuarios]

    texto_envio = f"📢 *COMUNICADO DO ADMINISTRADOR*\n\n{mensagem}"
    enviados = 0
    falhas = 0
    for uid in chat_ids:
        try:
            await send_markdown_safe(context.bot, uid, texto_envio)
            enviados += 1
        except Exception as e:
            logger.warning(f"Falha ao enviar comunicado para chat_id={uid}: {e}")
            falhas += 1

    await _reply_markdown_safe(
        update,
        f"✅ Comunicado enviado!\n• Entregues: *{enviados}*\n• Falhas/Bloqueios: *{falhas}*",
    )


async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Trata cliques nos botões inline das mensagens."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    chat_id = query.message.chat_id
    data = query.data or ""

    if data == "cmd:edicoes":
        with get_db() as db:
            _registrar_interacao(db, chat_id, "btn:edicoes")
            texto = _build_edicoes_text(db)
        await _reply_markdown_safe(query.message, texto, disable_web_page_preview=True)
        return

    if data == "cmd:notificacoes":
        with get_db() as db:
            _registrar_interacao(db, chat_id, "btn:notificacoes")
            usuario = db.query(Usuario).filter(Usuario.chat_id == chat_id).first()
            receber = bool(getattr(usuario, "receber_resumos", True)) if usuario else True
        texto, teclado = _build_notificacoes_payload(receber)
        await _reply_markdown_safe(query.message, texto, reply_markup=teclado)
        return

    if data in ("notif:all", "notif:alerts"):
        novo_valor = data == "notif:all"
        with get_db() as db:
            _registrar_interacao(db, chat_id, f"btn:{data}")
            usuario = db.query(Usuario).filter(Usuario.chat_id == chat_id).first()
            if not usuario:
                usuario = Usuario(
                    chat_id=chat_id,
                    username=query.from_user.username,
                    first_name=query.from_user.first_name,
                    ativo=True,
                    receber_resumos=novo_valor,
                )
                db.add(usuario)
            else:
                usuario.receber_resumos = novo_valor
            db.commit()

        texto, teclado = _build_notificacoes_payload(novo_valor)
        try:
            await query.edit_message_text(
                texto,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=teclado,
            )
        except BadRequest:
            await _reply_markdown_safe(query.message, texto, reply_markup=teclado)

