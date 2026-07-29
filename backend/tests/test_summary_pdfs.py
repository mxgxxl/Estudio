"""
Resúmenes de IA persistidos, por PDF.

  POST /pdfs/{pdf_id}/summary   -> genera/regenera y persiste (1 generación)
  GET  /pdfs/{pdf_id}/summary   -> resumen cacheado (coste 0)
  GET  /topics/{id}/summaries   -> resúmenes cacheados de los PDFs del tema

Verifica caché (servir no llama a Gemini), regenerar sobrescribe, que el resumen
es compartido por pdf_id, la limpieza al borrar el PDF y el aislamiento
multiusuario. Se mockea el cliente Gemini (contador de llamadas) para no llamar
al modelo. In-process (TestClient + mongomock).
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
    n = 0

    async def generate_content(self, **kwargs):
        _FakeModels.calls += 1
        _FakeModels.n += 1
        marker = _FakeModels.n

        class _R:
            text = json.dumps({
                "overview": f"Resumen {marker}",
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


def _topic_two_pdfs(client, h, sid):
    """Flujo real: crea el tema vacío y le sube 2 PDFs. Devuelve (topic_id, a, b)."""
    t = client.post(f"/api/subjects/{sid}/topics", json={"name": "Tema"}, headers=h)
    assert t.status_code == 200, t.text
    tid = t.json()["id"]
    ra = client.post(f"/api/topics/{tid}/pdfs/upload", files={"file": ("a.pdf", b"%PDF-1.4 A", "application/pdf")}, headers=h)
    assert ra.status_code == 200, ra.text
    rb = client.post(f"/api/topics/{tid}/pdfs/upload", files={"file": ("b.pdf", b"%PDF-1.4 B", "application/pdf")}, headers=h)
    assert rb.status_code == 200, rb.text
    return tid, ra.json()["id"], rb.json()["id"]


def test_generate_and_cache(client):
    """Generar persiste; GET cacheado NO llama a Gemini (coste 0)."""
    h = _auth(client, "sum_gen@x.com")
    sid = _subject(client, h, "Asig")
    tid, a, b = _topic_two_pdfs(client, h, sid)

    before = _FakeModels.calls
    r = client.post(f"/api/pdfs/{a}/summary", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pdf_id"] == a and body["scope"] == "pdf"
    assert body["content"]["overview"].startswith("Resumen")
    assert _FakeModels.calls == before + 1  # 1 llamada a Gemini

    # Servir de caché: mismo contenido, SIN nueva llamada.
    g = client.get(f"/api/pdfs/{a}/summary", headers=h)
    assert g.status_code == 200, g.text
    assert g.json()["content"] == body["content"]
    assert _FakeModels.calls == before + 1


def test_get_missing_summary_404(client):
    h = _auth(client, "sum_missing@x.com")
    sid = _subject(client, h, "Asig")
    tid, a, b = _topic_two_pdfs(client, h, sid)
    r = client.get(f"/api/pdfs/{a}/summary", headers=h)
    assert r.status_code == 404, r.text


def test_regenerate_overwrites(client):
    h = _auth(client, "sum_regen@x.com")
    sid = _subject(client, h, "Asig")
    tid, a, b = _topic_two_pdfs(client, h, sid)

    first = client.post(f"/api/pdfs/{a}/summary", headers=h).json()
    second = client.post(f"/api/pdfs/{a}/summary", headers=h).json()
    assert second["id"] == first["id"]  # mismo doc (upsert)
    assert second["content"]["overview"] != first["content"]["overview"]  # sobrescrito

    # Sigue habiendo un único resumen para ese PDF.
    listed = client.get(f"/api/topics/{tid}/summaries", headers=h).json()
    assert len([s for s in listed if s["pdf_id"] == a]) == 1


def test_topic_summaries_list(client):
    h = _auth(client, "sum_list@x.com")
    sid = _subject(client, h, "Asig")
    tid, a, b = _topic_two_pdfs(client, h, sid)

    assert client.get(f"/api/topics/{tid}/summaries", headers=h).json() == []
    client.post(f"/api/pdfs/{a}/summary", headers=h)
    listed = client.get(f"/api/topics/{tid}/summaries", headers=h).json()
    assert {s["pdf_id"] for s in listed} == {a}
    client.post(f"/api/pdfs/{b}/summary", headers=h)
    listed = client.get(f"/api/topics/{tid}/summaries", headers=h).json()
    assert {s["pdf_id"] for s in listed} == {a, b}


def test_summary_deleted_with_pdf(client):
    """Al borrar el PDF por completo, su resumen se borra (sin huérfanos)."""
    h = _auth(client, "sum_del@x.com")
    sid = _subject(client, h, "Asig")
    tid, a, b = _topic_two_pdfs(client, h, sid)
    client.post(f"/api/pdfs/{a}/summary", headers=h)
    assert client.get(f"/api/pdfs/{a}/summary", headers=h).status_code == 200

    assert client.delete(f"/api/pdfs/{a}", headers=h).status_code == 200
    assert client.get(f"/api/pdfs/{a}/summary", headers=h).status_code == 404


def test_summary_deleted_on_unlink_orphan(client):
    """Desvincular un PDF de su ÚNICO tema lo deja huérfano y lo borra (vía
    _delete_pdf_if_orphan): su resumen debe borrarse con él."""
    h = _auth(client, "sum_orphan@x.com")
    sid = _subject(client, h, "Asig")
    tid, a, b = _topic_two_pdfs(client, h, sid)  # a y b solo están en tid
    client.post(f"/api/pdfs/{a}/summary", headers=h)
    assert client.get(f"/api/pdfs/{a}/summary", headers=h).status_code == 200

    r = client.delete(f"/api/topics/{tid}/pdfs/{a}", headers=h)
    assert r.status_code == 200 and r.json()["pdf_deleted"] is True  # quedó huérfano
    assert client.get(f"/api/pdfs/{a}/summary", headers=h).status_code == 404


def test_summary_kept_on_unlink_when_shared(client):
    """Desvincular un PDF de un tema (sigue en otro) NO borra su resumen."""
    h = _auth(client, "sum_unlink@x.com")
    sid = _subject(client, h, "Asig")
    tid1, a, b = _topic_two_pdfs(client, h, sid)
    # Vincula el PDF `a` a un segundo tema.
    t2 = client.post(f"/api/subjects/{sid}/topics", json={"name": "Tema 2"}, headers=h).json()["id"]
    assert client.post(f"/api/topics/{t2}/pdfs/{a}/link", headers=h).status_code == 200
    client.post(f"/api/pdfs/{a}/summary", headers=h)

    # Desvincula de tema1: el PDF sigue vivo (en tema2) -> resumen intacto.
    r = client.delete(f"/api/topics/{tid1}/pdfs/{a}", headers=h)
    assert r.status_code == 200 and r.json()["pdf_deleted"] is False
    assert client.get(f"/api/pdfs/{a}/summary", headers=h).status_code == 200


def test_summary_isolation(client):
    ha = _auth(client, "sum_ownerA@x.com")
    sid = _subject(client, ha, "De A")
    tid, a, b = _topic_two_pdfs(client, ha, sid)
    client.post(f"/api/pdfs/{a}/summary", headers=ha)

    hb = _auth(client, "sum_ownerB@x.com")
    # Otro usuario no puede generar, leer ni listar resúmenes ajenos.
    assert client.post(f"/api/pdfs/{a}/summary", headers=hb).status_code == 404
    assert client.get(f"/api/pdfs/{a}/summary", headers=hb).status_code == 404
    assert client.get(f"/api/topics/{tid}/summaries", headers=hb).status_code == 404
