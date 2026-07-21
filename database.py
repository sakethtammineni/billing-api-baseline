from sqlalchemy import create_engine, Column, Integer, String, Float, text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./billing.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    wallet_balance = Column(Float, default=0.0, nullable=False)
    tier = Column(String, default="standard", nullable=False)


class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, nullable=False)
    amount = Column(Float, nullable=False)
    status = Column(String, default="pending", nullable=False)
    description = Column(String, nullable=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Creates all tables and seeds one customer row if the table is empty."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        count = db.execute(text("SELECT COUNT(*) FROM customers")).scalar()
        if count == 0:
            db.execute(text(
                "INSERT INTO customers (name, email, wallet_balance, tier) "
                "VALUES ('Acme Corp', 'billing@acme.com', 5000.0, 'enterprise')"
            ))
            db.commit()
    finally:
        db.close()