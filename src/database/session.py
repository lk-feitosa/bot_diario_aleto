from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from src.config import settings
from .models import Base, TermoMonitorado

db_url = settings.DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

engine_kwargs = {
    "echo": (settings.LOG_LEVEL == "DEBUG")
}

if "sqlite" in db_url:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # PostgreSQL / Supabase
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_recycle"] = 300

engine = create_engine(db_url, **engine_kwargs)

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
