from passlib.context import CryptContext
from jose import jwt
import uuid
import os

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.getenv("SECRET_KEY")

def hash_password(password):
    return pwd_context.hash(password)

def verify_password(password, hashed):
    return pwd_context.verify(password, hashed)

def create_api_key():
    return str(uuid.uuid4())

def create_token(data: dict):
    return jwt.encode(data, SECRET_KEY, algorithm="HS256")