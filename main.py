from fastapi import FastAPI, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import SessionLocal, engine
from models import Base, User, Transaction
from auth import hash_password, verify_password, create_api_key, create_token, get_current_user
import os
import requests
import base64
import io
import qrcode
import uuid
from datetime import datetime

Base.metadata.create_all(bind=engine)
with engine.connect() as conn:
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS pix_key VARCHAR;"))
    conn.commit()

app = FastAPI()
templates = Jinja2Templates(directory="templates")

api_base = os.getenv("API_BASE", "https://api.promisse.com.br/v1")
api_key = os.getenv("PROMISSE_API_KEY")
store_id = os.getenv("PROMISSE_STORE_ID")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/")
def root(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "user_logged_in": False})

@app.get("/register")
def register_form(request: Request):
    return templates.TemplateResponse("register.html", {"request": request, "user_logged_in": False})

@app.post("/register")
def register(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(400, "Email já existe")
    user = User(email=email, password=hash_password(password), api_key=create_api_key())
    db.add(user); db.commit(); db.refresh(user)
    response = RedirectResponse("/dashboard", 302)
    response.set_cookie("access_token", create_token({"sub": user.id}))
    return response

@app.post("/login")
def login(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password):
        raise HTTPException(400, "Credenciais inválidas")
    response = RedirectResponse("/dashboard", 302)
    response.set_cookie("access_token", create_token({"sub": user.id}))
    return response

@app.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
        return RedirectResponse("/")
    user = db.query(User).get(user_id)
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user_logged_in": True,
        "user_email": user.email, "available": user.balance_available/100
    })

@app.get("/deposit")
def deposit_form(request: Request, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
        return RedirectResponse("/")
    user = db.query(User).get(user_id)
    return templates.TemplateResponse("deposit.html", {"request": request, "user_logged_in": True, "user_email": user.email})

@app.post("/deposit")
def create_deposit(request: Request, amount: int = Form(...), db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
        return RedirectResponse("/")
    user = db.query(User).get(user_id)
    # Simula integração com API (fallback)
    pix_code = f"pix-{uuid.uuid4().hex[:10]}"
    qr = qrcode.make(pix_code)
    buffered = io.BytesIO()
    qr.save(buffered, format="PNG")
    qr_base64 = base64.b64encode(buffered.getvalue()).decode()
    trans = Transaction(user_id=user_id, transaction_id=pix_code, amount=amount, status="pending", type="deposit")
    db.add(trans)
    user.balance_pending += amount
    db.commit()
    return templates.TemplateResponse("deposit_confirm.html", {
        "request": request, "user_logged_in": True,
        "user_email": user.email, "qr_base64": qr_base64,
        "pix_code": pix_code, "amount": amount/100
    })

@app.get("/withdraw")
def withdraw_form(request: Request, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
        return RedirectResponse("/")
    user = db.query(User).get(user_id)
    return templates.TemplateResponse("withdraw.html", {
        "request": request, "user_logged_in": True,
        "user_email": user.email, "pix_key": user.pix_key
    })

@app.post("/withdraw")
def create_withdraw(request: Request, amount: int = Form(...), pix_key: str = Form(None), db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
        return RedirectResponse("/")
    user = db.query(User).get(user_id)
    if user.balance_available < amount:
        raise HTTPException(400, "Saldo insuficiente")
    key = pix_key or user.pix_key
    if not key:
        raise HTTPException(400, "Chave Pix obrigatória")
    if pix_key:
        user.pix_key = pix_key
    trans = Transaction(user_id=user_id, transaction_id=f"withdraw-{uuid.uuid4()}", amount=-amount, status="approved", type="withdraw")
    db.add(trans)
    user.balance_available -= amount
    db.commit()
    return RedirectResponse("/dashboard", 302)

@app.get("/transfer")
def transfer_form(request: Request, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
        return RedirectResponse("/")
    user = db.query(User).get(user_id)
    return templates.TemplateResponse("transfer.html", {"request": request, "user_logged_in": True, "user_email": user.email})

@app.post("/transfer")
def create_transfer(request: Request, dest_email: str = Form(...), amount: int = Form(...), db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
        return RedirectResponse("/")
    user = db.query(User).get(user_id)
    if user.balance_available < amount:
        raise HTTPException(400, "Saldo insuficiente")
    dest = db.query(User).filter(User.email == dest_email).first()
    if not dest:
        raise HTTPException(400, "Destinatário não encontrado")
    out = Transaction(user_id=user_id, transaction_id=f"out-{uuid.uuid4()}", amount=-amount, status="approved", type="transfer_out")
    inc = Transaction(user_id=dest.id, transaction_id=f"in-{uuid.uuid4()}", amount=amount, status="approved", type="transfer_in")
    user.balance_available -= amount
    dest.balance_available += amount
    db.add_all([out, inc])
    db.commit()
    return RedirectResponse("/dashboard", 302)

@app.get("/history")
def history(request: Request, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
        return RedirectResponse("/")
    user = db.query(User).get(user_id)
    trans = db.query(Transaction).filter(Transaction.user_id == user_id).order_by(Transaction.id.desc()).all()
    return templates.TemplateResponse("history.html", {
        "request": request, "user_logged_in": True,
        "user_email": user.email, "transactions": trans
    })

@app.get("/settings")
def settings_form(request: Request, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
        return RedirectResponse("/")
    user = db.query(User).get(user_id)
    return templates.TemplateResponse("settings.html", {
        "request": request, "user_logged_in": True,
        "user_email": user.email, "user": user
    })

@app.post("/settings")
def update_settings(request: Request, pix_key: str = Form(...), db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
        return RedirectResponse("/")
    user = db.query(User).get(user_id)
    user.pix_key = pix_key
    db.commit()
    return RedirectResponse("/settings", 302)

@app.get("/logout")
def logout():
    response = RedirectResponse("/", 302)
    response.delete_cookie("access_token")
    return response