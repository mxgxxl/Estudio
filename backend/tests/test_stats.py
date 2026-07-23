"""
Estadísticas: correctness tras reescribir las consultas (racha sin bucle,
by-subject/by-topic/gaps sin N+1, overview en paralelo).

Verifica que los cuatro endpoints devuelven lo esperado, incluyendo:
- racha calculada desde los días con actividad (una sola consulta distinct),
- asignaturas/temas con 0 preguntas presentes en by-subject/by-topic,
- gaps solo con temas <60% y >2 respuestas por pregunta,
- aislamiento multiusuario.

In-process (TestClient + mongomock). Datos insertados directamente.
"""
import asyncio
from datetime import datetime, timezone, timedelta

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


def _register_id(client, email):
    r = client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _login(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _get(client, h, path):
    r = client.get(path, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _iso(d):
    return d.isoformat()


def _subj(srv, uid, sid, name="Asig", color="#111"):
    _run(srv.db.subjects.insert_one({"id": sid, "user_id": uid, "name": name, "color": color,
                                     "created_at": "2024-01-01T00:00:00+00:00"}))


def _topic(srv, uid, tid, sid, name="Tema"):
    _run(srv.db.topics.insert_one({"id": tid, "user_id": uid, "subject_id": sid, "name": name,
                                   "created_at": "2024-01-01T00:00:00+00:00"}))


def _q(srv, uid, qid, sid, tid, *, ans=0, ok=0, favorite=False, difficult=False, srs="2999-01-01T00:00:00+00:00"):
    _run(srv.db.questions.insert_one({
        "id": qid, "user_id": uid, "subject_id": sid, "topic_id": tid, "topic_name": "T",
        "pdf_source_id": None, "question_type": "mcq", "num_options": 3, "question": "P",
        "options": ["A", "B", "C"], "correct_index": 0, "explanation": "", "model_answer": "",
        "favorite": favorite, "difficult": difficult, "times_answered": ans, "times_correct": ok,
        "srs_next_review": srs, "created_at": "2024-01-01T00:00:00+00:00",
    }))


def _attempt(srv, uid, aid, streak_day, created_at, mode="practice", correct=1, total=2, score=5.0):
    _run(srv.db.attempts.insert_one({
        "id": aid, "user_id": uid, "mode": mode, "subject_ids": [], "topic_ids": [],
        "question_ids": [], "answers": [], "correct_count": correct, "wrong_count": total - correct,
        "unanswered_count": 0, "total": total, "penalty_factor": None, "raw_score": float(correct),
        "score_10": score, "streak_day": streak_day, "created_at": created_at,
    }))


@pytest.fixture(scope="module")
def data(client, srv):
    uid = _register_id(client, "stats@x.com")
    h = _login(client, "stats@x.com")

    # 3 asignaturas: s1 (con temas), s2 (tema sin practicar), s3 (vacía).
    _subj(srv, uid, "stat_s1", "Anatomía", "#a11")
    _subj(srv, uid, "stat_s2", "Fisio", "#b22")
    _subj(srv, uid, "stat_s3", "Vacía", "#c33")
    _topic(srv, uid, "stat_t1", "stat_s1", "Huesos")
    _topic(srv, uid, "stat_t2", "stat_s1", "Músculos")
    _topic(srv, uid, "stat_t3", "stat_s2", "Sin practicar")

    # t1: q1 fallada (4 resp, 1 acierto, 25%) difícil + due; q2 sin practicar.
    _q(srv, uid, "stat_q1", "stat_s1", "stat_t1", ans=4, ok=1, difficult=True, srs="2000-01-01T00:00:00+00:00")
    _q(srv, uid, "stat_q2", "stat_s1", "stat_t1", ans=0, ok=0)
    # t2: q3 dominada (5/5), favorita.
    _q(srv, uid, "stat_q3", "stat_s1", "stat_t2", ans=5, ok=5, favorite=True)
    # t3: q4 sin practicar.
    _q(srv, uid, "stat_q4", "stat_s2", "stat_t3", ans=0, ok=0)

    # Racha: hoy y ayer (dos días consecutivos) -> 2. Hoy dos intentos (mismo día).
    today = datetime.now(timezone.utc).date()
    _attempt(srv, uid, "stat_a1", _iso(today), _iso(datetime.now(timezone.utc)))
    _attempt(srv, uid, "stat_a2", _iso(today), _iso(datetime.now(timezone.utc) - timedelta(hours=1)))
    _attempt(srv, uid, "stat_a3", _iso(today - timedelta(days=1)), _iso(datetime.now(timezone.utc) - timedelta(days=1)))

    # Otro usuario (aislamiento): no debe contaminar nada.
    other = _register_id(client, "stats_other@x.com")
    _subj(srv, other, "stat_sx", "Ajena")
    _topic(srv, other, "stat_tx", "stat_sx")
    _q(srv, other, "stat_qx", "stat_sx", "stat_tx", ans=9, ok=0)
    _attempt(srv, other, "stat_ax", _iso(today), _iso(datetime.now(timezone.utc)))

    return {"uid": uid, "h": h}


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
def test_overview_counts_and_accuracy(client, data):
    s = _get(client, data["h"], "/api/stats")
    assert s["total_subjects"] == 3
    assert s["total_topics"] == 3
    assert s["total_questions"] == 4
    assert s["total_attempts"] == 3
    # Global: ans = 4+5 = 9, ok = 1+5 = 6 -> 66.7%
    assert s["answered_total"] == 9
    assert s["accuracy"] == 66.7
    assert s["favorites"] == 1
    assert s["difficult"] == 1
    assert s["errors_pool"] == 1   # solo q1 (4>1)
    assert s["due_srs"] == 1       # solo q1 (srs vencido y practicada)


def test_overview_streak_from_distinct_days(client, data):
    s = _get(client, data["h"], "/api/stats")
    # Hoy + ayer consecutivos (con dos intentos hoy contando el día una vez).
    assert s["streak"] == 2
    assert len(s["last_attempts"]) == 3


def test_by_subject_includes_empty(client, data):
    rows = {r["subject_id"]: r for r in _get(client, data["h"], "/api/stats/by-subject")}
    assert set(rows) == {"stat_s1", "stat_s2", "stat_s3"}
    # s1: total 3 preguntas, ans 9, ok 6.
    assert rows["stat_s1"]["total_questions"] == 3
    assert rows["stat_s1"]["answered"] == 9 and rows["stat_s1"]["correct"] == 6
    assert rows["stat_s1"]["accuracy"] == 66.7
    # s2: 1 pregunta sin practicar.
    assert rows["stat_s2"]["total_questions"] == 1 and rows["stat_s2"]["answered"] == 0
    assert rows["stat_s2"]["accuracy"] == 0.0
    # s3: vacía, presente con ceros.
    assert rows["stat_s3"]["total_questions"] == 0 and rows["stat_s3"]["accuracy"] == 0.0


def test_by_topic_includes_all(client, data):
    rows = {r["topic_id"]: r for r in _get(client, data["h"], "/api/stats/by-topic")}
    assert set(rows) == {"stat_t1", "stat_t2", "stat_t3"}
    assert rows["stat_t1"]["total_questions"] == 2 and rows["stat_t1"]["answered"] == 4
    assert rows["stat_t1"]["accuracy"] == 25.0
    assert rows["stat_t2"]["accuracy"] == 100.0
    assert rows["stat_t3"]["total_questions"] == 1 and rows["stat_t3"]["answered"] == 0


def test_gaps(client, data):
    g = _get(client, data["h"], "/api/stats/gaps")
    weak_ids = {t["topic_id"] for t in g["weak_topics"]}
    # t1 (25%, >2 resp) es laguna; t2 (100%) no; t3 (sin practicar) no.
    assert weak_ids == {"stat_t1"}
    t1 = next(t for t in g["weak_topics"] if t["topic_id"] == "stat_t1")
    assert t1["accuracy"] == 25.0 and t1["answered"] == 4
    # Pregunta débil: q1 (25% <50, >2 resp).
    assert {q["id"] for q in g["weak_questions"]} == {"stat_q1"}


def test_isolation(client, data):
    """El segundo usuario ve solo lo suyo (nada contaminado del primero)."""
    hb = _login(client, "stats_other@x.com")
    s = _get(client, hb, "/api/stats")
    assert s["total_subjects"] == 1 and s["total_questions"] == 1
    subs = _get(client, hb, "/api/stats/by-subject")
    assert {r["subject_id"] for r in subs} == {"stat_sx"}
