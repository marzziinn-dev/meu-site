from sqlalchemy import Column, Integer, String, ForeignKey
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True)
    password = Column(String)
    api_key = Column(String, unique=True)
    balance_available = Column(Integer, default=0)
    balance_pending = Column(Integer, default=0)

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    promise_id = Column(String)
    amount = Column(Integer)
    status = Column(String)