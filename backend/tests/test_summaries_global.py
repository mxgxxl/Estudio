"""
Lista global de resúmenes (GET /api/summaries) para la pestaña Resúmenes.

Verifica: lista global del usuario, coste 0 (no llama a Gemini), scoping
multiusuario y que las asignaturas/temas de cada resumen se DERIVAN vía
pdf_links (un PDF compartido en varios temas/asignaturas devuelve todos).

In-process (TestClient + mongomock).
"""
import json

import pytest
from fastapi.testclient import TestClient


def _fake_extract_pdf_text(_b: bytes) -> str:
    return ("Temario de prueba. " * 40).strip()


async def _fake_generate_questions(topic_name, source_text, num_questions,
                                   question_type="mcq", num_options=3, custom_instructions=""):
    return [{
        "question": f"P{i}", "options": ["A", "B", "C"], "correct_index": 0,
        "explanation": "", "question_type": "mcq", "num_options": 3, "model_answer": "",
    } for i in range(3)]


class _FakeModels:
    calls = 0

    async def generate_content(self, **kwargs):
        _FakeModels.calls += 1

        class _R:
            text = json.dumps({
                "overview": "Resumen de prueba",
                "key_concepts": [{"concept": "C", "explanation": "E"}],
                "sections": [{"title": "S", "points": ["p1", "p2"]}],
                "remember": ["r1"],
            })
        return _R()


class _FakeAio:
    models = _FakeModels()


class _FakeClient:
    aio = _FakeAio()


@pytest.fixture(scope="module")
def srv():
    import server
    server.extract_pdf_text = _fake_extract_pdf_text
    server.generate_questions_with_claude = _fake_generate_questions
    server.GEMINI_API_KEY = "test-key"
    server.gemini_client = _FakeClient()
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


def _subject(client, h, name):
    r = client.post("/api/subjects", json={"name": name}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _topic_with_pdf(client, h, sid, tname="Tema", fn="a.pdf"):
    """Flujo real de la app en dos pasos: crea el tema vacío y le sube un PDF
    (ninguno consume cuota). Devuelve (topic_id, pdf_id)."""
    t = client.post(f"/api/subjects/{sid}/topics", json={"name": tname}, headers=h)
    assert t.status_code == 200, t.text
    tid = t.json()["id"]
    up = client.post(
        f"/api/topics/{tid}/pdfs/upload",
        files={"file": (fn, b"%PDF-1.4 A", "application/pdf")},
        headers=h,
    )
    assert up.status_code == 200, up.text
    return tid, up.json()["id"]


def test_empty_when_no_summaries(client):
    h = _auth(client, "glob_empty@x.com")
    sid = _subject(client, h, "Asig")
    _topic_with_pdf(client, h, sid)
    assert client.get("/api/summaries", headers=h).json() == []


def test_global_list_is_zero_cost(client):
    h = _auth(client, "glob_cost@x.com")
    sid = _subject(client, h, "Asig")
    tid, a = _topic_with_pdf(client, h, sid, fn="apuntes.pdf")
    client.post(f"/api/pdfs/{a}/summary", headers=h)

    before = _FakeModels.calls
    r = client.get("/api/summaries", headers=h)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["pdf_id"] == a
    assert row["pdf_filename"] == "apuntes.pdf"
    assert row["content"]["overview"] == "Resumen de prueba"
    assert {s["id"] for s in row["subjects"]} == {sid}
    assert {t["id"] for t in row["topics"]} == {tid}
    assert _FakeModels.calls == before  # servir la lista NO llama a Gemini


def test_membership_across_subjects_and_topics(client):
    """Un PDF compartido en dos temas/asignaturas: el resumen (compartido) debe
    listar AMBAS asignaturas y AMBOS temas (derivado de pdf_links)."""
    h = _auth(client, "glob_share@x.com")
    s1 = _subject(client, h, "Derecho")
    s2 = _subject(client, h, "Historia")
    t1, a = _topic_with_pdf(client, h, s1, tname="Tema 1")
    # Segundo tema en OTRA asignatura, vinculado al MISMO PDF.
    t2 = client.post(f"/api/subjects/{s2}/topics", json={"name": "Tema 2"}, headers=h).json()["id"]
    assert client.post(f"/api/topics/{t2}/pdfs/{a}/link", headers=h).status_code == 200

    client.post(f"/api/pdfs/{a}/summary", headers=h)
    rows = client.get("/api/summaries", headers=h).json()
    assert len(rows) == 1
    row = rows[0]
    assert {s["id"] for s in row["subjects"]} == {s1, s2}
    assert {t["id"] for t in row["topics"]} == {t1, t2}


def test_isolation(client):
    ha = _auth(client, "glob_ownerA@x.com")
    sid = _subject(client, ha, "De A")
    tid, a = _topic_with_pdf(client, ha, sid)
    client.post(f"/api/pdfs/{a}/summary", headers=ha)

    hb = _auth(client, "glob_ownerB@x.com")
    # B no ve los resúmenes de A.
    assert client.get("/api/summaries", headers=hb).json() == []
    # Y A sí ve el suyo.
    assert len(client.get("/api/summaries", headers=ha).json()) == 1
