from fastapi import FastAPI, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from database import SessionLocal, engine
from models import Base, User, Transaction, AfiliadoComissao
from auth import hash_password, verify_password, create_api_key, create_token, get_current_user
import os
import logging
import uuid
import base64
import requests
import json
import re
import random
import string
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)

# ===== CORREÇÃO DAS TABELAS =====
with engine.connect() as conn:
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS pix_key VARCHAR;"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS nome_completo VARCHAR;"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS cpf VARCHAR;"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS telefone VARCHAR;"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS rota VARCHAR DEFAULT 'white';"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS codigo_afiliado VARCHAR;"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS afiliado_por INTEGER;"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS comissoes_acumuladas INTEGER DEFAULT 0;"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS total_vendas INTEGER DEFAULT 0;"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS total_reembolsos INTEGER DEFAULT 0;"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS percentual_reembolso FLOAT DEFAULT 0.0;"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();"))
    conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS user_id INTEGER;"))
    conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS transaction_id VARCHAR;"))
    conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS amount INTEGER;"))
    conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS final_amount INTEGER DEFAULT 0;"))
    conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS taxa INTEGER DEFAULT 0;"))
    conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS comissao_afiliado INTEGER DEFAULT 0;"))
    conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS status VARCHAR;"))
    conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS type VARCHAR;"))
    conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();"))
    conn.execute(text("ALTER TABLE afiliado_comissoes ADD COLUMN IF NOT EXISTS afiliado_id INTEGER;"))
    conn.execute(text("ALTER TABLE afiliado_comissoes ADD COLUMN IF NOT EXISTS venda_id INTEGER;"))
    conn.execute(text("ALTER TABLE afiliado_comissoes ADD COLUMN IF NOT EXISTS valor_venda INTEGER;"))
    conn.execute(text("ALTER TABLE afiliado_comissoes ADD COLUMN IF NOT EXISTS comissao INTEGER;"))
    conn.execute(text("ALTER TABLE afiliado_comissoes ADD COLUMN IF NOT EXISTS pago BOOLEAN DEFAULT FALSE;"))
    conn.execute(text("ALTER TABLE afiliado_comissoes ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();"))
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

# ==================== FUNÇÕES AUXILIARES ====================

def validar_cpf(cpf: str) -> bool:
    """Valida se um CPF é matematicamente válido"""
    cpf = re.sub(r'[^0-9]', '', cpf)
    
    if len(cpf) != 11:
        return False
    
    if cpf == cpf[0] * 11:
        return False
    
    # Primeiro dígito
    soma = 0
    for i in range(9):
        soma += int(cpf[i]) * (10 - i)
    resto = 11 - (soma % 11)
    if resto > 9:
        resto = 0
    if int(cpf[9]) != resto:
        return False
    
    # Segundo dígito
    soma = 0
    for i in range(10):
        soma += int(cpf[i]) * (11 - i)
    resto = 11 - (soma % 11)
    if resto > 9:
        resto = 0
    if int(cpf[10]) != resto:
        return False
    
    return True

