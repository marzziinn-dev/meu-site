from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from database import SessionLocal, engine
from models import Base, User
from auth import hash_password, create_api_key
import os

Base.metadata.create_all(bind=engine)

app = FastAPI()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/register")
def register(email: str, password: str, db: Session = Depends(get_db)):
    user = User(
        email=email,
        password=hash_password(password),
        api_key=create_api_key()
    )
    db.add(user)
    db.commit()
    return {"message": "User created"}

@app.get("/dashboard/{user_id}")
def dashboard(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    return {
        "available": user.balance_available,
        "pending": user.balance_pending
    }