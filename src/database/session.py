import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager

from src.config import settings
from src.database.models import Base

logger = logging.getLogger(__name__)

# Ajuste para compatibilidade com URLs do Render/Supabase
db_url = settings.DATABASE_URL
# O SQLAlchemy 2.0+ exige o driver explícito psycopg2 se a lib for psycopg2-binary
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+psycopg2://", 1)
elif db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

# Configurações de pool para bancos externos (Supabase)
engine_args = {}
if db_url.startswith("postgresql"):
    engine_args = {
        "pool_size": 5,
        "max_overflow": 10,
        "pool_timeout": 30,
        "pool_recycle": 1800,
    }

engine = create_engine(db_url, **engine_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Cria as tabelas se não existirem."""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Tabelas do banco de dados verificadas/criadas.")
    except Exception as e:
        logger.error(f"❌ Erro ao inicializar banco de dados: {e}")
        raise

@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
