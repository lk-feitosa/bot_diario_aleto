import re
import logging
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urljoin
from xml.etree import ElementTree
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
        explicit_feed_urls = [
            "https://al.to.leg.br/rss/diario",
            "https://www.al.to.leg.br/rss/diario",
            "https://al.to.leg.br/rss",
            "https://al.to.leg.br/feed",
            "https://al.to.leg.br/rss.xml",
            "https://www.al.to.leg.br/rss",
            "https://www.al.to.leg.br/feed",
        ]
        root_response = None
        async with httpx.AsyncClient(headers=self.headers, follow_redirects=True, timeout=30.0, verify=False) as client:
            root_urls = [self.diario_url, "https://www.al.to.leg.br/diario", "https://al.to.leg.br/diario"]
            for url in root_urls:
                try:
                    logger.info(f"Buscando diários oficiais em: {url}")
                    response = await client.get(url)
                    response.raise_for_status()
                    root_response = response
                    break
                except Exception as e:
                    logger.warning(f"Falha ao acessar {url}: {e}")

            feed_urls = list(explicit_feed_urls)
            if root_response is not None:
                soup = BeautifulSoup(root_response.text, "html.parser")
                for link_tag in soup.find_all("link", href=True):
                    rel = " ".join(link_tag.get("rel", [])).lower()
                    type_value = link_tag.get("type", "").lower()
                    if "alternate" in rel or "rss" in type_value or "atom" in type_value:
                        feed_url = urljoin(str(root_response.url), link_tag["href"].strip())
                        if feed_url not in feed_urls:
                            feed_urls.insert(0, feed_url)

            for feed_url in feed_urls:
                try:
                    logger.info(f"Consultando feed RSS/Atom da ALETO: {feed_url}")
                    feed_response = await client.get(feed_url)
                    feed_response.raise_for_status()
                    xml_root = ElementTree.fromstring(feed_response.content)
                    xml_items = xml_root.findall(".//item")
                    if not xml_items:
                        xml_items = xml_root.findall(".//{*}entry")
                    if not xml_items:
                        continue

                    items: List[DiarioItem] = []
                    seen_urls = set()
                    for xml_item in xml_items:
                        title_node = xml_item.find("{*}title")
                        if title_node is None:
                            title_node = xml_item.find("title")
                        titulo = unescape((title_node.text or "").strip()) if title_node is not None else ""

                        link = ""
                        link_node = xml_item.find("{*}link")
                        if link_node is None:
                            link_node = xml_item.find("link")
                        if link_node is not None:
                            link = link_node.text or link_node.attrib.get("href", "")

                        description_node = xml_item.find("{*}description")
                        if description_node is None:
                            description_node = xml_item.find("description")
                        raw_description = (description_node.text or "") if description_node is not None else ""
                        raw_description = unescape(raw_description)
                        description_soup = BeautifulSoup(raw_description, "html.parser")
                        pdf_links = [
                            a.get("href") for a in description_soup.find_all("a", href=True)
                            if re.search(r"\.pdf(?:$|[?#])", a["href"], re.IGNORECASE)
                        ]
                        if pdf_links:
                            link = pdf_links[0]

                        enclosure = xml_item.find("enclosure")
                        if enclosure is not None and enclosure.attrib.get("url"):
                            link = enclosure.attrib["url"]

                        if not link:
                            continue
                        url_download = urljoin(str(feed_response.url), link.strip())
                        if url_download in seen_urls:
                            continue
                        seen_urls.add(url_download)

                        match_numero = re.search(r"Diário\s+n[ºo°]?\s*(\d+)", titulo, re.IGNORECASE)
                        numero = match_numero.group(1) if match_numero else "Desconhecido"

                        date_node = xml_item.find("{*}pubDate")
                        if date_node is None:
                            date_node = xml_item.find("pubDate")
                        if date_node is None:
                            date_node = xml_item.find("{*}published")
                        if date_node is None:
                            date_node = xml_item.find("{*}updated")
                        data_str = ""
                        if date_node is not None and date_node.text:
                            try:
                                published = parsedate_to_datetime(date_node.text.strip())
                                data_str = published.strftime("%d/%m/%Y")
                            except (TypeError, ValueError, OverflowError):
                                match_data = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", date_node.text)
                                data_str = match_data.group(1) if match_data else ""

                        resumo_previa = description_soup.get_text(" ", strip=True)
                        items.append(DiarioItem(
                            numero=numero,
                            titulo=titulo,
                            data=data_str,
                            url_detalhe=url_download,
                            url_download=url_download,
                            resumo_previa=resumo_previa,
                        ))
                        if len(items) >= limit:
                            break

                    if items:
                        logger.info(f"Encontradas {len(items)} edições no RSS/Atom da ALETO.")
                        return items
                except (ElementTree.ParseError, httpx.HTTPError) as e:
                    logger.warning(f"Feed indisponível ou sem XML válido em {feed_url}: {e}")

        if root_response is None:
            raise RuntimeError("Não foi possível acessar o portal da ALETO nem nenhum feed RSS conhecido.")

        response = root_response
        soup = BeautifulSoup(response.text, "html.parser")
        items = []
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
