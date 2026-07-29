"""
Flashcards por PDF: selección de fuentes + reemplazo POR PDF con pdf_source_id.

Verifica el nuevo contrato de POST /topics/{id}/flashcards/generate:
- cada tarjeta guarda pdf_source_id (atribución a su PDF),
- regenerar un SUBCONJUNTO reemplaza solo esas fuentes y conserva el resto
  (incluidas su progreso SRS/favoritos y las tarjetas legacy sin fuente),
- regenerar TODOS los PDFs barre el tema entero (incluidas las legacy),
- la operación cuenta como 1 unidad de cuota aunque genere de N PDFs,
- reparto de num_cards proporcional al char_count,
- validación (ids ajenos) y aislamiento multiusuario.

In-process (TestClient + mongomock, IA mockeada).
"""
import asyncio

import pytest
from fastapi.testclient import TestClient


def _fake_extract_pdf_text(_b: bytes) -> str:
    return ("Temario de prueba. " * 40).strip()


async def _fake_generate_flashcards(topic_name, source_text, num_cards):
    # Devuelve exactamente num_cards para poder verificar el reparto.
    return [{"term": f"t{i}", "definition": f"d{i}", "example": ""} for i in range(num_cards)]


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
    server._generate_flashcards_from_text = _fake_generate_flashcards
    server.generate_questions_with_claude = _fake_generate_questions
    return server


