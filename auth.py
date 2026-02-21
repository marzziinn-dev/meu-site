import bcrypt
from jose import jwt, JWTError
import uuid
import os
from fastapi import HTTPException, Request
import logging

logger = logging.getLogger(__name__)

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"

def hash_password(password):
    if isinstance(password, str):
        password_bytes = password.encode('utf-8')
    else:
        password_bytes = password
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')

def verify_password(password, hashed):
    if isinstance(password, str):
        password_bytes = password.encode('utf-8')
    else:
        password_bytes = password
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]
    if isinstance(hashed, str):
        hashed_bytes = hashed.encode('utf-8')
    else:
        hashed_bytes = hashed
    return bcrypt.checkpw(password_bytes, hashed_bytes)

def create_api_key():
    return str(uuid.uuid4())

def create_token(data: dict):
    if 'sub' in data:
        data['sub'] = str(data['sub'])
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Não autenticado")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str: str = payload.get("sub")
        if user_id_str is None:
            raise HTTPException(status_code=401, detail="Token inválido: sem sub")
        user_id = int(user_id_str)
        return user_id
    except ValueError:
        raise HTTPException(status_code=401, detail="Token inválido: sub não é um número")
    except JWTError as e:
        logger.error(f"JWTError detalhado: {str(e)}")
        raise HTTPException(status_code=401, detail=f"Token inválido: {str(e)}")