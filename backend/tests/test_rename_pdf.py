"""
PATCH /api/pdfs/{id}: renombrar un PDF.

El rename es SINGLE-SOURCE: solo se escribe `pdfs.filename`. Aquí se fija esa
conducta, la validación (422), el aislamiento multiusuario (404 para PDF ajeno
o inexistente) y que el nuevo nombre se ve en las lecturas que lo derivan
(GET /pdfs y GET /summaries).

In-process (TestClient + mongomock); la extracción de PDF se mockea.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient


def _fake_extract_pdf_text(_b: bytes) -> str:
    return ("Temario de prueba. " * 40).strip()


@pytest.fixture(scope="module")
def srv():
    import server
    orig = server.extract_pdf_text
    server.extract_pdf_text = _fake_extract_pdf_text
    yield server
    server.extract_pdf_text = orig


@pytest.fixture(scope="module")
def client(srv):
    with TestClient(srv.app) as c:
        yield c


def _auth(client, email):
    assert client.post("/api/auth/register", json={"email": email, "password": "secret123"}).status_code == 201
    r = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _upload(client, h, name="original.pdf"):
    """Sube un PDF a la biblioteca (sin tema) y devuelve su id."""
    r = client.post("/api/pdfs", files={"file": (name, b"%PDF-1.4 fake", "application/pdf")}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _doc(srv, pdf_id):
    return asyncio.run(srv.db.pdfs.find_one({"id": pdf_id}, {"_id": 0}))


def _rename(client, h, pdf_id, filename):
    return client.patch(f"/api/pdfs/{pdf_id}", json={"filename": filename}, headers=h)


# --- Camino feliz ---------------------------------------------------------

def test_rename_own_pdf_ok(client, srv):
    h = _auth(client, "ren_ok@x.com")
    pid = _upload(client, h)

    r = _rename(client, h, pid, "Tema 3 — Constitución.pdf")
    assert r.status_code == 200, r.text
    assert _doc(srv, pid)["filename"] == "Tema 3 — Constitución.pdf"


def test_rename_trims_whitespace(client, srv):
    h = _auth(client, "ren_trim@x.com")
    pid = _upload(client, h)

    assert _rename(client, h, pid, "   Apuntes.pdf  ").status_code == 200
    assert _doc(srv, pid)["filename"] == "Apuntes.pdf"


def test_rename_only_touches_filename(client, srv):
    """No debe tocar text, char_count, created_at ni los ids."""
    h = _auth(client, "ren_single@x.com")
    pid = _upload(client, h)
    before = _doc(srv, pid)

    assert _rename(client, h, pid, "otro-nombre.pdf").status_code == 200
    after = _doc(srv, pid)

    assert after["filename"] == "otro-nombre.pdf"
    for field in ("id", "user_id", "text", "char_count", "created_at"):
        assert after[field] == before[field], field


# --- Validación (422) -----------------------------------------------------

def test_rename_empty_filename_422(client):
    h = _auth(client, "ren_empty@x.com")
    pid = _upload(client, h)
    assert _rename(client, h, pid, "").status_code == 422


def test_rename_blank_filename_422(client, srv):
    h = _auth(client, "ren_blank@x.com")
    pid = _upload(client, h, "queda.pdf")
    assert _rename(client, h, pid, "     ").status_code == 422
    assert _doc(srv, pid)["filename"] == "queda.pdf"  # sin cambios


def test_rename_too_long_422(client):
    h = _auth(client, "ren_long@x.com")
    pid = _upload(client, h)
    assert _rename(client, h, pid, "a" * 201).status_code == 422
    assert _rename(client, h, pid, "a" * 200).status_code == 200  # el tope sí entra


# --- Multiusuario / inexistente (404) -------------------------------------

def test_rename_missing_pdf_404(client):
    h = _auth(client, "ren_missing@x.com")
    assert _rename(client, h, "no-existe", "x.pdf").status_code == 404


def test_rename_other_users_pdf_404(client, srv):
    """Un PDF ajeno responde 404 (no 403): no se revela su existencia, y su
    nombre queda intacto."""
    owner = _auth(client, "ren_owner@x.com")
    other = _auth(client, "ren_other@x.com")
    pid = _upload(client, owner, "del-duenyo.pdf")

    assert _rename(client, other, pid, "secuestrado.pdf").status_code == 404
    assert _doc(srv, pid)["filename"] == "del-duenyo.pdf"


# --- El nombre nuevo se refleja en las lecturas que lo derivan ------------

def test_rename_shows_in_pdf_list(client):
    h = _auth(client, "ren_list@x.com")
    pid = _upload(client, h)
    assert _rename(client, h, pid, "nuevo-en-lista.pdf").status_code == 200

    items = client.get("/api/pdfs", headers=h).json()
    assert [p["filename"] for p in items if p["id"] == pid] == ["nuevo-en-lista.pdf"]


def test_rename_propagates_to_summaries_listing(client, srv):
    """El `pdf_filename` de GET /summaries se DERIVA de pdfs, así que el rename
    se ve sin tocar la colección summaries."""
    h = _auth(client, "ren_sum@x.com")
    pid = _upload(client, h)
    uid = asyncio.run(srv.db.pdfs.find_one({"id": pid}))["user_id"]
    # Resumen ya cacheado (insertado directo: generar llamaría a Gemini).
    asyncio.run(srv.db.summaries.insert_one(
        srv.Summary(user_id=uid, pdf_id=pid, content={"overview": "x"}).model_dump()
    ))

    assert _rename(client, h, pid, "renombrado-en-resumenes.pdf").status_code == 200

    rows = client.get("/api/summaries", headers=h).json()
    assert [s["pdf_filename"] for s in rows if s["pdf_id"] == pid] == ["renombrado-en-resumenes.pdf"]
