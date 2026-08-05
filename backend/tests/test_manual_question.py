"""
Autoría manual de preguntas: POST /api/questions (sin IA, sin cuota).

Verifica el alta de MCQ / V-F / desarrollo, la validación cruzada por tipo
(422) y el aislamiento por usuario (404 para tema inexistente o ajeno). El
documento creado debe tener el MISMO schema que las generadas por IA para ser
indistinguible en quizzes y banco.

In-process (TestClient + mongomock).
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


def _auth(client, email):
    assert client.post("/api/auth/register", json={"email": email, "password": "secret123"}).status_code == 201
    r = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_topic(client, h, subject="Asig", topic="Tema 1"):
    s = client.post("/api/subjects", json={"name": subject}, headers=h)
    assert s.status_code == 200, s.text
    sid = s.json()["id"]
    t = client.post(f"/api/subjects/{sid}/topics", json={"name": topic}, headers=h)
    assert t.status_code == 200, t.text
    return sid, t.json()["id"]


def _create(client, h, **body):
    return client.post("/api/questions", json=body, headers=h)


def _get_q(srv, qid):
    return asyncio.run(srv.db.questions.find_one({"id": qid}, {"_id": 0}))


# --- altas válidas ---------------------------------------------------------
def test_create_mcq_ok(client, srv):
    h = _auth(client, "mq_mcq@x.com")
    sid, tid = _make_topic(client, h)
    r = _create(client, h, topic_id=tid, question_type="mcq",
                question_text="¿Capital de Francia?",
                options=["París", "Madrid", "Roma"], correct_answer=0,
                explanation="Es París.")
    assert r.status_code == 201, r.text
    q = r.json()
    assert q["question_type"] == "mcq"
    assert q["question"] == "¿Capital de Francia?"
    assert q["options"] == ["París", "Madrid", "Roma"]
    assert q["correct_index"] == 0
    assert q["num_options"] == 3
    assert q["explanation"] == "Es París."
    assert q["subject_id"] == sid
    assert q["topic_id"] == tid
    assert q["pdf_source_id"] is None
    # Defaults SRS/estado idénticos a las generadas.
    assert q["favorite"] is False and q["difficult"] is False
    assert q["times_answered"] == 0 and q["times_correct"] == 0
    assert q["srs_ease"] == 2.5 and q["srs_interval_days"] == 0
    assert "srs_next_review" in q and "created_at" in q
    # No introducimos `source` (las generadas hoy no lo tienen) ni `_id`.
    assert "source" not in q and "_id" not in q
    # Persistida de verdad.
    assert _get_q(srv, q["id"]) is not None


def test_create_tf_ok(client, srv):
    h = _auth(client, "mq_tf@x.com")
    _, tid = _make_topic(client, h)
    r = _create(client, h, topic_id=tid, question_type="tf",
                question_text="El Sol es una estrella.", correct_answer=0)
    assert r.status_code == 201, r.text
    q = r.json()
    assert q["question_type"] == "tf"
    assert q["options"] == ["Verdadero", "Falso"]
    assert q["correct_index"] == 0
    assert q["num_options"] == 2


def test_create_dev_ok(client, srv):
    h = _auth(client, "mq_dev@x.com")
    _, tid = _make_topic(client, h)
    r = _create(client, h, topic_id=tid, question_type="dev",
                question_text="Explica la fotosíntesis.",
                dev_answer="Proceso por el que las plantas convierten luz en energía.")
    assert r.status_code == 201, r.text
    q = r.json()
    assert q["question_type"] == "dev"
    assert q["options"] == []
    assert q["num_options"] == 0
    assert q["model_answer"].startswith("Proceso por el que")


# --- validación cruzada por tipo (422) -------------------------------------
def test_mcq_without_options_422(client):
    h = _auth(client, "mq_v1@x.com")
    _, tid = _make_topic(client, h)
    r = _create(client, h, topic_id=tid, question_type="mcq",
                question_text="Sin opciones", correct_answer=0)
    assert r.status_code == 422, r.text


def test_mcq_correct_answer_out_of_range_422(client):
    h = _auth(client, "mq_v2@x.com")
    _, tid = _make_topic(client, h)
    r = _create(client, h, topic_id=tid, question_type="mcq",
                question_text="Fuera de rango", options=["A", "B"], correct_answer=5)
    assert r.status_code == 422, r.text


def test_mcq_too_few_options_422(client):
    h = _auth(client, "mq_v3@x.com")
    _, tid = _make_topic(client, h)
    r = _create(client, h, topic_id=tid, question_type="mcq",
                question_text="Una sola opción", options=["A"], correct_answer=0)
    assert r.status_code == 422, r.text


def test_tf_bad_correct_answer_422(client):
    h = _auth(client, "mq_v4@x.com")
    _, tid = _make_topic(client, h)
    r = _create(client, h, topic_id=tid, question_type="tf",
                question_text="V/F mal", correct_answer=2)
    assert r.status_code == 422, r.text


def test_dev_without_dev_answer_422(client):
    h = _auth(client, "mq_v5@x.com")
    _, tid = _make_topic(client, h)
    r = _create(client, h, topic_id=tid, question_type="dev",
                question_text="Sin respuesta modelo")
    assert r.status_code == 422, r.text


def test_bad_question_type_422(client):
    h = _auth(client, "mq_v6@x.com")
    _, tid = _make_topic(client, h)
    r = _create(client, h, topic_id=tid, question_type="essay",
                question_text="Tipo inválido")
    assert r.status_code == 422, r.text


def test_empty_question_text_422(client):
    h = _auth(client, "mq_v7@x.com")
    _, tid = _make_topic(client, h)
    r = _create(client, h, topic_id=tid, question_type="tf",
                question_text="   ", correct_answer=0)
    assert r.status_code == 422, r.text


# --- aislamiento / topic ---------------------------------------------------
def test_topic_not_found_404(client):
    h = _auth(client, "mq_nf@x.com")
    r = _create(client, h, topic_id="nope", question_type="tf",
                question_text="Sin tema", correct_answer=0)
    assert r.status_code == 404, r.text


def test_topic_of_other_user_404(client):
    """El tema de OTRO usuario → 404 (no 403): no revela su existencia."""
    h_owner = _auth(client, "mq_owner@x.com")
    _, tid = _make_topic(client, h_owner)
    h_other = _auth(client, "mq_other@x.com")
    r = _create(client, h_other, topic_id=tid, question_type="tf",
                question_text="Intruso", correct_answer=0)
    assert r.status_code == 404, r.text


# --- sin cuota: crear manual NO consume generaciones -----------------------
def test_manual_does_not_consume_quota(client):
    h = _auth(client, "mq_quota@x.com")
    _, tid = _make_topic(client, h)
    before = client.get("/api/usage/me", headers=h).json()
    for i in range(3):
        r = _create(client, h, topic_id=tid, question_type="tf",
                    question_text=f"Q{i}", correct_answer=i % 2)
        assert r.status_code == 201, r.text
    after = client.get("/api/usage/me", headers=h).json()
    assert after["generations"]["used"] == before["generations"]["used"]
