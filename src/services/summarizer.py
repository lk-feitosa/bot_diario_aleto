import asyncio
import logging
from typing import Optional
from src.config import settings
from src.services.pdf_processor import PDFDocumentData

logger = logging.getLogger(__name__)


PROMPT_SUMARIO_DIARIO = """
Você é um consultor e analista jurídico-legislativo especializado no Diário Oficial da Assembleia Legislativa do Estado do Tocantins (ALETO).
Sua missão é ler o texto integral do diário oficial abaixo e gerar um RESUMO COMPLETO, ESTRUTURADO, CLARO E DIRETO AO PONTO.

O resumo deve ser formatado em Markdown compatível com Telegram (use negrito *, tópicos -, emojis informativos).
Não inclua introduções genéricas como "Aqui está o resumo". Comece diretamente no formato abaixo:

📰 **RESUMO DO DIÁRIO OFICIAL DA ALETO**
📅 **Edição:** [Número do Diário se informado] | **Data:** [Data da Edição]
📄 **Total de Páginas:** [Total de Páginas]

---

⭐ **1. DESTAQUES EXECUTIVOS DO DIA**
- [Destaque 1 mais relevante: ex: nova lei aprovada, ata de registro de preços/licitação, grande contratação, movimentação de pessoal ou ato da Mesa]
- [Destaque 2]
- [Destaque 3]

🏛️ **2. ATIVIDADE LEGISLATIVA & PLENÁRIO**
- **Atas e Sessões:** [Resumo das sessões plenárias, presenças/ausências, votações. Se não houver, informe "Não constam matérias plenárias nesta edição"]
- **Projetos de Lei / Medidas Provisórias / Resoluções:** [Principais matérias, autores, temas e números dos projetos]

👥 **3. RECURSOS HUMANOS & ATOS DE PESSOAL**
⚠️ ATENÇÃO: É OBRIGATÓRIO listar nominalmente TODAS as pessoas afetadas e suas respectivas portarias/decretos. NÃO generalize dizendo "houve várias nomeações". ATENÇÃO ESPECIAL para lotações de servidores efetivos/concursados e comissionados.

- **Nomeações:** [Nome Completo - Cargo - Gabinete/Diretoria/Secretaria (Decreto/Portaria)]
- **Exonerações:** [Nome Completo - Cargo - Gabinete/Diretoria/Secretaria (Decreto/Portaria)]
- **Lotações, Remoções e Designações:** [Nome Completo - Cargo (ex: Analista Legislativo, etc.) - Setor de Lotação (ex: Controladoria Interna, Coordenadoria de Desenvolvimento de Sistemas, etc.) (Portaria nº X)]
- **Progressões, Licenças, Férias e Benefícios:** [Nome Completo - Tipo de Licença/Benefício/Férias - Período/Detalhamento (Portaria nº X)]
*(Se não houver atos de RH, declare: "Nenhum ato de RH registrado")*

💼 **4. CONTRATOS, LICITAÇÕES & CONVÊNIOS**
⚠️ ATENÇÃO: Especifique sempre o NOME DA EMPRESA (Razão Social/CNPJ), o OBJETO resumido, o VALOR (R$) e a VIGÊNCIA quando disponível.
- **Atas de Registro de Preços & Homologações:** [Empresa Contratada - Objeto - Valor (R$) - Vigência - Licitação/Processo]
- **Contratos e Aditivos:** [Empresa Contratada - Resumo do Objeto - Valor (R$) - Vigência]
- **Editais e Licitações:** [Modalidade - Objeto - Data de Abertura]
*(Se não houver, informe "Não constam contratações nesta edição")*

📑 **5. OUTROS ATOS ADMINISTRATIVOS RELEVANTES**
- [Portarias da diretoria, decisões da mesa diretora, suspensão/remarcação de férias, convocações ou avisos gerais]

---
💡 *Dica: Você pode consultar o PDF completo para visualizar a íntegra dos despachos e anexos.*

=== TEXTO DO DIÁRIO OFICIAL PARA ANÁLISE ===
{texto_diario}
"""


