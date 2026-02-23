from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.sql import func
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    nome_completo = Column(String, nullable=False)
    cpf = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True, nullable=False)
    telefone = Column(String, nullable=False)  # NOVO CAMPO
    password = Column(String, nullable=False)
    api_key = Column(String, unique=True)
    balance_available = Column(Integer, default=0)
    balance_pending = Column(Integer, default=0)
    pix_key = Column(String, nullable=True)

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    transaction_id = Column(String)
    amount = Column(Integer)
    final_amount = Column(Integer, default=0)
    status = Column(String)
    type = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())