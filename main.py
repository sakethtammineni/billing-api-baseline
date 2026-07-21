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


class CustomerSearch(BaseModel):
    email_query: str


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


# BUG 1 - SQL INJECTION (SECURITY / CRITICAL)
# email_query from the HTTP request is inserted directly into a raw SQL
# string using an f-string. An attacker sends:
#   {"email_query": "' OR '1'='1"}
# This collapses the WHERE clause and returns every row in the customers
# table - full data breach exposing names, emails, balances, and tiers.
@app.post("/customers/search")
def search_customers(payload: CustomerSearch, db: Session = Depends(get_db)):
    query = f"SELECT * FROM customers WHERE email LIKE '%{payload.email_query}%'"
    results = db.execute(text(query)).fetchall()
    return {"results": [dict(row._mapping) for row in results]}


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
    # BUG 3 - RELIABILITY (HIGH)
    # No timeout. No try/except. Invoice is already committed to the database.
    # If the webhook provider is slow or down, this raises an unhandled exception.
    # The API returns HTTP 500. The caller retries. A duplicate invoice is created.
    # The customer is double-billed with no audit trail.
    httpx.post(
        "https://hooks.billing-webhooks.internal/invoice-created",
        json={"invoice_id": invoice.id, "amount": invoice.amount},
    )
    return {"invoice_id": invoice.id, "status": invoice.status, "amount": invoice.amount}


# BUG 2 - RACE CONDITION (LOGIC / CRITICAL)
# Two concurrent top-up requests both read the same wallet_balance before
# either commits. Both add their amount to the stale value. Both commit.
# One top-up is silently lost.
# Example: balance = 1000. Two concurrent +500 requests.
# Both read 1000. Both write 1500. Final balance: 1500 instead of 2000.
# Customer paid for 1000 in credit and received 500. Silent revenue loss.
# Fix: add .with_for_update() to acquire a row-level lock before reading.
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