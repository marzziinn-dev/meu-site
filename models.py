from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Boolean, Float
from sqlalchemy.sql import func
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    nome_completo = Column(String, nullable=False)
    cpf = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True, nullable=False)
    telefone = Column(String, nullable=False)
    password = Column(String, nullable=False)
    api_key = Column(String, unique=True)
    
    # Campos de rota (Black/White)
    rota = Column(String, nullable=False, default="white")  # 'black' ou 'white'
    
    # Campos de afiliado
    codigo_afiliado = Column(String, unique=True)  # Código único para compartilhar
    afiliado_por = Column(Integer, ForeignKey("users.id"), nullable=True)  # Quem indicou
    comissoes_acumuladas = Column(Integer, default=0)  # Em centavos
    
    # Saldos
    balance_available = Column(Integer, default=0)
    balance_pending = Column(Integer, default=0)
    pix_key = Column(String, nullable=True)
    
    # Estatísticas
    total_vendas = Column(Integer, default=0)
    total_reembolsos = Column(Integer, default=0)
    percentual_reembolso = Column(Float, default=0.0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    transaction_id = Column(String)
    amount = Column(Integer)  # Valor original em centavos
    final_amount = Column(Integer, default=0)  # Valor líquido após taxas
    taxa = Column(Integer, default=0)  # Taxa cobrada em centavos
    comissao_afiliado = Column(Integer, default=0)  # Comissão paga ao afiliado
    status = Column(String)
    type = Column(String)  # deposit, withdraw, transfer_in, transfer_out
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AfiliadoComissao(Base):
    __tablename__ = "afiliado_comissoes"

    id = Column(Integer, primary_key=True)
    afiliado_id = Column(Integer, ForeignKey("users.id"))
    venda_id = Column(Integer, ForeignKey("transactions.id"))
    valor_venda = Column(Integer)  # Valor da venda em centavos
    comissao = Column(Integer)  # Comissão ganha em centavos
    pago = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())