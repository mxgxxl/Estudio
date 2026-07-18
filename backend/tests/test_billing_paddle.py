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


def _sub_event_custom_data(event_id, event_type, status, user_id,
                           sub_id="sub_cd_1", cust_id="ctm_cd_1", ends_at="2099-01-01T00:00:00Z"):
    """Payload SIN email: el emparejamiento debe hacerse por data.custom_data.user_id."""
    return {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": "2026-01-01T00:00:00Z",
        "data": {
            "id": sub_id,
            "status": status,
            "customer_id": cust_id,
            "custom_data": {"user_id": user_id},
            "current_billing_period": {"starts_at": "2026-01-01T00:00:00Z", "ends_at": ends_at},
        },
    }


# --------------------------------------------------------------------------
# Emparejamiento por custom_data.user_id (núcleo robusto) + reordenación
# --------------------------------------------------------------------------
class TestCustomDataMatching:
    def test_match_by_custom_data_user_id_without_email(self, client, srv, monkeypatch):
        """El webhook empareja por custom_data.user_id sin email ni llamada a la API."""
        reg = _register(client, "cd1@test.com")
        assert reg.status_code == 201
        user_id = reg.json()["id"]

        # Si el código cayera al fallback de email, esto se llamaría: lo vigilamos.
        calls = {"n": 0}

        async def _fake_fetch(customer_id):
            calls["n"] += 1
            return None

        monkeypatch.setattr(srv, "_fetch_paddle_customer_email", _fake_fetch)

        ev = _sub_event_custom_data("evt_cd_1", "subscription.activated", "active", user_id)
        r = _post_webhook(client, ev)
        assert r.status_code == 200, r.text
        assert calls["n"] == 0  # NO se recurrió a resolver email

        h = _login(client, "cd1@test.com")
        st = client.get("/api/billing/status", headers=h).json()
        assert st["plan"] == "premium"
        assert st["subscription_status"] == "active"
        assert st["paddle_subscription_id"] == "sub_cd_1"

    def test_invalid_custom_data_user_id_falls_back_to_email(self, client):
        """Un user_id inexistente en custom_data no debe emparejar; cae al fallback email."""
        assert _register(client, "cd2@test.com").status_code == 201
        ev = _sub_event_custom_data(
            "evt_cd_2", "subscription.activated", "active", "id-inexistente-manipulado",
            sub_id="sub_cd_2", cust_id="ctm_cd_2",
        )
        # Añadimos email real embebido para que el fallback lo encuentre.
        ev["data"]["customer"] = {"id": "ctm_cd_2", "email": "cd2@test.com"}
        r = _post_webhook(client, ev)
        assert r.status_code == 200, r.text

        h = _login(client, "cd2@test.com")
        st = client.get("/api/billing/status", headers=h).json()
        assert st["plan"] == "premium"  # emparejó por email, no por el id manipulado

    def test_stored_id_has_priority_over_email(self, client):
        """Si el customer_id guardado apunta a A, gana A aunque el email sea de B."""
        assert _register(client, "prioa@test.com").status_code == 201
        assert _register(client, "priob@test.com").status_code == 201

        # 1er evento: empareja A por email y guarda paddle_customer_id=ctm_prio_A.
        ev1 = _sub_event_nested(
            "evt_prio_1", "subscription.activated", "active", "prioa@test.com",
            sub_id="sub_prio_A", cust_id="ctm_prio_A",
        )
        assert _post_webhook(client, ev1).status_code == 200

        # 2º evento: customer_id=ctm_prio_A (guardado en A) pero email de B.
        # Con la reordenación, el customer_id debe ganar -> afecta a A, no a B.
        ev2 = _sub_event_nested(
            "evt_prio_2", "subscription.updated", "active", "priob@test.com",
            sub_id="sub_prio_A", cust_id="ctm_prio_A",
        )
        assert _post_webhook(client, ev2).status_code == 200

        hb = _login(client, "priob@test.com")
        assert client.get("/api/billing/status", headers=hb).json()["plan"] == "free"
        ha = _login(client, "prioa@test.com")
        assert client.get("/api/billing/status", headers=ha).json()["plan"] == "premium"


