"""
Banco de preguntas: listado global con filtros + 'practicar esta selección'.

Cubre GET /questions (filtros, búsqueda, orden, paginación, aislamiento),
GET /questions/ids (cap + total real, sin recortes silenciosos) y la extensión
de POST /quiz/start con question_ids.

In-process (TestClient + mongomock). Las preguntas se insertan directamente en
Mongo para controlar sus atributos (tipo, favorito, difícil, aciertos, fecha).
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


def _register_id(client, email):
    r = client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _login(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _insert(srv, **fields):
    """Inserta una pregunta con valores por defecto razonables."""
    doc = {
        "id": fields["id"],
        "user_id": fields["user_id"],
        "topic_id": fields.get("topic_id", "t1"),
        "topic_name": fields.get("topic_name", "Tema 1"),
        "subject_id": fields.get("subject_id", "s1"),
        "pdf_source_id": fields.get("pdf_source_id", "pdf1"),
        "question_type": fields.get("question_type", "mcq"),
        "num_options": fields.get("num_options", 3),
        "question": fields.get("question", "Enunciado"),
        "options": fields.get("options", ["A", "B", "C"]),
        "correct_index": fields.get("correct_index", 0),
        "explanation": "", "model_answer": "",
        "favorite": fields.get("favorite", False),
        "difficult": fields.get("difficult", False),
        "times_answered": fields.get("times_answered", 0),
        "times_correct": fields.get("times_correct", 0),
        "srs_next_review": fields.get("srs_next_review", "2999-01-01T00:00:00+00:00"),
        "last_correct": fields.get("last_correct", None),
        "created_at": fields.get("created_at", "2024-01-01T00:00:00+00:00"),
    }

    async def _do():
        await srv.db.questions.insert_one(doc)
    asyncio.run(_do())
    return doc["id"]


def _get(client, h, path):
    r = client.get(path, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------
# Un dataset compartido para un usuario.
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def dataset(client, srv):
    uid = _register_id(client, "bank@x.com")
    h = _login(client, "bank@x.com")
    # q1: mcq, s1/t1/pdf1, favorita, fallada (2 de 3), reciente
    _insert(srv, id="q1", user_id=uid, question="Los huesos del pie", favorite=True,
            times_answered=3, times_correct=2, created_at="2024-06-01T00:00:00+00:00")
    # q2: tf, s1/t2/pdf2, difícil, sin practicar
    _insert(srv, id="q2", user_id=uid, subject_id="s1", topic_id="t2", pdf_source_id="pdf2",
            question_type="tf", question="El corazón es un músculo", difficult=True,
            created_at="2024-05-01T00:00:00+00:00")
    # q3: mcq, s2/t3, sin PDF (pdf_source_id None), dominada (2/2)
    _insert(srv, id="q3", user_id=uid, subject_id="s2", topic_id="t3", pdf_source_id=None,
            question="Capital de Francia", times_answered=2, times_correct=2,
            created_at="2024-04-01T00:00:00+00:00")
    # q4: dev, s2/t3/pdf3, due (srs vencido, practicada), fallada del todo (0/1)
    _insert(srv, id="q4", user_id=uid, subject_id="s2", topic_id="t3", pdf_source_id="pdf3",
            question_type="dev", question="Explica la fotosíntesis",
            times_answered=1, times_correct=0, srs_next_review="2000-01-01T00:00:00+00:00",
            created_at="2024-03-01T00:00:00+00:00")
    # Otro usuario con su propia pregunta (aislamiento).
    other = _register_id(client, "bank_other@x.com")
    _insert(srv, id="qX", user_id=other, question="Ajena")
    return {"uid": uid, "h": h}


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
def test_list_all_only_own(client, dataset):
    body = _get(client, dataset["h"], "/api/questions")
    assert body["total"] == 4
    assert {i["id"] for i in body["items"]} == {"q1", "q2", "q3", "q4"}
    assert body["page"] == 1 and body["limit"] == 30


def test_filter_subject_topic_type(client, dataset):
    h = dataset["h"]
    assert _get(client, h, "/api/questions?subject_id=s1")["total"] == 2
    assert _get(client, h, "/api/questions?topic_id=t3")["total"] == 2
    assert _get(client, h, "/api/questions?question_type=mcq")["total"] == 2
    assert {i["id"] for i in _get(client, h, "/api/questions?question_type=tf")["items"]} == {"q2"}


def test_filter_pdf_source_including_none(client, dataset):
    h = dataset["h"]
    assert {i["id"] for i in _get(client, h, "/api/questions?pdf_source_id=pdf1")["items"]} == {"q1"}
    # "none" -> preguntas cuyo PDF de origen desapareció.
    assert {i["id"] for i in _get(client, h, "/api/questions?pdf_source_id=none")["items"]} == {"q3"}


def test_status_filters(client, dataset):
    h = dataset["h"]
    # falladas: answered > correct -> q1 y q4
    assert {i["id"] for i in _get(client, h, "/api/questions?status=errors")["items"]} == {"q1", "q4"}
    assert {i["id"] for i in _get(client, h, "/api/questions?status=favorites")["items"]} == {"q1"}
    assert {i["id"] for i in _get(client, h, "/api/questions?status=difficult")["items"]} == {"q2"}
    assert {i["id"] for i in _get(client, h, "/api/questions?status=unpracticed")["items"]} == {"q2"}
    assert {i["id"] for i in _get(client, h, "/api/questions?status=mastered")["items"]} == {"q3"}
    assert {i["id"] for i in _get(client, h, "/api/questions?status=due")["items"]} == {"q4"}


def test_search_and_sort(client, dataset):
    h = dataset["h"]
    # Búsqueda por subcadena (case-insensitive).
    assert {i["id"] for i in _get(client, h, "/api/questions?q=huesos")["items"]} == {"q1"}
    assert {i["id"] for i in _get(client, h, "/api/questions?q=CORAZ")["items"]} == {"q2"}
    # Orden por reciente (created_at desc): q1 primero.
    recent = _get(client, h, "/api/questions?sort=recent")["items"]
    assert recent[0]["id"] == "q1"
    # most_failed: más respondidas primero -> q1 (3) por delante.
    mf = _get(client, h, "/api/questions?sort=most_failed")["items"]
    assert mf[0]["id"] == "q1"


def test_pagination(client, dataset):
    h = dataset["h"]
    p1 = _get(client, h, "/api/questions?limit=2&page=1")
    p2 = _get(client, h, "/api/questions?limit=2&page=2")
    assert p1["total"] == 4 and len(p1["items"]) == 2
    assert len(p2["items"]) == 2
    ids = {i["id"] for i in p1["items"]} | {i["id"] for i in p2["items"]}
    assert ids == {"q1", "q2", "q3", "q4"}


def test_ids_endpoint_total_and_cap(client, dataset, srv):
    h = dataset["h"]
    body = _get(client, h, "/api/questions/ids")
    assert body["total"] == 4 and body["capped"] is False
    assert set(body["ids"]) == {"q1", "q2", "q3", "q4"}

    # Cap: bajar el tope y comprobar que avisa (total real > ids devueltos).
    orig = srv.QUESTIONS_IDS_CAP
    srv.QUESTIONS_IDS_CAP = 2
    try:
        capped = _get(client, h, "/api/questions/ids")
        assert capped["total"] == 4
        assert len(capped["ids"]) == 2
        assert capped["capped"] is True
    finally:
        srv.QUESTIONS_IDS_CAP = orig


def test_isolation(client, dataset):
    hb = _login(client, "bank_other@x.com")
    body = _get(client, hb, "/api/questions")
    assert body["total"] == 1
    assert {i["id"] for i in body["items"]} == {"qX"}


def test_quiz_start_with_question_ids(client, dataset):
    h = dataset["h"]
    r = client.post("/api/quiz/start", json={
        "behavior": "practice", "question_ids": ["q1", "q3"], "num_questions": 20,
    }, headers=h)
    assert r.status_code == 200, r.text
    got = {q["id"] for q in r.json()["questions"]}
    assert got == {"q1", "q3"}


def test_quiz_start_question_ids_are_user_scoped(client, dataset):
    """Los ids de otro usuario no se cuelan aunque se pasen explícitamente."""
    h = dataset["h"]
    r = client.post("/api/quiz/start", json={
        "behavior": "practice", "question_ids": ["q1", "qX"],
    }, headers=h)
    assert r.status_code == 200, r.text
    got = {q["id"] for q in r.json()["questions"]}
    assert got == {"q1"}


def test_quiz_start_respects_num_questions(client, dataset):
    h = dataset["h"]
    r = client.post("/api/quiz/start", json={
        "behavior": "practice", "question_ids": ["q1", "q2", "q3", "q4"], "num_questions": 2,
    }, headers=h)
    assert r.status_code == 200, r.text
    assert len(r.json()["questions"]) == 2


# --------------------------------------------------------------------------
# random_sample: muestreo aleatorio uniforme ($sample), acotado al CAP y aislado.
# --------------------------------------------------------------------------
def _seed_user(client, srv, email, n):
    """Registra un usuario y le inserta n preguntas con ids prefijados por email."""
    uid = _register_id(client, email)
    h = _login(client, email)
    prefix = email.split("@")[0]
    for i in range(n):
        _insert(srv, id=f"{prefix}_{i}", user_id=uid)
    return uid, h


def test_random_sample_returns_exactly_n(client, srv):
    _, h = _seed_user(client, srv, "rsN@x.com", 20)
    body = _get(client, h, "/api/questions/ids?random_sample=5")
    assert body["sampled"] is True and body["capped"] is False
    assert body["total"] == 20
    assert len(body["ids"]) == 5
    assert len(set(body["ids"])) == 5                 # sin repetidos
    assert all(i.startswith("rsN_") for i in body["ids"])  # todos del filtro/usuario


def test_random_sample_user_isolation(client, srv):
    """A pide 50 aleatorias sin filtros de scope: solo salen SUS preguntas."""
    _seed_user(client, srv, "rsA@x.com", 10)
    _seed_user(client, srv, "rsB@x.com", 10)  # otro usuario, no debe colarse
    ha = _login(client, "rsA@x.com")
    body = _get(client, ha, "/api/questions/ids?random_sample=50")
    assert body["total"] == 10                        # solo las de A
    assert len(body["ids"]) == 10                     # min(50, CAP, 10)
    assert all(i.startswith("rsA_") for i in body["ids"])


def test_random_sample_zero_422(client, srv):
    _, h = _seed_user(client, srv, "rs0@x.com", 3)
    assert client.get("/api/questions/ids?random_sample=0", headers=h).status_code == 422
    assert client.get("/api/questions/ids?random_sample=-1", headers=h).status_code == 422


def test_random_sample_over_cap(client, srv):
    _, h = _seed_user(client, srv, "rsCap@x.com", 10)
    orig = srv.QUESTIONS_IDS_CAP
    srv.QUESTIONS_IDS_CAP = 3
    try:
        body = _get(client, h, "/api/questions/ids?random_sample=100")
        assert body["sampled"] is True
        assert body["total"] == 10
        assert len(body["ids"]) == 3                   # acotado al CAP
    finally:
        srv.QUESTIONS_IDS_CAP = orig
