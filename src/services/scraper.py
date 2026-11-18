import re
import logging
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass
from urllib.parse import urljoin
import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class DiarioItem:
    numero: str
    titulo: str
    data: str
    url_detalhe: str
    url_download: str
    resumo_previa: str


class AletoScraper:
    def __init__(self, base_url: str = settings.ALETO_BASE_URL, diario_url: str = settings.ALETO_DIARIO_URL):
        self.base_url = base_url.rstrip("/")
        self.diario_url = diario_url
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (X-UA-Compatible; Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def fetch_latest_edicoes(self, limit: int = 10) -> List[DiarioItem]:
        """
        Busca as edições mais recentes publicadas no portal da ALETO.
        """
        urls = list(dict.fromkeys([
            self.diario_url,
            "https://www.al.to.leg.br/diario",
            "https://al.to.leg.br/diario",
        ]))
        response = None
        async with httpx.AsyncClient(headers=self.headers, follow_redirects=True, timeout=30.0, verify=False) as client:
            for url in urls:
                try:
                    logger.info(f"Buscando diários oficiais em: {url}")
                    response = await client.get(url)
                    response.raise_for_status()
                    break
                except Exception as e:
                    logger.warning(f"Falha ao acessar {url}: {e}")

        if response is None:
            raise RuntimeError("Não foi possível acessar nenhuma URL conhecida do portal da ALETO.")

        soup = BeautifulSoup(response.text, "html.parser")
        items: List[DiarioItem] = []
        seen_urls = set()

        # Aceita tanto o layout atual (blocos .row) quanto layouts mais simples.
        rows = soup.find_all("div", class_="row")
        candidates = []
        for row in rows:
            for link_tag in row.find_all("a", href=True):
                titulo = link_tag.get_text(" ", strip=True)
                context = " ".join(row.stripped_strings)
                if re.search(r"diário|diario", f"{titulo} {context}", re.IGNORECASE):
                    candidates.append((row, link_tag, titulo))

        if not candidates:
            for link_tag in soup.find_all("a", href=True):
                titulo = link_tag.get_text(" ", strip=True)
                href = link_tag.get("href", "").strip()
                if re.search(r"diário|diario", titulo, re.IGNORECASE) or re.search(r"\.(pdf)(?:$|[?#])", href, re.IGNORECASE):
                    candidates.append((link_tag.parent, link_tag, titulo))

        for row, link_tag, titulo in candidates:
            href = link_tag.get("href", "").strip()
            url_download = urljoin(str(response.url), href)
            if url_download in seen_urls:
                continue
            seen_urls.add(url_download)

            # Extração do número do diário
            match_numero = re.search(r"Diário\s+n[ºo°]?\s*(\d+)", titulo, re.IGNORECASE)
            numero = match_numero.group(1) if match_numero else "Desconhecido"

            # Extração da data
            context = " ".join(row.stripped_strings)
            match_data = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", context)
            data_str = match_data.group(1) if match_data else ""

            if not data_str:
                # Fallback: tentar extrair do título "de DD de MMMM de AAAA"
                match_data_titulo = re.search(r"de\s+(\d{1,2}\s+de\s+[a-zA-ZçÇ]+\s+de\s+\d{4})", titulo, re.IGNORECASE)
                if match_data_titulo:
                    meses = {
                        "janeiro": "01", "fevereiro": "02", "março": "03", "abril": "04",
                        "maio": "05", "junho": "06", "julho": "07", "agosto": "08",
                        "setembro": "09", "outubro": "10", "novembro": "11", "dezembro": "12",
                    }
                    dia, _, mes, _, ano = match_data_titulo.group(1).lower().split()
                    data_str = f"{int(dia):02d}/{meses.get(mes, '00')}/{ano}"
                else:
                    data_str = "Data não identificada"

            # Prévia do texto
            col_content = row.find_all("div", class_="col-12")
            resumo_previa = ""
            if len(col_content) > 1:
                resumo_previa = col_content[1].get_text(" ", strip=True)

            items.append(DiarioItem(
                numero=numero,
                titulo=titulo,
                data=data_str,
                url_detalhe=url_download,
                url_download=url_download,
                resumo_previa=resumo_previa
            ))

            if len(items) >= limit:
                break

        logger.info(f"Encontradas {len(items)} edições no portal da ALETO.")
        return items

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def download_pdf(self, url: str, destino: Path) -> Path:
        """
        Baixa o arquivo PDF do diário e salva no caminho informado.
        """
        logger.info(f"Iniciando download do PDF: {url} -> {destino}")
        destino.parent.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(headers=self.headers, follow_redirects=True, timeout=90.0, verify=False) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                with open(destino, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=16384):
                        f.write(chunk)

        logger.info(f"Download concluído com sucesso: {destino} ({destino.stat().st_size} bytes)")
        return destino
