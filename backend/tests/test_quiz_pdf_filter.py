"""
Filtro de PDFs de origen en el pool de un estudio (`pdf_ids`), en single-topic
scope. Extiende POST /quiz/start y GET /quiz/available.

Cubre:
- available con pdf_ids incluye/excluye correctamente.
- start con pdf_ids acota el pool.
- composición pdf_ids × selection=errors|srs|favorites = intersección.
- pdf_id ajeno al tema → 400.
- topic_ids con 0 o >1 elementos + pdf_ids → 400.
- huérfanos (pdf_source_id None): sin pdf_ids incluidos; con pdf_ids excluidos.
- pdf_ids ignorado cuando llega question_ids (ni siquiera se valida).
- regresión SRS: no avanza en selection != "srs" aunque el pool venga de pdf_ids.

In-process (TestClient + mongomock), con pdf_links reales.
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


def _link(srv, uid, pdf_id, topic_id="t", subject_id="s"):
    asyncio.run(srv._link_pdf_to_topic(uid, pdf_id, topic_id, subject_id))


def _insert_q(srv, uid, qid, *, pdf_source_id, topic_id="t", subject_id="s",
              question_type="mcq", times_answered=0, times_correct=0, favorite=False,
              srs_next_review=None, srs_ease=2.5, srs_interval_days=0.0):
    doc = {
        "id": qid, "user_id": uid, "topic_id": topic_id, "topic_name": "T",
        "subject_id": subject_id, "pdf_source_id": pdf_source_id,
        "question_type": question_type, "num_options": 3,
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


def _start_ids(client, h, **body):
    r = _start(client, h, **body)
    assert r.status_code == 200, r.text
    return {q["id"] for q in r.json()["questions"]}


def _avail(client, h, **params):
    r = client.get("/api/quiz/available", params={"topic_ids": ["t"], **params}, headers=h)
    return r


def _ans(qid, selected=0, correct_index=0):
    return {"question_id": qid, "selected": selected, "correct_index": correct_index, "question_type": "mcq"}


def _submit(client, h, answers, **body):
    payload = {"subject_ids": [], "topic_ids": ["t"], "answers": answers,
               "duration_seconds": 10, **body}
    return client.post("/api/quiz/submit", json=payload, headers=h)


PAST = "2000-01-01T00:00:00+00:00"
FUTURE = "2999-01-01T00:00:00+00:00"


# --- available: incluye/excluye por pdf_ids ---------------------------------
def test_available_includes_excludes_by_pdf(client, srv):
    h, uid = _auth(client, "avpdf@x.com")
    _link(srv, uid, "p1")
    _link(srv, uid, "p2")
    _insert_q(srv, uid, "a_p1", pdf_source_id="p1")
    _insert_q(srv, uid, "a_p2", pdf_source_id="p2")
    _insert_q(srv, uid, "a_orph", pdf_source_id=None)

    def count(**params):
        r = _avail(client, h, **params)
        assert r.status_code == 200, r.text
        return r.json()["count"]

    assert count() == 3                                  # sin pdf_ids: todos, incl. huérfano
    assert count(pdf_ids=["p1"]) == 1                    # solo p1, huérfano fuera
    assert count(pdf_ids=["p1", "p2"]) == 2              # p1+p2, huérfano fuera


# --- start: acota el pool + huérfanos ---------------------------------------
def test_start_scopes_pool_and_orphans(client, srv):
    h, uid = _auth(client, "stpdf@x.com")
    _link(srv, uid, "p1")
    _link(srv, uid, "p2")
    _insert_q(srv, uid, "s_p1", pdf_source_id="p1")
    _insert_q(srv, uid, "s_p2", pdf_source_id="p2")
    _insert_q(srv, uid, "s_orph", pdf_source_id=None)

    assert _start_ids(client, h) == {"s_p1", "s_p2", "s_orph"}      # sin pdf_ids: incl. huérfano
    assert _start_ids(client, h, pdf_ids=["p1"]) == {"s_p1"}        # solo p1
    assert _start_ids(client, h, pdf_ids=["p1", "p2"]) == {"s_p1", "s_p2"}  # huérfano excluido


# --- composición pdf_ids × selection = intersección -------------------------
def test_pdf_ids_intersects_selection(client, srv):
    h, uid = _auth(client, "xsel@x.com")
    _link(srv, uid, "p1")
    _link(srv, uid, "p2")
    # errores
    _insert_q(srv, uid, "e_p1", pdf_source_id="p1", times_answered=3, times_correct=1)
    _insert_q(srv, uid, "e_p2", pdf_source_id="p2", times_answered=3, times_correct=1)
    # favoritas
    _insert_q(srv, uid, "f_p1", pdf_source_id="p1", favorite=True)
    _insert_q(srv, uid, "f_p2", pdf_source_id="p2", favorite=True)
    # srs due
    _insert_q(srv, uid, "d_p1", pdf_source_id="p1", srs_next_review=PAST)
    _insert_q(srv, uid, "d_p2", pdf_source_id="p2", srs_next_review=PAST)

    assert _start_ids(client, h, selection="errors", pdf_ids=["p1"]) == {"e_p1"}
    assert _start_ids(client, h, selection="favorites", pdf_ids=["p1"]) == {"f_p1"}
    assert _start_ids(client, h, selection="srs", pdf_ids=["p1"]) == {"d_p1"}
    # Sin pdf_ids, la selección trae ambos PDFs.
    assert _start_ids(client, h, selection="errors") == {"e_p1", "e_p2"}


# --- validación: pdf ajeno al tema → 400 ------------------------------------
def test_pdf_not_in_topic_400(client, srv):
    h, uid = _auth(client, "ajeno@x.com")
    _link(srv, uid, "p1")
    _insert_q(srv, uid, "n_p1", pdf_source_id="p1")

    assert _start(client, h, pdf_ids=["nope"]).status_code == 400
    assert _avail(client, h, pdf_ids=["nope"]).status_code == 400
    # Mezcla de válido + inválido también falla.
    assert _start(client, h, pdf_ids=["p1", "nope"]).status_code == 400


# --- validación: multi-topic (0 o >1) + pdf_ids → 400 -----------------------
def test_multi_topic_scope_400(client, srv):
    h, uid = _auth(client, "multi@x.com")
    _link(srv, uid, "p1")
    _insert_q(srv, uid, "m_p1", pdf_source_id="p1")

    # 0 temas
    r0 = client.post("/api/quiz/start", json={"topic_ids": [], "num_questions": 50, "pdf_ids": ["p1"]}, headers=h)
    assert r0.status_code == 400, r0.text
    # >1 tema
    r2 = client.post("/api/quiz/start", json={"topic_ids": ["t", "t2"], "num_questions": 50, "pdf_ids": ["p1"]}, headers=h)
    assert r2.status_code == 400, r2.text
    # available igual
    ra = client.get("/api/quiz/available", params={"topic_ids": [], "pdf_ids": ["p1"]}, headers=h)
    assert ra.status_code == 400, ra.text


# --- pdf_ids IGNORADO cuando llega question_ids (ni se valida) ---------------
def test_pdf_ids_ignored_with_question_ids(client, srv):
    h, uid = _auth(client, "qids@x.com")
    _link(srv, uid, "p1")
    _insert_q(srv, uid, "q_a", pdf_source_id="p1")
    _insert_q(srv, uid, "q_b", pdf_source_id="p1")

    # question_ids define el pool; pdf_ids inválido NO debe provocar 400 ni filtrar.
    ids = _start_ids(client, h, question_ids=["q_b"], pdf_ids=["inexistente"])
    assert ids == {"q_b"}


# --- regresión SRS: no avanza fuera de srs aunque el pool venga de pdf_ids ---
def test_srs_untouched_outside_srs_with_pdf_ids(client, srv):
    h, uid = _auth(client, "srspdf@x.com")
    _link(srv, uid, "p1")
    _insert_q(srv, uid, "srs_keep", pdf_source_id="p1",
              srs_next_review="2030-06-15T00:00:00+00:00", srs_ease=2.9, srs_interval_days=6.0)

    # Arranca con filtro de PDF (selección all) y luego envía como examen.
    ids = _start_ids(client, h, selection="all", behavior="exam", pdf_ids=["p1"])
    assert ids == {"srs_keep"}

    before = _get_q(srv, "srs_keep")
    r = _submit(client, h, [_ans("srs_keep")], selection="all", behavior="exam", penalty_factor=1)
    assert r.status_code == 200, r.text
    after = _get_q(srv, "srs_keep")
    # Estado SRS IDÉNTICO (el filtro de pdf no toca el gate de SRS).
    assert after["srs_next_review"] == before["srs_next_review"]
    assert after["srs_ease"] == before["srs_ease"]
    assert after["srs_interval_days"] == before["srs_interval_days"]
    # Pero la respuesta se contabiliza.
    assert after["times_answered"] == before["times_answered"] + 1


def test_srs_advances_in_srs_with_pdf_ids(client, srv):
    h, uid = _auth(client, "srspdf2@x.com")
    _link(srv, uid, "p1")
    _insert_q(srv, uid, "srs_adv", pdf_source_id="p1",
              srs_next_review=PAST, srs_ease=2.5, srs_interval_days=6.0)

    ids = _start_ids(client, h, selection="srs", pdf_ids=["p1"])
    assert ids == {"srs_adv"}

    before = _get_q(srv, "srs_adv")
    r = _submit(client, h, [_ans("srs_adv")], selection="srs", behavior="practice")
    assert r.status_code == 200, r.text
    after = _get_q(srv, "srs_adv")
    assert after["srs_next_review"] != before["srs_next_review"]     # avanzó
    assert after["srs_interval_days"] != before["srs_interval_days"]