def gerar_codigo_afiliado():
    """Gera um código de afiliado único"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def calcular_taxa(valor_centavos, rota, user):
    """
    Calcula a taxa baseada na rota do usuário
    Black: 7% + R$1,00 na entrada, R$1,00 na saída
    White: taxa padrão de 3%
    """
    if rota == 'black':
        # Taxa de entrada: 7% + R$1,00
        taxa = int(valor_centavos * 0.07) + 100
        return taxa
    else:  # white
        # Taxa padrão de 3%
        taxa = int(valor_centavos * 0.03)
        return taxa

def verificar_admin(request: Request):
    """Verifica se o usuário tem acesso ao painel administrativo"""
    admin_token = request.cookies.get("admin_token")
    return admin_token == "admin_logado"

# ==================== PAINEL ADMINISTRATIVO ====================
SENHA_ADMIN = "Revolution555mwller"

@app.get("/admin-painel", response_class=HTMLResponse)
def admin_painel_login_form(request: Request, erro: str = None):
    return templates.TemplateResponse("admin_login.html", {
        "request": request,
        "user_logged_in": False,
        "erro": erro
    })

@app.post("/admin-painel")
def admin_painel_login(request: Request, senha: str = Form(...)):
    if senha == SENHA_ADMIN:
        response = RedirectResponse(url="/admin-dashboard", status_code=302)
        response.set_cookie(key="admin_token", value="admin_logado", httponly=True, secure=True, samesite="lax")
        return response
    else:
        return templates.TemplateResponse("admin_login.html", {
            "request": request,
            "user_logged_in": False,
            "erro": "Senha incorreta"
        })

@app.get("/admin-dashboard", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    if not verificar_admin(request):
        return RedirectResponse(url="/admin-painel", status_code=302)
    
    total_usuarios = db.query(User).count()
    total_transacoes = db.query(Transaction).count()
    saldo_total_sistema = db.query(func.sum(User.balance_available)).scalar() or 0
    saldo_pendente_total = db.query(func.sum(User.balance_pending)).scalar() or 0
    transacoes_hoje = db.query(Transaction).filter(
        func.date(Transaction.created_at) == func.current_date()
    ).count()
    
    ultimas_transacoes = db.query(Transaction).order_by(Transaction.id.desc()).limit(20).all()
    usuarios = db.query(User).all()
    
    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "user_logged_in": True,
        "user_email": "ADMINISTRADOR",
        "total_usuarios": total_usuarios,
        "total_transacoes": total_transacoes,
        "saldo_total_sistema": saldo_total_sistema / 100,
        "saldo_pendente_total": saldo_pendente_total / 100,
        "transacoes_hoje": transacoes_hoje,
        "ultimas_transacoes": ultimas_transacoes,
        "usuarios": usuarios
    })

@app.post("/admin/adicionar-saldo")
def admin_adicionar_saldo(
    request: Request,
    user_id: int = Form(...),
    valor: int = Form(...),
    db: Session = Depends(get_db)
):
    if not verificar_admin(request):
        return JSONResponse({"erro": "Acesso negado"}, status_code=403)
    
    user = db.query(User).filter(User.id == user_id).first()
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
    
    return RedirectResponse(url="/admin-dashboard", status_code=302)

@app.post("/admin/remover-saldo")
def admin_remover_saldo(
    request: Request,
    user_id: int = Form(...),
    valor: int = Form(...),
    db: Session = Depends(get_db)
):
    if not verificar_admin(request):
        return JSONResponse({"erro": "Acesso negado"}, status_code=403)
    
    user = db.query(User).filter(User.id == user_id).first()
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
    
    return RedirectResponse(url="/admin-dashboard", status_code=302)

@app.get("/admin/logout")
def admin_logout():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("admin_token")
    return response

# ==================== API PRÓPRIA ====================

@app.get("/api/v1/saldo", response_class=JSONResponse)
def api_saldo(request: Request, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
        return JSONResponse({"erro": "Não autenticado"}, status_code=401)
    
    user = db.query(User).filter(User.id == user_id).first()
    return {
        "user_id": user.id,
        "email": user.email,
        "nome": user.nome_completo,
        "saldo_disponivel": user.balance_available / 100,
        "saldo_pendente": user.balance_pending / 100,
        "moeda": "BRL"
    }

@app.get("/api/v1/transacoes", response_class=JSONResponse)
def api_transacoes(request: Request, limite: int = 10, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
        return JSONResponse({"erro": "Não autenticado"}, status_code=401)
    
    transacoes = db.query(Transaction).filter(
        Transaction.user_id == user_id,
        Transaction.status == "approved"
    ).order_by(Transaction.id.desc()).limit(limite).all()
    
    resultado = []
    for t in transacoes:
        resultado.append({
            "id": t.id,
            "transaction_id": t.transaction_id,
            "tipo": t.type,
            "valor": t.final_amount / 100,
            "status": t.status,
            "data": t.created_at.isoformat() if t.created_at else None
        })
    
    return {"transacoes": resultado}

@app.get("/api/v1/estatisticas", response_class=JSONResponse)
def api_estatisticas(request: Request, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
        return JSONResponse({"erro": "Não autenticado"}, status_code=401)
    
    total_depositos = db.query(func.sum(Transaction.final_amount)).filter(
        Transaction.user_id == user_id,
        Transaction.type == 'deposit',
        Transaction.status == 'approved'
    ).scalar() or 0
    
    total_saques = db.query(func.sum(Transaction.final_amount)).filter(
        Transaction.user_id == user_id,
        Transaction.type == 'withdraw',
        Transaction.status == 'approved'
    ).scalar() or 0
    
    return {
        "total_depositado": abs(total_depositos) / 100,
        "total_sacado": abs(total_saques) / 100,
        "saldo_atual": (db.query(User).filter(User.id == user_id).first().balance_available) / 100
    }

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
def register_form(request: Request, erro: str = None, sucesso: str = None, 
                 nome_completo: str = "", cpf: str = "", email: str = "", 
                 telefone: str = "", codigo_afiliado: str = ""):
    return templates.TemplateResponse("register.html", {
        "request": request,
        "user_logged_in": False,
        "erro": erro,
        "sucesso": sucesso,
        "nome_completo": nome_completo,
        "cpf": cpf,
        "email": email,
        "telefone": telefone,
        "codigo_afiliado": codigo_afiliado
    })

@app.post("/register")
def register(
    request: Request,
    nome_completo: str = Form(...),
    cpf: str = Form(...),
    email: str = Form(...),
    telefone: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    aceitar_termos: str = Form(...),
    rota: str = Form(...),
    codigo_afiliado: str = Form(None),
    db: Session = Depends(get_db)
):
    logger.info(f"Novo registro: {email}")
    
    # ===== VALIDAÇÃO DOS TERMOS =====
    if aceitar_termos != "on":
        return templates.TemplateResponse("register.html", {
            "request": request,
            "user_logged_in": False,
            "erro": "Você precisa aceitar os Termos de Uso e Política de Privacidade.",
            "nome_completo": nome_completo,
            "cpf": cpf,
            "email": email,
            "telefone": telefone,
            "codigo_afiliado": codigo_afiliado
        })
    
    # ===== VALIDAÇÃO DA CONFIRMAÇÃO DE SENHA =====
    if password != confirm_password:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "user_logged_in": False,
            "erro": "As senhas não conferem.",
            "nome_completo": nome_completo,
            "cpf": cpf,
            "email": email,
            "telefone": telefone,
            "codigo_afiliado": codigo_afiliado
        })
    
    # ===== VALIDAÇÃO DO NOME COMPLETO =====
    nome_completo = nome_completo.strip()
    partes = nome_completo.split()
    
    if len(partes) < 2:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "user_logged_in": False,
            "erro": "Nome completo deve conter pelo menos nome e sobrenome (ex: João Silva)",
            "nome_completo": nome_completo,
            "cpf": cpf,
            "email": email,
            "telefone": telefone,
            "codigo_afiliado": codigo_afiliado
        })
    
    for parte in partes:
        if not parte.isalpha():
            return templates.TemplateResponse("register.html", {
                "request": request,
                "user_logged_in": False,
                "erro": "Nome deve conter apenas letras (sem números ou caracteres especiais)",
                "nome_completo": nome_completo,
                "cpf": cpf,
                "email": email,
                "telefone": telefone,
                "codigo_afiliado": codigo_afiliado
            })
    
    # ===== VALIDAÇÃO DO CPF =====
    cpf_limpo = re.sub(r'[^0-9]', '', cpf)
    
    if not cpf_limpo.isdigit() or len(cpf_limpo) != 11:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "user_logged_in": False,
            "erro": "CPF deve conter 11 dígitos numéricos (ex: 123.456.789-00)",
            "nome_completo": nome_completo,
            "cpf": cpf,
            "email": email,
            "telefone": telefone,
            "codigo_afiliado": codigo_afiliado
        })
    
    if not validar_cpf(cpf_limpo):
        return templates.TemplateResponse("register.html", {
            "request": request,
            "user_logged_in": False,
            "erro": "CPF inválido. Digite um CPF válido.",
            "nome_completo": nome_completo,
            "cpf": cpf,
            "email": email,
            "telefone": telefone,
            "codigo_afiliado": codigo_afiliado
        })
    
    # ===== VALIDAÇÃO DO TELEFONE =====
    telefone_limpo = re.sub(r'[^0-9]', '', telefone)
    if len(telefone_limpo) < 10 or len(telefone_limpo) > 11:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "user_logged_in": False,
            "erro": "Telefone inválido. Digite um número com DDD (ex: 11999999999)",
            "nome_completo": nome_completo,
            "cpf": cpf,
            "email": email,
            "telefone": telefone,
            "codigo_afiliado": codigo_afiliado
        })
    
    # ===== VALIDAÇÃO DA SENHA =====
    if len(password) < 5:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "user_logged_in": False,
            "erro": "A senha deve ter no mínimo 5 caracteres.",
            "nome_completo": nome_completo,
            "cpf": cpf,
            "email": email,
            "telefone": telefone,
            "codigo_afiliado": codigo_afiliado
        })
    
    # ===== VALIDAÇÕES DE DUPLICIDADE =====
    if db.query(User).filter(User.email == email).first():
        return templates.TemplateResponse("register.html", {
            "request": request,
            "user_logged_in": False,
            "erro": "Email já cadastrado. Tente outro email.",
            "nome_completo": nome_completo,
            "cpf": cpf,
            "email": email,
            "telefone": telefone,
            "codigo_afiliado": codigo_afiliado
        })
    
    if db.query(User).filter(User.cpf == cpf_limpo).first():
        return templates.TemplateResponse("register.html", {
            "request": request,
            "user_logged_in": False,
            "erro": "CPF já cadastrado em outra conta.",
            "nome_completo": nome_completo,
            "cpf": cpf,
            "email": email,
            "telefone": telefone,
            "codigo_afiliado": codigo_afiliado
        })
    
    # ===== PROCESSAR CÓDIGO DO AFILIADO =====
    afiliado_por_id = None
    if codigo_afiliado:
        afiliado = db.query(User).filter(User.codigo_afiliado == codigo_afiliado).first()
        if afiliado:
            afiliado_por_id = afiliado.id
            logger.info(f"Usuário cadastrado com indicação do afiliado {afiliado.email}")
    
    # ===== CRIAÇÃO DO USUÁRIO =====
    user = User(
        nome_completo=nome_completo,
        cpf=cpf_limpo,
        email=email,
        telefone=telefone_limpo,
        password=hash_password(password),
        api_key=create_api_key(),
        rota=rota,
        codigo_afiliado=gerar_codigo_afiliado(),
        afiliado_por=afiliado_por_id
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    token = create_token({"sub": user.id})
    logger.info(f"Usuário criado: ID {user.id}, rota {rota}, código afiliado {user.codigo_afiliado}")
    
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

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, erro: str = None, email: str = ""):
    return templates.TemplateResponse("login.html", {
      "request": request,
        "user_logged_in": False,
        "erro": erro,
        "email": email
    })

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    logger.info(f"Login: {email}")
    user = db.query(User).filter(User.email == email).first()
    
    if not user or not verify_password(password, user.password):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "user_logged_in": False,
            "erro": "Credenciais inválidas. Verifique seu email e senha.",
            "email": email
        })
    
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
    try:
        user_id = get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/")
    
    user = db.query(User).filter(User.id == user_id).first()
    
    # Estatísticas
    total_depositos = db.query(func.sum(Transaction.final_amount)).filter(
        Transaction.user_id == user_id,
        Transaction.type == 'deposit',
        Transaction.status == 'approved'
    ).scalar() or 0
    
    total_saques = db.query(func.sum(Transaction.final_amount)).filter(
        Transaction.user_id == user_id,
        Transaction.type == 'withdraw',
        Transaction.status == 'approved'
    ).scalar() or 0
    
    transacoes_recentes = db.query(Transaction).filter(
        Transaction.user_id == user_id,
        Transaction.status == 'approved'
    ).order_by(Transaction.id.desc()).limit(5).all()
    
    transacoes_formatadas = []
    for t in transacoes_recentes:
        transacoes_formatadas.append({
            "id": t.id,
            "type": t.type,
            "amount": t.final_amount / 100,
            "status": t.status,
            "created_at": t.created_at.strftime("%d/%m/%Y %H:%M") if t.created_at else ""
        })
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user_logged_in": True,
        "user_email": user.email,
        "user_nome": user.nome_completo,
        "available": user.balance_available / 100,
        "pending": user.balance_pending / 100,
        "total_depositos": abs(total_depositos) / 100,
        "total_saques": abs(total_saques) / 100,
        "transacoes_recentes": transacoes_formatadas,
        "tem_acesso_admin": verificar_admin(request)
    })

@app.get("/afiliados", response_class=HTMLResponse)
def pagina_afiliados(request: Request, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
    except:
        return RedirectResponse(url="/")
    
    user = db.query(User).filter(User.id == user_id).first()
    
    comissoes = db.query(AfiliadoComissao).filter(AfiliadoComissao.afiliado_id == user_id).all()
    indicacoes = db.query(User).filter(User.afiliado_por == user_id).all()
    link_afiliado = f"https://{request.url.hostname}/register?ref={user.codigo_afiliado}"
    
    return templates.TemplateResponse("afiliados.html", {
        "request": request,
        "user_logged_in": True,
        "user_email": user.email,
        "user_nome": user.nome_completo,
        "codigo_afiliado": user.codigo_afiliado,
        "link_afiliado": link_afiliado,
        "comissoes": comissoes,
        "indicacoes": indicacoes,
        "comissoes_acumuladas": user.comissoes_acumuladas / 100
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
        "amount": trans.amount / 100,
        "final_amount": trans.final_amount / 100,
        "type": trans.type,
        "created_at": trans.created_at.isoformat() if trans.created_at else None
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
        trans = db.query(Transaction).filter(
            Transaction.user_id == user_id,
            Transaction.status == "approved"
        ).order_by(Transaction.id.desc()).all()
        
        transactions = []
        for t in trans:
            amount = t.final_amount if t.final_amount != 0 else t.amount
            transactions.append({
                "id": t.id,
                "type": t.type,
                "amount": amount / 100,
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