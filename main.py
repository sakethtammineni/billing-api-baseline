from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
import httpx

from database import get_db, init_db, Customer, Invoice

app = FastAPI(title="B2B Billing API", version="1.0.0")


@app.on_event("startup")
def on_startup():
    init_db()


class InvoiceCreate(BaseModel):
    customer_id: int
    amount: float
    description: str = ""


class WalletTopUp(BaseModel):
    customer_id: int
    amount: float


@app.get("/health")
def health():
    return {"status": "ok", "service": "billing-api"}


@app.get("/customers/{customer_id}")
def get_customer(customer_id: int, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return {
        "id": customer.id,
        "name": customer.name,
        "email": customer.email,
        "wallet_balance": customer.wallet_balance,
        "tier": customer.tier,
    }


@app.post("/invoices")
def create_invoice(payload: InvoiceCreate, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == payload.customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Invoice amount must be positive")
    invoice = Invoice(
        customer_id=payload.customer_id,
        amount=payload.amount,
        description=payload.description,
        status="pending",
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return {"invoice_id": invoice.id, "status": invoice.status, "amount": invoice.amount}


@app.post("/wallet/topup")
def wallet_topup(payload: WalletTopUp, db: Session = Depends(get_db)):
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Top-up amount must be positive")
    customer = db.query(Customer).filter(Customer.id == payload.customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    customer.wallet_balance += payload.amount
    db.commit()
    return {"customer_id": customer.id, "new_balance": customer.wallet_balance}