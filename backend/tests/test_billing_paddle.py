"""
Smoke test de PAGOS con Paddle (Billing v4) — in-process.

Arranca la app con FastAPI TestClient sobre un Mongo en memoria (ver conftest.py).
Verifica:
- /api/billing/checkout exige login y rechaza (409) si el usuario ya es premium.
- Webhook: firma válida -> 200 y usuario actualizado a premium/active.
- Webhook: firma inválida -> 401, sin cambios.
- Idempotencia: mismo event_id dos veces no reprocesa ni duplica.
- subscription.canceled (status canceled) -> plan vuelve a "free".

No llama a Paddle real: firmamos los payloads con el mismo algoritmo del backend.
"""
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient


WEBHOOK_SECRET = "pdl_ntfset_test_secret_123"
PRICE_ID = "pri_test_premium_0001"


@pytest.fixture(scope="module")
def srv():
    import server
    # Configura Paddle en el módulo (el endpoint lee estas globales en runtime).
    server.PADDLE_WEBHOOK_SECRET = WEBHOOK_SECRET
    server.PADDLE_PREMIUM_PRICE_ID = PRICE_ID
    server.PADDLE_ENV = "sandbox"
    return server


@pytest.fixture(scope="module")
def client(srv):
    with TestClient(srv.app) as c:
        yield c


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _register(client, email, password="secret123"):
    return client.post("/api/auth/register", json={"email": email, "password": password})