class DiarioSummarizer:
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_MODEL
        self._client = None
        self._init_client()

    def _init_client(self) -> None:
        if not self.api_key:
            logger.warning("GEMINI_API_KEY não configurada. O sumarizador funcionará em modo fallback heurístico.")
            return

        try:
            # Tenta utilizar o novo SDK google-genai
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
            self._use_new_sdk = True
            logger.info(f"Cliente Gemini inicializado com sucesso (google-genai / {self.model_name}).")
        except Exception as e1:
            logger.warning(f"Não foi possível inicializar google-genai ({e1}). Tentando google.generativeai...")
            try:
                import google.generativeai as legacy_genai
                legacy_genai.configure(api_key=self.api_key)
                self._client = legacy_genai.GenerativeModel(self.model_name)
                self._use_new_sdk = False
                logger.info(f"Cliente Gemini legado inicializado com sucesso ({self.model_name}).")
            except Exception as e2:
                logger.error(f"Erro ao inicializar biblioteca do Gemini: {e2}")
                self._client = None

    async def generate_summary(
        self,
        doc_data: PDFDocumentData,
        numero_edicao: str = "",
        data_edicao: str = "",
        max_retries: int = 3
    ) -> str:
        """
        Gera um resumo completo do diário oficial utilizando o Gemini (com retries) ou fallback heurístico.
        """
        prompt = PROMPT_SUMARIO_DIARIO.format(
            texto_diario=doc_data.texto_completo[:300000]  # Limite de segurança de 300k caracteres
        )

        if self._client and self.api_key:
            for attempt in range(1, max_retries + 1):
                try:
                    logger.info(f"Enviando requisição ao Gemini (Tentativa {attempt}/{max_retries})...")
                    if self._use_new_sdk:
                        response = await asyncio.to_thread(
                            self._client.models.generate_content,
                            model=self.model_name,
                            contents=prompt,
                        )
                        resumo = response.text
                    else:
                        response = await asyncio.to_thread(self._client.generate_content, prompt)
                        resumo = response.text

                    if resumo and len(resumo.strip()) > 50:
                        logger.info("Resumo gerado com sucesso pelo Gemini!")
                        return resumo.strip()

                    logger.warning(f"Gemini retornou resposta vazia/curta na tentativa {attempt}.")
                except Exception as e:
                    logger.warning(f"Falha na tentativa {attempt}/{max_retries} do Gemini: {e}")
                    if attempt < max_retries:
                        backoff = 2 ** attempt
                        logger.info(f"Aguardando {backoff}s antes de tentar novamente...")
                        await asyncio.sleep(backoff)
                    else:
                        logger.error(f"Todas as {max_retries} tentativas do Gemini falharam: {e}", exc_info=True)
        else:
            logger.warning("Gemini indisponível: chave ausente ou cliente não inicializado.")

        return self._generate_fallback_summary(doc_data, numero_edicao, data_edicao)

    def _generate_fallback_summary(self, doc_data: PDFDocumentData, numero_edicao: str, data_edicao: str) -> str:
        """Gera um resumo estruturado baseado em extração de tópicos caso a IA não esteja disponível."""
        import re

        linhas = doc_data.texto_completo.split("\n")
        decretos = []
        portarias = []
        atas = []
        leis = []

        # Padrões para ignorar citações legais de cabeçalho/preâmbulo
        preambulo_ignore = re.compile(
            r"(consonância com|alterada pela|fulcro no art|nos termos da|Lei nº 4\.250|Lei nº 4\.209|Lei nº 1\.818|Lei nº 14\.133)",
            re.IGNORECASE
        )

        for linha in linhas:
            linha_strip = linha.strip()
            if not linha_strip:
                continue

            if re.match(r"^DECRETO ADMINISTRATIVO Nº", linha_strip, re.IGNORECASE):
                if linha_strip not in decretos:
                    decretos.append(linha_strip)
            elif re.match(r"^PORTARIA Nº", linha_strip, re.IGNORECASE):
                if linha_strip not in portarias:
                    portarias.append(linha_strip)
            elif re.match(r"^Ata da", linha_strip, re.IGNORECASE):
                if linha_strip not in atas:
                    atas.append(linha_strip)
            elif re.match(r"^(PROJETO DE LEI|LEI Nº)", linha_strip, re.IGNORECASE):
                # Filtra citações de leis no preâmbulo
                if not preambulo_ignore.search(linha_strip):
                    if linha_strip not in leis:
                        leis.append(linha_strip)

        resumo = [
            f"📰 *RESUMO DO DIÁRIO OFICIAL DA ALETO*",
            f"📅 *Edição:* Nº {numero_edicao or 'N/A'} | *Data:* {data_edicao or 'N/A'}",
            f"📄 *Total de Páginas:* {doc_data.total_paginas}",
            "",
            "⚠️ *Nota:* Este resumo foi gerado em modo de emergência devido à indisponibilidade temporária da API de IA.",
            "",
            "🏛️ *ATOS E MATÉRIAS IDENTIFICADOS NA EDIÇÃO:*"
        ]

        if leis:
            resumo.append("\n📜 *Leis e Projetos:*")
            for item in leis[:8]:
                resumo.append(f"- {item}")

        if decretos:
            resumo.append("\n📋 *Decretos Administrativos:*")
            for item in decretos[:15]:
                resumo.append(f"- {item}")

        if portarias:
            resumo.append("\n📑 *Portarias:*")
            for item in portarias[:15]:
                resumo.append(f"- {item}")

        if atas:
            resumo.append("\n🎙️ *Atas das Sessões:*")
            for item in atas[:5]:
                resumo.append(f"- {item}")

        if not (leis or decretos or portarias or atas):
            resumo.append("\nℹ️ Edição processada com sucesso. Consulte o arquivo PDF original para leitura detalhada.")

        return "\n".join(resumo)

