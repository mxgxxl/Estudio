"""
Iteration 3 tests:
- POST /api/topics/{topic_id}/pdfs/upload  (add PDF without generating)
- POST /api/topics/{topic_id}/generate     (batched generation for >10 questions)
- POST /api/quiz/submit with penalty_factor=1 ('1 wrong = -1 right')
- MongoDB indices verified via list_indexes
- Performance sanity on list endpoints (subjects/topics/stats)
- POST /api/pdfs/{pdf_id}/regenerate still works after batching refactor
- subjects/topics upload with question_type='tf' still works (batching path)
"""
import os
import time
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://anatomy-exam-prep-2.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"
PDF_PATH = "/tmp/tronco.pdf"
LONG_TIMEOUT = 240  # batched generation: each batch can take 30-60s
GEN_TIMEOUT = 180


def _no_underscore_id(obj):
    if isinstance(obj, dict):
        assert "_id" not in obj, f"_id leaked: {list(obj.keys())}"
        for v in obj.values():
            _no_underscore_id(v)
    elif isinstance(obj, list):
        for v in obj:
            _no_underscore_id(v)


@pytest.fixture(scope="module")
def session():
    return requests.Session()


@pytest.fixture(scope="module")
def state():
    return {}


# ------------------------- 1. Basics + indices -------------------------
class TestBasicsAndIndices:
    def test_root(self, session):
        r = session.get(f"{API}/", timeout=15)
        assert r.status_code == 200
        assert r.json().get("status") == "ok"

    def test_indices_created_on_startup(self):
        """Connect directly to local Mongo and confirm the indices spec from server.ensure_indices."""
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "anatomia_db")
        db = MongoClient(mongo_url)[db_name]
        expected = {
            "subjects":  ["id_1"],
            "topics":    ["id_1", "subject_id_1"],
            "pdfs":      ["id_1", "topic_id_1"],
            "questions": [
                "id_1", "topic_id_1", "subject_id_1", "pdf_source_id_1",
                "srs_next_review_1",
            ],
            "attempts":  ["id_1", "created_at_-1"],
        }
        for col, idx_names in expected.items():
            present = {i["name"] for i in db[col].list_indexes()}
            missing = [n for n in idx_names if n not in present]
            assert not missing, f"{col} missing indices: {missing}; present: {present}"

    def test_list_endpoints_perf(self, session):
        """/api/subjects, /api/topics, /api/stats should respond <5s."""
        for path in ("/subjects", "/topics", "/stats"):
            t0 = time.time()
            r = session.get(f"{API}{path}", timeout=15)
            elapsed = time.time() - t0
            assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:200]}"
            assert elapsed < 5.0, f"{path} too slow: {elapsed:.2f}s"
            _no_underscore_id(r.json())


