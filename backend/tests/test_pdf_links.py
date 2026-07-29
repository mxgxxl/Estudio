"""
Fase 1 (commit 2): relación muchos-a-muchos PDF<->tema vía la colección pdf_links.

Verifica que los endpoints leen de pdf_links y, sobre todo, la CASCADA con
orfandad al borrar: un PDF solo se borra cuando no le queda ningún vínculo.

In-process (TestClient + mongomock, IA mockeada). Como los endpoints de asociar
un PDF a varios temas llegan en Fase 2, para montar el estado "PDF en 2 temas"
se usa el helper interno server._link_pdf_to_topic (test de caja blanca).
"""
import asyncio

import pytest
from fastapi.testclient import TestClient


def _fake_extract_pdf_text(_b: bytes) -> str:
    return ("Temario de prueba. " * 40).strip()


async def _fake_generate_questions(topic_name, source_text, num_questions,
                                   question_type="mcq", num_options=3, custom_instructions=""):
    return [{
        "question": f"P{i} {topic_name}", "options": ["A", "B", "C"], "correct_index": 0,
        "explanation": "", "question_type": "mcq", "num_options": 3, "model_answer": "",
    } for i in range(3)]


async def _fake_generate_flashcards(topic_name, source_text, num_cards):
    return [{"term": f"T{i}", "definition": f"D{i}", "example": ""} for i in range(3)]


@pytest.fixture(scope="module")
def srv():
    import server
    server.extract_pdf_text = _fake_extract_pdf_text
    server.generate_questions_with_claude = _fake_generate_questions
    server._generate_flashcards_from_text = _fake_generate_flashcards
    return server


@pytest.fixture(scope="module")
def client(srv):
    with TestClient(srv.app) as c:
        yield c


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
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


