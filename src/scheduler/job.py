import logging
from datetime import datetime
from zoneinfo import ZoneInfo
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


def _is_fallback_summary(resumo: Optional[str]) -> bool:
    """Identifica se o resumo salvo está vazio ou foi gerado pelo modo fallback (sem IA)."""
    if not resumo:
        return True
    return (
        "ATOS E MATÉRIAS IDENTIFICADOS NA EDIÇÃO" in resumo
        or "Resumo Automático Simplificado" in resumo
    )


async def run_daily_check_pipeline(
    app: Optional[Application] = None,
    force_current: bool = False,
    target_numero: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executa o ciclo completo de monitoramento:
    1. Varre o portal da ALETO em busca de novos diários.
    2. Baixa o PDF das novas edições (ou edições com resumo simples sem IA).
    3. Extrai o texto e processa alertas de termos nominais.
    4. Gera o resumo inteligente via IA.
    5. Dispara notificações no Telegram (apenas para a edição atual, sem spam de diários antigos).
    6. Registra/atualiza tudo no banco de dados.
    """
    logger.info("🔍 [SCHEDULER] Iniciando rotina de checagem do Diário Oficial ALETO...")
    scraper = AletoScraper()
    summarizer = DiarioSummarizer()
    novas_edicoes_count = 0
    total_alertas_count = 0
    broadcasted = False
    edicoes_processadas: List[str] = []

    try:
        itens = await scraper.fetch_latest_edicoes(limit=5)
    except Exception as e:
        logger.error(f"Erro ao consultar portal da ALETO: {e}", exc_info=True)
        return {"sucesso": False, "erro": str(e), "novas_edicoes": 0, "edicoes_processadas": []}

    if target_numero:
        itens = [item for item in itens if item.numero == target_numero]
        if not itens:
            return {
                "sucesso": True,
                "novas_edicoes": 0,
                "alertas_emitidos": 0,
                "broadcasted": False,
                "edicoes_processadas": [],
            }

    data_hoje = datetime.now(ZoneInfo(settings.TIMEZONE)).strftime("%d/%m/%Y")
    itens_do_dia = [item for item in itens if item.data == data_hoje]
    if not force_current and not target_numero:
        itens = itens_do_dia or itens[:5]
    newest_url = itens[0].url_download if itens else None
    if not itens:
        logger.info("Nenhuma edição encontrada no portal para processar.")
        return {"sucesso": True, "novas_edicoes": 0, "alertas_emitidos": 0, "edicoes_processadas": []}
    if not itens_do_dia:
        logger.info(
            f"Nenhuma edição publicada hoje ({data_hoje}); verificando as edições mais recentes disponíveis."
        )

    # Em /verificar sem número específico, prioriza atualizar edições recentes sem IA ou ausentes no banco
    algum_pendente_ou_fallback = False
    if force_current and not target_numero:
        with get_db() as db:
            for it in itens:
                ex = (
                    db.query(Edicao)
                    .filter((Edicao.url_download == it.url_download) | (Edicao.numero == it.numero))
                    .first()
                )
                if ex is None or _is_fallback_summary(ex.resumo):
                    algum_pendente_ou_fallback = True
                    break

    for item in reversed(itens):  # Processa em ordem cronológica (mais antigo para o mais novo)
        with get_db() as db:
            existente = (
                db.query(Edicao)
                .filter((Edicao.url_download == item.url_download) | (Edicao.numero == item.numero))
                .first()
            )
            precisa_upgrade_ia = force_current and existente is not None and _is_fallback_summary(existente.resumo)
            forcar_este_item = bool(target_numero) or (
                force_current and not algum_pendente_ou_fallback and item.url_download == newest_url
            )

            if existente and not precisa_upgrade_ia and not forcar_este_item:
                logger.info(f"⏭️ Edição nº {item.numero} já possui resumo IA completo: {item.url_download}")
                continue

            if existente:
                motivo = "atualização de resumo simples para IA" if precisa_upgrade_ia else "solicitação manual"
                logger.info(f"🔁 Regenerando resumo da edição nº {item.numero} ({motivo}).")
            else:
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

            # Ao regenerar, não duplica alertas já registrados para a edição.
            if existente:
                matches = []

            # 4. Geração do Resumo Inteligente com Gemini
            resumo_ia = await summarizer.generate_summary(
                doc_data=doc_data,
                numero_edicao=item.numero,
                data_edicao=item.data
            )

            # 5. Salva a Edição no Banco
            if existente:
                nova_edicao = existente
                nova_edicao.resumo = resumo_ia
                nova_edicao.pdf_path = None
                nova_edicao.processado_em = datetime.utcnow()
            else:
                nova_edicao = Edicao(
                    numero=item.numero,
                    data_publicacao=item.data,
                    url_download=item.url_download,
                    pdf_path=None,
                    resumo=resumo_ia,
                    processado_em=datetime.utcnow()
                )
                db.add(nova_edicao)
                db.flush()  # Para obter o ID da nova edição

            # Limpa o PDF do disco após processamento completo
            try:
                caminho_pdf.unlink(missing_ok=True)
                logger.info(f"🗑️ PDF temporário removido: {caminho_pdf.name}")
            except Exception as e_clean:
                logger.warning(f"Não foi possível remover PDF temporário: {e_clean}")

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
            edicoes_processadas.append(nova_edicao.numero)

            # 7. Broadcast do Resumo Geral para Todos os Usuários (apenas para edição nova do dia/mais recente)
            deve_fazer_broadcast = (
                not existente
                and not force_current
                and (item.data == data_hoje or item.url_download == newest_url)
            )
            if deve_fazer_broadcast and app and app.bot:
                await broadcast_edition_summary(app.bot, nova_edicao)
                broadcasted = True

    logger.info(
        f"🏁 [SCHEDULER] Ciclo concluído: {novas_edicoes_count} novas edições processadas, "
        f"{total_alertas_count} alertas emitidos."
    )
    return {
        "sucesso": True,
        "novas_edicoes": novas_edicoes_count,
        "alertas_emitidos": total_alertas_count,
        "broadcasted": broadcasted,
        "edicoes_processadas": edicoes_processadas,
    }
