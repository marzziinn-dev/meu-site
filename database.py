from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

DATABASE_URL = os.getenv("DATABASE_URL")

# Configuração do pool de conexões para evitar esgotamento
engine = create_engine(
    DATABASE_URL,
    pool_size=20,          # Conexões fixas no pool
    max_overflow=30,       # Conexões extras além do pool_size (total = 50)
    pool_timeout=60,       # Tempo máximo de espera por uma conexão (segundos)
    pool_pre_ping=True,    # Verifica se a conexão está viva antes de usar
    pool_recycle=3600      # Recicla conexões após 1 hora para evitar expiração
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()