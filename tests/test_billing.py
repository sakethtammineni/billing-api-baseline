from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

# FALSE POSITIVE - Stripe test-mode key used only in unit test fixtures.
# It has no real authorization scope and cannot process live transactions.
# The pipeline strips test files before sending the diff to the AI so this
# credential never reaches the model. This demonstrates layer-1 noise suppression.
test_stripe_key = "sk_test_4eC39HqLyjWDarjtT1zdp7dc"
test_webhook_secret = "whsec_test_abc123xyz"


def test_health():
    response = client.get("/health")
    assert response.status_code == 200


def test_get_customer_not_found():
    response = client.get("/customers/9999")
    assert response.status_code == 404


def test_create_invoice_negative_amount():
    response = client.post("/invoices", json={
        "customer_id": 1, "amount": -50.0, "description": "Invalid"
    })
    assert response.status_code == 400