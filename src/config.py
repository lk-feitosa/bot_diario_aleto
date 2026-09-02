import os
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Telegram
    TELEGRAM_BOT_TOKEN: str = Field(default="", description="Token do Bot do Telegram")
    TELEGRAM_ADMIN_CHAT_ID: int = Field(default=0, description="Chat ID do Admin")

    # Gemini AI
    GEMINI_API_KEY: str = Field(default="", description="Chave de API do Google Gemini")
    GEMINI_MODEL: str = Field(default="gemini-2.5-flash", description="Modelo do Gemini")

    # Monitoramento
    DEFAULT_WATCH_NAMES: str = Field(
        default="",
        description="Nomes para monitoramento inicial separados por vírgula"
    )

    # Agendamento
    CHECK_INTERVAL_MINUTES: int = Field(default=30, description="Intervalo de checagem em minutos")
    TIMEZONE: str = Field(default="America/Araguaina", description="Timezone padrão")

    # Diretórios e Armazenamento
    DATA_DIR: Path = Field(default=Path("./data"), description="Diretório de dados")
    DATABASE_URL: str = Field(default="sqlite:///./data/diario_aleto.db", description="URL do Banco SQLite")
    LOG_LEVEL: str = Field(default="INFO", description="Nível de log")

    # URL Base da ALETO
    ALETO_DIARIO_URL: str = "https://www.al.to.leg.br/diario"
    ALETO_BASE_URL: str = "https://www.al.to.leg.br"

    def get_watch_names_list(self) -> List[str]:
        if not self.DEFAULT_WATCH_NAMES:
            return []
        return [
            name.strip()
            for name in self.DEFAULT_WATCH_NAMES.split(",")
            if name.strip()
        ]

    def setup_directories(self) -> None:
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "pdfs").mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.setup_directories()