def _upload_topic(client, h, subject_id, name):
    """Crea tema + PDF (y su vínculo) y genera preguntas, por el flujo real en
    tres pasos. Genera para que las preguntas queden con pdf_source_id = pdf_id
    (lo necesitan los tests de desvinculación). Devuelve (topic_id, pdf_id)."""
    t = client.post(f"/api/subjects/{subject_id}/topics", json={"name": name}, headers=h)
    assert t.status_code == 200, t.text
    tid = t.json()["id"]
    up = client.post(
        f"/api/topics/{tid}/pdfs/upload",
        files={"file": ("t.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers=h,
    )
    assert up.status_code == 200, up.text
    pid = up.json()["id"]
    g = client.post(
        f"/api/topics/{tid}/generate",
        json={"pdf_ids": [pid], "num_questions": 3},
        headers=h,
    )
    assert g.status_code == 200, g.text
    return tid, pid


def _add_pdf(client, h, topic_id):
    r = client.post(
        f"/api/topics/{topic_id}/pdfs/upload",
        files={"file": ("x.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers=h,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _link(srv, uid, pdf_id, topic_id, subject_id=None):
    asyncio.run(srv._link_pdf_to_topic(uid, pdf_id, topic_id, subject_id))


def _links_count(srv, uid, pdf_id):
    return asyncio.run(srv.db.pdf_links.count_documents({"user_id": uid, "pdf_id": pdf_id}))


def _pdf_exists(srv, uid, pdf_id):
    return asyncio.run(srv.db.pdfs.find_one({"id": pdf_id, "user_id": uid})) is not None


def _topic_pdf_ids(client, h, topic_id):
    r = client.get(f"/api/topics/{topic_id}/pdfs", headers=h)
    assert r.status_code == 200, r.text
    return {p["id"] for p in r.json()}


# --------------------------------------------------------------------------
# Lectura vía pdf_links
# --------------------------------------------------------------------------
class TestReadThroughLinks:
    def test_upload_creates_link_and_listing_reads_it(self, client, srv):
        uid = _register(client, "read1@t.com")
        h = _login(client, "read1@t.com")
        s = _subject(client, h, "S")
        t1, p1 = _upload_topic(client, h, s, "T1")
        assert _links_count(srv, uid, p1) == 1
        assert _topic_pdf_ids(client, h, t1) == {p1}

    def test_generate_rejects_pdf_not_linked_to_topic(self, client, srv):
        uid = _register(client, "read2@t.com")
        h = _login(client, "read2@t.com")
        s = _subject(client, h, "S")
        t1, p1 = _upload_topic(client, h, s, "T1")
        t2, p2 = _upload_topic(client, h, s, "T2")
        # p2 NO está vinculado a t1 -> generate en t1 con p2 debe fallar (404).
        r = client.post(f"/api/topics/{t1}/generate",
                        json={"pdf_ids": [p2], "num_questions": 3}, headers=h)
        assert r.status_code == 404

    def test_link_is_idempotent(self, client, srv):
        uid = _register(client, "read3@t.com")
        h = _login(client, "read3@t.com")
        s = _subject(client, h, "S")
        t1, p1 = _upload_topic(client, h, s, "T1")
        t2, p2 = _upload_topic(client, h, s, "T2")
        _link(srv, uid, p1, t2, s)
        _link(srv, uid, p1, t2, s)  # repetido
        assert _links_count(srv, uid, p1) == 2  # t1 + t2, sin duplicar


# --------------------------------------------------------------------------
# Cascada de borrado con orfandad
# --------------------------------------------------------------------------
class TestCascadeDelete:
    def test_pdf_in_one_topic_delete_topic_removes_pdf(self, client, srv):
        uid = _register(client, "c1@t.com")
        h = _login(client, "c1@t.com")
        s = _subject(client, h, "S")
        t1, p1 = _upload_topic(client, h, s, "T1")
        assert _pdf_exists(srv, uid, p1) and _links_count(srv, uid, p1) == 1

        assert client.delete(f"/api/topics/{t1}", headers=h).status_code == 200
        assert _links_count(srv, uid, p1) == 0
        assert not _pdf_exists(srv, uid, p1)  # huérfano -> borrado
        assert client.get(f"/api/topics/{t1}", headers=h).status_code == 404

    def test_pdf_in_two_topics_delete_one_keeps_pdf(self, client, srv):
        uid = _register(client, "c2@t.com")
        h = _login(client, "c2@t.com")
        s = _subject(client, h, "S")
        t1, p1 = _upload_topic(client, h, s, "T1")
        t2, _ = _upload_topic(client, h, s, "T2")
        _link(srv, uid, p1, t2, s)  # p1 ahora en t1 y t2
        assert _links_count(srv, uid, p1) == 2

        assert client.delete(f"/api/topics/{t1}", headers=h).status_code == 200
        assert _links_count(srv, uid, p1) == 1          # queda el de t2
        assert _pdf_exists(srv, uid, p1)                # NO se borra
        assert p1 in _topic_pdf_ids(client, h, t2)      # t2 lo sigue viendo

    def test_pdf_in_two_topics_delete_both_removes_pdf(self, client, srv):
        uid = _register(client, "c3@t.com")
        h = _login(client, "c3@t.com")
        s = _subject(client, h, "S")
        t1, p1 = _upload_topic(client, h, s, "T1")
        t2, _ = _upload_topic(client, h, s, "T2")
        _link(srv, uid, p1, t2, s)

        assert client.delete(f"/api/topics/{t1}", headers=h).status_code == 200
        assert _pdf_exists(srv, uid, p1)                # sigue por t2
        assert client.delete(f"/api/topics/{t2}", headers=h).status_code == 200
        assert _links_count(srv, uid, p1) == 0
        assert not _pdf_exists(srv, uid, p1)            # ahora huérfano -> borrado

    def test_delete_pdf_endpoint_removes_from_all_topics(self, client, srv):
        uid = _register(client, "c4@t.com")
        h = _login(client, "c4@t.com")
        s = _subject(client, h, "S")
        t1, p1 = _upload_topic(client, h, s, "T1")
        t2, _ = _upload_topic(client, h, s, "T2")
        _link(srv, uid, p1, t2, s)

        assert client.delete(f"/api/pdfs/{p1}", headers=h).status_code == 200
        assert _links_count(srv, uid, p1) == 0
        assert not _pdf_exists(srv, uid, p1)
        assert p1 not in _topic_pdf_ids(client, h, t1)
        assert p1 not in _topic_pdf_ids(client, h, t2)
        # Las preguntas creadas desde p1 quedan desligadas (pdf_source_id = None).
        remaining = asyncio.run(srv.db.questions.count_documents(
            {"user_id": uid, "pdf_source_id": p1}))
        assert remaining == 0

    def test_delete_subject_deletes_pdf_only_if_no_other_subject(self, client, srv):
        uid = _register(client, "c5@t.com")
        h = _login(client, "c5@t.com")
        s1 = _subject(client, h, "S1")
        s2 = _subject(client, h, "S2")
        t1, p1 = _upload_topic(client, h, s1, "T1")   # p1 en S1/T1
        t2, p2 = _upload_topic(client, h, s2, "T2")   # p2 en S2/T2
        _link(srv, uid, p1, t2, s2)                   # p1 TAMBIÉN en S2/T2

        # Borrar S1: se va T1 y el vínculo p1-t1, pero p1 sigue por S2/T2.
        assert client.delete(f"/api/subjects/{s1}", headers=h).status_code == 200
        assert _pdf_exists(srv, uid, p1)
        assert _links_count(srv, uid, p1) == 1
        assert p1 in _topic_pdf_ids(client, h, t2)

        # Borrar S2: p1 (y p2) quedan huérfanos -> se borran.
        assert client.delete(f"/api/subjects/{s2}", headers=h).status_code == 200
        assert not _pdf_exists(srv, uid, p1)
        assert not _pdf_exists(srv, uid, p2)

    def test_orphan_helper_direct(self, client, srv):
        uid = _register(client, "c6@t.com")
        h = _login(client, "c6@t.com")
        s = _subject(client, h, "S")
        t1, p1 = _upload_topic(client, h, s, "T1")
        t2, _ = _upload_topic(client, h, s, "T2")
        _link(srv, uid, p1, t2, s)  # p1 en t1 y t2

        # Quita el vínculo con t1: aún queda t2 -> no se borra.
        asyncio.run(srv.db.pdf_links.delete_one({"user_id": uid, "pdf_id": p1, "topic_id": t1}))
        deleted = asyncio.run(srv._delete_pdf_if_orphan(uid, p1))
        assert deleted is False and _pdf_exists(srv, uid, p1)

        # Quita el último vínculo -> huérfano -> se borra.
        asyncio.run(srv.db.pdf_links.delete_one({"user_id": uid, "pdf_id": p1, "topic_id": t2}))
        deleted = asyncio.run(srv._delete_pdf_if_orphan(uid, p1))
        assert deleted is True and not _pdf_exists(srv, uid, p1)


# --------------------------------------------------------------------------
# Aislamiento multiusuario en el borrado
# --------------------------------------------------------------------------
class TestDeleteIsolation:
    def test_delete_does_not_touch_other_users_pdfs(self, client, srv):
        uid_a = _register(client, "iso-a@t.com")
        ha = _login(client, "iso-a@t.com")
        uid_b = _register(client, "iso-b@t.com")
        hb = _login(client, "iso-b@t.com")

        sa = _subject(client, ha, "SA")
        ta, pa = _upload_topic(client, ha, sa, "TA")
        sb = _subject(client, hb, "SB")
        tb, pb = _upload_topic(client, hb, sb, "TB")

        # A borra su tema: los datos de B quedan intactos.
        assert client.delete(f"/api/topics/{ta}", headers=ha).status_code == 200
        assert _pdf_exists(srv, uid_b, pb)
        assert _links_count(srv, uid_b, pb) == 1
        assert pb in _topic_pdf_ids(client, hb, tb)


# --------------------------------------------------------------------------
# Fase 2: endpoints link / unlink / GET /pdfs + link_count
# --------------------------------------------------------------------------
def _list_pdfs(client, h):
    r = client.get("/api/pdfs", headers=h)
    assert r.status_code == 200, r.text
    return {p["id"]: p for p in r.json()}


class TestLinkUnlinkEndpoints:
    def test_link_existing_pdf_to_second_topic(self, client, srv):
        uid = _register(client, "lk1@t.com")
        h = _login(client, "lk1@t.com")
        s = _subject(client, h, "S")
        t1, p1 = _upload_topic(client, h, s, "T1")
        t2, p2 = _upload_topic(client, h, s, "T2")

        r = client.post(f"/api/topics/{t2}/pdfs/{p1}/link", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["link_count"] == 2
        # p1 ahora se ve en ambos temas; p2 sigue solo en t2.
        assert _topic_pdf_ids(client, h, t2) == {p1, p2}
        assert _topic_pdf_ids(client, h, t1) == {p1}

    def test_link_is_idempotent(self, client, srv):
        uid = _register(client, "lk2@t.com")
        h = _login(client, "lk2@t.com")
        s = _subject(client, h, "S")
        t1, p1 = _upload_topic(client, h, s, "T1")
        t2, _ = _upload_topic(client, h, s, "T2")
        assert client.post(f"/api/topics/{t2}/pdfs/{p1}/link", headers=h).status_code == 200
        r = client.post(f"/api/topics/{t2}/pdfs/{p1}/link", headers=h)
        assert r.status_code == 200
        assert _links_count(srv, uid, p1) == 2  # sin duplicar

    def test_link_404_topic_or_pdf_or_cross_user(self, client, srv):
        _register(client, "lk-a@t.com"); ha = _login(client, "lk-a@t.com")
        _register(client, "lk-b@t.com"); hb = _login(client, "lk-b@t.com")
        sa = _subject(client, ha, "SA"); ta, pa = _upload_topic(client, ha, sa, "TA")
        sb = _subject(client, hb, "SB"); tb, pb = _upload_topic(client, hb, sb, "TB")

        # B intenta vincular el PDF de A a un tema de B -> PDF no encontrado.
        assert client.post(f"/api/topics/{tb}/pdfs/{pa}/link", headers=hb).status_code == 404
        # B intenta vincular su PDF a un tema de A -> tema no encontrado.
        assert client.post(f"/api/topics/{ta}/pdfs/{pb}/link", headers=hb).status_code == 404
        # Tema/PDF inexistentes.
        assert client.post(f"/api/topics/nope/pdfs/{pb}/link", headers=hb).status_code == 404
        assert client.post(f"/api/topics/{tb}/pdfs/nope/link", headers=hb).status_code == 404

    def test_unlink_keeps_pdf_when_in_other_topics(self, client, srv):
        uid = _register(client, "ul1@t.com")
        h = _login(client, "ul1@t.com")
        s = _subject(client, h, "S")
        t1, p1 = _upload_topic(client, h, s, "T1")
        t2, _ = _upload_topic(client, h, s, "T2")
        assert client.post(f"/api/topics/{t2}/pdfs/{p1}/link", headers=h).status_code == 200

        r = client.delete(f"/api/topics/{t1}/pdfs/{p1}", headers=h)
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True, "pdf_deleted": False}
        assert _pdf_exists(srv, uid, p1)                 # sigue por t2
        assert p1 not in _topic_pdf_ids(client, h, t1)   # ya no en t1
        assert p1 in _topic_pdf_ids(client, h, t2)

    def test_unlink_last_topic_deletes_pdf_and_unlinks_questions(self, client, srv):
        uid = _register(client, "ul2@t.com")
        h = _login(client, "ul2@t.com")
        s = _subject(client, h, "S")
        t1, p1 = _upload_topic(client, h, s, "T1")
        # Tiene preguntas generadas (pdf_source_id = p1).
        assert asyncio.run(srv.db.questions.count_documents(
            {"user_id": uid, "pdf_source_id": p1})) > 0

        r = client.delete(f"/api/topics/{t1}/pdfs/{p1}", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["pdf_deleted"] is True
        assert not _pdf_exists(srv, uid, p1)             # huérfano -> borrado
        # Las preguntas se conservan pero sin referencia al PDF.
        assert asyncio.run(srv.db.questions.count_documents(
            {"user_id": uid, "pdf_source_id": p1})) == 0
        assert asyncio.run(srv.db.questions.count_documents(
            {"user_id": uid, "topic_id": t1})) > 0

    def test_unlink_404_when_pdf_not_in_topic(self, client, srv):
        uid = _register(client, "ul3@t.com")
        h = _login(client, "ul3@t.com")
        s = _subject(client, h, "S")
        t1, p1 = _upload_topic(client, h, s, "T1")
        t2, p2 = _upload_topic(client, h, s, "T2")
        # p2 no está en t1.
        assert client.delete(f"/api/topics/{t1}/pdfs/{p2}", headers=h).status_code == 404

    def test_unlink_isolation(self, client, srv):
        _register(client, "ul-a@t.com"); ha = _login(client, "ul-a@t.com")
        uid_b = _register(client, "ul-b@t.com"); hb = _login(client, "ul-b@t.com")
        sb = _subject(client, hb, "SB"); tb, pb = _upload_topic(client, hb, sb, "TB")
        # A intenta desvincular un PDF de un tema de B -> tema no encontrado.
        assert client.delete(f"/api/topics/{tb}/pdfs/{pb}", headers=ha).status_code == 404
        assert _pdf_exists(srv, uid_b, pb)

    def test_list_topic_pdfs_includes_link_count(self, client, srv):
        uid = _register(client, "lc1@t.com")
        h = _login(client, "lc1@t.com")
        s = _subject(client, h, "S")
        t1, p1 = _upload_topic(client, h, s, "T1")
        t2, _ = _upload_topic(client, h, s, "T2")
        client.post(f"/api/topics/{t2}/pdfs/{p1}/link", headers=h)
        row = next(p for p in client.get(f"/api/topics/{t1}/pdfs", headers=h).json() if p["id"] == p1)
        assert row["link_count"] == 2

    def test_library_lists_all_pdfs_with_link_count(self, client, srv):
        uid = _register(client, "lib1@t.com")
        h = _login(client, "lib1@t.com")
        s = _subject(client, h, "S")
        t1, p1 = _upload_topic(client, h, s, "T1")
        t2, p2 = _upload_topic(client, h, s, "T2")
        client.post(f"/api/topics/{t2}/pdfs/{p1}/link", headers=h)  # p1 en t1 y t2

        lib = _list_pdfs(client, h)
        assert set(lib.keys()) == {p1, p2}
        assert lib[p1]["link_count"] == 2
        assert set(lib[p1]["topic_ids"]) == {t1, t2}
        assert lib[p2]["link_count"] == 1
        assert "text" not in lib[p1]  # no se expone el texto

    def test_library_isolated_per_user(self, client, srv):
        _register(client, "lib-a@t.com"); ha = _login(client, "lib-a@t.com")
        _register(client, "lib-b@t.com"); hb = _login(client, "lib-b@t.com")
        sa = _subject(client, ha, "SA"); _t, pa = _upload_topic(client, ha, sa, "TA")
        sb = _subject(client, hb, "SB"); _t2, pb = _upload_topic(client, hb, sb, "TB")
        assert set(_list_pdfs(client, ha).keys()) == {pa}
        assert set(_list_pdfs(client, hb).keys()) == {pb}


# --------------------------------------------------------------------------
# Fase 3: subir a la biblioteca sin tema (POST /pdfs)
# --------------------------------------------------------------------------
def _upload_library_pdf(client, h, name="lib.pdf"):
    r = client.post(
        "/api/pdfs",
        files={"file": (name, b"%PDF-1.4 fake", "application/pdf")},
        headers=h,
    )
    return r


class TestLibraryUpload:
    def test_upload_creates_unlinked_pdf(self, client, srv):
        uid = _register(client, "l3a@t.com")
        h = _login(client, "l3a@t.com")
        r = _upload_library_pdf(client, h, "suelto.pdf")
        assert r.status_code == 200, r.text
        body = r.json()
        pid = body["id"]
        assert body["link_count"] == 0 and body["topic_ids"] == [] and body["question_count"] == 0
        # Existe en la biblioteca, sin vínculos y sin topic_id.
        assert _pdf_exists(srv, uid, pid)
        assert _links_count(srv, uid, pid) == 0
        lib = _list_pdfs(client, h)
        assert pid in lib and lib[pid]["link_count"] == 0
        doc = asyncio.run(srv.db.pdfs.find_one({"id": pid}, {"_id": 0, "topic_id": 1}))
        assert doc.get("topic_id") is None

    def test_library_pdf_survives_topic_and_subject_deletion(self, client, srv):
        uid = _register(client, "l3b@t.com")
        h = _login(client, "l3b@t.com")
        # Un PDF de biblioteca sin vincular.
        lib_pid = _upload_library_pdf(client, h, "biblio.pdf").json()["id"]
        # Y contenido normal que sí se borrará.
        s = _subject(client, h, "S")
        t1, p1 = _upload_topic(client, h, s, "T1")

        assert client.delete(f"/api/topics/{t1}", headers=h).status_code == 200
        assert not _pdf_exists(srv, uid, p1)          # el del tema se borra
        assert _pdf_exists(srv, uid, lib_pid)         # el de biblioteca NO se toca

        assert client.delete(f"/api/subjects/{s}", headers=h).status_code == 200
        assert _pdf_exists(srv, uid, lib_pid)         # sigue intacto tras borrar la asignatura

    def test_library_pdf_can_be_linked_then_orphaned(self, client, srv):
        uid = _register(client, "l3c@t.com")
        h = _login(client, "l3c@t.com")
        lib_pid = _upload_library_pdf(client, h).json()["id"]
        s = _subject(client, h, "S")
        t1, _ = _upload_topic(client, h, s, "T1")

        # Vincular el PDF de biblioteca al tema.
        assert client.post(f"/api/topics/{t1}/pdfs/{lib_pid}/link", headers=h).status_code == 200
        assert lib_pid in _topic_pdf_ids(client, h, t1)
        assert _links_count(srv, uid, lib_pid) == 1

        # Desvincular del único tema -> huérfano -> se borra (comportamiento normal).
        r = client.delete(f"/api/topics/{t1}/pdfs/{lib_pid}", headers=h)
        assert r.status_code == 200 and r.json()["pdf_deleted"] is True
        assert not _pdf_exists(srv, uid, lib_pid)

    def test_delete_library_pdf_with_zero_links(self, client, srv):
        uid = _register(client, "l3d@t.com")
        h = _login(client, "l3d@t.com")
        lib_pid = _upload_library_pdf(client, h).json()["id"]
        assert client.delete(f"/api/pdfs/{lib_pid}", headers=h).status_code == 200
        assert not _pdf_exists(srv, uid, lib_pid)

    def test_upload_validations(self, client, srv):
        _register(client, "l3e@t.com")
        h = _login(client, "l3e@t.com")
        # No es PDF.
        r = client.post("/api/pdfs", files={"file": ("x.txt", b"hola", "text/plain")}, headers=h)
        assert r.status_code == 400
        # Requiere autenticación.
        assert client.post("/api/pdfs", files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")}).status_code == 401