def _login(client, email, password="secret123"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _sign(secret, body_bytes, ts="1700000000"):
    signed = f"{ts}:".encode("utf-8") + body_bytes
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def _post_webhook(client, payload, secret=WEBHOOK_SECRET, ts="1700000000", bad=False):
    body = json.dumps(payload).encode("utf-8")
    h1 = "deadbeef" if bad else _sign(secret, body, ts)
    return client.post(
        "/api/webhooks/paddle",
        content=body,
        headers={"Paddle-Signature": f"ts={ts};h1={h1}", "Content-Type": "application/json"},
    )


def _sub_event(event_id, event_type, status, email,
               sub_id="sub_test_001", cust_id="ctm_test_001", ends_at="2099-01-01T00:00:00Z"):
    return {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": "2026-01-01T00:00:00Z",
        "data": {
            "id": sub_id,
            "status": status,
            "customer_id": cust_id,
            "customer_email": email,
            "current_billing_period": {"starts_at": "2026-01-01T00:00:00Z", "ends_at": ends_at},
        },
    }


# --------------------------------------------------------------------------
# Checkout
# --------------------------------------------------------------------------
class TestCheckout:
    def test_checkout_requires_login(self, client):
        assert client.post("/api/billing/checkout").status_code == 401

    def test_checkout_returns_data_for_free_user(self, client):
        assert _register(client, "pay1@test.com").status_code == 201
        h = _login(client, "pay1@test.com")
        r = client.post("/api/billing/checkout", headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["price_id"] == PRICE_ID
        assert body["client_token_env"] == "sandbox"
        assert body["customer_email"] == "pay1@test.com"


# --------------------------------------------------------------------------
# Webhook: firma, actualización, idempotencia, cancelación
# --------------------------------------------------------------------------
class TestWebhook:
    def test_invalid_signature_rejected(self, client):
        ev = _sub_event("evt_bad", "subscription.activated", "active", "pay1@test.com")
        r = _post_webhook(client, ev, bad=True)
        assert r.status_code == 401
        # El usuario sigue free.
        h = _login(client, "pay1@test.com")
        assert client.get("/api/billing/status", headers=h).json()["plan"] == "free"

    def test_valid_signature_upgrades_user(self, client):
        ev = _sub_event("evt_001", "subscription.activated", "active", "pay1@test.com")
        r = _post_webhook(client, ev)
        assert r.status_code == 200, r.text
        h = _login(client, "pay1@test.com")
        st = client.get("/api/billing/status", headers=h).json()
        assert st["plan"] == "premium"
        assert st["subscription_status"] == "active"
        assert st["paddle_subscription_id"] == "sub_test_001"
        assert st["current_period_end"] == "2099-01-01T00:00:00Z"

    def test_checkout_409_when_already_premium(self, client):
        h = _login(client, "pay1@test.com")
        assert client.post("/api/billing/checkout", headers=h).status_code == 409

    def test_idempotent_same_event_id(self, client, srv):
        # Reenviar el MISMO event_id no reprocesa (responde duplicate) ni duplica registros.
        ev = _sub_event("evt_001", "subscription.activated", "active", "pay1@test.com")
        r = _post_webhook(client, ev)
        assert r.status_code == 200
        assert r.json().get("duplicate") is True

        async def _count():
            return await srv.db.paddle_events.count_documents({"event_id": "evt_001"})
        import asyncio
        assert asyncio.run(_count()) == 1

    def test_user_not_found_returns_200(self, client):
        ev = _sub_event("evt_ghost", "subscription.activated", "active", "noexiste@test.com",
                        sub_id="sub_ghost_999", cust_id="ctm_ghost_999")
        r = _post_webhook(client, ev)
        assert r.status_code == 200
        assert r.json().get("user_found") is False

    def test_canceled_reverts_to_free(self, client):
        ev = _sub_event("evt_cancel", "subscription.canceled", "canceled", "pay1@test.com")
        r = _post_webhook(client, ev)
        assert r.status_code == 200, r.text
        h = _login(client, "pay1@test.com")
        st = client.get("/api/billing/status", headers=h).json()
        assert st["plan"] == "free"
        assert st["subscription_status"] == "canceled"


def _sub_event_nested(event_id, event_type, status, email,
                      sub_id="sub_nested_1", cust_id="ctm_nested_1", ends_at="2099-01-01T00:00:00Z"):
    """Payload con la ESTRUCTURA REAL de Paddle Billing v4: email dentro de data.customer."""
    return {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": "2026-01-01T00:00:00Z",
        "data": {
            "id": sub_id,
            "status": status,
            "customer_id": cust_id,
            "customer": {"id": cust_id, "email": email},
            "current_billing_period": {"starts_at": "2026-01-01T00:00:00Z", "ends_at": ends_at},
        },
    }


def _sub_event_no_email(event_id, event_type, status,
                        sub_id="sub_apionly_1", cust_id="ctm_apionly_1", ends_at="2099-01-01T00:00:00Z"):
    """Payload SIN email embebido: solo customer_id (hay que resolver vía API)."""
    return {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": "2026-01-01T00:00:00Z",
        "data": {
            "id": sub_id,
            "status": status,
            "customer_id": cust_id,
            "current_billing_period": {"starts_at": "2026-01-01T00:00:00Z", "ends_at": ends_at},
        },
    }


# --------------------------------------------------------------------------
# Resolución del email del cliente (fix del bug email=None)
# --------------------------------------------------------------------------
class TestCustomerEmailResolution:
    def test_email_from_nested_customer_object(self, client):
        """Estructura real: el email viene en data.customer.email."""
        assert _register(client, "nested@test.com").status_code == 201
        ev = _sub_event_nested("evt_nested_1", "subscription.activated", "active", "nested@test.com")
        r = _post_webhook(client, ev)
        assert r.status_code == 200, r.text
        h = _login(client, "nested@test.com")
        st = client.get("/api/billing/status", headers=h).json()
        assert st["plan"] == "premium"
        assert st["subscription_status"] == "active"

    def test_email_resolved_via_paddle_api(self, client, srv, monkeypatch):
        """Sin email embebido: se resuelve por customer_id vía la API de Paddle."""
        assert _register(client, "apionly@test.com").status_code == 201

        calls = {"n": 0}

        async def _fake_fetch(customer_id):
            calls["n"] += 1
            return "apionly@test.com" if customer_id == "ctm_apionly_1" else None

        monkeypatch.setattr(srv, "_fetch_paddle_customer_email", _fake_fetch)

        ev = _sub_event_no_email("evt_apionly_1", "subscription.activated", "active")
        r = _post_webhook(client, ev)
        assert r.status_code == 200, r.text
        assert calls["n"] == 1  # se llamó a la resolución por API

        h = _login(client, "apionly@test.com")
        st = client.get("/api/billing/status", headers=h).json()
        assert st["plan"] == "premium"
        assert st["paddle_subscription_id"] == "sub_apionly_1"
