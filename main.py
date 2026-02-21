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
with engine.connect() as conn:
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS pix_key VARCHAR;"))
    conn.commit()
# =================================================

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
        # LOGS para depuração
        print(f"Tentando registrar: {email}")
        print(f"Senha recebida: {password}")
        print(f"Tamanho da senha: {len(password)} caracteres")
        print(f"Tamanho em bytes: {len(password.encode('utf-8'))}")

        # Verifica se email já existe
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            print("Email já existe")
            raise HTTPException(400, "Email já existe")
        
        # Hash da senha (agora com tratamento interno)
        hashed = hash_password(password)
        print(f"Hash gerado: {hashed[:50]}...")

        user = User(
            email=email,
            password=hashed,
            api_key=create_api_key()
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"Usuário criado com ID: {user.id}")

        token = create_token({"sub": user.id})
        response = RedirectResponse(url="/dashboard", status_code=302)
        response.set_cookie(key="access_token", value=token)
        return response
    except HTTPException:
        raise
    except Exception as e:
        print(f"ERRO NO REGISTRO: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Erro interno: {str(e)}")

@app.post("/login")
def login(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    try:
        print(f"Tentando login: {email}")
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print("Usuário não encontrado")
            raise HTTPException(400, "Credenciais inválidas")
        
        if not verify_password(password, user.password):
            print("Senha inválida")
            raise HTTPException(400, "Credenciais inválidas")
        
        print(f"Login OK para user {user.id}")
        token = create_token({"sub": user.id})
        response = RedirectResponse(url="/dashboard", status_code=302)
        response.set_cookie(key="access_token", value=token)
        return response
    except Exception as e:
        print(f"ERRO NO LOGIN: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Erro interno: {str(e)}")

# (O restante do código permanece igual – dashboard, deposit, withdraw, history, logout)
# Cole abaixo todas as outras rotas que estavam no main.py anterior, a partir de @app.get("/dashboard")
# Para economizar espaço, não vou repetir tudo aqui, mas você deve manter as outras rotas inalteradas.
# Se preferir, posso fornecer o arquivo completo novamente, mas o essencial é a alteração no auth.py e os logs na rota de registro.

# ... (aqui você cola o resto das rotas do main.py que eu já enviei antes, sem alterações)