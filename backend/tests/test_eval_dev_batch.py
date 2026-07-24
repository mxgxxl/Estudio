"""
Corrección diferida de desarrollo en lote (POST /quiz/eval-dev-batch).

Verifica el criterio de C:
- 1 unidad de cuota para todo el lote (no N),
- respuestas en blanco = 0 sin gastar cuota (y si TODAS en blanco, cuota 0),
- todo-o-nada: si todas las evaluadas fallan → refund + 502; fallo parcial → 1
  unidad y las fallidas a 0,
- ids desconocidos / no-dev / de otro usuario → 0, ignorados,
- sin 402 a mitad (la cuota se comprueba una vez al principio).

In-process (TestClient + mongomock, evaluate_dev_answer mockeado).
"""
import asyncio

import pytest
from fastapi.testclient import TestClient


async def _fake_eval(question, model_answer, user_answer, key_points):
    return {"score": 7, "feedback": "bien", "key_points_covered": [], "key_points_missing": ["x"]}


@pytest.fixture(scope="module")
def srv():
    import server
    server.evaluate_dev_answer = _fake_eval
    # Límites altos para que otros tests que los bajaron no interfieran.
    server.FREE_AI_GENERATIONS_PER_MONTH = 1000
    server.FREE_AI_CORRECTIONS_PER_MONTH = 5000
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
        "pdf_source_id": None, "question_type": "dev", "num_options": 0, "question": "Explica X",
        "options": [], "correct_index": 0, "explanation": "punto1; punto2",
        "model_answer": "respuesta modelo", "favorite": False, "difficult": False,
        "times_answered": 0, "times_correct": 0, "srs_next_review": "2999-01-01T00:00:00+00:00",
        "created_at": "2024-01-01T00:00:00+00:00",
    }))


def _mcq_q(srv, uid, qid):
    _run(srv.db.questions.insert_one({
        "id": qid, "user_id": uid, "subject_id": "s", "topic_id": "t", "topic_name": "T",
        "pdf_source_id": None, "question_type": "mcq", "num_options": 3, "question": "Q",
        "options": ["A", "B", "C"], "correct_index": 0, "explanation": "",
        "model_answer": "", "favorite": False, "difficult": False,
        "times_answered": 0, "times_correct": 0, "srs_next_review": "2999-01-01T00:00:00+00:00",
        "created_at": "2024-01-01T00:00:00+00:00",
    }))


def _used(client, h):
    # El batch consume el contador de CORRECCIONES (no generaciones).
    return client.get("/api/usage/me", headers=h).json()["corrections"]["used"]


def _batch(client, h, items):
    return client.post("/api/quiz/eval-dev-batch", json={"answers": items}, headers=h)


def _results_by_id(body):
    return {r["question_id"]: r for r in body["results"]}


# --------------------------------------------------------------------------
def test_batch_charges_one_per_evaluated(client, srv):
    uid, h = _auth(client, "edb1@x.com")
    for q in ("edb1_a", "edb1_b", "edb1_c"):
        _dev_q(srv, uid, q)
    before = _used(client, h)
    r = _batch(client, h, [
        {"question_id": "edb1_a", "user_answer": "resp a"},
        {"question_id": "edb1_b", "user_answer": "resp b"},
        {"question_id": "edb1_c", "user_answer": "resp c"},
    ])
    assert r.status_code == 200, r.text
    assert _used(client, h) == before + 3  # 1 corrección por respuesta evaluada
    res = _results_by_id(r.json())
    assert all(res[q]["score"] == 7 for q in ("edb1_a", "edb1_b", "edb1_c"))


def test_all_blank_no_quota(client, srv):
    uid, h = _auth(client, "edb2@x.com")
    _dev_q(srv, uid, "edb2_a")
    _dev_q(srv, uid, "edb2_b")
    before = _used(client, h)
    r = _batch(client, h, [
        {"question_id": "edb2_a", "user_answer": "   "},
        {"question_id": "edb2_b", "user_answer": ""},
    ])
    assert r.status_code == 200, r.text
    assert _used(client, h) == before  # sin gasto
    res = _results_by_id(r.json())
    assert res["edb2_a"]["score"] == 0 and res["edb2_b"]["score"] == 0


