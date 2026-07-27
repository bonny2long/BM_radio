from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from .config import settings
from .database_dialect import engine_options


def create_application_engine(database_url: str) -> Engine:
    return create_engine(database_url, **engine_options(database_url))


engine = create_application_engine(settings.BM_RADIO_DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