# ------------------------- 2. Setup: TEST subject + minimal topic -------------------------
class TestSetup:
    def test_pdf_present(self):
        assert os.path.exists(PDF_PATH), f"missing test PDF at {PDF_PATH}"
        assert os.path.getsize(PDF_PATH) > 1000

    def test_create_test_subject(self, session, state):
        r = session.post(f"{API}/subjects",
                         json={"name": "TEST_Iter3_Batching", "color": "#6C8A9C"},
                         timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        _no_underscore_id(body)
        state["subject_id"] = body["id"]

    def test_create_topic_with_small_mcq(self, session, state):
        """Use subjects upload to create a topic + 5 mcq qs (4-options)."""
        sid = state["subject_id"]
        with open(PDF_PATH, "rb") as f:
            r = session.post(
                f"{API}/subjects/{sid}/topics/upload",
                files={"file": ("tronco.pdf", f, "application/pdf")},
                data={"name": "TEST_Tronco_Batch_MCQ",
                      "num_questions": "5",
                      "question_type": "mcq",
                      "num_options": "4"},
                timeout=LONG_TIMEOUT,
            )
        assert r.status_code == 200, r.text
        body = r.json()
        _no_underscore_id(body)
        assert body["questions_created"] >= 3, body
        state["topic_id"] = body["topic"]["id"]
        state["pdf_id"] = body["pdf_id"]


# ------------------------- 3. New endpoint: add_pdf_to_topic -------------------------
class TestAddPdfToTopic:
    def test_add_pdf_no_generation(self, session, state):
        """POST /api/topics/{id}/pdfs/upload should ONLY register the PDF."""
        tid = state["topic_id"]
        # count questions before
        q_before = session.get(f"{API}/topics/{tid}/questions", timeout=20).json()
        n_before = len(q_before)
        with open(PDF_PATH, "rb") as f:
            r = session.post(
                f"{API}/topics/{tid}/pdfs/upload",
                files={"file": ("tronco2.pdf", f, "application/pdf")},
                timeout=120,
            )
        assert r.status_code == 200, r.text
        body = r.json()
        _no_underscore_id(body)
        for k in ("id", "topic_id", "filename", "char_count"):
            assert k in body, f"missing {k} in response: {body}"
        assert body["topic_id"] == tid
        assert body["filename"] == "tronco2.pdf"
        assert body["char_count"] > 200
        assert body.get("question_count", 0) == 0
        state["second_pdf_id"] = body["id"]
        # Confirm questions NOT changed
        q_after = session.get(f"{API}/topics/{tid}/questions", timeout=20).json()
        assert len(q_after) == n_before, "add_pdf must not create questions"
        # Confirm pdf is listed
        pdfs = session.get(f"{API}/topics/{tid}/pdfs", timeout=20).json()
        assert any(p["id"] == body["id"] for p in pdfs)

    def test_add_pdf_topic_not_found(self, session):
        with open(PDF_PATH, "rb") as f:
            r = session.post(
                f"{API}/topics/does-not-exist/pdfs/upload",
                files={"file": ("x.pdf", f, "application/pdf")},
                timeout=60,
            )
        assert r.status_code == 404

    def test_add_pdf_rejects_non_pdf(self, session, state):
        tid = state["topic_id"]
        r = session.post(
            f"{API}/topics/{tid}/pdfs/upload",
            files={"file": ("x.txt", b"hello", "text/plain")},
            timeout=20,
        )
        assert r.status_code == 400


# ------------------------- 4. New endpoint: generate_from_topic_pdfs (batching) -------------------------
class TestGenerateFromTopicPdfs:
    def test_generate_validation_no_pdf_ids(self, session, state):
        tid = state["topic_id"]
        r = session.post(f"{API}/topics/{tid}/generate",
                         json={"pdf_ids": [], "num_questions": 5},
                         timeout=20)
        assert r.status_code == 400

    def test_generate_validation_bad_num(self, session, state):
        tid = state["topic_id"]
        r = session.post(f"{API}/topics/{tid}/generate",
                         json={"pdf_ids": [state["pdf_id"]], "num_questions": 1},
                         timeout=20)
        assert r.status_code == 400

    def test_generate_validation_topic_not_found(self, session, state):
        r = session.post(f"{API}/topics/does-not-exist/generate",
                         json={"pdf_ids": [state["pdf_id"]], "num_questions": 5},
                         timeout=20)
        assert r.status_code == 404

    def test_generate_batched_12_mcq(self, session, state):
        """num_questions=12 → 2 batches of 10 + 2 (BATCH_SIZE=10).
        Expect partial-success tolerant: at least 10 questions created."""
        tid = state["topic_id"]
        pdf_ids = [state["pdf_id"], state["second_pdf_id"]]
        q_before = session.get(f"{API}/topics/{tid}/questions", timeout=20).json()
        n_before = len(q_before)
        t0 = time.time()
        r = session.post(
            f"{API}/topics/{tid}/generate",
            json={"pdf_ids": pdf_ids,
                  "num_questions": 12,
                  "question_type": "mcq",
                  "num_options": 4},
            timeout=GEN_TIMEOUT,
        )
        elapsed = time.time() - t0
        print(f"\ngenerate 12 mcq took {elapsed:.1f}s; status={r.status_code}")
        assert r.status_code == 200, r.text
        body = r.json()
        _no_underscore_id(body)
        created = body["questions_created"]
        # Batching tolerates partial failures: ≥10 is acceptable
        assert created >= 10, f"Expected ≥10 questions, got {created}"
        assert created <= 12, f"Should not exceed requested 12, got {created}"
        assert set(body["pdf_ids_used"]) == set(pdf_ids)
        # Confirm persisted
        q_after = session.get(f"{API}/topics/{tid}/questions", timeout=20).json()
        assert len(q_after) == n_before + created
        # New ones should have mcq with 4 options
        new_qs = q_after[-created:]
        for q in new_qs:
            assert q["question_type"] == "mcq"
            assert q["num_options"] == 4
            assert len(q["options"]) == 4
            assert 0 <= q["correct_index"] < 4
            assert q["pdf_source_id"] in pdf_ids  # primary pdf
        state["generated_qs"] = new_qs


# ------------------------- 5. Penalty math: '1 wrong = -1 right' (penalty_factor=1) -------------------------
class TestPenaltyFactor1:
    def _start_quiz(self, session, sid, n):
        r = session.post(f"{API}/quiz/start",
                         json={"mode": "practice",
                               "subject_ids": [sid],
                               "question_type": "mcq",
                               "num_options": 4,
                               "num_questions": n},
                         timeout=30)
        assert r.status_code == 200, r.text
        return r.json()["questions"]

    def test_penalty1_three_correct_one_wrong(self, session, state):
        """3 correct + 1 wrong → raw = 3 - 1/1 = 2 → score_10 = (2/4)*10 = 5.0"""
        sid = state["subject_id"]
        qs = self._start_quiz(session, sid, 4)
        if len(qs) < 4:
            pytest.skip(f"only {len(qs)} mcq questions available")
        answers = []
        for i in range(3):
            answers.append({"question_id": qs[i]["id"],
                            "selected": qs[i]["correct_index"],
                            "correct_index": qs[i]["correct_index"]})
        wrong_sel = (qs[3]["correct_index"] + 1) % qs[3]["num_options"]
        answers.append({"question_id": qs[3]["id"],
                        "selected": wrong_sel,
                        "correct_index": qs[3]["correct_index"]})
        r = session.post(f"{API}/quiz/submit",
                         json={"mode": "practice",
                               "subject_ids": [sid],
                               "answers": answers,
                               "duration_seconds": 30,
                               "penalty_factor": 1},
                         timeout=30)
        assert r.status_code == 200, r.text
        b = r.json()
        _no_underscore_id(b)
        assert b["correct"] == 3
        assert b["wrong"] == 1
        assert b["unanswered"] == 0
        assert b["total"] == 4
        assert b["penalty_factor"] == 1
        # raw = 3 - 1 = 2; score_10 = 5.0
        assert abs(b["raw_score"] - 2.0) < 0.01, b
        assert abs(b["score_10"] - 5.0) < 0.01, b

    def test_penalty1_one_correct_two_wrong_clamps_to_zero(self, session, state):
        """1 correct + 2 wrong + 0 unanswered, penalty=1 → raw = 1 - 2 = -1 → clamp 0; score_10=0"""
        sid = state["subject_id"]
        qs = self._start_quiz(session, sid, 3)
        if len(qs) < 3:
            pytest.skip("not enough mcq questions")
        a0 = {"question_id": qs[0]["id"],
              "selected": qs[0]["correct_index"],
              "correct_index": qs[0]["correct_index"]}
        a1_wrong = (qs[1]["correct_index"] + 1) % qs[1]["num_options"]
        a1 = {"question_id": qs[1]["id"], "selected": a1_wrong, "correct_index": qs[1]["correct_index"]}
        a2_wrong = (qs[2]["correct_index"] + 1) % qs[2]["num_options"]
        a2 = {"question_id": qs[2]["id"], "selected": a2_wrong, "correct_index": qs[2]["correct_index"]}
        r = session.post(f"{API}/quiz/submit",
                         json={"mode": "practice",
                               "subject_ids": [sid],
                               "answers": [a0, a1, a2],
                               "duration_seconds": 20,
                               "penalty_factor": 1},
                         timeout=30)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["correct"] == 1
        assert b["wrong"] == 2
        assert b["unanswered"] == 0
        assert b["total"] == 3
        assert b["penalty_factor"] == 1
        assert b["raw_score"] == 0.0
        assert b["score_10"] == 0.0
        # Sanity: response contains the expected keys
        for k in ("attempt_id", "correct", "wrong", "unanswered",
                  "raw_score", "score_10", "penalty_factor"):
            assert k in b


# ------------------------- 6. Regenerate single PDF (uses batching internally) -------------------------
class TestRegenerateAfterRefactor:
    def test_regenerate_pdf_mcq(self, session, state):
        pdf_id = state["pdf_id"]
        r = session.post(f"{API}/pdfs/{pdf_id}/regenerate",
                         json={"num_questions": 4, "question_type": "mcq", "num_options": 3},
                         timeout=GEN_TIMEOUT)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["questions_created"] >= 3

    def test_regenerate_pdf_tf_batching_path(self, session, state):
        """TF goes through same batching code path."""
        pdf_id = state["pdf_id"]
        r = session.post(f"{API}/pdfs/{pdf_id}/regenerate",
                         json={"num_questions": 4, "question_type": "tf"},
                         timeout=GEN_TIMEOUT)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["questions_created"] >= 3
        # verify TF questions stored correctly
        tid = state["topic_id"]
        qs = session.get(f"{API}/topics/{tid}/questions", timeout=20).json()
        tf_qs = [q for q in qs if q["question_type"] == "tf"]
        assert len(tf_qs) >= 3
        for q in tf_qs[-3:]:
            assert q["options"] == ["Verdadero", "Falso"]
            assert q["correct_index"] in (0, 1)


# ------------------------- 7. Cleanup -------------------------
class TestZCleanup:
    def test_cleanup(self, session, state):
        sid = state.get("subject_id")
        if not sid:
            pytest.skip("no subject")
        r = session.delete(f"{API}/subjects/{sid}", timeout=30)
        assert r.status_code == 200
        # verify gone
        r2 = session.get(f"{API}/subjects/{sid}", timeout=20)
        assert r2.status_code == 404
