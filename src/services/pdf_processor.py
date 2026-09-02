import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import pymupdf  # PyMuPDF

logger = logging.getLogger(__name__)


@dataclass
class PDFPageContent:
    numero_pagina: int  # 1-indexed
    texto: str


@dataclass
class PDFDocumentData:
    caminho: Path
    total_paginas: int
    paginas: List[PDFPageContent]
    texto_completo: str


class PDFProcessor:
    @staticmethod
    def extract_text(pdf_path: Path) -> PDFDocumentData:
        """
        Extrai o texto completo e por página de um arquivo PDF usando PyMuPDF.
        """
        if not pdf_path.exists():
            raise FileNotFoundError(f"Arquivo PDF não encontrado: {pdf_path}")

        logger.info(f"Processando arquivo PDF: {pdf_path}")
        doc = pymupdf.open(str(pdf_path))
        total_paginas = len(doc)
        paginas: List[PDFPageContent] = []
        textos_completos: List[str] = []

        for i in range(total_paginas):
            page = doc[i]
            # Extrai o texto limpo da página
            text = page.get_text("text") or ""
            numero_pagina = i + 1
            paginas.append(PDFPageContent(numero_pagina=numero_pagina, texto=text))
            
            # Adiciona cabeçalho demarcando a página para a IA saber exatamente as páginas
            textos_completos.append(f"\n--- [PÁGINA {numero_pagina}] ---\n{text}")

        doc.close()
        texto_unificado = "\n".join(textos_completos).strip()
        logger.info(f"PDF processado com sucesso: {total_paginas} páginas extraídas, {len(texto_unificado)} caracteres.")

        return PDFDocumentData(
            caminho=pdf_path,
            total_paginas=total_paginas,
            paginas=paginas,
            texto_completo=texto_unificado
        )
