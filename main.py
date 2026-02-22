from fastapi import FastAPI, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import SessionLocal, engine
from models import Base, User, Transaction
from auth import hash_password, verify_password, create_api_key, create_token, get_current_user
import os
import logging
import uuid
import base64
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
    conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS final_amount INTEGER DEFAULT 0;"))
    conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS status VARCHAR;"))
    conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS type VARCHAR;"))
    conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();"))
    conn.commit()
# ================================

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Variáveis de ambiente
SECRET_KEY = os.getenv("SECRET_KEY")
PROMISSE_API_KEY = os.getenv("PROMISSE_API_KEY")

logger.info("=== VERIFICAÇÃO DE CREDENCIAIS ===")
logger.info(f"SECRET_KEY definida: {'sim' if SECRET_KEY else 'não'}")
logger.info(f"PROMISSE_API_KEY definida: {'sim' if PROMISSE_API_KEY else 'não'}")
if PROMISSE_API_KEY:
    logger.info(f"PROMISSE_API_KEY (primeiros 10 chars): {PROMISSE_API_KEY[:10]}...")
    logger.info(f"Tamanho da chave: {len(PROMISSE_API_KEY)}")
logger.info("================================")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_admin(request: Request):
    """Verifica se o usuário é admin (pelo cookie)"""
    admin_token = request.cookies.get("admin_token")
    if admin_token != "admin_logado":
        raise HTTPException(status_code=401, detail="Acesso negado")
    return True

# ==================== PAINEL ADMIN SECRETO ====================
SENHA_ADMIN = "Revolution555mwller"

@app.get("/admin-painel-9f3k2d", response_class=HTMLResponse)
def admin_login_form(request: Request):
    return templates.TemplateResponse("admin_login.html", {
        "request": request,
        "user_logged_in": False
    })

@app.post("/admin-painel-9f3k2d")
def admin_login(request: Request, senha: str = Form(...)):
    if senha == SENHA_ADMIN:
        response = RedirectResponse(url="/admin-dashboard-7h4g9w", status_code=302)
        response.set_cookie(key="admin_token", value="admin_logado", httponly=True)
        return response
    else:
        return templates.TemplateResponse("admin_login.html", {
            "request": request,
            "user_logged_in": False,
            "erro": "Senha incorreta"
        })

@app.get("/admin-dashboard-7h4g9w", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db), admin: bool = Depends(get_admin)):
    usuarios = db.query(User).all()
    transacoes = db.query(Transaction).order_by(Transaction.id.desc()).limit(50).all()
    
    stats = {
        "total_usuarios": len(usuarios),
        "saldo_total": sum(u.balance_available for u in usuarios) / 100,
        "saldo_pendente": sum(u.balance_pending for u in usuarios) / 100,
        "total_transacoes": db.query(Transaction).count()
    }
    
    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "user_logged_in": True,
        "user_email": "ADMIN",
        "usuarios": usuarios,
        "transacoes": transacoes,
        "stats": stats
    })

@app.post("/admin/adicionar-saldo")
def admin_adicionar_saldo(
    request: Request,
    email: str = Form(...),
    valor: int = Form(...),
    db: Session = Depends(get_db),
    admin: bool = Depends(get_admin)
):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return JSONResponse({"erro": "Usuário não encontrado"}, status_code=404)
    
    user.balance_available += valor
    trans = Transaction(
        user_id=user.id,
        transaction_id=f"admin_add_{uuid.uuid4()}",
        amount=valor,
        final_amount=valor,
        status="approved",
        type="deposit"
    )
    db.add(trans)
    db.commit()
    
    return RedirectResponse(url="/admin-dashboard-7h4g9w", status_code=302)

@app.post("/admin/remover-saldo")
def admin_remover_saldo(
    request: Request,
    email: str = Form(...),
    valor: int = Form(...),
    db: Session = Depends(get_db),
    admin: bool = Depends(get_admin)
):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return JSONResponse({"erro": "Usuário não encontrado"}, status_code=404)
    
    if user.balance_available < valor:
        return JSONResponse({"erro": "Saldo insuficiente"}, status_code=400)
    
    user.balance_available -= valor
    trans = Transaction(
        user_id=user.id,
        transaction_id=f"admin_remove_{uuid.uuid4()}",
        amount=-valor,
        final_amount=-valor,
        status="approved",
        type="withdraw"
    )
    db.add(trans)
    db.commit()
    
    return RedirectResponse(url="/admin-dashboard-7h4g9w", status_code=302)