@pytest.fixture(scope="module")
def client(srv):
    with TestClient(srv.app) as c:
        yield c


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _auth(client, email):
    assert client.post("/api/auth/register", json={"email": email, "password": "secret123"}).status_code == 201
    r = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _subject(client, h, name):
    r = client.post("/api/subjects", json={"name": name}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _topic_two_pdfs(client, h, subject_id):
    """Crea un tema con 2 PDFs (A y B) por el flujo real (tema vacío + subir PDF).
    Devuelve (topic_id, pdf_a, pdf_b)."""
    t = client.post(f"/api/subjects/{subject_id}/topics", json={"name": "Tema"}, headers=h)
    assert t.status_code == 200, t.text
    tid = t.json()["id"]
    ra = client.post(
        f"/api/topics/{tid}/pdfs/upload",
        files={"file": ("a.pdf", b"%PDF-1.4 A", "application/pdf")},
        headers=h,
    )
    assert ra.status_code == 200, ra.text
    rb = client.post(
        f"/api/topics/{tid}/pdfs/upload",
        files={"file": ("b.pdf", b"%PDF-1.4 B", "application/pdf")},
        headers=h,
    )
    assert rb.status_code == 200, rb.text
    return tid, ra.json()["id"], rb.json()["id"]


def _cards(client, h, tid):
    r = client.get(f"/api/topics/{tid}/flashcards", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _gen(client, h, tid, body=None):
    return client.post(f"/api/topics/{tid}/flashcards/generate", json=body if body is not None else {}, headers=h)


def _used(client, h):
    return client.get("/api/usage/me", headers=h).json()["used"]


def _run(srv, coro_fn):
    return asyncio.run(coro_fn())


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
def test_generate_all_attributes_source(client):
    h = _auth(client, "fc_all@x.com")
    sid = _subject(client, h, "Asig")
    tid, a, b = _topic_two_pdfs(client, h, sid)

    r = _gen(client, h, tid, {"num_cards": 12})
    assert r.status_code == 200, r.text
    cards = _cards(client, h, tid)
    assert len(cards) == 12
    assert all(c["pdf_source_id"] in (a, b) for c in cards)
    # Reparto proporcional: PDFs de igual char_count -> mitad y mitad.
    na = sum(1 for c in cards if c["pdf_source_id"] == a)
    nb = sum(1 for c in cards if c["pdf_source_id"] == b)
    assert na > 0 and nb > 0 and na + nb == 12
    assert abs(na - nb) <= 1


def test_subset_regen_preserves_others_and_progress(client, srv):
    h = _auth(client, "fc_subset@x.com")
    sid = _subject(client, h, "Asig")
    tid, a, b = _topic_two_pdfs(client, h, sid)

    assert _gen(client, h, tid, {"num_cards": 10}).status_code == 200
    cards = _cards(client, h, tid)
    a_cards = [c for c in cards if c["pdf_source_id"] == a]
    b_ids_before = {c["id"] for c in cards if c["pdf_source_id"] == b}
    assert a_cards and b_ids_before

    # Marca favorito + repasa una tarjeta de A (progreso que NO debe perderse).
    target = a_cards[0]
    assert client.post(f"/api/flashcards/{target['id']}/favorite", headers=h).status_code == 200
    assert client.post(f"/api/flashcards/{target['id']}/review?correct=true", headers=h).status_code == 200
    a_ids_before = {c["id"] for c in a_cards}

    # Regenera SOLO B.
    assert _gen(client, h, tid, {"pdf_ids": [b], "num_cards": 6}).status_code == 200
    after = _cards(client, h, tid)

    # Las de A siguen ahí, con su progreso.
    a_after = {c["id"]: c for c in after if c["pdf_source_id"] == a}
    assert set(a_after.keys()) == a_ids_before
    assert a_after[target["id"]]["favorite"] is True
    assert a_after[target["id"]]["times_reviewed"] == 1
    # Las de B se reemplazaron (ids nuevos).
    b_ids_after = {c["id"] for c in after if c["pdf_source_id"] == b}
    assert b_ids_after and b_ids_after.isdisjoint(b_ids_before)


def test_full_regen_sweeps_legacy(client, srv):
    h = _auth(client, "fc_legacy_full@x.com")
    sid = _subject(client, h, "Asig")
    tid, a, b = _topic_two_pdfs(client, h, sid)

    # Inserta una tarjeta legacy (sin pdf_source_id) directamente en Mongo.
    async def _insert():
        await srv.db.flashcards.insert_one({
            "id": "legacy-1", "user_id": (await srv.db.topics.find_one({"id": tid}))["user_id"],
            "topic_id": tid, "topic_name": "Tema", "term": "L", "definition": "D",
            "example": "", "favorite": False, "times_reviewed": 0, "times_correct": 0,
            "created_at": "2020-01-01T00:00:00+00:00",
        })
    _run(srv, _insert)

    # Regenerar TODOS barre el tema completo, incluida la legacy.
    assert _gen(client, h, tid, {"num_cards": 8}).status_code == 200
    after_ids = {c["id"] for c in _cards(client, h, tid)}
    assert "legacy-1" not in after_ids


def test_subset_regen_preserves_legacy(client, srv):
    h = _auth(client, "fc_legacy_subset@x.com")
    sid = _subject(client, h, "Asig")
    tid, a, b = _topic_two_pdfs(client, h, sid)

    async def _insert():
        await srv.db.flashcards.insert_one({
            "id": "legacy-2", "user_id": (await srv.db.topics.find_one({"id": tid}))["user_id"],
            "topic_id": tid, "topic_name": "Tema", "term": "L", "definition": "D",
            "example": "", "favorite": False, "times_reviewed": 0, "times_correct": 0,
            "created_at": "2020-01-01T00:00:00+00:00",
        })
    _run(srv, _insert)

    # Regenerar un subconjunto NO toca la legacy.
    assert _gen(client, h, tid, {"pdf_ids": [a], "num_cards": 5}).status_code == 200
    after_ids = {c["id"] for c in _cards(client, h, tid)}
    assert "legacy-2" in after_ids


def test_quota_counts_one_for_multi_pdf(client):
    h = _auth(client, "fc_quota@x.com")
    sid = _subject(client, h, "Asig")
    tid, a, b = _topic_two_pdfs(client, h, sid)  # _upload_topic ya consumió 1

    before = _used(client, h)
    assert _gen(client, h, tid, {"num_cards": 10}).status_code == 200
    after = _used(client, h)
    assert after == before + 1  # 1 unidad pese a generar de 2 PDFs


def test_foreign_pdf_ids(client):
    h = _auth(client, "fc_foreign@x.com")
    sid = _subject(client, h, "Asig")
    tid, a, b = _topic_two_pdfs(client, h, sid)

    # Solo ids ajenos -> 404.
    assert _gen(client, h, tid, {"pdf_ids": ["nope"]}).status_code == 404
    # Mezcla: se usan solo los válidos (200) y se atribuyen a ese PDF.
    assert _gen(client, h, tid, {"pdf_ids": [a, "nope"], "num_cards": 5}).status_code == 200
    after = _cards(client, h, tid)
    assert all(c["pdf_source_id"] == a for c in after if c["pdf_source_id"] is not None)


def test_isolation(client):
    ha = _auth(client, "fc_ownerA@x.com")
    sid = _subject(client, ha, "De A")
    tid, a, b = _topic_two_pdfs(client, ha, sid)
    hb = _auth(client, "fc_ownerB@x.com")
    assert _gen(client, hb, tid, {"num_cards": 5}).status_code == 404
