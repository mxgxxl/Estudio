"""
Smoke test de LÍMITES DE USO DE IA (cuota mensual por usuario) — in-process.

Arranca la app con FastAPI TestClient sobre un Mongo en memoria (ver conftest.py)
y con la generación de IA mockeada. Verifica:

- Un usuario "free" puede generar hasta el límite; la siguiente generación da 402
  (NO 429, NO 401).
- GET /api/usage/me refleja el contador (plan, used, limit, remaining, ...).
- Al avanzar artificialmente ai_period_start (>30 días atrás), la siguiente
  generación reinicia el periodo y vuelve a permitir.
- Un fallo simulado en Gemini revierte el consumo (no se penaliza al usuario).

Se ejecuta sin servicios externos (no llama a Gemini real).
"""
import asyncio

import pytest
from fastapi.testclient import TestClient


# --- Mocks de IA / extracción (igual que el smoke de multiusuario) ---
def _fake_extract_pdf_text(_pdf_bytes: bytes) -> str:
    return ("Temario de prueba. " * 40).strip()


async def _fake_generate_questions(topic_name, source_text, num_questions,
                                   question_type="mcq", num_options=3,
                                   custom_instructions=""):
    return [{
        "question": f"Pregunta {i} de {topic_name}",
        "options": ["A", "B", "C"],
        "correct_index": 0,
        "explanation": "porque sí",
        "question_type": "mcq",
        "num_options": 3,
        "model_answer": "",
    } for i in range(3)]


async def _fake_generate_flashcards(topic_name, source_text, num_cards):
    return [
        {"term": f"Concepto {i}", "definition": f"Definición {i}", "example": ""}
        for i in range(3)
    ]


FREE_LIMIT = 3  # límite pequeño para que el 402 salte rápido en el test


@pytest.fixture(scope="module")
def srv():
    import server
    server.extract_pdf_text = _fake_extract_pdf_text
    server.generate_questions_with_claude = _fake_generate_questions
    server._generate_flashcards_from_text = _fake_generate_flashcards
    # Límite bajo para el plan free (se lee de la global del módulo en runtime).
    server.FREE_AI_GENERATIONS_PER_MONTH = FREE_LIMIT
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


def _create_subject(client, headers, name):
    r = client.post("/api/subjects", json={"name": name}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _upload_topic(client, headers, subject_id, name):
    return client.post(
        f"/api/subjects/{subject_id}/topics/upload",
        data={"name": name, "num_questions": "3", "question_type": "mcq", "num_options": "3"},
        files={"file": ("t.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers=headers,
    )


def _db_update_user(srv, email, fields):
    async def _do():
        await srv.db.users.update_one({"email": email}, {"$set": fields})
    asyncio.run(_do())


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
class TestAiQuota:
    def test_usage_me_initial(self, client):
        assert _register(client, "free1@test.com").status_code == 201
        h = _login(client, "free1@test.com")
        r = client.get("/api/usage/me", headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["plan"] == "free"
        assert body["used"] == 0
        assert body["limit"] == FREE_LIMIT
        assert body["remaining"] == FREE_LIMIT
        assert "period_start" in body and "days_until_reset" in body

    def test_consume_up_to_limit_then_402(self, client):
        h = _login(client, "free1@test.com")
        sub = _create_subject(client, h, "Asig free1")

        # 1ª generación: upload_topic consume 1 -> used=1.
        up = _upload_topic(client, h, sub["id"], "Tema 1")
        assert up.status_code == 200, up.text
        topic_id = up.json()["topic"]["id"]

        usage = client.get("/api/usage/me", headers=h).json()
        assert usage["used"] == 1 and usage["remaining"] == FREE_LIMIT - 1

        # Generaciones de flashcards hasta agotar el límite (used 2, 3 ...).
        for expected_used in range(2, FREE_LIMIT + 1):
            r = client.post(f"/api/topics/{topic_id}/flashcards/generate?num_cards=5", headers=h)
            assert r.status_code == 200, r.text
            u = client.get("/api/usage/me", headers=h).json()
            assert u["used"] == expected_used

        # En el límite: la siguiente generación debe dar 402 (no 429, no 401).
        r = client.post(f"/api/topics/{topic_id}/flashcards/generate?num_cards=5", headers=h)
        assert r.status_code == 402, r.text
        assert "límite" in r.json()["detail"].lower()

        # El contador NO se mueve tras el rechazo.
        u = client.get("/api/usage/me", headers=h).json()
        assert u["used"] == FREE_LIMIT and u["remaining"] == 0

    def test_period_reset_allows_again(self, client, srv):
        h = _login(client, "free1@test.com")
        # Avanzar artificialmente el inicio de periodo > 30 días atrás (y forzar used alto).
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        _db_update_user(srv, "free1@test.com", {"ai_period_start": old, "ai_generations_used": 999})

        # La siguiente generación reinicia el periodo y se permite.
        usage_before = client.get("/api/usage/me", headers=h).json()
        # /usage/me ya muestra el periodo como reiniciado (lectura, sin escribir).
        assert usage_before["used"] == 0

        sub = client.get("/api/subjects", headers=h).json()[0]
        up = _upload_topic(client, h, sub["id"], "Tema tras reset")
        assert up.status_code == 200, up.text

        u = client.get("/api/usage/me", headers=h).json()
        assert u["used"] == 1  # contador reiniciado y consumido 1

    def test_gemini_failure_refunds(self, client, srv):
        assert _register(client, "free2@test.com").status_code == 201
        h = _login(client, "free2@test.com")
        sub = _create_subject(client, h, "Asig free2")

        before = client.get("/api/usage/me", headers=h).json()["used"]
        assert before == 0

        # Simular fallo de Gemini en la generación de preguntas.
        async def _boom(*args, **kwargs):
            raise RuntimeError("fallo simulado de Gemini")

        orig = srv.generate_questions_with_claude
        srv.generate_questions_with_claude = _boom
        try:
            # El fallo se propaga (no es 402). TestClient re-lanza la excepción
            # del servidor; lo importante es que el endpoint reembolse antes.
            with pytest.raises(RuntimeError):
                _upload_topic(client, h, sub["id"], "Tema que falla")
        finally:
            srv.generate_questions_with_claude = orig

        # El consumo se ha revertido: el contador sigue en 0.
        after = client.get("/api/usage/me", headers=h).json()["used"]
        assert after == 0
