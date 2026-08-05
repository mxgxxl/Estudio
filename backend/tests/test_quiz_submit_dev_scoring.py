"""
POST /quiz/submit con preguntas de DESARROLLO (question_type == "dev").

Fija el contrato del crédito PROPORCIONAL: cada dev aporta `dev_score/10` (0.0-1.0)
a la nota, incluido el blanco (dev_score 0 → 0). Los conteos enteros
correct/wrong mantienen el umbral `dev_score >= 5` (tiles/SRS). Los dev están
EXENTOS de penalización (esta es anti-azar de MCQ/VF, no aplica a respuesta abierta).

Regresión del bug de binarización (antes: dev < 5 → 0 puntos; dev >= 5 → 1 punto,
descartando el crédito parcial → notas de 0 cuando debían ser mayores).

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


def _mcq(qid, selected, correct_index=0):
    return {"question_id": qid, "selected": selected, "correct_index": correct_index, "question_type": "mcq"}


def _dev(qid, dev_score, selected=0):
    # `selected` es irrelevante para dev (siempre entra por la rama dev); un dev en
    # blanco llega con selected=-1 pero se corrige a dev_score=0 en eval-dev-batch.
    return {"question_id": qid, "selected": selected, "correct_index": -1,
            "question_type": "dev", "dev_score": dev_score}


def _submit(client, h, answers, penalty_factor=None, blanks_count_as_wrong=False):
    body = {
        "behavior": "exam",
        "selection": "all",
        "subject_ids": [],
        "topic_ids": [],
        "answers": answers,
        "duration_seconds": 30,
        "penalty_factor": penalty_factor,
        "blanks_count_as_wrong": blanks_count_as_wrong,
    }
    return client.post("/api/quiz/submit", json=body, headers=h)


def test_dev_partial_credit_two_questions(client):
    """Solo dev, scores [0, 2]: points = 0 + 0.2 = 0.2; nota = (0.2/2)*10 = 1.0.
    Antes (binarizado) daba 0."""
    h = _auth(client, "dev_partial_02@x.com")
    r = _submit(client, h, [_dev("q1", 0), _dev("q2", 2)])
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["score_10"] == 1.0
    assert b["correct"] == 0 and b["wrong"] == 2  # ambos < 5 → no acertadas
    assert b["unanswered"] == 0 and b["total"] == 2


def test_dev_partial_credit_three_questions_decimals(client):
    """Solo dev, scores [1, 0, 0]: points = 0.1; nota = round((0.1/3)*10, 2) = 0.33.
    Antes daba 0 ('faltaban decimales')."""
    h = _auth(client, "dev_partial_100@x.com")
    r = _submit(client, h, [_dev("q1", 1), _dev("q2", 0), _dev("q3", 0)])
    b = r.json()
    assert b["score_10"] == 0.33
    assert b["correct"] == 0 and b["wrong"] == 3 and b["total"] == 3


def test_dev_perfect_scores(client):
    """Solo dev, scores [10, 10]: points = 2.0; nota = 10.0."""
    h = _auth(client, "dev_perfect@x.com")
    r = _submit(client, h, [_dev("q1", 10), _dev("q2", 10)])
    b = r.json()
    assert b["score_10"] == 10.0
    assert b["correct"] == 2 and b["wrong"] == 0


def test_dev_exempt_from_penalty(client):
    """Un dev de 4 con penalización 2 NO penaliza: points = 0.4, penalized = 0,
    raw = 0.4, nota = 4.0. Antes (contaba como wrong) daba 0."""
    h = _auth(client, "dev_no_penalty@x.com")
    r = _submit(client, h, [_dev("q1", 4)], penalty_factor=2)
    b = r.json()
    assert b["score_10"] == 4.0
    assert b["raw_score"] == 0.4
    assert b["wrong"] == 1            # < 5 → cuenta como fallo en los tiles...
    assert b["correct"] == 0         # ...pero NO resta nota (exento)


def test_dev_threshold_five_counts_correct(client):
    """dev_score exactamente 5: umbral intacto → correct == 1 en los conteos; y la
    nota es proporcional: points = 0.5 → score_10 = 5.0."""
    h = _auth(client, "dev_threshold5@x.com")
    r = _submit(client, h, [_dev("q1", 5)])
    b = r.json()
    assert b["correct"] == 1 and b["wrong"] == 0
    assert b["score_10"] == 5.0


def test_mixed_mcq_and_dev_with_penalty(client):
    """Mixto: 1 MCQ acierto + 1 MCQ fallo + 1 dev(6), penalización 2.
    points = 1.0 + 0.6 = 1.6; penalized = 1 (solo el fallo MCQ, dev exento);
    raw = 1.6 - 1/2 = 1.1; nota = round((1.1/3)*10, 2) = 3.67."""
    h = _auth(client, "dev_mixed@x.com")
    answers = [_mcq("q1", 0), _mcq("q2", 1), _dev("q3", 6)]
    r = _submit(client, h, answers, penalty_factor=2)
    b = r.json()
    assert b["raw_score"] == 1.1
    assert b["score_10"] == 3.67
    assert b["correct"] == 2 and b["wrong"] == 1  # MCQ ok + dev(6>=5) aciertan


def test_dev_blank_does_not_penalize_with_toggle(client):
    """Dev en blanco (dev_score 0) junto a MCQ, con blanks_count_as_wrong=True y pf>0:
    el dev en blanco cuenta como wrong (no unanswered) y NO resta nota; solo el
    blanco MCQ penaliza. 1 MCQ ok + 1 MCQ blanco + 1 dev blanco, pf 2:
    points = 1.0; penalized = 1 (blanco MCQ); raw = 1 - 1/2 = 0.5; nota = 1.67.
    Si el dev blanco penalizara, penalized sería 2 → raw 0 → nota 0."""
    h = _auth(client, "dev_blank_toggle@x.com")
    answers = [_mcq("q1", 0), _mcq("q2", -1), _dev("q3", 0, selected=-1)]
    r = _submit(client, h, answers, penalty_factor=2, blanks_count_as_wrong=True)
    b = r.json()
    assert b["wrong"] == 1          # el dev en blanco (< 5) es fallo, no unanswered
    assert b["unanswered"] == 1     # solo el blanco MCQ
    assert b["blanks_penalized"] is True
    assert b["raw_score"] == 0.5    # el dev blanco NO añade a penalized
    assert b["score_10"] == 1.67


def test_mcq_only_scoring_unchanged(client):
    """No-regresión: quiz solo-MCQ con y sin penalización da los mismos números que
    antes del cambio (points == conteo de aciertos cuando no hay dev)."""
    h = _auth(client, "dev_reg_mcq@x.com")
    answers = [_mcq("q1", 0), _mcq("q2", 0), _mcq("q3", 1), _mcq("q4", 1)]
    # Sin penalización: raw = 2 aciertos, nota (2/4)*10 = 5.0.
    no_pen = _submit(client, h, answers).json()
    assert no_pen["correct"] == 2 and no_pen["wrong"] == 2
    assert no_pen["raw_score"] == 2.0 and no_pen["score_10"] == 5.0
    # Con penalización 1: raw = 2 - 2/1 = 0.
    pen = _submit(client, h, answers, penalty_factor=1).json()
    assert pen["raw_score"] == 0.0 and pen["score_10"] == 0.0
