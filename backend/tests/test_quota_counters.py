"""
Dos contadores de cuota (generaciones y correcciones) con ciclo unificado.

Verifica:
- /usage/me devuelve ambos bloques + retrocompat (flat = generaciones),
- corregir (eval-dev / eval-dev-batch) consume CORRECCIONES, no generaciones,
- batch: 1 corrección por respuesta evaluada,
- ciclo unificado: ambos comparten ai_period_start y se reinician juntos,
- 402 diferenciado ("crear material" vs "correcciones").

In-process (TestClient + mongomock, evaluate_dev_answer mockeado).
"""
import asyncio
from datetime import datetime, timezone, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


async def _fake_eval(question, model_answer, user_answer, key_points):
    return {"score": 7, "feedback": "ok", "key_points_covered": [], "key_points_missing": []}


@pytest.fixture(scope="module")
def srv():
    import server
    server.evaluate_dev_answer = _fake_eval
    # Fijamos límites conocidos (otros módulos los mutan; globals compartidos).
    server.FREE_AI_GENERATIONS_PER_MONTH = 30
    server.FREE_AI_CORRECTIONS_PER_MONTH = 300
    return server


@pytest.fixture(scope="module")
def client(srv):
    with TestClient(srv.app) as c:
        yield c


def _run(coro):
    return asyncio.run(coro)


def _auth(client, email):
    r = client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    r = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert r.status_code == 200, r.text
    return uid, {"Authorization": f"Bearer {r.json()['access_token']}"}


def _dev_q(srv, uid, qid):
    _run(srv.db.questions.insert_one({
        "id": qid, "user_id": uid, "subject_id": "s", "topic_id": "t", "topic_name": "T",
        "pdf_source_id": None, "question_type": "dev", "num_options": 0, "question": "Explica",
        "options": [], "correct_index": 0, "explanation": "p1; p2", "model_answer": "modelo",
        "favorite": False, "difficult": False, "times_answered": 0, "times_correct": 0,
        "srs_next_review": "2999-01-01T00:00:00+00:00", "created_at": "2024-01-01T00:00:00+00:00",
    }))


def _usage(client, h):
    return client.get("/api/usage/me", headers=h).json()


def _batch(client, h, items):
    return client.post("/api/quiz/eval-dev-batch", json={"answers": items}, headers=h)


# --------------------------------------------------------------------------
def test_usage_me_returns_both_blocks(client):
    _, h = _auth(client, "qc_usage@x.com")
    u = _usage(client, h)
    assert u["generations"] == {
        "used": 0, "limit": 30, "remaining": 30,
        "by_type": {"questions": {"used": 0}, "summaries": {"used": 0}, "flashcards": {"used": 0}},
    }
    assert u["corrections"] == {"used": 0, "limit": 300, "remaining": 300}
    # Retrocompat: los campos planos = generaciones.
    assert u["used"] == 0 and u["limit"] == 30 and u["remaining"] == 30
    assert "period_start" in u and "days_until_reset" in u


def test_corrections_consume_correction_counter_only(client, srv):
    uid, h = _auth(client, "qc_corr@x.com")
    for q in ("qc_a", "qc_b", "qc_c"):
        _dev_q(srv, uid, q)
    r = _batch(client, h, [
        {"question_id": "qc_a", "user_answer": "x"},
        {"question_id": "qc_b", "user_answer": "y"},
        {"question_id": "qc_c", "user_answer": ""},  # blanco: no cuenta
    ])
    assert r.status_code == 200, r.text
    u = _usage(client, h)
    assert u["corrections"]["used"] == 2   # 1 por respuesta evaluada (blanco fuera)
    assert u["generations"]["used"] == 0   # las generaciones no se tocan


def test_single_eval_dev_consumes_one_correction(client, srv):
    uid, h = _auth(client, "qc_single@x.com")
    _dev_q(srv, uid, "qc_s1")
    r = client.post("/api/quiz/eval-dev", json={"question_id": "qc_s1", "user_answer": "resp"}, headers=h)
    assert r.status_code == 200, r.text
    assert _usage(client, h)["corrections"]["used"] == 1


def test_unified_period_resets_both(client, srv):
    uid, h = _auth(client, "qc_reset@x.com")
    _dev_q(srv, uid, "qc_r1")
    # Fuerza consumo alto en ambos y un periodo caducado (>30 días).
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    _run(srv.db.users.update_one({"id": uid}, {"$set": {
        "ai_generations_used": 500, "ai_corrections_used": 500, "ai_period_start": old,
    }}))
    # /usage/me (solo lectura) ya muestra ambos reiniciados.
    u = _usage(client, h)
    assert u["generations"]["used"] == 0 and u["corrections"]["used"] == 0
    # Una corrección real reinicia el periodo y consume 1 (los dos a 0 y luego +1).
    assert _batch(client, h, [{"question_id": "qc_r1", "user_answer": "x"}]).status_code == 200
    u = _usage(client, h)
    assert u["corrections"]["used"] == 1
    assert u["generations"]["used"] == 0


def test_402_messages_differ(client, srv):
    uid, h = _auth(client, "qc_402@x.com")
    _dev_q(srv, uid, "qc_e1")
    _dev_q(srv, uid, "qc_e2")

    # Correcciones: límite temporal a 1.
    orig_c = srv.FREE_AI_CORRECTIONS_PER_MONTH
    srv.FREE_AI_CORRECTIONS_PER_MONTH = 1
    try:
        assert _batch(client, h, [{"question_id": "qc_e1", "user_answer": "x"}]).status_code == 200
        r = _batch(client, h, [{"question_id": "qc_e2", "user_answer": "y"}])
        assert r.status_code == 402
        assert "correcciones" in r.json()["detail"].lower()
    finally:
        srv.FREE_AI_CORRECTIONS_PER_MONTH = orig_c

    # Generaciones: mensaje diferente, probado en el helper directamente.
    orig_g = srv.FREE_AI_GENERATIONS_PER_MONTH
    srv.FREE_AI_GENERATIONS_PER_MONTH = 1
    try:
        async def _consume_gen():
            user = await srv.db.users.find_one({"id": uid})
            return await srv.check_and_consume_ai_quota(user, kind="generation", gen_kind="questions")
        _run(_consume_gen())  # 1ª ok
        with pytest.raises(HTTPException) as ei:
            _run(_consume_gen())  # 2ª supera el límite
        assert ei.value.status_code == 402
        assert "crear material" in ei.value.detail.lower()
    finally:
        srv.FREE_AI_GENERATIONS_PER_MONTH = orig_g
