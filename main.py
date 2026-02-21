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
import requests
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)

# ===== CORREÇÃO DAS TABELAS =====
with engine.connect() as conn:
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS pix_key VARCHAR;"))
    conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS user_id INTEGER;"))
    conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS transaction_id VARCHAR;"))
    conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS amount INTEGER;"))
    conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS status VARCHAR;"))
    conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS type VARCHAR;"))
    conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();"))
    conn.commit()
# ================================

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Variáveis de ambiente da Promisse
api_base = os.getenv("API_BASE", "https://api.promisse.com.br/v1")
api_key = os.getenv("PROMISSE_API_KEY")
store_id = os.getenv("PROMISSE_STORE_ID")

SECRET_KEY = os.getenv("SECRET_KEY")
logger.info(f"SECRET_KEY definida: {'sim' if SECRET_KEY else 'não'}")
logger.info(f"PROMISSE_API_KEY definida: {'sim' if api_key else 'não'}")
logger.info(f"PROMISSE_STORE_ID definida: {'sim' if store_id else 'não'}")

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
        # --- INTEGRAÇÃO COM A API DA PROMISSE ---
        amount_real = amount / 100
        payload = {
            "amount": amount_real,
            "storeId": store_id,
            "webhookUrl": "https://revolution-pay.onrender.com/webhook",
        }

        # Verifica se a API key está presente
        if not api_key:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "user_logged_in": True,
                "user_email": user.email,
                "error_message": "Chave da API Promisse não configurada.",
                "back_url": "/deposit"
            }, status_code=500)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        logger.info(f"Enviando requisição para {api_base}/transactions")
        logger.info(f"Payload: {json.dumps(payload)}")
        logger.info(f"Headers: Authorization: Bearer {api_key[:5]}... (oculto)")

        response = requests.post(f"{api_base}/transactions", json=payload, headers=headers, timeout=30)
        
        # Log detalhado da resposta
        logger.info(f"Status code: {response.status_code}")
        logger.info(f"Resposta bruta: {response.text}")
        
        # Se a resposta não for JSON, tenta mostrar o texto
        try:
            data = response.json()
            logger.info(f"Resposta JSON: {json.dumps(data, indent=2)}")
        except:
            data = {"raw": response.text}
            logger.error(f"Resposta não é JSON: {response.text}")

        if response.status_code not in (200, 201):
            error_msg = f"Erro na API Promisse: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return templates.TemplateResponse("error.html", {
                "request": request,
                "user_logged_in": True,
                "user_email": user.email,
                "error_message": error_msg,
                "back_url": "/deposit"
            }, status_code=400)

        # Tentativa de extrair o código Pix de vários campos possíveis
        pix_code = None
        possible_fields = ["brcode", "pix_code", "qr_code", "end_to_end", "pixCopiaECola", "pix", "code", "copiaecola"]
        for field in possible_fields:
            if field in data:
                pix_code = data[field]
                logger.info(f"Código Pix encontrado no campo '{field}': {pix_code[:50]}...")
                break
        
        # Se não achou, tenta procurar em objetos aninhados
        if not pix_code and "pix" in data and isinstance(data["pix"], dict):
            pix_data = data["pix"]
            for field in possible_fields:
                if field in pix_data:
                    pix_code = pix_data[field]
                    logger.info(f"Código Pix encontrado em data['pix']['{field}']")
                    break
        
        if not pix_code:
            # Se ainda não encontrou, lista os campos disponíveis
            campos = list(data.keys())
            error_msg = f"Código Pix não encontrado. Campos disponíveis: {campos}"
            logger.error(error_msg)
            return templates.TemplateResponse("error.html", {
                "request": request,
                "user_logged_in": True,
                "user_email": user.email,
                "error_message": error_msg,
                "back_url": "/deposit"
            }, status_code=500)

        # Gera o QR code a partir do código Pix
        qr = qrcode.make(pix_code)
        buffered = io.BytesIO()
        qr.save(buffered, format="PNG")
        qr_base64 = base64.b64encode(buffered.getvalue()).decode()

        # Salva a transação no banco
        trans = Transaction(
            user_id=user_id,
            transaction_id=data.get("id", str(uuid.uuid4())),
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
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro de conexão com a API: {str(e)}")
        return templates.TemplateResponse("error.html", {
            "request": request,
            "user_logged_in": True,
            "user_email": user.email,
            "error_message": f"Erro de conexão com a API: {str(e)}",
            "back_url": "/deposit"
        }, status_code=500)
    except Exception as e:
        db.rollback()
        logger.error(f"Erro no depósito: {str(e)}", exc_info=True)
        return templates.TemplateResponse("error.html", {
            "request": request,
            "user_logged_in": True,
            "user_email": user.email,
            "error_message": f"Erro interno no depósito: {str(e)}",
            "back_url": "/deposit"
        }, status_code=500)

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
        return templates.TemplateResponse("error.html", {
            "request": request,
            "user_logged_in": True,
            "user_email": user.email,
            "error_message": "Saldo insuficiente para realizar o saque.",
            "back_url": "/withdraw"
        }, status_code=400)
    key = pix_key or user.pix_key
    if not key:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "user_logged_in": True,
            "user_email": user.email,
            "error_message": "Chave Pix obrigatória.",
            "back_url": "/withdraw"
        }, status_code=400)
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
        return templates.TemplateResponse("error.html", {
            "request": request,
            "user_logged_in": True,
            "user_email": user.email,
            "error_message": "Saldo insuficiente para transferência.",
            "back_url": "/transfer"
        }, status_code=400)
    dest = db.query(User).filter(User.email == dest_email).first()
    if not dest:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "user_logged_in": True,
            "user_email": user.email,
            "error_message": "Destinatário não encontrado.",
            "back_url": "/transfer"
        }, status_code=400)
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
        logger.error(f"Erro no histórico: {str(e)}", exc_info=True)
        return templates.TemplateResponse("error.html", {
            "request": request,
            "user_logged_in": True,
            "user_email": user.email,
            "error_message": f"Erro interno no histórico: {str(e)}",
            "back_url": "/dashboard"
        }, status_code=500)

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