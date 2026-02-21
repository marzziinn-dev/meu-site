from passlib.context import CryptContext
from jose import jwt, JWTError
import uuid
import os
from fastapi import HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"

# Configuração para receber token do cookie ou header
class TokenFromCookieOrHeader(HTTPBearer):
    async def __call__(self, request: Request) -> Optional[HTTPAuthorizationCredentials]:
        # Primeiro tenta pegar do cookie
        token = request.cookies.get("access_token")
        if token:
            return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        
        # Se não tiver no cookie, tenta do header (padrão HTTPBearer)
        try:
            return await super().__call__(request)
        except:
            return None

oauth2_scheme = TokenFromCookieOrHeader(auto_error=False)

def hash_password(password):
    return pwd_context.hash(password)

def verify_password(password, hashed):
    return pwd_context.verify(password, hashed)

def create_api_key():
    return str(uuid.uuid4())

def create_token(data: dict):
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: Optional[str] = None, request: Request = None):
    """
    Versão simplificada que pode ser usada com dependência manual
    """
    # Se token não foi passado, tenta pegar do request
    if not token and request:
        token = request.cookies.get("access_token")
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não autenticado"
        )
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token inválido"
            )
        return user_id
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido"
        )

# Dependência para usar nas rotas
async def get_current_user_dep(request: Request):
    return get_current_user(request=request)