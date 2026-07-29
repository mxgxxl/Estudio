"""
Smoke test de MULTIUSUARIO (aislamiento de datos por usuario) — in-process.

Arranca la app con FastAPI TestClient sobre un Mongo en memoria (ver conftest.py)
y con la generación de IA mockeada, de forma que se ejecuta sin servicios externos.

Verifica:
- Dos usuarios A y B; cada uno crea subject, topic (con preguntas), flashcards,
  intentos de quiz y récords de supervivencia.
- A no ve recursos de B en NINGÚN listado.
- A no puede leer / modificar / borrar recursos de B por id (recibe 404, nunca 403).
- stats / gaps / survival solo devuelven datos del usuario actual.
- /auth/* y /diag/* siguen accesibles según su política original
  (diag sin token; el resto del router exige token).

También cubre el smoke de auth (register/login/me, duplicados, credenciales malas)
para confirmar 0 regresiones.
"""
import pytest
from fastapi.testclient import TestClient


# --- Mocks de IA: evitan llamar a Gemini y permiten crear topics/flashcards reales ---
async def _fake_extract_unused():  # placeholder (no usado)
    return ""


def _fake_extract_pdf_text(_pdf_bytes: bytes) -> str:
    # Texto largo y determinista; supera el umbral de 200 chars del endpoint.
    return ("Temario de prueba. " * 40).strip()


async def _fake_generate_questions(topic_name, source_text, num_questions,
                                   question_type="mcq", num_options=3,
                                   custom_instructions=""):
    out = []
    for i in range(max(3, min(num_questions, 3))):
        out.append({
            "question": f"Pregunta {i} de {topic_name}",
            "options": ["A", "B", "C"],
            "correct_index": 0,
            "explanation": "porque sí",
            "question_type": "mcq",
            "num_options": 3,
            "model_answer": "",
        })
    return out


async def _fake_generate_flashcards(topic_name, source_text, num_cards):
    return [
        {"term": f"Concepto {i}", "definition": f"Definición {i}", "example": ""}
        for i in range(3)
    ]


@pytest.fixture(scope="module")
def client():
    import server
    # Mockea las funciones de IA / extracción (se llaman como globales del módulo).
    server.extract_pdf_text = _fake_extract_pdf_text
    server.generate_questions_with_claude = _fake_generate_questions
    server._generate_flashcards_from_text = _fake_generate_flashcards
    with TestClient(server.app) as c:
        yield c


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _register(client, email, password="secret123"):
    return client.post("/api/auth/register", json={"email": email, "password": password})


