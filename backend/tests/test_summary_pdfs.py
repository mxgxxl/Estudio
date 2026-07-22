"""
Resumen IA con selección de PDFs (POST /topics/{id}/summary).

El resumen se genera al vuelo (no se persiste). Verifica que acepta pdf_ids
opcional (default = todos), valida contra los PDFs del tema y respeta el
aislamiento multiusuario. Se mockea el cliente Gemini para no llamar al modelo.

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
    async def generate_content(self, **kwargs):
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
    # Mockea el cliente Gemini y su clave para que el resumen se genere.
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


def _topic_two_pdfs(client, h, sid):
    r = client.post(
        f"/api/subjects/{sid}/topics/upload",
        data={"name": "Tema", "num_questions": "3", "question_type": "mcq", "num_options": "3"},
        files={"file": ("a.pdf", b"%PDF-1.4 A", "application/pdf")},
        headers=h,
    )
    assert r.status_code == 200, r.text
    tid, a = r.json()["topic"]["id"], r.json()["pdf_id"]
    r = client.post(f"/api/topics/{tid}/pdfs/upload", files={"file": ("b.pdf", b"%PDF-1.4 B", "application/pdf")}, headers=h)
    assert r.status_code == 200, r.text
    return tid, a, r.json()["id"]


def test_summary_all_pdfs_default(client):
    h = _auth(client, "sum_all@x.com")
    sid = _subject(client, h, "Asig")
    tid, a, b = _topic_two_pdfs(client, h, sid)
    r = client.post(f"/api/topics/{tid}/summary", json={}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["overview"] == "Resumen de prueba"


def test_summary_subset(client):
    h = _auth(client, "sum_subset@x.com")
    sid = _subject(client, h, "Asig")
    tid, a, b = _topic_two_pdfs(client, h, sid)
    r = client.post(f"/api/topics/{tid}/summary", json={"pdf_ids": [a]}, headers=h)
    assert r.status_code == 200, r.text


def test_summary_foreign_ids_404(client):
    h = _auth(client, "sum_foreign@x.com")
    sid = _subject(client, h, "Asig")
    tid, a, b = _topic_two_pdfs(client, h, sid)
    r = client.post(f"/api/topics/{tid}/summary", json={"pdf_ids": ["nope"]}, headers=h)
    assert r.status_code == 404, r.text


def test_summary_isolation(client):
    ha = _auth(client, "sum_ownerA@x.com")
    sid = _subject(client, ha, "De A")
    tid, a, b = _topic_two_pdfs(client, ha, sid)
    hb = _auth(client, "sum_ownerB@x.com")
    r = client.post(f"/api/topics/{tid}/summary", json={}, headers=hb)
    assert r.status_code == 404, r.text
