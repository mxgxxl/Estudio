"""
Desglose por tipo de "crear material" (sub-contadores del ciclo actual).

INVARIANTE central: ai_gen_questions_used + ai_gen_summaries_used +
ai_gen_flashcards_used == ai_generations_used, siempre. Se garantiza en el ÚNICO
punto de consumo/refund/reset (check_and_consume_ai_quota / _refund_ai_quota).

Cubre:
- Consumir cada gen_kind sube el agregado Y su sub-contador (los demás a 0).
- Invariante suma == agregado tras generaciones mixtas.
- Refund decrementa agregado y sub-contador juntos.
- Reset de ciclo pone agregado + 3 sub-contadores a 0 (vía consume y vía /usage/me).
- Guardia: kind='generation' sin gen_kind → ValueError, ANTES de tocar la cuota
  (no deja consumo a medias).
- Los 4 endpoints reales de generación pasan su gen_kind (no disparan el
  ValueError y suben el sub-contador correcto).
- /usage/me expone generations.by_type.

In-process (TestClient + mongomock).
"""
import json
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


def _fake_extract_pdf_text(_b: bytes) -> str:
    return ("Temario de prueba. " * 60).strip()


async def _fake_generate_questions(topic_name, source_text, num_questions,
                                   question_type="mcq", num_options=3, custom_instructions=""):
    return [{
        "question": f"P{i}", "options": ["A", "B", "C"], "correct_index": 0,
        "explanation": "", "question_type": "mcq", "num_options": 3, "model_answer": "",
    } for i in range(3)]


async def _fake_generate_flashcards(topic_name, source_text, num_cards):
    return [{"term": f"T{i}", "definition": "D", "example": ""} for i in range(3)]


