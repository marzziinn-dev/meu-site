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
logger.info("=== VERIFICAÇÃO DE CREDENCIAIS ===")
logger.info(f"SECRET_KEY definida: {'sim' if SECRET_KEY else 'não'}")
logger.info(f"PROMISSE_API_KEY definida: {'sim' if api_key else 'não'}")
if api_key:
    logger.info(f"PROMISSE_API_KEY (primeiros 10 chars): {api_key[:10]}...")
logger.info(f"PROMISSE_STORE_ID definida: {'sim' if store_id else 'não'}")
if store_id:
    logger.info(f"PROMISSE_STORE_ID: {store_id}")
logger.info("================================")

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

@app.get("/teste-api")
def testar_api():
    """Endpoint para testar a conexão com a API Promisse"""
    if not api_key or not store_id:
        return {"erro": "Credenciais não configuradas"}
    
    try:
        headers = {"Authorization": f"Bearer {api_key}"}
        # Tenta um GET simples para verificar autenticação
        response = requests.get(f"{api_base}/stores/{store_id}", headers=headers, timeout=10)
        return {
            "status_code": response.status_code,
            "resposta": response.text[:500]
        }
    except Exception as e:
        return {"erro": str(e)}

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
        # Validação das credenciais antes de prosseguir
        if not api_key:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "user_logged_in": True,
                "user_email": user.email,
                "error_message": "Chave da API Promisse não configurada. Configure a variável PROMISSE_API_KEY no ambiente do Render.",
                "back_url": "/deposit"
            }, status_code=500)
        
        if not store_id:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "user_logged_in": True,
                "user_email": user.email,
                "error_message": "ID da loja não configurado. Configure a variável PROMISSE_STORE_ID no ambiente do Render.",
                "back_url": "/deposit"
            }, status_code=500)

        amount_real = amount / 100
        payload = {
            "amount": amount_real,
            "storeId": store_id,
            "webhookUrl": "https://revolution-pay.onrender.com/webhook",
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        logger.info(f"Enviando requisição para {api_base}/transactions")
        logger.info(f"Payload: {json.dumps(payload)}")
        logger.info(f"Headers: Authorization: Bearer {api_key[:10]}... (oculto)")

        response = requests.post(f"{api_base}/transactions", json=payload, headers=headers, timeout=30)
        
        logger.info(f"Status code: {response.status_code}")
        logger.info(f"Resposta bruta: {response.text}")
        
        try:
            data = response.json()
            logger.info(f"Resposta JSON: {json.dumps(data, indent=2)}")
        except:
            data = {"raw": response.text}
            logger.error(f"Resposta não é JSON: {response.text}")

        # Se o status code não for sucesso, já trata
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

        # Verifica se a resposta indica erro (mesmo com status 200)
        if data.get("status") == "error":
            error_code = data.get("code", "desconhecido")
            error_msg = f"Erro na API Promisse: {error_code}"
            if data.get("message"):
                error_msg += f" - {data['message']}"
            logger.error(error_msg)
            
            # Mensagem mais amigável para ACCESS_FORBIDDEN
            if error_code == "ACCESS_FORBIDDEN":
                error_msg = "Acesso negado pela API Promisse. Verifique se sua chave de API e store_id estão corretos e ativos."
            
            return templates.TemplateResponse("error.html", {
                "request": request,
                "user_logged_in": True,
                "user_email": user.email,
                "error_message": error_msg,
                "back_url": "/deposit"
            }, status_code=400)

        # Procura o código Pix
        pix_code = None
        possible_fields = ["brcode", "pix_code", "qr_code", "end_to_end", "pixCopiaECola", "pix", "copiaecola"]
        for field in possible_fields:
            if field in data:
                pix_code = data[field]
                logger.info(f"Código Pix encontrado no campo '{field}': {pix_code[:50]}...")
                break
        
        if not pix_code:
            # Se não encontrou, tenta dentro de objetos aninhados
            if "pix" in data and isinstance(data["pix"], dict):
                for field in possible_fields:
                    if field in data["pix"]:
                        pix_code = data["pix"][field]
                        logger.info(f"Código Pix encontrado em data['pix']['{field}']")
                        break
        
        if not pix_code:
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

        # Gera o QR code
        qr = qrcode.make(pix_code)
        buffered = io.BytesIO()
        qr.save(buffered, format="PNG")
        qr_base64 = base64.b64encode(buffered.getvalue()).decode()

        # Salva a transação
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

# As demais rotas (withdraw, transfer, history, settings, logout) permanecem as mesmas
# ... (copie aqui as rotas que já estavam funcionando, pois não houve alteração nelas)