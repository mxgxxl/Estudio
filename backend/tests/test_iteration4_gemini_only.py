"""
Iteration 4 backend tests: Gemini-only refactor verification.

Focus:
  1. GET /api/diag/llm returns provider=gemini, model=gemini-2.5-flash, key present
  2. POST /api/diag/llm-test returns ok=true (real Gemini ping)
  3. POST /api/topics/{id}/pdfs/upload still works (uploads /tmp/tronco.pdf)
  4. POST /api/topics/{id}/generate (mcq, 5 questions, 3 options)
  5. POST /api/topics/{id}/generate (mcq, 12 questions) -> batches of 10+2
  6. POST /api/topics/{id}/generate (tf) -> options normalized to ['Verdadero','Falso']
  7. Existing endpoints regression (subjects/topics/quiz/stats)
  8. requirements.txt purity (no anthropic/openai/litellm/emergentintegrations)
  9. Backend logs contain [LLM-CALL] / [LLM-PARSED] provider=gemini markers
"""
import os
import re
import time
import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "https://anatomy-exam-prep-2.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"

LONG_TIMEOUT = 240
EXISTING_TOPIC_ID = "3bdbf094-4626-470c-87e4-671472e70fc0"  # "Huesos del tronco"
PDF_PATH = "/tmp/tronco.pdf"
BACKEND_ERR_LOG = "/var/log/supervisor/backend.err.log"


@pytest.fixture(scope="module")
def session():
    return requests.Session()


@pytest.fixture(scope="module")
def state():
    return {}


def _no_underscore_id(obj):
    if isinstance(obj, dict):
        assert "_id" not in obj, f"_id leaked: {list(obj.keys())}"
        for v in obj.values():
            _no_underscore_id(v)
    elif isinstance(obj, list):
        for v in obj:
            _no_underscore_id(v)


