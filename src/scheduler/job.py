import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from telegram.ext import Application

from src.config import settings
from src.database.session import get_db
from src.database.models import Edicao, Usuario, TermoMonitorado, Alerta
from src.services.scraper import AletoScraper, DiarioItem
from src.services.pdf_processor import PDFProcessor
from src.services.alert_engine import AlertEngine, AlertMatch
from src.services.summarizer import DiarioSummarizer
from src.bot.bot import send_alert_to_user, broadcast_edition_summary

logger = logging.getLogger(__name__)


async def run_daily_check_pipeline(app: Optional[Application] = None) -> Dict[str, Any]:
    """
    Executa o ciclo completo de monitoramento:
    1. Varre o portal da ALETO em busca de novos diários.
    2. Baixa o PDF das novas edições.
    3. Extrai o texto e processa alertas de termos nominais.
    4. Gera o resumo inteligente via IA.
    5. Dispara notificações no Telegram.
    6. Registra tudo no banco SQLite.
    """
    logger.info("🔍 [SCHEDULER] Iniciando rotina de checagem do Diário Oficial ALETO...")
    scraper = AletoScraper()
    summarizer = DiarioSummarizer()
    novas_edicoes_count = 0
    total_alertas_count = 0

    try:
        itens = await scraper.fetch_latest_edicoes(limit=5)
    except Exception as e:
        logger.error(f"Erro ao consultar portal da ALETO: {e}", exc_info=True)
        return {"sucesso": False, "erro": str(e), "novas_edicoes": 0}

    for item in reversed(itens):  # Processa em ordem cronológica (mais antigo para o mais novo)
        with get_db() as db:
            total_banco = db.query(Edicao).count()
            existente = db.query(Edicao).filter(Edicao.url_download == item.url_download).first()
            if existente:
                continue

            # Se o banco estiver completamente vazio (primeira execução do sistema),
            # processa apenas a edição mais recente (item == itens[0]) e ignora as anteriores
            if total_banco == 0 and item != itens[0]:
                logger.info(f"⏭️ Ignorando edição histórica nº {item.numero} na primeira inicialização.")
                # Registra no banco para não processar depois, mas sem enviar notificações
                edicao_historica = Edicao(
                    numero=item.numero,
                    data_publicacao=item.data,
                    url_download=item.url_download,
                    processado_em=datetime.utcnow()
                )
                db.add(edicao_historica)
                db.commit()
                continue

            logger.info(f"✨ Nova edição detectada! Diário nº {item.numero} ({item.data}) - {item.url_download}")

            # 1. Download do PDF
            nome_arquivo = f"diario_{item.numero}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pdf"
            caminho_pdf = settings.DATA_DIR / "pdfs" / nome_arquivo

            try:
                await scraper.download_pdf(item.url_download, caminho_pdf)
            except Exception as e_down:
                logger.error(f"Falha no download do PDF ({item.url_download}): {e_down}")
                continue

            # 2. Extração de texto do PDF
            try:
                doc_data = PDFProcessor.extract_text(caminho_pdf)
            except Exception as e_pdf:
                logger.error(f"Falha ao extrair texto do PDF ({caminho_pdf}): {e_pdf}")
                continue

            # 3. Busca de Termos Monitorados (Global e por Usuário)
            termos_globais = db.query(TermoMonitorado).filter(
                TermoMonitorado.usuario_id.is_(None),
                TermoMonitorado.ativo == True
            ).all()

            termos_usuarios = db.query(TermoMonitorado).filter(
                TermoMonitorado.usuario_id.isnot(None),
                TermoMonitorado.ativo == True
            ).all()

            lista_termos_busca = list(set([t.termo for t in termos_globais + termos_usuarios]))

            # Executa a engine de busca
            matches: List[AlertMatch] = AlertEngine.search_terms(doc_data, lista_termos_busca)

            # 4. Geração do Resumo Inteligente com Gemini
            resumo_ia = await summarizer.generate_summary(
                doc_data=doc_data,
                numero_edicao=item.numero,
                data_edicao=item.data
            )

            # 5. Salva a Edição no Banco
            nova_edicao = Edicao(
                numero=item.numero,
                data_publicacao=item.data,
                url_download=item.url_download,
                pdf_path=str(caminho_pdf),
                resumo=resumo_ia,
                processado_em=datetime.utcnow()
            )
            db.add(nova_edicao)
            db.flush()  # Para obter o ID da nova edição

            # 6. Salva Alertas no Banco e Dispara Notificações
            for match in matches:
                # Localiza usuários associados ao termo
                usuarios_alvo = db.query(Usuario).join(TermoMonitorado).filter(
                    TermoMonitorado.termo.ilike(match.termo),
                    TermoMonitorado.ativo == True,
                    Usuario.ativo == True
                ).all()

                # Se o termo for global, notificar o admin
                is_global = any(g.termo.lower() == match.termo.lower() for g in termos_globais)

                alerta_db = Alerta(
                    edicao_id=nova_edicao.id,
                    termo=match.termo,
                    pagina=match.pagina,
                    trecho=match.trecho,
                    enviado_em=datetime.utcnow()
                )
                db.add(alerta_db)
                total_alertas_count += 1

                if app and app.bot:
                    # Enviar para usuários específicos
                    for user in usuarios_alvo:
                        await send_alert_to_user(app.bot, user.chat_id, match, nova_edicao)

                    # Se for global e o admin não estiver entre os alvos
                    if is_global and settings.TELEGRAM_ADMIN_CHAT_ID:
                        alvo_ids = [u.chat_id for u in usuarios_alvo]
                        if settings.TELEGRAM_ADMIN_CHAT_ID not in alvo_ids:
                            await send_alert_to_user(app.bot, settings.TELEGRAM_ADMIN_CHAT_ID, match, nova_edicao)

            db.commit()
            novas_edicoes_count += 1

            # 7. Broadcast do Resumo Geral para Todos os Usuários
            if app and app.bot:
                await broadcast_edition_summary(app.bot, nova_edicao)

    logger.info(
        f"🏁 [SCHEDULER] Ciclo concluído: {novas_edicoes_count} novas edições processadas, "
        f"{total_alertas_count} alertas emitidos."
    )
    return {
        "sucesso": True,
        "novas_edicoes": novas_edicoes_count,
        "alertas_emitidos": total_alertas_count
    }
