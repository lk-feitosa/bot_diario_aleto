import asyncio
import logging
from pathlib import Path
from rich import print as rprint
from rich.panel import Panel

from src.config import settings
from src.database.session import init_db, get_db
from src.database.models import Edicao, TermoMonitorado
from src.services.scraper import AletoScraper
from src.services.pdf_processor import PDFProcessor
from src.services.alert_engine import AlertEngine
from src.services.summarizer import DiarioSummarizer
from src.bot.messages import format_alert_message

logging.basicConfig(level="INFO")


async def run_test():
    rprint(Panel.fit("[bold green]🧪 INICIANDO TESTE DO PIPELINE ALETO[/bold green]"))

    # 1. Init DB
    init_db()
    rprint("[bold blue]1. Banco de Dados inicializado.[/bold blue]")

    # 2. Test Scraper
    scraper = AletoScraper()
    edicoes = await scraper.fetch_latest_edicoes(limit=2)
    assert len(edicoes) > 0, "Nenhuma edição encontrada pelo scraper!"
    latest = edicoes[0]
    rprint(f"[bold green]2. Scraper OK:[/bold green] Última edição nº {latest.numero} ({latest.data}) - {latest.url_download}")

    # 3. Test Download
    pdf_path = settings.DATA_DIR / "pdfs" / f"test_diario_{latest.numero}.pdf"
    await scraper.download_pdf(latest.url_download, pdf_path)
    assert pdf_path.exists() and pdf_path.stat().st_size > 0, "PDF não foi baixado corretamente!"
    rprint(f"[bold green]3. Download PDF OK:[/bold green] Salvo em {pdf_path} ({pdf_path.stat().st_size / 1024:.1f} KB)")

    # 4. Test PDF Processor
    doc_data = PDFProcessor.extract_text(pdf_path)
    assert doc_data.total_paginas > 0, "PDF sem páginas extraídas!"
    assert len(doc_data.texto_completo) > 100, "Texto extraído muito curto!"
    rprint(f"[bold green]4. Extração de PDF OK:[/bold green] Total de páginas: {doc_data.total_paginas}, Caracteres: {len(doc_data.texto_completo)}")

    # 5. Test Alert Engine com termos de teste
    test_terms = ["Amélio Cayres", "Eduarda Mendes", "Exonerar", "TermoInexistenteXYZ"]
    matches = AlertEngine.search_terms(doc_data, test_terms)
    rprint(f"[bold green]5. Alert Engine OK:[/bold green] {len(matches)} ocorrências encontradas para termos de teste.")
    for m in matches[:2]:
        alerta_formatado = format_alert_message(m, latest.numero, latest.data, latest.url_download)
        rprint(Panel(alerta_formatado, title=f"Exemplo de Alerta - {m.termo} (Pág {m.pagina})"))

    # 6. Test Summarizer (Fallback ou Gemini)
    summarizer = DiarioSummarizer()
    resumo = await summarizer.generate_summary(doc_data, latest.numero, latest.data)
    assert len(resumo) > 50, "Resumo gerado muito curto!"
    rprint(Panel(resumo[:800] + "\n...(resumo truncado para exibição de teste)...", title="Resumo Gerado"))

    rprint("[bold green]✅ TODOS OS TESTES PASSARAM COM SUCESSO![/bold green]")


if __name__ == "__main__":
    asyncio.run(run_test())