def _login(client, email, password="secret123"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create_subject(client, headers, name):
    r = client.post("/api/subjects", json={"name": name}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _upload_topic(client, headers, subject_id, name):
    """Flujo real de la app: crea tema vacío, sube un PDF y genera preguntas
    (tres pasos). Devuelve el tema (dict). Las preguntas hacen falta para los
    tests de aislamiento/acciones sobre preguntas."""
    t = client.post(f"/api/subjects/{subject_id}/topics", json={"name": name}, headers=headers)
    assert t.status_code == 200, t.text
    topic = t.json()
    up = client.post(
        f"/api/topics/{topic['id']}/pdfs/upload",
        files={"file": ("t.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers=headers,
    )
    assert up.status_code == 200, up.text
    g = client.post(
        f"/api/topics/{topic['id']}/generate",
        json={"pdf_ids": [up.json()["id"]], "num_questions": 3},
        headers=headers,
    )
    assert g.status_code == 200, g.text
    return topic


# --------------------------------------------------------------------------
# Fixture: dos usuarios A y B con datos completos
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def world(client):
    assert _register(client, "a@test.com").status_code == 201
    assert _register(client, "b@test.com").status_code == 201
    ha = _login(client, "a@test.com")
    hb = _login(client, "b@test.com")

    sa = _create_subject(client, ha, "Asignatura A")
    sb = _create_subject(client, hb, "Asignatura B")
    ta = _upload_topic(client, ha, sa["id"], "Tema A")
    tb = _upload_topic(client, hb, sb["id"], "Tema B")

    qa = client.get(f"/api/topics/{ta['id']}/questions", headers=ha).json()
    qb = client.get(f"/api/topics/{tb['id']}/questions", headers=hb).json()

    return {
        "ha": ha, "hb": hb,
        "sa": sa, "sb": sb,
        "ta": ta, "tb": tb,
        "qa": qa, "qb": qb,
    }


# --------------------------------------------------------------------------
# Auth smoke (sin regresiones)
# --------------------------------------------------------------------------
class TestAuthSmoke:
    def test_register_duplicate(self, client, world):
        assert _register(client, "a@test.com").status_code == 409

    def test_login_bad_password(self, client):
        r = client.post("/api/auth/login", json={"email": "a@test.com", "password": "wrong"})
        assert r.status_code == 401

    def test_me_requires_token(self, client):
        assert client.get("/api/auth/me").status_code == 401

    def test_me_with_token(self, client, world):
        r = client.get("/api/auth/me", headers=world["ha"])
        assert r.status_code == 200
        assert r.json()["email"] == "a@test.com"


# --------------------------------------------------------------------------
# Política de acceso: diag público, datos protegidos
# --------------------------------------------------------------------------
class TestAccessPolicy:
    def test_diag_llm_public(self, client):
        assert client.get("/api/diag/llm").status_code == 200

    def test_diag_llm_test_public(self, client):
        assert client.post("/api/diag/llm-test").status_code == 200

    def test_subjects_requires_auth(self, client):
        assert client.get("/api/subjects").status_code == 401

    def test_quiz_requires_auth(self, client):
        assert client.post("/api/quiz/start", json={"mode": "practice"}).status_code == 401


# --------------------------------------------------------------------------
# Aislamiento en LISTADOS
# --------------------------------------------------------------------------
class TestListIsolation:
    def test_subjects_listing(self, client, world):
        a = client.get("/api/subjects", headers=world["ha"]).json()
        b = client.get("/api/subjects", headers=world["hb"]).json()
        a_ids = {s["id"] for s in a}
        b_ids = {s["id"] for s in b}
        assert world["sa"]["id"] in a_ids and world["sb"]["id"] not in a_ids
        assert world["sb"]["id"] in b_ids and world["sa"]["id"] not in b_ids

    def test_topics_listing(self, client, world):
        a = client.get("/api/topics", headers=world["ha"]).json()
        a_ids = {t["id"] for t in a}
        assert world["ta"]["id"] in a_ids
        assert world["tb"]["id"] not in a_ids

    def test_subject_topics_listing(self, client, world):
        # A pide los topics de SU asignatura: ve el suyo.
        r = client.get(f"/api/subjects/{world['sa']['id']}/topics", headers=world["ha"])
        assert r.status_code == 200
        assert {t["id"] for t in r.json()} == {world["ta"]["id"]}


# --------------------------------------------------------------------------
# Aislamiento por ID: A no puede tocar recursos de B (404, nunca 403)
# --------------------------------------------------------------------------
class TestCrossUserById:
    def test_subject_get_patch_delete(self, client, world):
        sb, ha = world["sb"]["id"], world["ha"]
        assert client.get(f"/api/subjects/{sb}", headers=ha).status_code == 404
        assert client.patch(f"/api/subjects/{sb}", json={"name": "x"}, headers=ha).status_code == 404
        assert client.delete(f"/api/subjects/{sb}", headers=ha).status_code == 404
        assert client.get(f"/api/subjects/{sb}/topics", headers=ha).status_code == 404

    def test_topic_get_delete_and_children(self, client, world):
        tb, ha = world["tb"]["id"], world["ha"]
        assert client.get(f"/api/topics/{tb}", headers=ha).status_code == 404
        assert client.get(f"/api/topics/{tb}/questions", headers=ha).status_code == 404
        assert client.get(f"/api/topics/{tb}/pdfs", headers=ha).status_code == 404
        assert client.get(f"/api/topics/{tb}/text", headers=ha).status_code == 404
        assert client.delete(f"/api/topics/{tb}", headers=ha).status_code == 404

    def test_question_actions(self, client, world):
        qbid = world["qb"][0]["id"]
        ha = world["ha"]
        assert client.post(f"/api/questions/{qbid}/favorite", headers=ha).status_code == 404
        assert client.post(f"/api/questions/{qbid}/difficult", headers=ha).status_code == 404
        assert client.patch(f"/api/questions/{qbid}", json={"question": "x"}, headers=ha).status_code == 404
        assert client.delete(f"/api/questions/{qbid}", headers=ha).status_code == 404

    def test_eval_dev_cross_user(self, client, world):
        qbid = world["qb"][0]["id"]
        r = client.post("/api/quiz/eval-dev",
                        json={"question_id": qbid, "user_answer": "hola"},
                        headers=world["ha"])
        assert r.status_code == 404

    def test_b_resources_still_accessible_by_b(self, client, world):
        # El dueño legítimo sí accede (no se ha roto nada).
        assert client.get(f"/api/topics/{world['tb']['id']}", headers=world["hb"]).status_code == 200


# --------------------------------------------------------------------------
# Quiz: solo entran preguntas del usuario actual
# --------------------------------------------------------------------------
class TestQuizIsolation:
    def test_quiz_start_only_own(self, client, world):
        r = client.post("/api/quiz/start",
                        json={"mode": "practice", "num_questions": 50},
                        headers=world["ha"])
        assert r.status_code == 200
        started_ids = {q["id"] for q in r.json()["questions"]}
        a_ids = {q["id"] for q in world["qa"]}
        b_ids = {q["id"] for q in world["qb"]}
        assert started_ids <= a_ids
        assert started_ids.isdisjoint(b_ids)

    def test_quiz_submit_records_for_user(self, client, world):
        start = client.post("/api/quiz/start",
                            json={"mode": "practice", "num_questions": 50},
                            headers=world["ha"]).json()
        answers = [{
            "question_id": q["id"],
            "selected": q["correct_index"],
            "correct_index": q["correct_index"],
            "question_type": "mcq",
        } for q in start["questions"]]
        r = client.post("/api/quiz/submit",
                        json={"mode": "practice", "answers": answers, "duration_seconds": 10},
                        headers=world["ha"])
        assert r.status_code == 200
        assert r.json()["total"] == len(answers)


# --------------------------------------------------------------------------
# Stats / gaps aislados
# --------------------------------------------------------------------------
class TestStatsIsolation:
    def test_stats_overview(self, client, world):
        a = client.get("/api/stats", headers=world["ha"]).json()
        b = client.get("/api/stats", headers=world["hb"]).json()
        # A ya envió un intento; B no.
        assert a["total_subjects"] == 1 and a["total_topics"] == 1
        assert b["total_attempts"] == 0
        assert a["total_attempts"] >= 1

    def test_by_subject_only_own(self, client, world):
        a = client.get("/api/stats/by-subject", headers=world["ha"]).json()
        ids = {row["subject_id"] for row in a}
        assert ids == {world["sa"]["id"]}

    def test_by_topic_only_own(self, client, world):
        a = client.get("/api/stats/by-topic", headers=world["ha"]).json()
        ids = {row["topic_id"] for row in a}
        assert ids == {world["ta"]["id"]}

    def test_gaps_only_own(self, client, world):
        a = client.get("/api/stats/gaps", headers=world["ha"]).json()
        topic_ids = {t["topic_id"] for t in a["weak_topics"]}
        assert world["tb"]["id"] not in topic_ids


# --------------------------------------------------------------------------
# Flashcards aisladas
# --------------------------------------------------------------------------
class TestFlashcardIsolation:
    def test_generate_and_isolation(self, client, world):
        ha, hb = world["ha"], world["hb"]
        ra = client.post(f"/api/topics/{world['ta']['id']}/flashcards/generate?num_cards=5", headers=ha)
        assert ra.status_code == 200
        cards_a = client.get(f"/api/topics/{world['ta']['id']}/flashcards", headers=ha).json()
        assert len(cards_a) >= 1

        # B no puede generar ni leer flashcards del topic de A.
        assert client.post(f"/api/topics/{world['ta']['id']}/flashcards/generate", headers=hb).status_code == 404
        assert client.get(f"/api/topics/{world['ta']['id']}/flashcards", headers=hb).status_code == 404

        # B no puede tocar una flashcard de A por id.
        cid = cards_a[0]["id"]
        assert client.post(f"/api/flashcards/{cid}/favorite", headers=hb).status_code == 404
        assert client.post(f"/api/flashcards/{cid}/review?correct=true", headers=hb).status_code == 404
        assert client.delete(f"/api/flashcards/{cid}", headers=hb).status_code == 404


# --------------------------------------------------------------------------
# Survival records aislados (mismo scope_id por dos usuarios)
# --------------------------------------------------------------------------
class TestSurvivalIsolation:
    def test_records_isolated(self, client, world):
        ha, hb = world["ha"], world["hb"]
        payload_a = {"scope_type": "subject", "scope_id": world["sa"]["id"], "scope_name": "A",
                     "score": 10, "questions_answered": 10, "lives_lost": 1, "question_type": "mcq"}
        payload_b = {"scope_type": "subject", "scope_id": world["sb"]["id"], "scope_name": "B",
                     "score": 5, "questions_answered": 5, "lives_lost": 2, "question_type": "mcq"}
        assert client.post("/api/survival/records", json=payload_a, headers=ha).json()["saved"] is True
        assert client.post("/api/survival/records", json=payload_b, headers=hb).json()["saved"] is True

        ra = client.get("/api/survival/records", headers=ha).json()
        rb = client.get("/api/survival/records", headers=hb).json()
        assert {r["scope_id"] for r in ra} == {world["sa"]["id"]}
        assert {r["scope_id"] for r in rb} == {world["sb"]["id"]}

    def test_record_by_scope_isolated(self, client, world):
        # A consulta el récord del scope de B -> vacío (filtrado por usuario).
        r = client.get(f"/api/survival/records/subject/{world['sb']['id']}", headers=world["ha"])
        assert r.status_code == 200
        assert r.json() == {}
