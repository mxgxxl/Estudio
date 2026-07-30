"""
POST /quiz/submit con preguntas EN BLANCO (selected == -1).

Fija el contrato del que depende la UX de "dejar en blanco": una no respondida
es NEUTRA — cuenta como `unanswered`, NO como `wrong`, y NO penaliza bajo ningún
ratio. (El scoring está auditado; esto protege el endpoint de regresiones.)

In-process (TestClient + mongomock).
"""
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


def _ans(qid, selected, correct_index=0):
    return {"question_id": qid, "selected": selected, "correct_index": correct_index, "question_type": "mcq"}


def _submit(client, h, answers, penalty_factor=None):
    body = {
        "mode": "exam",
        "subject_ids": [],
        "topic_ids": [],
        "answers": answers,
        "duration_seconds": 30,
        "penalty_factor": penalty_factor,
    }
    return client.post("/api/quiz/submit", json=body, headers=h)


def test_blank_is_neutral_not_wrong(client):
    """2 aciertos, 1 fallo, 1 en blanco con penalización 1: la blanca no suma a
    'wrong' ni penaliza. raw = 2 - 1/1 = 1; nota = (1/4)*10 = 2.5."""
    h = _auth(client, "blank_neutral@x.com")
    answers = [
        _ans("q1", 0),      # acierto
        _ans("q2", 0),      # acierto
        _ans("q3", 1),      # fallo (correct_index 0)
        _ans("q4", -1),     # EN BLANCO
    ]
    r = _submit(client, h, answers, penalty_factor=1)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["correct"] == 2
    assert b["wrong"] == 1          # la blanca NO cuenta como fallo
    assert b["unanswered"] == 1
    assert b["total"] == 4
    assert b["raw_score"] == 1.0    # 2 - (1/1); si la blanca penalizara sería 0
    assert b["score_10"] == 2.5


def test_blanks_do_not_penalize_under_any_ratio(client):
    """Solo aciertos y blancos: bajo cualquier penalización la nota no baja por las
    blancas (solo diluyen el denominador)."""
    h = _auth(client, "blank_ratios@x.com")
    answers = [_ans("q1", 0)] + [_ans(f"b{i}", -1) for i in range(3)]  # 1 acierto, 3 blancas
    for pf in (1, 2, 3, 4):
        r = _submit(client, h, answers, penalty_factor=pf)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["correct"] == 1 and b["wrong"] == 0 and b["unanswered"] == 3
        assert b["raw_score"] == 1.0            # sin fallos, la penalización no resta
        assert b["score_10"] == 2.5             # (1/4)*10; las blancas cuentan en el total


def test_all_blank_submits_cleanly(client):
    """Enviar un examen entero en blanco no rompe: 0/0, todas unanswered, nota 0."""
    h = _auth(client, "blank_all@x.com")
    answers = [_ans(f"q{i}", -1) for i in range(5)]
    r = _submit(client, h, answers, penalty_factor=2)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["correct"] == 0 and b["wrong"] == 0 and b["unanswered"] == 5
    assert b["total"] == 5 and b["raw_score"] == 0.0 and b["score_10"] == 0.0
