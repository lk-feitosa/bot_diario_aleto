import re
import logging
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass
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
        logger.info(f"Buscando diários oficiais em: {self.diario_url}")
        async with httpx.AsyncClient(headers=self.headers, follow_redirects=True, timeout=30.0, verify=False) as client:
            response = await client.get(self.diario_url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        items: List[DiarioItem] = []

        # Localiza os blocos de diário na página
        # O HTML da ALETO organiza cada diário dentro de divs row
        rows = soup.find_all("div", class_="row")
        
        for row in rows:
            h4 = row.find("h4")
            if not h4:
                continue

            link_tag = h4.find("a")
            if not link_tag:
                continue

            titulo = link_tag.get_text(strip=True)
            href = link_tag.get("href", "").strip()

            if not href.startswith("http"):
                url_download = f"{self.base_url}{href}"
            else:
                url_download = href

            # Extração do número do diário
            match_numero = re.search(r"Diário\s+n[ºo°]?\s*(\d+)", titulo, re.IGNORECASE)
            numero = match_numero.group(1) if match_numero else "Desconhecido"

            # Extração da data
            data_tag = row.find("small", text=re.compile(r"Data:", re.IGNORECASE))
            if not data_tag:
                # Tenta buscar pelo texto geral dentro dos smalls
                smalls = row.find_all("small")
                data_str = ""
                for s in smalls:
                    if "Data:" in s.text:
                        match_data = re.search(r"(\d{2}/\d{2}/\d{4})", s.text)
                        if match_data:
                            data_str = match_data.group(1)
                            break
            else:
                match_data = re.search(r"(\d{2}/\d{2}/\d{4})", data_tag.get_text())
                data_str = match_data.group(1) if match_data else ""

            if not data_str:
                # Fallback: tentar extrair do título "de DD de MMMM de AAAA"
                match_data_titulo = re.search(r"de\s+(\d{1,2}\s+de\s+[a-zA-ZçÇ]+\s+de\s+\d{4})", titulo, re.IGNORECASE)
                data_str = match_data_titulo.group(1) if match_data_titulo else "Data não identificada"

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
