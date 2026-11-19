from typing import List, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from src.services.alert_engine import AlertMatch


def format_alert_message(match: AlertMatch, numero_edicao: str, data_edicao: str, url_download: str) -> str:
    """Formata uma mensagem de alerta prioritário para envio no Telegram."""
    ato_info = f"\n📋 **Ato Relacionado:** {match.ato_identificado}" if match.ato_identificado else ""
    
    return (
        f"🚨 **ALERTA DE MENÇÃO NOMINAL IDENTIFICADA!** 🚨\n\n"
        f"🔍 **Termo Localizado:** `{match.termo}`\n"
        f"📅 **Diário ALETO:** Edição nº {numero_edicao} ({data_edicao})\n"
        f"📄 **Página:** {match.pagina}{ato_info}\n\n"
        f"📝 **Trecho Publicado:**\n"
        f"> {match.trecho}\n\n"
        f"📥 [Clique aqui para baixar o Diário Oficial em PDF]({url_download})"
    )


def build_edition_keyboard(url_download: str) -> InlineKeyboardMarkup:
    """Cria botões interativos para o rodapé dos resumos."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Baixar PDF Original", url=url_download)],
        [
            InlineKeyboardButton("📚 Últimas Edições", callback_data="cmd:edicoes"),
            InlineKeyboardButton("🔔 Notificações", callback_data="cmd:notificacoes"),
        ],
    ])


def format_welcome_message(first_name: Optional[str] = None, is_admin: bool = False) -> str:
    nome = f", {first_name}" if first_name else ""
    admin_section = ""
    if is_admin:
        admin_section = (
            f"\n🔐 **Comandos de Administrador:**\n"
            f"• `/verificar` ou `/verificar <nº>` - Forçar varredura e regenerar resumo com IA\n"
            f"• `/status` - Consultar status do sistema, IA e banco de dados\n"
            f"• `/usuarios` - Listar usuários cadastrados e interações\n"
            f"• `/comunicado <texto>` - Enviar aviso para todos os usuários ativos\n"
        )

    return (
        f"👋 **Olá{nome}! Seja bem-vindo ao Bot do Diário Oficial da ALETO.**\n\n"
        f"🤖 Eu monitoro o portal da Assembleia Legislativa do Tocantins ([al.to.leg.br](https://al.to.leg.br/)) "
        f"todos os dias úteis para você.\n\n"
        f"✨ **O que eu faço:**\n"
        f"• 📥 Baixo as novas edições assim que são publicadas.\n"
        f"• 🧠 Crio um **resumo completo e estruturado por IA** (RH, Projetos de Lei, Decretos, Licitações).\n"
        f"• 🚨 **Aviso imediatamente** se o seu nome ou termos monitorados forem publicados.\n\n"
        f"📌 **Comandos Disponíveis:**\n"
        f"• `/ultimo` ou `/ultimo <nº>` - Visualizar o resumo da última edição (ou de uma específica)\n"
        f"• `/edicoes` - Listar as últimas edições disponíveis no banco\n"
        f"• `/buscar <termo>` - Pesquisar menções nas edições e alertas salvos\n"
        f"• `/monitorar <nome>` - Adicionar um nome para alerta imediato\n"
        f"• `/listar` - Listar seus nomes/termos em monitoramento\n"
        f"• `/remover <nome>` - Remover um nome da lista\n"
        f"• `/notificacoes` - Alternar entre receber resumos diários ou somente alertas\n"
        f"• `/ajuda` - Exibir esta mensagem de ajuda\n"
        f"{admin_section}\n"
        f"🔒 **Aviso de Privacidade:**\n"
        f"O bot só acessa o portal da ALETO público e armazena apenas seu ID de chat, preferência de notificações e termos de monitoramento."
    )


def split_long_message(text: str, max_length: int = 4000) -> List[str]:
    """Divide um texto longo em blocos menores de 4000 caracteres respeitando quebras de linha."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    lines = text.split("\n")
    current_chunk = []
    current_length = 0

    for line in lines:
        line_len = len(line) + 1
        if current_length + line_len > max_length:
            if current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_length = 0
            
            # Se uma única linha for maior que max_length
            if line_len > max_length:
                while len(line) > max_length:
                    chunks.append(line[:max_length])
                    line = line[max_length:]
                if line:
                    current_chunk.append(line)
                    current_length = len(line)
                continue

        current_chunk.append(line)
        current_length += line_len

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks
