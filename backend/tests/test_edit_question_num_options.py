"""
PATCH /api/questions/{id}: `num_options` se deriva de `options`.

Desde que la edición permite añadir/quitar opciones (EditQuestionDialog usa
QuestionFields), el campo tenía que dejar de quedarse con el valor antiguo: lo
pintan las tarjetas del Banco y de TopicDetail como "N opc" y el backend filtra
por él. Se deriva en el servidor, sin ampliar el contrato de EditQuestionReq.

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


def _make_topic(client, h):
    sid = client.post("/api/subjects", json={"name": "Asig"}, headers=h).json()["id"]
    tid = client.post(f"/api/subjects/{sid}/topics", json={"name": "Tema"}, headers=h).json()["id"]
    return tid


def _mcq(client, h, tid, options):
    """Crea una mcq por el alta manual (num_options = len(options))."""
    r = client.post("/api/questions", json={
        "topic_id": tid, "question_type": "mcq", "question_text": "¿?",
        "options": options, "correct_answer": 0,
    }, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _doc(srv, qid):
    return asyncio.run(srv.db.questions.find_one({"id": qid}, {"_id": 0}))


def test_adding_an_option_updates_num_options(client, srv):
    h = _auth(client, "numopts_add@x.com")
    tid = _make_topic(client, h)
    q = _mcq(client, h, tid, ["A", "B", "C"])
    assert q["num_options"] == 3

    r = client.patch(f"/api/questions/{q['id']}",
                     json={"options": ["A", "B", "C", "D"], "correct_index": 0}, headers=h)
    assert r.status_code == 200, r.text
    assert _doc(srv, q["id"])["num_options"] == 4


def test_removing_an_option_updates_num_options(client, srv):
    h = _auth(client, "numopts_del@x.com")
    tid = _make_topic(client, h)
    q = _mcq(client, h, tid, ["A", "B", "C", "D"])
    assert q["num_options"] == 4

    r = client.patch(f"/api/questions/{q['id']}",
                     json={"options": ["A", "B"], "correct_index": 1}, headers=h)
    assert r.status_code == 200, r.text
    doc = _doc(srv, q["id"])
    assert doc["num_options"] == 2
    assert doc["options"] == ["A", "B"] and doc["correct_index"] == 1


def test_patch_without_options_leaves_num_options_untouched(client, srv):
    """Editar solo el enunciado/explicación no debe tocar num_options."""
    h = _auth(client, "numopts_keep@x.com")
    tid = _make_topic(client, h)
    q = _mcq(client, h, tid, ["A", "B", "C"])

    r = client.patch(f"/api/questions/{q['id']}",
                     json={"question": "Otro enunciado", "explanation": "porque sí"}, headers=h)
    assert r.status_code == 200, r.text
    doc = _doc(srv, q["id"])
    assert doc["num_options"] == 3          # intacto
    assert doc["question"] == "Otro enunciado"


def test_num_options_is_derived_not_client_supplied(client, srv):
    """El cliente no puede colar un num_options incoherente: se ignora (no está
    en EditQuestionReq) y gana el derivado de las opciones."""
    h = _auth(client, "numopts_derived@x.com")
    tid = _make_topic(client, h)
    q = _mcq(client, h, tid, ["A", "B", "C"])

    r = client.patch(f"/api/questions/{q['id']}",
                     json={"options": ["A", "B"], "correct_index": 0, "num_options": 99}, headers=h)
    assert r.status_code == 200, r.text
    assert _doc(srv, q["id"])["num_options"] == 2


def test_tf_edit_keeps_num_options_two(client, srv):
    """Una V/F editada sigue con num_options 2 (options = Verdadero/Falso)."""
    h = _auth(client, "numopts_tf@x.com")
    tid = _make_topic(client, h)
    r = client.post("/api/questions", json={
        "topic_id": tid, "question_type": "tf", "question_text": "¿Cierto?",
        "correct_answer": 0,
    }, headers=h)
    assert r.status_code == 201, r.text
    qid = r.json()["id"]

    r = client.patch(f"/api/questions/{qid}",
                     json={"options": ["Verdadero", "Falso"], "correct_index": 1}, headers=h)
    assert r.status_code == 200, r.text
    doc = _doc(srv, qid)
    assert doc["num_options"] == 2 and doc["correct_index"] == 1
