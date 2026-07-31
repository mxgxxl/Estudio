"""
Dos ejes de estudio en el backend — SELECCIÓN (all|errors|srs|favorites) ×
COMPORTAMIENTO (practice|exam). El viejo `mode` quedó retirado del todo (Paso B):
ni se acepta en request, ni se deriva, ni se emite en la respuesta.

Cubre:
- quiz_start selecciona el pool por `selection` (cada valor).
- La respuesta trae los ejes y NO `mode`; sin ejes, defaults (all/practice).
- quiz_submit persiste selection/behavior en Attempt (nunca `mode`).
- GET /quiz/available cuenta por selección (gating).
- SRS SOLO avanza en selection=="srs":
  * en srs avanza,
  * fuera de srs no se toca,
  * y (clave) el estado SRS PREVIO de una pregunta queda IDÉNTICO al responderla
    en examen (el bug era que un simulacro reescribía intervalos ya puestos).

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
    uid = client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()["id"]
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, uid


def _insert_q(srv, uid, qid, *, topic_id="t", subject_id="s", question_type="mcq",
              times_answered=0, times_correct=0, favorite=False,
              srs_next_review=None, srs_ease=2.5, srs_interval_days=0.0):
    doc = {
        "id": qid, "user_id": uid, "topic_id": topic_id, "topic_name": "T",
        "subject_id": subject_id, "question_type": question_type, "num_options": 3,
        "question": f"Q {qid}", "options": ["A", "B", "C"], "correct_index": 0,
        "explanation": "", "model_answer": "", "favorite": favorite, "difficult": False,
        "times_answered": times_answered, "times_correct": times_correct,
        "srs_ease": srs_ease, "srs_interval_days": srs_interval_days,
        "srs_next_review": srs_next_review or "2999-01-01T00:00:00+00:00",
    }
    asyncio.run(srv.db.questions.insert_one(doc))


def _get_q(srv, qid):
    return asyncio.run(srv.db.questions.find_one({"id": qid}, {"_id": 0}))


def _start(client, h, **body):
    return client.post("/api/quiz/start", json={"topic_ids": ["t"], "num_questions": 50, **body}, headers=h)


def _ans(qid, selected=0, correct_index=0):
    return {"question_id": qid, "selected": selected, "correct_index": correct_index, "question_type": "mcq"}


def _submit(client, h, answers, **body):
    payload = {"subject_ids": [], "topic_ids": ["t"], "answers": answers,
               "duration_seconds": 10, **body}
    return client.post("/api/quiz/submit", json=payload, headers=h)


def _attempt(srv, attempt_id):
    return asyncio.run(srv.db.attempts.find_one({"id": attempt_id}, {"_id": 0}))


PAST = "2000-01-01T00:00:00+00:00"
FUTURE = "2999-01-01T00:00:00+00:00"


# --- selección por eje nuevo ----------------------------------------------
def test_selection_filters_pool(client, srv):
    h, uid = _auth(client, "sel@x.com")
    _insert_q(srv, uid, "u1")                                  # sin practicar
    _insert_q(srv, uid, "err1", times_answered=3, times_correct=1)   # fallada
    _insert_q(srv, uid, "mastered", times_answered=2, times_correct=2)
    _insert_q(srv, uid, "fav1", favorite=True)
    _insert_q(srv, uid, "due1", srs_next_review=PAST)          # SRS due
    _insert_q(srv, uid, "notdue", srs_next_review=FUTURE)

    def ids(**body):
        r = _start(client, h, **body)
        assert r.status_code == 200, r.text
        return {q["id"] for q in r.json()["questions"]}

    assert ids(selection="errors") == {"err1"}
    assert ids(selection="favorites") == {"fav1"}
    assert ids(selection="srs") == {"due1"}  # solo la due (el resto tiene next_review futuro)
    assert ids(selection="all") == {"u1", "err1", "mastered", "fav1", "due1", "notdue"}


def test_start_response_has_axes(client, srv):
    h, uid = _auth(client, "resp@x.com")
    _insert_q(srv, uid, "r1")
    r = _start(client, h, selection="all", behavior="exam")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["selection"] == "all" and body["behavior"] == "exam"
    assert "mode" not in body  # `mode` retirado de la respuesta (Paso B)


# --- GET /quiz/available (gating por selección) ----------------------------
def test_quiz_available_counts_by_selection(client, srv):
    h, uid = _auth(client, "avail@x.com")
    _insert_q(srv, uid, "av_u")
    _insert_q(srv, uid, "av_err", times_answered=3, times_correct=1)
    _insert_q(srv, uid, "av_fav", favorite=True)
    _insert_q(srv, uid, "av_due", srs_next_review=PAST)

    def count(**params):
        r = client.get("/api/quiz/available", params={"topic_ids": ["t"], **params}, headers=h)
        assert r.status_code == 200, r.text
        return r.json()["count"]

    assert count(selection="all") == 4
    assert count(selection="errors") == 1
    assert count(selection="favorites") == 1
    assert count(selection="srs") == 1


def test_quiz_available_zero_for_empty_selection(client, srv):
    """El caso que gatea el bug: hay preguntas del tipo pero 0 de la selección."""
    h, uid = _auth(client, "avail0@x.com")
    _insert_q(srv, uid, "z1")  # sin fallar, sin favorita, no due (next_review futuro)

    def count(**params):
        r = client.get("/api/quiz/available", params={"topic_ids": ["t"], **params}, headers=h)
        assert r.status_code == 200, r.text
        return r.json()["count"]

    assert count(selection="all") == 1
    assert count(selection="errors") == 0
    assert count(selection="srs") == 0
    assert count(selection="favorites") == 0


# --- Attempt persiste los dos ejes (mode retirado del todo) ----------------
def test_attempt_persists_axes(client, srv):
    h, uid = _auth(client, "att@x.com")
    _insert_q(srv, uid, "a1")

    # Errores jugado como examen: se persisten ambos ejes, nunca `mode`.
    r = _submit(client, h, [_ans("a1")], selection="errors", behavior="exam", penalty_factor=1)
    assert r.status_code == 200, r.text
    at = _attempt(srv, r.json()["attempt_id"])
    assert at["selection"] == "errors" and at["behavior"] == "exam"
    assert "mode" not in at


def test_axes_default_when_absent(client, srv):
    """Sin ejes en el request → defaults tolerantes (all/practice)."""
    h, uid = _auth(client, "defaults@x.com")
    _insert_q(srv, uid, "d1")
    r = _submit(client, h, [_ans("d1")])
    at = _attempt(srv, r.json()["attempt_id"])
    assert at["selection"] == "all" and at["behavior"] == "practice"


# --- SRS solo en selection=="srs" -----------------------------------------
def test_srs_advances_in_srs(client, srv):
    h, uid = _auth(client, "srs_adv@x.com")
    _insert_q(srv, uid, "sadv", srs_next_review=PAST, srs_ease=2.5, srs_interval_days=6.0)
    before = _get_q(srv, "sadv")
    r = _submit(client, h, [_ans("sadv")], selection="srs", behavior="practice")
    assert r.status_code == 200, r.text
    after = _get_q(srv, "sadv")
    assert after["srs_next_review"] != before["srs_next_review"]     # avanzó
    assert after["srs_interval_days"] != before["srs_interval_days"]
    assert after["times_answered"] == before["times_answered"] + 1


def test_existing_srs_state_untouched_in_exam(client, srv):
    """El bug que arreglamos: un simulacro reescribía intervalos SRS ya puestos.
    Una pregunta con estado SRS PREVIO respondida en examen (selection=all) debe
    quedar con los TRES campos idénticos — pero contando la respuesta."""
    h, uid = _auth(client, "srs_keep@x.com")
    _insert_q(srv, uid, "skeep", srs_next_review="2030-06-15T00:00:00+00:00",
              srs_ease=2.9, srs_interval_days=6.0)
    before = _get_q(srv, "skeep")
    r = _submit(client, h, [_ans("skeep")], selection="all", behavior="exam", penalty_factor=1)
    assert r.status_code == 200, r.text
    after = _get_q(srv, "skeep")
    # Estado SRS IDÉNTICO al previo.
    assert after["srs_next_review"] == before["srs_next_review"]
    assert after["srs_ease"] == before["srs_ease"]
    assert after["srs_interval_days"] == before["srs_interval_days"]
    # Pero la respuesta SÍ se contabilizó.
    assert after["times_answered"] == before["times_answered"] + 1
    assert after["last_correct"] is True


