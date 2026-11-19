import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager

from src.config import settings
from src.database.models import Base, TermoMonitorado

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
        "pool_recycle": 300,
        "pool_pre_ping": True,
        "connect_args": {
            "connect_timeout": 10,
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        },
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


def seed_default_watch_names() -> None:
    """Garante que os termos de DEFAULT_WATCH_NAMES existam como termos globais ativos."""
    watch_names = settings.get_watch_names_list()
    if not watch_names:
        return

    with get_db() as db:
        adicionados = 0
        for nome in watch_names:
            existente = db.query(TermoMonitorado).filter(
                TermoMonitorado.usuario_id.is_(None),
                TermoMonitorado.termo.ilike(nome),
            ).first()
            if not existente:
                db.add(TermoMonitorado(usuario_id=None, termo=nome, ativo=True))
                adicionados += 1
        if adicionados:
            db.commit()
            logger.info(f"🔍 {adicionados} termo(s) global(is) de DEFAULT_WATCH_NAMES sincronizado(s).")
