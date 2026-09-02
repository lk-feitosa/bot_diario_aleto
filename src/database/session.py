from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from src.config import settings
from .models import Base, TermoMonitorado

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    echo=(settings.LOG_LEVEL == "DEBUG")
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Inicializa as tabelas do banco de dados e carrega termos padrão se configurados."""
    settings.setup_directories()
    Base.metadata.create_all(bind=engine)

    # Inserir termos padrão do .env se ainda não existirem
    default_names = settings.get_watch_names_list()
    if default_names:
        with get_db() as db:
            for name in default_names:
                existing = db.query(TermoMonitorado).filter(
                    TermoMonitorado.termo == name,
                    TermoMonitorado.usuario_id.is_(None)
                ).first()
                if not existing:
                    db.add(TermoMonitorado(termo=name, usuario_id=None, ativo=True))
            db.commit()


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Context manager para sessões do banco de dados."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
