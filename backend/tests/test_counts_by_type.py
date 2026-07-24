"""
counts_by_type por tema (para que QuizSetup muestre disponibilidad por tipo y
no proponga un examen de un tipo que no existe).

Verifica que /subjects/{id}/topics y /topics devuelven counts_by_type
{mcq, tf, dev} correcto, incluyendo temas sin preguntas y aislamiento.

In-process (TestClient + mongomock). Preguntas insertadas directamente.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def srv():
    import server
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


def _subj(srv, uid, sid):
    _run(srv.db.subjects.insert_one({"id": sid, "user_id": uid, "name": "Asig", "color": "#111",
                                     "created_at": "2024-01-01T00:00:00+00:00"}))


def _topic(srv, uid, tid, sid):
    _run(srv.db.topics.insert_one({"id": tid, "user_id": uid, "subject_id": sid, "name": "Tema",
                                   "created_at": "2024-01-01T00:00:00+00:00"}))


def _q(srv, uid, qid, sid, tid, qtype):
    _run(srv.db.questions.insert_one({
        "id": qid, "user_id": uid, "subject_id": sid, "topic_id": tid, "topic_name": "T",
        "pdf_source_id": None, "question_type": qtype, "num_options": 3 if qtype == "mcq" else 0,
        "question": "P", "options": ["A", "B", "C"] if qtype != "dev" else [], "correct_index": 0,
        "explanation": "", "model_answer": "m" if qtype == "dev" else "",
        "favorite": False, "difficult": False, "times_answered": 0, "times_correct": 0,
        "srs_next_review": "2999-01-01T00:00:00+00:00", "created_at": "2024-01-01T00:00:00+00:00",
    }))


@pytest.fixture(scope="module")
def data(client, srv):
    uid, h = _auth(client, "cbt@x.com")
    _subj(srv, uid, "cbt_s")
    _topic(srv, uid, "cbt_t1", "cbt_s")
    _topic(srv, uid, "cbt_t2", "cbt_s")  # sin preguntas
    # t1: 2 mcq, 1 tf, 3 dev
    _q(srv, uid, "cbt_q1", "cbt_s", "cbt_t1", "mcq")
    _q(srv, uid, "cbt_q2", "cbt_s", "cbt_t1", "mcq")
    _q(srv, uid, "cbt_q3", "cbt_s", "cbt_t1", "tf")
    _q(srv, uid, "cbt_q4", "cbt_s", "cbt_t1", "dev")
    _q(srv, uid, "cbt_q5", "cbt_s", "cbt_t1", "dev")
    _q(srv, uid, "cbt_q6", "cbt_s", "cbt_t1", "dev")

    # Otro usuario: no debe contaminar los conteos.
    other, _ = _auth(client, "cbt_other@x.com")
    _subj(srv, other, "cbt_sx")
    _topic(srv, other, "cbt_tx", "cbt_sx")
    _q(srv, other, "cbt_qx", "cbt_sx", "cbt_tx", "dev")
    return {"uid": uid, "h": h}


def test_counts_by_type_in_subject_topics(client, data):
    rows = {t["id"]: t for t in _get(client, data["h"], "/api/subjects/cbt_s/topics")}
    assert rows["cbt_t1"]["counts_by_type"] == {"mcq": 2, "tf": 1, "dev": 3}
    assert rows["cbt_t2"]["counts_by_type"] == {"mcq": 0, "tf": 0, "dev": 0}


def test_counts_by_type_in_global_topics(client, data):
    rows = {t["id"]: t for t in _get(client, data["h"], "/api/topics") if t["subject_id"] == "cbt_s"}
    assert rows["cbt_t1"]["counts_by_type"] == {"mcq": 2, "tf": 1, "dev": 3}


def _get(client, h, path):
    r = client.get(path, headers=h)
    assert r.status_code == 200, r.text
    return r.json()
