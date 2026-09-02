import re
import unicodedata
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass
from src.services.pdf_processor import PDFDocumentData, PDFPageContent

logger = logging.getLogger(__name__)


@dataclass
class AlertMatch:
    termo: str
    pagina: int
    trecho: str
    ato_identificado: Optional[str] = None


def normalize_text(text: str) -> str:
    """Normaliza o texto removendo acentos e convertendo para minúsculas para busca insensível."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\s+", " ", text)
    return text.lower().strip()


class AlertEngine:
    @staticmethod
    def _find_act_header(text: str, match_pos: int) -> Optional[str]:
        """
        Tenta identificar o título do ato (Decreto, Portaria, Resolução, Lei, Edital)
        imediatamente anterior ao trecho da ocorrência.
        """
        text_before = text[:match_pos]
        # Padrões comuns em diários oficiais
        act_patterns = [
            r"((?:DECRETO|PORTARIA|RESOLUÇÃO|LEI|ATO|MEDIDA PROVISÓRIA|EDITAL|AVISO)\s+(?:ADMINISTRATIVO|LEGISLATIVO|CONJUNTO)?\s*(?:N[ºo°]?\s*[\d\.\/]+[^\n]*))",
            r"((?:OFÍCIO|CONTRATO|CONVÊNIO|TERMO ADITIVO|EXTRATO)\s+(?:N[ºo°]?\s*[\d\.\/]+[^\n]*))",
            r"((?:ATOS LEGISLATIVOS|ATOS ADMINISTRATIVOS|MESA DIRETORA|PRESIDÊNCIA)[^\n]*)"
        ]

        for pattern in act_patterns:
            matches = list(re.finditer(pattern, text_before, re.IGNORECASE))
            if matches:
                last_match = matches[-1]
                # Se estiver relativamente próximo (ex: até 1500 caracteres antes)
                if match_pos - last_match.end() < 1500:
                    return last_match.group(1).strip()
        return None

    @staticmethod
    def _extract_snippet(text: str, start_idx: int, end_idx: int, window: int = 250) -> str:
        """Extrai um trecho com contexto ao redor da palavra encontrada."""
        snippet_start = max(0, start_idx - window)
        snippet_end = min(len(text), end_idx + window)

        # Tentar ajustar para quebrar em palavras inteiras
        if snippet_start > 0:
            first_space = text.find(" ", snippet_start)
            if first_space != -1 and first_space < start_idx:
                snippet_start = first_space + 1

        if snippet_end < len(text):
            last_space = text.rfind(" ", start_idx, snippet_end)
            if last_space != -1 and last_space > end_idx:
                snippet_end = last_space

        snippet = text[snippet_start:snippet_end].strip()
        # Limpar quebras de linha excessivas
        snippet = re.sub(r"\n\s*\n+", "\n", snippet)
        
        prefix = "..." if snippet_start > 0 else ""
        suffix = "..." if snippet_end < len(text) else ""
        return f"{prefix}{snippet}{suffix}"

    @classmethod
    def search_terms(cls, doc_data: PDFDocumentData, terms: List[str]) -> List[AlertMatch]:
        """
        Pesquisa uma lista de termos/nomes em todas as páginas do diário.
        """
        if not terms:
            return []

        matches: List[AlertMatch] = []
        clean_terms = [t.strip() for t in terms if t.strip()]

        for page in doc_data.paginas:
            page_text = page.texto
            norm_page_text = normalize_text(page_text)

            for term in clean_terms:
                norm_term = normalize_text(term)
                if not norm_term:
                    continue

                # Busca flexível por regex (palavras completas)
                term_escaped = re.escape(norm_term)
                pattern = rf"\b{term_escaped}\b"
                
                for m in re.finditer(pattern, norm_page_text):
                    # Localiza a posição aproximada no texto original da página
                    # Faz uma busca por correspondência de substrings no texto original
                    orig_match = re.search(re.escape(term), page_text, re.IGNORECASE)
                    if orig_match:
                        start, end = orig_match.span()
                    else:
                        # Fallback se caracteres diferirem por acentuação
                        approx_ratio = len(page_text) / (len(norm_page_text) or 1)
                        start = int(m.start() * approx_ratio)
                        end = int(m.end() * approx_ratio)

                    snippet = cls._extract_snippet(page_text, start, end)
                    act_header = cls._find_act_header(page_text, start)

                    match_obj = AlertMatch(
                        termo=term,
                        pagina=page.numero_pagina,
                        trecho=snippet,
                        ato_identificado=act_header
                    )
                    matches.append(match_obj)
                    logger.warning(
                        f"🚨 ALERTA: Termo '{term}' encontrado na página {page.numero_pagina}! "
                        f"Ato: {act_header or 'Não identificado'}"
                    )

        return matches
