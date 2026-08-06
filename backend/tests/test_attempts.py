"""
Snapshot por pregunta (Attempt.items) + endpoints de historial de intentos:
GET /api/attempts (paginado, filtros, aislamiento) y GET /api/attempts/{id}.

- quiz_submit persiste `items` cuando llega `snapshot` (is_correct recalculado en
  el backend; dev conserva user_answer/dev_score/feedback). Sin snapshot → sin items.
- Aislamiento multiusuario en ambos endpoints.

In-process (TestClient + mongomock). quiz_submit tolera qids inexistentes, así que
no hace falta sembrar preguntas.
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


def _submit(client, h, *, answers, snapshot=None, behavior="exam", selection="all",
            subject_ids=None, topic_ids=None):
    body = {
        "behavior": behavior, "selection": selection,
        "subject_ids": subject_ids or [], "topic_ids": topic_ids or [],
        "answers": answers, "duration_seconds": 42,
    }
    if snapshot is not None:
        body["snapshot"] = snapshot
    return client.post("/api/quiz/submit", json=body, headers=h)


def _attempt_doc(srv, aid):
    return asyncio.run(srv.db.attempts.find_one({"id": aid}, {"_id": 0}))


# --- snapshot en quiz_submit ------------------------------------------------
def test_submit_persists_snapshot(client, srv):
    h = _auth(client, "att_snap@x.com")
    answers = [
        {"question_id": "m1", "selected": 2, "correct_index": 2, "question_type": "mcq"},
        {"question_id": "t1", "selected": 1, "correct_index": 0, "question_type": "tf"},
        {"question_id": "d1", "selected": -1, "correct_index": -1, "question_type": "dev", "dev_score": 7},
    ]
    snapshot = [
        # El cliente MIENTE is_correct=False en la mcq acertada: el backend lo recalcula.
        {"question_id": "m1", "question_type": "mcq", "question": "¿2+2?",
         "options": ["3", "5", "4"], "selected": 2, "correct_index": 2, "is_correct": False},
        {"question_id": "t1", "question_type": "tf", "question": "El cielo es azul",
         "options": ["Verdadero", "Falso"], "selected": 1, "correct_index": 0},
        {"question_id": "d1", "question_type": "dev", "question": "Explica X", "options": [],
         "selected": -1, "correct_index": -1, "user_answer": "mi respuesta", "dev_score": 7, "feedback": "bien"},
    ]
    r = _submit(client, h, answers=answers, snapshot=snapshot)
    assert r.status_code == 200, r.text
    items = _attempt_doc(srv, r.json()["attempt_id"])["items"]
    assert len(items) == 3
    # mcq: opciones en orden mostrado; is_correct recalculado (selected==correct) → True.
    assert items[0]["options"] == ["3", "5", "4"] and items[0]["selected"] == 2
    assert items[0]["is_correct"] is True
    # tf: selected 1 != correct 0 → False.
    assert items[1]["is_correct"] is False
    # dev: display + is_correct por umbral (dev_score 7 >= 5).
    assert items[2]["user_answer"] == "mi respuesta" and items[2]["dev_score"] == 7.0
    assert items[2]["feedback"] == "bien" and items[2]["is_correct"] is True


def test_submit_without_snapshot_has_no_items(client, srv):
    h = _auth(client, "att_nosnap@x.com")
    answers = [{"question_id": "m1", "selected": 0, "correct_index": 0, "question_type": "mcq"}]
    r = _submit(client, h, answers=answers)
    assert r.status_code == 200, r.text
    assert _attempt_doc(srv, r.json()["attempt_id"]).get("items") is None


def test_submit_snapshot_mismatch_400(client):
    h = _auth(client, "att_mismatch@x.com")
    answers = [{"question_id": "m1", "selected": 0, "correct_index": 0, "question_type": "mcq"}]
    snapshot = [{"question_id": "OTRA", "question_type": "mcq", "options": ["a", "b"],
                 "selected": 0, "correct_index": 0}]
    r = _submit(client, h, answers=answers, snapshot=snapshot)
    assert r.status_code == 400, r.text


# --- GET /attempts (listado) ------------------------------------------------
def _mcq_answer(qid):
    return [{"question_id": qid, "selected": 0, "correct_index": 0, "question_type": "mcq"}]


def _mcq_snap(qid):
    return [{"question_id": qid, "question_type": "mcq", "question": "Q",
             "options": ["a", "b"], "selected": 0, "correct_index": 0}]


def test_list_attempts_pagination_and_order(client):
    h = _auth(client, "att_list@x.com")
    ids = []
    for i in range(3):
        snap = _mcq_snap(f"q{i}") if i == 2 else None
        beh = "exam" if i == 2 else "practice"
        ids.append(_submit(client, h, answers=_mcq_answer(f"q{i}"), snapshot=snap, behavior=beh).json()["attempt_id"])

    p1 = client.get("/api/attempts?page=1&limit=2", headers=h).json()
    assert p1["total"] == 3 and p1["page"] == 1 and p1["limit"] == 2
    assert len(p1["items"]) == 2
    assert p1["items"][0]["id"] == ids[2]                       # más reciente primero
    assert p1["items"][0]["has_items"] is True                 # el 3º trae snapshot
    assert p1["items"][0]["behavior"] == "exam"
    assert p1["items"][1]["has_items"] is False

    p2 = client.get("/api/attempts?page=2&limit=2", headers=h).json()
    assert len(p2["items"]) == 1 and p2["items"][0]["id"] == ids[0]


def test_list_attempts_filters(client):
    h = _auth(client, "att_filter@x.com")
    _submit(client, h, answers=_mcq_answer("a"), behavior="exam", selection="errors")
    _submit(client, h, answers=_mcq_answer("b"), behavior="practice", selection="all")
    ex = client.get("/api/attempts?behavior=exam", headers=h).json()
    assert ex["total"] == 1 and ex["items"][0]["behavior"] == "exam"
    err = client.get("/api/attempts?selection=errors", headers=h).json()
    assert err["total"] == 1 and err["items"][0]["selection"] == "errors"


def test_list_attempts_isolation(client):
    ha = _auth(client, "att_isoA@x.com")
    hb = _auth(client, "att_isoB@x.com")
    _submit(client, ha, answers=_mcq_answer("x"))
    b = client.get("/api/attempts", headers=hb).json()
    assert b["total"] == 0 and b["items"] == []


def test_list_attempts_resolves_names(client):
    h = _auth(client, "att_names@x.com")
    s = client.post("/api/subjects", json={"name": "Bio"}, headers=h).json()["id"]
    t = client.post(f"/api/subjects/{s}/topics", json={"name": "Célula"}, headers=h).json()["id"]
    _submit(client, h, answers=_mcq_answer("z"), subject_ids=[s], topic_ids=[t])
    row = client.get("/api/attempts", headers=h).json()["items"][0]
    assert row["subjects"] == [{"id": s, "name": "Bio"}]
    assert row["topics"] == [{"id": t, "name": "Célula"}]


# --- GET /attempts/{id} (detalle) ------------------------------------------
def test_get_attempt_detail_with_items(client):
    h = _auth(client, "att_det@x.com")
    aid = _submit(client, h, answers=_mcq_answer("q1"), snapshot=_mcq_snap("q1")).json()["attempt_id"]
    r = client.get(f"/api/attempts/{aid}", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["id"] == aid and len(d["items"]) == 1 and d["items"][0]["is_correct"] is True


def test_get_attempt_404_other_user(client):
    ha = _auth(client, "att_detA@x.com")
    hb = _auth(client, "att_detB@x.com")
    aid = _submit(client, ha, answers=_mcq_answer("q")).json()["attempt_id"]
    assert client.get(f"/api/attempts/{aid}", headers=hb).status_code == 404


def test_get_attempt_404_missing(client):
    h = _auth(client, "att_miss@x.com")
    assert client.get("/api/attempts/nope", headers=h).status_code == 404


def test_get_attempt_legacy_without_items(client):
    h = _auth(client, "att_legacy@x.com")
    aid = _submit(client, h, answers=_mcq_answer("q")).json()["attempt_id"]
    d = client.get(f"/api/attempts/{aid}", headers=h).json()
    assert d.get("items") is None