@app.get("/admin/usuarios/{user_id}")
def admin_usuario_detalhe(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: bool = Depends(get_admin)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return JSONResponse({"erro": "Usuário não encontrado"}, status_code=404)
    
    transacoes = db.query(Transaction).filter(Transaction.user_id == user_id).order_by(Transaction.id.desc()).all()
    
    return templates.TemplateResponse("admin_usuario.html", {
        "request": request,
        "user_logged_in": True,
        "user_email": "ADMIN",
        "usuario": user,
        "transacoes": transacoes
    })

@app.get("/admin/recuperar-transacoes")
def recuperar_transacoes(request: Request, db: Session = Depends(get_db), admin: bool = Depends(get_admin)):
    pendentes = db.query(Transaction).filter(
        Transaction.status == "pending",
        Transaction.type == "deposit"
    ).all()
    
    resultados = []
    for trans in pendentes:
        user = db.query(User).filter(User.id == trans.user_id).first()
        if user:
            user.balance_pending -= trans.final_amount
            user.balance_available += trans.final_amount
            trans.status = "approved"
            resultados.append({
                "id": trans.id,
                "user_email": user.email,
                "amount": trans.amount,
                "final_amount": trans.final_amount,
                "status": "approved (recuperado)"
            })
    
    db.commit()
    return {
        "mensagem": "Recuperação concluída",
        "transacoes_recuperadas": resultados
    }

@app.get("/admin/logout")
def admin_logout():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("admin_token")
    return response

# ==================== ROTAS NORMAIS DO SITE ====================

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

@app.get("/api/verificar-transacao/{transaction_id}")
def verificar_transacao(transaction_id: str, request: Request, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
        return JSONResponse({"erro": "Não autenticado"}, status_code=401)
    
    trans = db.query(Transaction).filter(
        Transaction.transaction_id == transaction_id,
        Transaction.user_id == user_id
    ).first()
    
    if not trans:
        return JSONResponse({"erro": "Transação não encontrada"}, status_code=404)
    
    return JSONResponse({
        "status": trans.status,
        "amount": trans.amount,
        "final_amount": trans.final_amount
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
def create_deposit(request: Request, 
                   amount: int = Form(...), 
                   final_amount: int = Form(...),
                   db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
        return RedirectResponse(url="/")
    user = db.query(User).filter(User.id == user_id).first()

    if not PROMISSE_API_KEY:
        logger.error("PROMISSE_API_KEY não configurada")
        return templates.TemplateResponse("error.html", {
            "request": request,
            "user_logged_in": True,
            "user_email": user.email,
            "error_message": "Chave da API Promisse não configurada.",
            "back_url": "/deposit"
        }, status_code=500)

    payload = {
        "amount": amount,
        "webhook": "https://revolution-pay.onrender.com/webhook"
    }

    headers = {
        "Authorization": PROMISSE_API_KEY,
        "Content-Type": "application/json"
    }

    url = "https://api.promisse.com.br/transactions"
    
    logger.info(f"Enviando requisição para {url}")
    logger.info(f"Payload: {json.dumps(payload)}")

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        logger.info(f"Status code: {response.status_code}")
        logger.info(f"Resposta: {response.text}")

        if response.status_code not in (200, 201):
            return templates.TemplateResponse("error.html", {
                "request": request,
                "user_logged_in": True,
                "user_email": user.email,
                "error_message": f"Erro na API: {response.status_code} - {response.text}",
                "back_url": "/deposit"
            }, status_code=400)

        data = response.json()
        if data.get("status") == "error":
            return templates.TemplateResponse("error.html", {
                "request": request,
                "user_logged_in": True,
                "user_email": user.email,
                "error_message": f"Erro: {data.get('code', 'desconhecido')}",
                "back_url": "/deposit"
            }, status_code=400)

        qr_base64 = data.get("qrCodeBase64", "")
        if qr_base64.startswith("data:image/png;base64,"):
            qr_base64 = qr_base64.replace("data:image/png;base64,", "")
        pix_code = data.get("copyPaste", "")
        transaction_id = data.get("id", str(uuid.uuid4()))

        trans = Transaction(
            user_id=user_id,
            transaction_id=transaction_id,
            amount=amount,
            final_amount=final_amount,
            status="pending",
            type="deposit"
        )
        db.add(trans)
        user.balance_pending += final_amount
        db.commit()

        return templates.TemplateResponse("deposit_confirm.html", {
            "request": request,
            "user_logged_in": True,
            "user_email": user.email,
            "qr_base64": qr_base64,
            "pix_code": pix_code,
            "amount": amount / 100,
            "transaction_id": transaction_id
        })

    except Exception as e:
        db.rollback()
        logger.error(f"Erro: {str(e)}")
        return templates.TemplateResponse("error.html", {
            "request": request,
            "user_logged_in": True,
            "user_email": user.email,
            "error_message": f"Erro interno: {str(e)}",
            "back_url": "/deposit"
        }, status_code=500)

@app.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    logger.info(f"📩 Webhook recebido: {json.dumps(data, indent=2)}")
    
    trans_id = data.get("id")
    status = data.get("status")
    
    if status == "paid":
        trans = db.query(Transaction).filter(Transaction.transaction_id == trans_id).first()
        if trans and trans.status == "pending":
            user = db.query(User).filter(User.id == trans.user_id).first()
            if user:
                user.balance_pending -= trans.final_amount
                user.balance_available += trans.final_amount
                trans.status = "approved"
                db.commit()
                logger.info(f"✅ Pagamento confirmado: {trans_id}, valor líquido: {trans.final_amount}")
            else:
                logger.error(f"❌ Usuário não encontrado para transação {trans_id}")
        else:
            logger.warning(f"⚠️ Transação {trans_id} já processada ou não encontrada")
    
    return {"message": "ok"}

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
        "pix_key": user.pix_key,
        "available": user.balance_available / 100
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
            "error_message": f"Saldo insuficiente. Disponível: R$ {user.balance_available/100:.2f}",
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
        final_amount=-amount,
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
        "user_email": user.email,
        "available": user.balance_available / 100
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
            "error_message": f"Saldo insuficiente. Disponível: R$ {user.balance_available/100:.2f}",
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
        final_amount=-amount,
        status="approved",
        type="transfer_out"
    )
    inc = Transaction(
        user_id=dest.id,
        transaction_id=f"in-{uuid.uuid4()}",
        amount=amount,
        final_amount=amount,
        status="a