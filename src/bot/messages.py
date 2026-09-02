from typing import List, Optional
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


def format_welcome_message(first_name: Optional[str] = None) -> str:
    nome = f", {first_name}" if first_name else ""
    return (
        f"👋 **Olá{nome}! Seja bem-vindo ao Bot do Diário Oficial da ALETO.**\n\n"
        f"🤖 Eu monitoro o portal da Assembleia Legislativa do Tocantins ([al.to.leg.br/diario](https://www.al.to.leg.br/diario)) "
        f"todos os dias úteis para você.\n\n"
        f"✨ **O que eu faço:**\n"
        f"• 📥 Baixo as novas edições assim que são publicadas.\n"
        f"• 🧠 Crio um **resumo completo e estruturado por IA** (RH, Projetos de Lei, Decretos, Licitações).\n"
        f"• 🚨 **Aviso imediatamente** se o seu nome ou termos monitorados forem publicados.\n\n"
        f"📌 **Comandos Disponíveis:**\n"
        f"• `/ultimo` - Visualizar o resumo da última edição publicada\n"
        f"• `/monitorar <nome>` - Adicionar um nome para alerta imediato\n"
        f"• `/listar` - Listar seus nomes/termos em monitoramento\n"
        f"• `/remover <nome>` - Remover um nome da lista\n"
        f"• `/verificar` - Forçar verificação manual de novas edições\n"
        f"• `/status` - Consultar status do monitoramento e banco de dados\n"
        f"• `/ajuda` - Exibir esta mensagem de ajuda"
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
