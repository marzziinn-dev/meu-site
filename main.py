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
from fastapi import status
from fastapi.exceptions import HTTPException as FastAPIHTTPException

# Cria as tabelas se não existirem
Base.metadata.create_all(bind=engine)

# ===== CORREÇÃO AUTOMÁTICA DA COLUNA PIX_KEY =====
# Executa uma vez na inicialização para garantir que a coluna exista
with engine.connect() as conn:
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS pix_key VARCHAR;"))
    conn.commit()
# =================================================

app = FastAPI()
templates = Jinja2Templates(directory="templates")

api_base = os.getenv("API_BASE", "https://api.promisse.com.br/v1")
api_key = os.getenv("PROMISSE_API_KEY")  # Verifique se no Render é PROMISSE_API_KEY ou PROMISE_API_KEY
store_id = os.getenv("PROMISSE_STORE_ID")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request: Request, exc: FastAPIHTTPException):
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        return RedirectResponse(url="/")
    return HTMLResponse(content=f"Erro: {exc.detail}", status_code=exc.status_code)

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "user_logged_in": False})

@app.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    return templates.TemplateResponse("register.html", {"request": request, "user_logged_in": False})

@app.post("/register")
def register(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    try:
        # Verifica se a senha excede 72 bytes (limite do bcrypt)
        if len(password.encode('utf-8')) > 72:
            raise HTTPException(400, "Senha muito longa. O máximo permitido é 72 caracteres.")
        
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            raise HTTPException(400, "Email já existe")
        user = User(
            email=email,
            password=hash_password(password),
            api_key=create_api_key()
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_token({"sub": user.id})
        response = RedirectResponse(url="/dashboard", status_code=302)
        response.set_cookie(key="access_token", value=token)
        return response
    except HTTPException:
        raise
    except Exception as e:
        print(f"ERRO NO REGISTRO: {str(e)}")
        raise HTTPException(500, f"Erro interno: {str(e)}")

@app.post("/login")
def login(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user or not verify_password(password, user.password):
            raise HTTPException(400, "Credenciais inválidas")
        token = create_token({"sub": user.id})
        response = RedirectResponse(url="/dashboard", status_code=302)
        response.set_cookie(key="access_token", value=token)
        return response
    except Exception as e:
        print(f"ERRO NO LOGIN: {str(e)}")
        raise HTTPException(500, f"Erro interno: {str(e)}")

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/")
    user = db.query(User).filter(User.id == user_id).first()
    recent_transactions = db.query(Transaction).filter(Transaction.user_id == user_id).order_by(Transaction.id.desc()).limit(5).all()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user_logged_in": True,
        "user_email": user.email,
        "available": user.balance_available / 100,
        "pending": user.balance_pending / 100,
        "recent_transactions": [
            {"id": t.id, "amount": t.amount / 100, "status": t.status, "type": t.type}
            for t in recent_transactions
        ]
    })

@app.get("/deposit", response_class=HTMLResponse)
def deposit_form(request: Request, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/")
    user = db.query(User).filter(User.id == user_id).first()
    return templates.TemplateResponse("deposit.html", {
        "request": request,
        "user_logged_in": True,
        "user_email": user.email
    })

@app.post("/deposit")
def create_deposit(request: Request, amount: int = Form(...), db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/")
    user = db.query(User).filter(User.id == user_id).first()

    payload = {
        "amount": amount // 100,
        "storeId": store_id,
        "webhookUrl": "https://revolution-pay.onrender.com/webhook",
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(f"{api_base}/transactions", json=payload, headers=headers)
        if response.status_code not in (200, 201):
            raise HTTPException(500, f"Erro na API: {response.text}")
        data = response.json()

        trans_id = data["id"]
        pix_code = data.get("end_to_end") or data.get("pix_code") or "pix-code-placeholder"

        qr = qrcode.QRCode()
        qr.add_data(pix_code)
        qr.make(fit=True)
        img = qr.make_image(fill="black", back_color="white")
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        qr_base64 = base64.b64encode(buffered.getvalue()).decode()

        trans = Transaction(
            user_id=user_id,
            transaction_id=trans_id,
            amount=amount,
            status="pending",
            type="deposit"
        )
        db.add(trans)
        user.balance_pending += amount
        db.commit()

        return templates.TemplateResponse("deposit_confirm.html", {
            "request": request,
            "user_logged_in": True,
            "user_email": user.email,
            "qr_base64": qr_base64,
            "pix_code": pix_code,
            "amount": amount / 100
        })
    except Exception as e:
        db.rollback()
        print(f"ERRO NO DEPÓSITO: {str(e)}")
        raise HTTPException(500, str(e))

@app.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    trans_id = data.get("id")
    status = data.get("status")

    if status == "paid":
        trans = db.query(Transaction).filter(Transaction.transaction_id == trans_id).first()
        if trans:
            user = db.query(User).filter(User.id == trans.user_id).first()
            user.balance_pending -= trans.amount
            user.balance_available += trans.amount
            trans.status = "approved"
            db.commit()
    return {"message": "ok"}

@app.get("/withdraw", response_class=HTMLResponse)
def withdraw_form(request: Request, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/")
    user = db.query(User).filter(User.id == user_id).first()
    return templates.TemplateResponse("withdraw.html", {
        "request": request,
        "user_logged_in": True,
        "user_email": user.email,
        "pix_key": user.pix_key
    })

@app.post("/withdraw")
def create_withdraw(request: Request, amount: int = Form(...), pix_key: str = Form(None), db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/")
    user = db.query(User).filter(User.id == user_id).first()
    if user.balance_available < amount:
        raise HTTPException(400, "Saldo insuficiente")
    key = pix_key or user.pix_key
    if not key:
        raise HTTPException(400, "Informe chave Pix")
    if pix_key:
        user.pix_key = pix_key

    payload = {
        "amount": amount // 100,
        "storeId": store_id,
        "webhookUrl": "https://revolution-pay.onrender.com/webhook",
        "receiver": {
            "pix_key": key
        }
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(f"{api_base}/withdraws", json=payload, headers=headers)
        if response.status_code not in (200, 201):
            raise HTTPException(500, f"Erro na API: {response.text}")
        data = response.json()
        trans_id = data["id"]

        trans = Transaction(
            user_id=user_id,
            transaction_id=trans_id,
            amount=-amount,
            status="pending",
            type="withdraw"
        )
        db.add(trans)
        user.balance_available -= amount
        db.commit()
        return RedirectResponse("/dashboard", status_code=302)
    except Exception as e:
        db.rollback()
        print(f"ERRO NO SAQUE: {str(e)}")
        raise HTTPException(500, str(e))

@app.get("/history", response_class=HTMLResponse)
def history(request: Request, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/")
    user = db.query(User).filter(User.id == user_id).first()
    trans = db.query(Transaction).filter(Transaction.user_id == user_id).order_by(Transaction.id.desc()).all()
    return templates.TemplateResponse("history.html", {
        "request": request,
        "user_logged_in": True,
        "user_email": user.email,
        "transactions": [{"id": t.id, "amount": t.amount / 100, "status": t.status, "type": t.type} for t in trans]
    })

@app.get("/logout")
def logout():
    response = RedirectResponse("/", status_code=302)
    response.delete_cookie("access_token")
    return response