# --------------------------------------------------------------------------
# Customer portal (gestión/cancelación de la suscripción)
# --------------------------------------------------------------------------
class TestBillingPortal:
    def test_portal_requires_login(self, client):
        assert client.post("/api/billing/portal").status_code == 401

    def test_portal_no_customer_id_returns_409(self, client):
        # Usuario sin paddle_customer_id -> error claro (409), no 500.
        assert _register(client, "portalfree@test.com").status_code == 201
        h = _login(client, "portalfree@test.com")
        r = client.post("/api/billing/portal", headers=h)
        assert r.status_code == 409
        assert r.json()["detail"]  # mensaje logueable y mostrable

    def test_portal_success_returns_cancel_deep_link(self, client, srv, monkeypatch):
        assert _register(client, "portalok@test.com").status_code == 201
        # Un webhook de suscripción activa guarda paddle_customer_id y subscription_id.
        ev = _sub_event(
            "evt_portal_ok", "subscription.activated", "active", "portalok@test.com",
            sub_id="sub_portal_ok", cust_id="ctm_portal_ok",
        )
        assert _post_webhook(client, ev).status_code == 200

        captured = {}

        async def _fake_portal(customer_id, subscription_id):
            captured["customer_id"] = customer_id
            captured["subscription_id"] = subscription_id
            return {
                "urls": {
                    "general": {"overview": "https://portal.paddle.com/overview"},
                    "subscriptions": [
                        {"id": subscription_id, "cancel_subscription": "https://portal.paddle.com/cancel"}
                    ],
                }
            }

        monkeypatch.setattr(srv, "_create_paddle_portal_session", _fake_portal)

        h = _login(client, "portalok@test.com")
        r = client.post("/api/billing/portal", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["portal_url"] == "https://portal.paddle.com/cancel"
        # Se usaron el customer_id y subscription_id guardados del usuario.
        assert captured["customer_id"] == "ctm_portal_ok"
        assert captured["subscription_id"] == "sub_portal_ok"

    def test_portal_paddle_api_failure_returns_502(self, client, srv, monkeypatch):
        assert _register(client, "portalfail@test.com").status_code == 201
        ev = _sub_event(
            "evt_portal_fail", "subscription.activated", "active", "portalfail@test.com",
            sub_id="sub_portal_fail", cust_id="ctm_portal_fail",
        )
        assert _post_webhook(client, ev).status_code == 200

        async def _boom(customer_id, subscription_id):
            raise srv.HTTPException(
                status_code=502, detail="No se pudo abrir el portal de gestión (permisos de Paddle)"
            )

        monkeypatch.setattr(srv, "_create_paddle_portal_session", _boom)

        h = _login(client, "portalfail@test.com")
        r = client.post("/api/billing/portal", headers=h)
        assert r.status_code == 502
        assert "portal" in r.json()["detail"].lower()


def _sub_event_scheduled(event_id, status, email, scheduled_change,
                         sub_id="sub_sch_1", cust_id="ctm_sch_1", ends_at="2099-06-01T00:00:00Z"):
    """subscription.updated con (o sin) scheduled_change. El usuario sigue active."""
    ev = _sub_event_nested(event_id, "subscription.updated", status, email,
                           sub_id=sub_id, cust_id=cust_id, ends_at=ends_at)
    ev["data"]["scheduled_change"] = scheduled_change
    return ev


# --------------------------------------------------------------------------
# Cancelación programada a fin de periodo (scheduled_change)
# --------------------------------------------------------------------------
class TestScheduledCancellation:
    def test_scheduled_cancel_keeps_premium_and_flags(self, client):
        assert _register(client, "sched@test.com").status_code == 201
        # 1) Alta: premium activo, sin cancelación programada.
        ev1 = _sub_event_nested(
            "evt_sch_active", "subscription.activated", "active", "sched@test.com",
            sub_id="sub_sch_1", cust_id="ctm_sch_1", ends_at="2099-06-01T00:00:00Z",
        )
        assert _post_webhook(client, ev1).status_code == 200
        h = _login(client, "sched@test.com")
        st = client.get("/api/billing/status", headers=h).json()
        assert st["plan"] == "premium" and st["cancel_scheduled"] is False

        # 2) El usuario cancela a fin de periodo: subscription.updated + scheduled_change.
        ev2 = _sub_event_scheduled(
            "evt_sch_cancel", "active", "sched@test.com",
            {"action": "cancel", "effective_at": "2099-06-01T00:00:00Z", "resume_at": None},
        )
        assert _post_webhook(client, ev2).status_code == 200
        st = client.get("/api/billing/status", headers=h).json()
        # Sigue premium hasta que expire, pero ya marcado como cancelación programada.
        assert st["plan"] == "premium"
        assert st["subscription_status"] == "active"
        assert st["cancel_scheduled"] is True
        assert st["current_period_end"] == "2099-06-01T00:00:00Z"

    def test_reactivation_clears_scheduled_flag(self, client):
        # Si Paddle envía scheduled_change=null (el usuario deshizo la baja), el
        # flag debe limpiarse. Test autónomo: fija la baja y luego la revierte.
        assert _register(client, "resume@test.com").status_code == 201
        set_cancel = _sub_event_scheduled(
            "evt_resume_set", "active", "resume@test.com",
            {"action": "cancel", "effective_at": "2099-06-01T00:00:00Z", "resume_at": None},
            sub_id="sub_resume_1", cust_id="ctm_resume_1",
        )
        assert _post_webhook(client, set_cancel).status_code == 200
        h = _login(client, "resume@test.com")
        assert client.get("/api/billing/status", headers=h).json()["cancel_scheduled"] is True

        clear_cancel = _sub_event_scheduled(
            "evt_resume_clear", "active", "resume@test.com", None,
            sub_id="sub_resume_1", cust_id="ctm_resume_1",
        )
        assert _post_webhook(client, clear_cancel).status_code == 200
        st = client.get("/api/billing/status", headers=h).json()
        assert st["plan"] == "premium"
        assert st["cancel_scheduled"] is False