class _FakeModels:
    async def generate_content(self, **kwargs):
        class _R:
            text = json.dumps({
                "overview": "o", "key_concepts": [], "sections": [], "remember": [],
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
    server._generate_flashcards_from_text = _fake_generate_flashcards
    server.GEMINI_API_KEY = "test-key"
    server.gemini_client = _FakeClient()
    return server


@pytest.fixture(scope="module")
def client(srv):
    with TestClient(srv.app) as c:
        yield c


# --- helpers ---------------------------------------------------------------
def _auth(client, email):
    assert client.post("/api/auth/register", json={"email": email, "password": "secret123"}).status_code == 201
    r = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert r.status_code == 200, r.text
    uid = r.json().get("user", {}).get("id") or _uid_from_me(client, r.json()["access_token"])
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, uid


def _uid_from_me(client, token):
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    return r.json()["id"]


def _user(srv, uid):
    return asyncio.run(srv.db.users.find_one({"id": uid}))


def _consume(srv, uid, gen_kind):
    asyncio.run(srv.check_and_consume_ai_quota(_user(srv, uid), gen_kind=gen_kind))


def _subject(client, h, name):
    r = client.post("/api/subjects", json={"name": name}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _topic_with_pdf(client, h, sid):
    t = client.post(f"/api/subjects/{sid}/topics", json={"name": "Tema"}, headers=h)
    assert t.status_code == 200, t.text
    tid = t.json()["id"]
    up = client.post(f"/api/topics/{tid}/pdfs/upload",
                     files={"file": ("a.pdf", b"%PDF-1.4 A", "application/pdf")}, headers=h)
    assert up.status_code == 200, up.text
    return tid, up.json()["id"]


SUBFIELDS = ("ai_gen_questions_used", "ai_gen_summaries_used", "ai_gen_flashcards_used")


def _invariant(u):
    assert sum(int(u.get(f, 0) or 0) for f in SUBFIELDS) == int(u.get("ai_generations_used", 0) or 0)


# --- tests: helper (punto único) -------------------------------------------
def test_consume_each_kind_bumps_aggregate_and_its_subcounter(client, srv):
    h, uid = _auth(client, "each@x.com")
    _consume(srv, uid, "questions")
    u = _user(srv, uid)
    assert u["ai_generations_used"] == 1
    assert u["ai_gen_questions_used"] == 1
    assert u["ai_gen_summaries_used"] == 0 and u["ai_gen_flashcards_used"] == 0

    _consume(srv, uid, "summaries")
    _consume(srv, uid, "flashcards")
    u = _user(srv, uid)
    assert u["ai_generations_used"] == 3
    assert u["ai_gen_questions_used"] == 1 and u["ai_gen_summaries_used"] == 1 and u["ai_gen_flashcards_used"] == 1
    _invariant(u)


def test_invariant_holds_after_mixed(client, srv):
    h, uid = _auth(client, "mixed@x.com")
    for gk in ["questions", "questions", "flashcards", "summaries", "questions"]:
        _consume(srv, uid, gk)
    u = _user(srv, uid)
    assert u["ai_generations_used"] == 5
    assert u["ai_gen_questions_used"] == 3 and u["ai_gen_flashcards_used"] == 1 and u["ai_gen_summaries_used"] == 1
    _invariant(u)


def test_refund_decrements_aggregate_and_the_CORRECT_subcounter(client, srv):
    """Con varios tipos en juego, el refund de UNO debe bajar su sub-contador y el
    agregado, dejando los OTROS intactos. (Un refund al tipo equivocado cuadraría
    el agregado pero corrompería el desglose; por eso se consumen tipos distintos.)"""
    h, uid = _auth(client, "refund@x.com")
    _consume(srv, uid, "questions")
    _consume(srv, uid, "summaries")
    _consume(srv, uid, "flashcards")

    # Refund SOLO de resúmenes.
    asyncio.run(srv._refund_ai_quota({"id": uid}, gen_kind="summaries"))

    u = _user(srv, uid)
    assert u["ai_generations_used"] == 2          # agregado baja 1
    assert u["ai_gen_summaries_used"] == 0         # el tipo devuelto baja
    assert u["ai_gen_questions_used"] == 1         # los otros NO se tocan
    assert u["ai_gen_flashcards_used"] == 1
    _invariant(u)

    # Y un segundo refund de otro tipo distinto, para no fijar el tipo por azar.
    asyncio.run(srv._refund_ai_quota({"id": uid}, gen_kind="flashcards"))
    u = _user(srv, uid)
    assert u["ai_generations_used"] == 1
    assert u["ai_gen_flashcards_used"] == 0
    assert u["ai_gen_questions_used"] == 1 and u["ai_gen_summaries_used"] == 0
    _invariant(u)


def test_reset_zeroes_aggregate_and_subcounters(client, srv):
    h, uid = _auth(client, "reset@x.com")
    _consume(srv, uid, "questions")
    _consume(srv, uid, "flashcards")
    # Forzar expiración del periodo.
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    asyncio.run(srv.db.users.update_one({"id": uid}, {"$set": {"ai_period_start": old}}))
    # El siguiente consumo reinicia (todo a 0) y consume 1 del nuevo tipo.
    _consume(srv, uid, "summaries")
    u = _user(srv, uid)
    assert u["ai_generations_used"] == 1
    assert u["ai_gen_summaries_used"] == 1
    assert u["ai_gen_questions_used"] == 0 and u["ai_gen_flashcards_used"] == 0
    _invariant(u)


def test_guard_missing_gen_kind_raises_before_consuming(client, srv):
    h, uid = _auth(client, "guard@x.com")
    with pytest.raises(ValueError):
        asyncio.run(srv.check_and_consume_ai_quota(_user(srv, uid)))  # kind=generation, sin gen_kind
    # La guardia va ANTES del $inc: la cuota NO se movió.
    u = _user(srv, uid)
    assert u["ai_generations_used"] == 0
    assert all(u.get(f, 0) == 0 for f in SUBFIELDS)


# --- tests: endpoints reales (no disparan la guardia) ----------------------
def test_real_generation_endpoints_pass_their_gen_kind(client, srv):
    h, uid = _auth(client, "real@x.com")
    sid = _subject(client, h, "S")
    tid, pid = _topic_with_pdf(client, h, sid)

    assert client.post(f"/api/topics/{tid}/generate",
                       json={"pdf_ids": [pid], "num_questions": 3}, headers=h).status_code == 200
    assert client.post(f"/api/pdfs/{pid}/regenerate",
                       json={"num_questions": 3, "question_type": "mcq", "num_options": 3}, headers=h).status_code == 200
    assert client.post(f"/api/topics/{tid}/flashcards/generate", json={}, headers=h).status_code == 200
    assert client.post(f"/api/pdfs/{pid}/summary", headers=h).status_code == 200

    gen = client.get("/api/usage/me", headers=h).json()["generations"]
    bt = gen["by_type"]
    assert bt["questions"]["used"] == 2   # generate + regenerate
    assert bt["flashcards"]["used"] == 1
    assert bt["summaries"]["used"] == 1
    assert gen["used"] == 4
    # invariante desde la API
    assert bt["questions"]["used"] + bt["summaries"]["used"] + bt["flashcards"]["used"] == gen["used"]


# --- tests: /usage/me ------------------------------------------------------
def test_usage_me_exposes_by_type(client, srv):
    h, uid = _auth(client, "bytype@x.com")
    _consume(srv, uid, "summaries")
    gen = client.get("/api/usage/me", headers=h).json()["generations"]
    assert gen["by_type"]["summaries"]["used"] == 1
    assert gen["by_type"]["questions"]["used"] == 0 and gen["by_type"]["flashcards"]["used"] == 0


def test_usage_me_shows_reset_breakdown_when_period_expired(client, srv):
    h, uid = _auth(client, "resetdisplay@x.com")
    _consume(srv, uid, "questions")
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    asyncio.run(srv.db.users.update_one({"id": uid}, {"$set": {"ai_period_start": old}}))
    gen = client.get("/api/usage/me", headers=h).json()["generations"]
    assert gen["used"] == 0
    assert gen["by_type"] == {"questions": {"used": 0}, "summaries": {"used": 0}, "flashcards": {"used": 0}}
