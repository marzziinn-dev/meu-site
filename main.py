from fastapi import FastAPI, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import SessionLocal, engine
from models import Base, User, Transaction
from auth import hash_password, verify_password, create_api_key, create_token, get_current_user
import os
import logging
import uuid
import qrcode
import base64
import io

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)

with engine.connect() as conn:
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS pix_key VARCHAR;"))
    conn.commit()

app = FastAPI()
templates = Jinja2Templates(directory="templates")

SECRET_KEY = os.getenv("SECRET_KEY")
logger.info(f"SECRET_KEY definida: {'sim' if SECRET_KEY else 'não'}")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    try:
        user_id = get_current_user(request)
        if user_id:
            return RedirectResponse(url="/dashboard", status_code=302)
    except:
        pass
    return templates.TemplateResponse("login.html", {"request": request, "user_logged_in": False})

@app.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    return templates.TemplateResponse("register.html", {"request": request, "user_logged_in": False})

@app.post("/register")
def register(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    logger.info(f"Registro: {email}")
    if db.query(User).filter(User.email == email).first():
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
    logger.info(f"Token gerado no registro: {token[:20]}...")
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=3600*24*7
    )
    return response

@app.post("/login")
def login(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    logger.info(f"Login: {email}")
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password):
        raise HTTPException(400, "Credenciais inválidas")
    token = create_token({"sub": user.id})
    logger.info(f"Token gerado no login: {token[:20]}...")
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=3600*24*7
    )
    return response

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    cookie_token = request.cookies.get("access_token")
    logger.info(f"Cookie recebido no dashboard: {cookie_token[:20] if cookie_token else 'Nenhum'}")
    try:
        user_id = get_current_user(request)
        logger.info(f"Autenticação OK, user_id: {user_id}")
    except HTTPException as e:
        logger.warning(f"Falha na autenticação: {e.detail}")
        return RedirectResponse(url="/")
    user = db.query(User).filter(User.id == user_id).first()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user_logged_in": True,
        "user_email": user.email,
        "available": user.balance_available / 100
    })

@app.get("/deposit", response_class=HTMLResponse)
def deposit_form(request: Request, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
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
    except:
        return RedirectResponse(url="/")
    user = db.query(User).filter(User.id == user_id).first()
    try:
        # --- SIMULAÇÃO DE INTEGRAÇÃO COM A PROMISSE ---
        # Aqui você vai substituir pela chamada real à API
        pix_code = f"pix-{uuid.uuid4().hex[:10]}"
        qr = qrcode.make(pix_code)
        buffered = io.BytesIO()
        qr.save(buffered, format="PNG")
        qr_base64 = base64.b64encode(buffered.getvalue()).decode()
        # ---------------------------------------------

        trans = Transaction(
            user_id=user_id,
            transaction_id=pix_code,
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
        logger.error(f"Erro no depósito: {str(e)}")
        raise HTTPException(500, f"Erro interno no depósito: {str(e)}")

@app.get("/withdraw", response_class=HTMLResponse)
def withdraw_form(request: Request, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
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
    except:
        return RedirectResponse(url="/")
    user = db.query(User).filter(User.id == user_id).first()
    if user.balance_available < amount:
        raise HTTPException(400, "Saldo insuficiente")
    key = pix_key or user.pix_key
    if not key:
        raise HTTPException(400, "Chave Pix obrigatória")
    if pix_key:
        user.pix_key = pix_key
    trans = Transaction(
        user_id=user_id,
        transaction_id=f"withdraw-{uuid.uuid4()}",
        amount=-amount,
        status="approved",
        type="withdraw"
    )
    db.add(trans)
    user.balance_available -= amount
    db.commit()
    return RedirectResponse("/dashboard", 302)

@app.get("/transfer", response_class=HTMLResponse)
def transfer_form(request: Request, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
        return RedirectResponse(url="/")
    user = db.query(User).filter(User.id == user_id).first()
    return templates.TemplateResponse("transfer.html", {
        "request": request,
        "user_logged_in": True,
        "user_email": user.email
    })

@app.post("/transfer")
def create_transfer(request: Request, dest_email: str = Form(...), amount: int = Form(...), db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
        return RedirectResponse(url="/")
    user = db.query(User).filter(User.id == user_id).first()
    if user.balance_available < amount:
        raise HTTPException(400, "Saldo insuficiente")
    dest = db.query(User).filter(User.email == dest_email).first()
    if not dest:
        raise HTTPException(400, "Destinatário não encontrado")
    out = Transaction(
        user_id=user_id,
        transaction_id=f"out-{uuid.uuid4()}",
        amount=-amount,
        status="approved",
        type="transfer_out"
    )
    inc = Transaction(
        user_id=dest.id,
        transaction_id=f"in-{uuid.uuid4()}",
        amount=amount,
        status="approved",
        type="transfer_in"
    )
    user.balance_available -= amount
    dest.balance_available += amount
    db.add_all([out, inc])
    db.commit()
    return RedirectResponse("/dashboard", 302)

@app.get("/history", response_class=HTMLResponse)
def history(request: Request, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
        return RedirectResponse(url="/")
    user = db.query(User).filter(User.id == user_id).first()
    try:
        trans = db.query(Transaction).filter(Transaction.user_id == user_id).order_by(Transaction.id.desc()).all()
        # Converte para lista de dicionários para facilitar no template
        transactions = []
        for t in trans:
            transactions.append({
                "id": t.id,
                "type": t.type,
                "amount": t.amount / 100,
                "status": t.status,
                "created_at": t.created_at.strftime("%d/%m/%Y %H:%M") if t.created_at else ""
            })
        return templates.TemplateResponse("history.html", {
            "request": request,
            "user_logged_in": True,
            "user_email": user.email,
            "transactions": transactions
        })
    except Exception as e:
        logger.error(f"Erro no histórico: {str(e)}")
        raise HTTPException(500, f"Erro interno no histórico: {str(e)}")

@app.get("/settings", response_class=HTMLResponse)
def settings_form(request: Request, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
        return RedirectResponse(url="/")
    user = db.query(User).filter(User.id == user_id).first()
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "user_logged_in": True,
        "user_email": user.email,
        "user": user
    })

@app.post("/settings")
def update_settings(request: Request, pix_key: str = Form(...), db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
        return RedirectResponse(url="/")
    user = db.query(User).filter(User.id == user_id).first()
    user.pix_key = pix_key
    db.commit()
    return RedirectResponse("/settings", 302)

@app.get("/logout")
def logout():
    response = RedirectResponse("/", 302)
    response.delete_cookie("access_token")
    return response