"""
Crear temas VACÍOS (sin PDF) — desacople de la subida de PDF respecto a la
creación del tema.

Verifica el nuevo endpoint POST /api/subjects/{subject_id}/topics:
- crea un tema sin PDF y sin generar preguntas (no consume cuota de IA),
- valida nombre y propiedad de la asignatura (multiusuario),
- y que luego se le pueden adjuntar PDFs con los endpoints existentes.

In-process (TestClient + mongomock, IA mockeada).
"""
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


@pytest.fixture(scope="module")
def srv():
    import server
    server.extract_pdf_text = _fake_extract_pdf_text
    server.generate_questions_with_claude = _fake_generate_questions
    return server


@pytest.fixture(scope="module")
def client(srv):
    with TestClient(srv.app) as c:
        yield c


def _register(client, email):
    r = client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _login(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _subject(client, h, name):
    r = client.post("/api/subjects", json={"name": name}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_create_empty_topic_no_pdf_no_questions(client):
    h = _login(client, _register(client, "empty1@x.com") and "empty1@x.com")
    sid = _subject(client, h, "Asig")

    r = client.post(f"/api/subjects/{sid}/topics", json={"name": "  Tema vacío  "}, headers=h)
    assert r.status_code == 200, r.text
    topic = r.json()
    assert topic["name"] == "Tema vacío"  # se recorta
    assert topic["subject_id"] == sid

    tid = topic["id"]
    # No hay PDFs ni preguntas.
    assert client.get(f"/api/topics/{tid}/pdfs", headers=h).json() == []
    assert client.get(f"/api/topics/{tid}/questions", headers=h).json() == []


def test_create_empty_topic_rejects_blank_name(client):
    h = _login(client, _register(client, "empty2@x.com") and "empty2@x.com")
    sid = _subject(client, h, "Asig")
    r = client.post(f"/api/subjects/{sid}/topics", json={"name": "   "}, headers=h)
    assert r.status_code == 400, r.text


def test_create_empty_topic_unknown_subject_404(client):
    h = _login(client, _register(client, "empty3@x.com") and "empty3@x.com")
    r = client.post("/api/subjects/does-not-exist/topics", json={"name": "T"}, headers=h)
    assert r.status_code == 404, r.text


def test_create_empty_topic_isolation(client):
    """Un usuario no puede crear temas en la asignatura de otro."""
    ha = _login(client, _register(client, "ownerA@x.com") and "ownerA@x.com")
    sid_a = _subject(client, ha, "De A")
    hb = _login(client, _register(client, "ownerB@x.com") and "ownerB@x.com")
    r = client.post(f"/api/subjects/{sid_a}/topics", json={"name": "Intruso"}, headers=hb)
    assert r.status_code == 404, r.text


def test_attach_pdf_to_empty_topic(client):
    """Tras crear vacío, se le puede subir un PDF con el endpoint existente."""
    h = _login(client, _register(client, "empty4@x.com") and "empty4@x.com")
    sid = _subject(client, h, "Asig")
    tid = client.post(f"/api/subjects/{sid}/topics", json={"name": "T"}, headers=h).json()["id"]

    r = client.post(
        f"/api/topics/{tid}/pdfs/upload",
        files={"file": ("x.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers=h,
    )
    assert r.status_code == 200, r.text
    pdfs = client.get(f"/api/topics/{tid}/pdfs", headers=h).json()
    assert len(pdfs) == 1
