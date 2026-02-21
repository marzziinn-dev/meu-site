# Revolution Pay

Um gateway de pagamentos simples integrado com PromissePay, usando FastAPI, SQLAlchemy e HTML templates.

## Setup
1. Crie .env com:
   - SECRET_KEY=seu-secret
   - DATABASE_URL=postgresql://...
   - PROMISSE_API_KEY=sk_live_...
   - API_BASE=https://api.promisse.com.br/v1  # Ajuste se necessário
   - PROMISSE_STORE_ID=seu-store-id-do-dashboard

2. Instale deps: pip install -r requirements.txt
3. Rode local: uvicorn main:app --reload
4. Deploy no Render.

## Features
- Registro/Login
- Dashboard com saldos
- Depósito via Pix (QR aleatório)
- Saque via Pix
- Histórico
- Webhook para confirmações