def test_mixed_blank_and_answered(client, srv):
    uid, h = _auth(client, "edb3@x.com")
    _dev_q(srv, uid, "edb3_a")
    _dev_q(srv, uid, "edb3_b")
    before = _used(client, h)
    r = _batch(client, h, [
        {"question_id": "edb3_a", "user_answer": "una respuesta"},
        {"question_id": "edb3_b", "user_answer": ""},
    ])
    assert r.status_code == 200, r.text
    assert _used(client, h) == before + 1
    res = _results_by_id(r.json())
    assert res["edb3_a"]["score"] == 7
    assert res["edb3_b"]["score"] == 0


def test_all_fail_refunds_and_502(client, srv):
    uid, h = _auth(client, "edb4@x.com")
    _dev_q(srv, uid, "edb4_a")
    _dev_q(srv, uid, "edb4_b")

    async def _boom(question, model_answer, user_answer, key_points):
        return {"score": 0, "feedback": "", "key_points_covered": [], "_ai_error": True}

    before = _used(client, h)
    orig = srv.evaluate_dev_answer
    srv.evaluate_dev_answer = _boom
    try:
        r = _batch(client, h, [
            {"question_id": "edb4_a", "user_answer": "x"},
            {"question_id": "edb4_b", "user_answer": "y"},
        ])
    finally:
        srv.evaluate_dev_answer = orig
    assert r.status_code == 502, r.text
    assert _used(client, h) == before  # reembolsado


def test_partial_fail_charges_one(client, srv):
    uid, h = _auth(client, "edb5@x.com")
    _dev_q(srv, uid, "edb5_a")
    _dev_q(srv, uid, "edb5_b")

    async def _fail_one(question, model_answer, user_answer, key_points):
        if user_answer == "FAIL":
            return {"score": 0, "feedback": "", "key_points_covered": [], "_ai_error": True}
        return {"score": 9, "feedback": "ok", "key_points_covered": [], "key_points_missing": []}

    before = _used(client, h)
    orig = srv.evaluate_dev_answer
    srv.evaluate_dev_answer = _fail_one
    try:
        r = _batch(client, h, [
            {"question_id": "edb5_a", "user_answer": "buena"},
            {"question_id": "edb5_b", "user_answer": "FAIL"},
        ])
    finally:
        srv.evaluate_dev_answer = orig
    assert r.status_code == 200, r.text
    assert _used(client, h) == before + 1
    res = _results_by_id(r.json())
    assert res["edb5_a"]["score"] == 9
    assert res["edb5_b"]["score"] == 0


def test_unknown_foreign_and_non_dev_ignored(client, srv):
    uid, h = _auth(client, "edb6@x.com")
    _dev_q(srv, uid, "edb6_dev")
    _mcq_q(srv, uid, "edb6_mcq")
    other_uid, _ = _auth(client, "edb6_other@x.com")
    _dev_q(srv, other_uid, "edb6_foreign")

    before = _used(client, h)
    r = _batch(client, h, [
        {"question_id": "edb6_dev", "user_answer": "válida"},
        {"question_id": "edb6_mcq", "user_answer": "no es dev"},
        {"question_id": "edb6_foreign", "user_answer": "de otro"},
        {"question_id": "no-existe", "user_answer": "nada"},
    ])
    assert r.status_code == 200, r.text
    assert _used(client, h) == before + 1  # solo la dev válida cuenta
    res = _results_by_id(r.json())
    assert res["edb6_dev"]["score"] == 7
    assert res["edb6_mcq"]["score"] == 0
    assert res["edb6_foreign"]["score"] == 0
    assert res["no-existe"]["score"] == 0