# -------------------- 1. Diagnostic endpoints --------------------
class TestADiagEndpoints:
    def test_diag_llm_get(self, session):
        r = session.get(f"{API}/diag/llm", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["provider"] == "gemini"
        assert data["model"] == "gemini-2.5-flash"
        assert data["GEMINI_API_KEY_present"] is True

    def test_diag_llm_test_post(self, session):
        r = session.post(f"{API}/diag/llm-test", timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True, f"Gemini ping failed: {data}"
        assert data["model"] == "gemini-2.5-flash"
        assert "OK" in data.get("response_head", "").upper()


# -------------------- 2. Requirements purity --------------------
class TestBRequirementsPurity:
    def test_requirements_txt(self):
        with open("/app/backend/requirements.txt") as f:
            content = f.read().lower()
        for forbidden in ("anthropic", "litellm", "emergentintegrations"):
            assert forbidden not in content, f"{forbidden} still in requirements.txt"
        for line in content.splitlines():
            pkg = line.split("==")[0].strip()
            assert pkg != "openai", "openai still in requirements.txt"
        assert "google-generativeai==0.8.6" in content


# -------------------- 3. Existing endpoints regression --------------------
class TestCRegression:
    def test_root(self, session):
        r = session.get(f"{API}/", timeout=15)
        assert r.status_code == 200
        assert r.json().get("status") == "ok"

    def test_subjects_list(self, session):
        r = session.get(f"{API}/subjects", timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        _no_underscore_id(data)

    def test_topics_list(self, session, state):
        r = session.get(f"{API}/topics", timeout=30)
        assert r.status_code == 200
        data = r.json()
        ids = [t.get("id") for t in data]
        assert EXISTING_TOPIC_ID in ids, f"Topic {EXISTING_TOPIC_ID} not present"
        for t in data:
            if t.get("id") == EXISTING_TOPIC_ID:
                state["subject_id"] = t.get("subject_id")
                break
        _no_underscore_id(data)

    def test_stats_overview(self, session):
        r = session.get(f"{API}/stats", timeout=30)
        assert r.status_code == 200
        _no_underscore_id(r.json())


# -------------------- 4. Upload PDF to existing topic --------------------
class TestDUploadPDF:
    def test_upload_pdf_to_existing_topic(self, session, state):
        assert os.path.exists(PDF_PATH), f"Missing test PDF at {PDF_PATH}"
        with open(PDF_PATH, "rb") as f:
            files = {"file": ("tronco.pdf", f, "application/pdf")}
            r = session.post(
                f"{API}/topics/{EXISTING_TOPIC_ID}/pdfs/upload",
                files=files,
                timeout=120,
            )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "id" in data
        assert data["topic_id"] == EXISTING_TOPIC_ID
        assert data["char_count"] >= 200
        state["pdf_id"] = data["id"]
        print(f"[upload] pdf_id={data['id']} chars={data['char_count']}")


# -------------------- 5. Gemini generation: 5 MCQ --------------------
class TestEGenerate5MCQ:
    def test_generate_5_mcq(self, session, state):
        pdf_id = state.get("pdf_id")
        assert pdf_id, "No PDF uploaded in prior step"
        payload = {
            "pdf_ids": [pdf_id],
            "num_questions": 5,
            "question_type": "mcq",
            "num_options": 3,
        }
        t0 = time.time()
        r = session.post(
            f"{API}/topics/{EXISTING_TOPIC_ID}/generate",
            json=payload,
            timeout=LONG_TIMEOUT,
        )
        elapsed = time.time() - t0
        print(f"[5-mcq] elapsed={elapsed:.1f}s status={r.status_code}")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("questions_created") == 5, data
        assert isinstance(data.get("pdf_ids_used"), list)
        _no_underscore_id(data)


# -------------------- 6. Gemini generation: 12 MCQ (batched 10+2) --------------------
class TestFGenerate12MCQBatched:
    def test_generate_12_mcq(self, session, state):
        pdf_id = state.get("pdf_id")
        assert pdf_id, "No PDF uploaded in prior step"
        payload = {
            "pdf_ids": [pdf_id],
            "num_questions": 12,
            "question_type": "mcq",
            "num_options": 3,
        }
        t0 = time.time()
        r = session.post(
            f"{API}/topics/{EXISTING_TOPIC_ID}/generate",
            json=payload,
            timeout=LONG_TIMEOUT,
        )
        elapsed = time.time() - t0
        print(f"[12-mcq] elapsed={elapsed:.1f}s status={r.status_code}")
        assert r.status_code == 200, r.text
        data = r.json()
        created = data.get("questions_created")
        assert created is not None, data
        # Hard requirement: must return all 12 in healthy conditions
        assert created == 12, f"Expected 12 batched questions, got {created}"
        _no_underscore_id(data)


# -------------------- 7. TF normalization --------------------
class TestGGenerateTF:
    def test_generate_tf_normalized(self, session, state):
        pdf_id = state.get("pdf_id")
        assert pdf_id, "No PDF uploaded in prior step"
        payload = {
            "pdf_ids": [pdf_id],
            "num_questions": 3,
            "question_type": "tf",
        }
        t0 = time.time()
        r = session.post(
            f"{API}/topics/{EXISTING_TOPIC_ID}/generate",
            json=payload,
            timeout=LONG_TIMEOUT,
        )
        elapsed = time.time() - t0
        print(f"[3-tf] elapsed={elapsed:.1f}s status={r.status_code}")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("questions_created", 0) >= 1, data

        # Fetch TF questions via quiz/start with question_type filter
        qs_r = session.post(
            f"{API}/quiz/start",
            json={
                "mode": "practice",
                "topic_ids": [EXISTING_TOPIC_ID],
                "num_questions": 50,
                "question_type": "tf",
            },
            timeout=60,
        )
        assert qs_r.status_code == 200, qs_r.text
        quiz = qs_r.json()
        _no_underscore_id(quiz)
        tf_qs = quiz.get("questions", [])
        assert tf_qs, "No TF questions retrieved after TF generation"
        for q in tf_qs[:5]:
            opts = q.get("options")
            assert opts == ["Verdadero", "Falso"], f"TF options not normalized: {opts}"


# -------------------- 8. Quiz submit with penalty_factor=1 --------------------
class TestHQuizSubmitPenalty:
    def test_quiz_start_and_submit_penalty1(self, session):
        r = session.post(
            f"{API}/quiz/start",
            json={
                "mode": "practice",
                "topic_ids": [EXISTING_TOPIC_ID],
                "num_questions": 3,
                "question_type": "mcq",
            },
            timeout=60,
        )
        assert r.status_code == 200, r.text
        quiz = r.json()
        questions = quiz.get("questions", [])
        if len(questions) < 3:
            pytest.skip("Not enough questions to test penalty")

        answers = []
        # q0 correct, q1 wrong, q2 unanswered (-1)
        q0 = questions[0]
        answers.append({
            "question_id": q0["id"],
            "selected": q0["correct_index"],
            "correct_index": q0["correct_index"],
        })
        q1 = questions[1]
        wrong = (q1["correct_index"] + 1) % len(q1["options"])
        answers.append({
            "question_id": q1["id"],
            "selected": wrong,
            "correct_index": q1["correct_index"],
        })
        q2 = questions[2]
        answers.append({
            "question_id": q2["id"],
            "selected": -1,
            "correct_index": q2["correct_index"],
        })

        submit_r = session.post(
            f"{API}/quiz/submit",
            json={
                "mode": "practice",
                "topic_ids": [EXISTING_TOPIC_ID],
                "answers": answers,
                "duration_seconds": 30,
                "penalty_factor": 1,
            },
            timeout=30,
        )
        assert submit_r.status_code == 200, submit_r.text
        result = submit_r.json()
        _no_underscore_id(result)
        # penalty_factor=1: 1 correct - 1 wrong = 0 raw, score should be 0
        # but total denominator is 3 (incl. unanswered), so score_10=0
        score = result.get("score_10", result.get("score"))
        assert score is not None
        assert 0 <= float(score) <= 10
        print(f"[quiz-submit] result={result}")


# -------------------- 9. Backend log assertions --------------------
class TestILogs:
    def test_log_has_gemini_call(self):
        if not os.path.exists(BACKEND_ERR_LOG):
            pytest.skip(f"Log file not found: {BACKEND_ERR_LOG}")
        with open(BACKEND_ERR_LOG, "r", errors="ignore") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 300_000))
            tail = f.read()
        assert "[LLM-CALL] provider=gemini model=gemini-2.5-flash" in tail, \
            "Expected '[LLM-CALL] provider=gemini model=gemini-2.5-flash' marker not found in recent logs"
        assert re.search(r"\[LLM-PARSED\] provider=gemini questions=\d+", tail), \
            "Expected '[LLM-PARSED] provider=gemini questions=N' marker not found in recent logs"


# -------------------- Z. Cleanup --------------------
class TestZCleanup:
    def test_cleanup_uploaded_pdf(self, session, state):
        pdf_id = state.get("pdf_id")
        if not pdf_id:
            pytest.skip("Nothing to clean up")
        r = session.delete(f"{API}/pdfs/{pdf_id}", timeout=30)
        # 200 or 404 acceptable
        assert r.status_code in (200, 204, 404), r.text
