"""
Backend tests for v2 Study App (multi-subject refactor).
Covers: subjects CRUD + migration, topic upload (PDF), PDF list/regenerate/delete,
quiz start/submit (with penalty + tf), stats overview & by-subject, no _id leakage.
"""
import os
import io
import time
import json
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://anatomy-exam-prep-2.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
PDF_PATH = "/tmp/tronco.pdf"
LONG_TIMEOUT = 120  # Claude calls can take 30s+


def _no_underscore_id(obj):
    """Recursively assert no MongoDB _id field exists."""
    if isinstance(obj, dict):
        assert "_id" not in obj, f"_id leaked: {list(obj.keys())}"
        for v in obj.values():
            _no_underscore_id(v)
    elif isinstance(obj, list):
        for v in obj:
            _no_underscore_id(v)


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    return s


@pytest.fixture(scope="module")
def state():
    return {}


# -------------------- Root + migration --------------------
class TestRootAndMigration:
    def test_root(self, session):
        r = session.get(f"{API}/", timeout=15)
        assert r.status_code == 200
        assert r.json().get("status") == "ok"

    def test_migration_default_subject(self, session, state):
        r = session.get(f"{API}/subjects", timeout=30)
        assert r.status_code == 200
        data = r.json()
        _no_underscore_id(data)
        assert isinstance(data, list)
        # Anatomía subject must exist from migration
        anatomia = next((s for s in data if s["name"] == "Anatomía"), None)
        assert anatomia is not None, "Migration: 'Anatomía' subject missing"
        for k in ("id", "name", "color", "topic_count", "question_count", "accuracy"):
            assert k in anatomia
        assert anatomia["topic_count"] >= 2
        assert anatomia["question_count"] >= 1
        state["anatomia_id"] = anatomia["id"]


# -------------------- Subjects CRUD --------------------
class TestSubjectsCRUD:
    def test_create_subject(self, session, state):
        r = session.post(f"{API}/subjects", json={"name": "TEST_Fisiologia", "color": "#5C8A7A"}, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        _no_underscore_id(body)
        assert body["name"] == "TEST_Fisiologia"
        assert body["color"] == "#5C8A7A"
        assert "id" in body
        state["test_subject_id"] = body["id"]

    def test_create_subject_empty_name(self, session):
        r = session.post(f"{API}/subjects", json={"name": "   "}, timeout=20)
        assert r.status_code == 400

    def test_get_subject(self, session, state):
        sid = state["test_subject_id"]
        r = session.get(f"{API}/subjects/{sid}", timeout=20)
        assert r.status_code == 200
        body = r.json()
        _no_underscore_id(body)
        assert body["id"] == sid
        assert body["topic_count"] == 0
        assert body["question_count"] == 0

    def test_patch_subject(self, session, state):
        sid = state["test_subject_id"]
        r = session.patch(f"{API}/subjects/{sid}", json={"name": "TEST_Fisiologia_v2"}, timeout=20)
        assert r.status_code == 200
        # verify by GET
        r2 = session.get(f"{API}/subjects/{sid}", timeout=20)
        assert r2.json()["name"] == "TEST_Fisiologia_v2"

    def test_patch_subject_not_found(self, session):
        r = session.patch(f"{API}/subjects/does-not-exist", json={"name": "x"}, timeout=20)
        assert r.status_code == 404

    def test_list_topics_for_subject_empty(self, session, state):
        sid = state["test_subject_id"]
        r = session.get(f"{API}/subjects/{sid}/topics", timeout=20)
        assert r.status_code == 200
        assert r.json() == []


# -------------------- Topic upload + PDF endpoints --------------------
class TestTopicUploadAndPdf:
    def test_upload_topic_mcq(self, session, state):
        sid = state["test_subject_id"]
        assert os.path.exists(PDF_PATH), f"Missing {PDF_PATH}"
        with open(PDF_PATH, "rb") as f:
            files = {"file": ("tronco.pdf", f, "application/pdf")}
            data = {
                "name": "TEST_Tronco_MCQ",
                "num_questions": "5",
                "question_type": "mcq",
                "num_options": "4",
            }
            r = session.post(
                f"{API}/subjects/{sid}/topics/upload",
                data=data,
                files=files,
                timeout=LONG_TIMEOUT,
            )
        assert r.status_code == 200, r.text
        body = r.json()
        _no_underscore_id(body)
        assert "topic" in body and "pdf_id" in body and "questions_created" in body
        assert body["questions_created"] > 0
        assert body["topic"]["subject_id"] == sid
        state["topic_id"] = body["topic"]["id"]
        state["pdf_id"] = body["pdf_id"]
        # Verify questions have num_options=4 and type mcq
        rq = session.get(f"{API}/topics/{body['topic']['id']}/questions", timeout=30)
        assert rq.status_code == 200
        qs = rq.json()
        _no_underscore_id(qs)
        assert len(qs) > 0
        for q in qs:
            assert q["question_type"] == "mcq"
            assert q["num_options"] == 4
            assert len(q["options"]) == 4
            assert 0 <= q["correct_index"] < 4

    def test_upload_topic_tf(self, session, state):
        sid = state["test_subject_id"]
        with open(PDF_PATH, "rb") as f:
            files = {"file": ("tronco.pdf", f, "application/pdf")}
            data = {
                "name": "TEST_Tronco_TF",
                "num_questions": "3",
                "question_type": "tf",
                "num_options": "2",
            }
            r = session.post(
                f"{API}/subjects/{sid}/topics/upload",
                data=data,
                files=files,
                timeout=LONG_TIMEOUT,
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["questions_created"] > 0
        state["tf_topic_id"] = body["topic"]["id"]
        state["tf_pdf_id"] = body["pdf_id"]
        rq = session.get(f"{API}/topics/{body['topic']['id']}/questions", timeout=30)
        qs = rq.json()
        assert len(qs) > 0
        for q in qs:
            assert q["question_type"] == "tf"
            assert q["options"] == ["Verdadero", "Falso"]
            assert q["correct_index"] in (0, 1)

    def test_list_pdfs_no_text_exposed(self, session, state):
        tid = state["topic_id"]
        r = session.get(f"{API}/topics/{tid}/pdfs", timeout=20)
        assert r.status_code == 200
        pdfs = r.json()
        _no_underscore_id(pdfs)
        assert len(pdfs) == 1
        p = pdfs[0]
        assert "text" not in p, "Full text should not be exposed in list"
        for k in ("id", "filename", "char_count", "question_count"):
            assert k in p
        assert p["question_count"] > 0

    def test_regenerate_from_pdf_tf(self, session, state):
        pdf_id = state["pdf_id"]
        r = session.post(
            f"{API}/pdfs/{pdf_id}/regenerate",
            json={"num_questions": 3, "question_type": "tf"},
            timeout=LONG_TIMEOUT,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["questions_created"] > 0
        # confirm pdf record now has more linked questions
        tid = state["topic_id"]
        r2 = session.get(f"{API}/topics/{tid}/pdfs", timeout=20)
        rec = r2.json()[0]
        assert rec["question_count"] >= 5 + body["questions_created"] - 1  # ~

    def test_delete_pdf_keeps_questions(self, session, state):
        pdf_id = state["tf_pdf_id"]
        tid = state["tf_topic_id"]
        # count questions before
        before = session.get(f"{API}/topics/{tid}/questions", timeout=20).json()
        n_before = len(before)
        r = session.delete(f"{API}/pdfs/{pdf_id}", timeout=20)
        assert r.status_code == 200
        # pdfs list should be empty
        plist = session.get(f"{API}/topics/{tid}/pdfs", timeout=20).json()
        assert plist == []
        # questions remain but pdf_source_id is now null
        after = session.get(f"{API}/topics/{tid}/questions", timeout=20).json()
        assert len(after) == n_before
        for q in after:
            assert q.get("pdf_source_id") in (None, "")


# -------------------- Quiz: start + submit (penalty, tf, shuffle) --------------------
class TestQuiz:
    def test_quiz_start_filtered_by_subject_and_type(self, session, state):
        sid = state["test_subject_id"]
        r = session.post(
            f"{API}/quiz/start",
            json={"mode": "practice", "subject_ids": [sid], "question_type": "mcq", "num_options": 4, "num_questions": 5},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        _no_underscore_id(body)
        assert len(body["questions"]) > 0
        for q in body["questions"]:
            assert q["question_type"] == "mcq"
            assert q["num_options"] == 4
            assert len(q["options"]) == 4
        state["mcq_quiz"] = body["questions"]

    def test_quiz_start_tf(self, session, state):
        sid = state["test_subject_id"]
        r = session.post(
            f"{API}/quiz/start",
            json={"mode": "practice", "subject_ids": [sid], "question_type": "tf", "num_questions": 5},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        qs = body["questions"]
        assert len(qs) > 0
        for q in qs:
            assert q["question_type"] == "tf"
            # Shuffling rule: TF stays V then F
            assert q["options"] == ["Verdadero", "Falso"]

    def test_quiz_start_no_questions(self, session):
        # non-existent subject filter
        r = session.post(
            f"{API}/quiz/start",
            json={"mode": "practice", "subject_ids": ["nonexistent-id"], "num_questions": 5},
            timeout=20,
        )
        assert r.status_code == 404

    def test_quiz_submit_with_penalty(self, session, state):
        qs = state.get("mcq_quiz") or []
        if len(qs) < 2:
            pytest.skip("Need >=2 MCQ questions for penalty test")
        # 1 correct + 1 wrong + 1 unanswered (if present)
        answers = []
        # first one correct
        q0 = qs[0]
        answers.append({"question_id": q0["id"], "selected": q0["correct_index"], "correct_index": q0["correct_index"]})
        # second one wrong
        q1 = qs[1]
        wrong_sel = (q1["correct_index"] + 1) % q1["num_options"]
        answers.append({"question_id": q1["id"], "selected": wrong_sel, "correct_index": q1["correct_index"]})
        # third unanswered if exists
        if len(qs) >= 3:
            q2 = qs[2]
            answers.append({"question_id": q2["id"], "selected": -1, "correct_index": q2["correct_index"]})

        r = session.post(
            f"{API}/quiz/submit",
            json={
                "mode": "practice",
                "subject_ids": [state["test_subject_id"]],
                "answers": answers,
                "duration_seconds": 30,
                "penalty_factor": 3,
            },
            timeout=30,
        )
        assert r.status_code == 200, r.text
        b = r.json()
        _no_underscore_id(b)
        assert b["correct"] == 1
        assert b["wrong"] == 1
        if len(answers) == 3:
            assert b["unanswered"] == 1
            assert b["total"] == 3
            # raw = 1 - 1/3 = 0.667 (unanswered does NOT subtract); score_10 = 0.667/3 * 10 = 2.22
            assert abs(b["raw_score"] - 0.667) < 0.01
            assert abs(b["score_10"] - 2.22) < 0.02
        else:
            assert b["total"] == 2
            # raw = 1 - 1/3 = 0.667; score_10 = 3.33
            assert abs(b["raw_score"] - 0.667) < 0.01
            assert abs(b["score_10"] - 3.33) < 0.02
        assert b["penalty_factor"] == 3

    def test_quiz_submit_no_penalty_clamp(self, session, state):
        # Submit with no penalty_factor; raw = correct
        qs = state.get("mcq_quiz") or []
        if not qs:
            pytest.skip("No quiz cache")
        q = qs[0]
        wrong_sel = (q["correct_index"] + 1) % q["num_options"]
        r = session.post(
            f"{API}/quiz/submit",
            json={
                "mode": "practice",
                "subject_ids": [state["test_subject_id"]],
                "answers": [{"question_id": q["id"], "selected": wrong_sel, "correct_index": q["correct_index"]}],
                "duration_seconds": 5,
                "penalty_factor": None,
            },
            timeout=30,
        )
        assert r.status_code == 200
        b = r.json()
        assert b["correct"] == 0
        assert b["wrong"] == 1
        assert b["raw_score"] == 0.0
        assert b["score_10"] == 0.0


# -------------------- Stats --------------------
class TestStats:
    def test_stats_overview(self, session):
        r = session.get(f"{API}/stats", timeout=30)
        assert r.status_code == 200
        b = r.json()
        _no_underscore_id(b)
        for k in ("total_subjects", "total_topics", "total_questions", "total_attempts",
                  "answered_total", "accuracy", "favorites", "difficult", "errors_pool",
                  "due_srs", "last_attempts"):
            assert k in b, f"Missing key {k}"
        assert b["total_subjects"] >= 2  # Anatomía + TEST_

    def test_stats_by_subject(self, session, state):
        r = session.get(f"{API}/stats/by-subject", timeout=30)
        assert r.status_code == 200
        rows = r.json()
        _no_underscore_id(rows)
        assert isinstance(rows, list)
        assert len(rows) >= 2
        for row in rows:
            for k in ("subject_id", "subject_name", "color", "total_questions",
                      "answered", "correct", "accuracy"):
                assert k in row


# -------------------- Cleanup --------------------
class TestZCleanup:
    def test_delete_test_subject_cascade(self, session, state):
        sid = state.get("test_subject_id")
        if not sid:
            pytest.skip("No subject to delete")
        # before: topics under subject
        topics_before = session.get(f"{API}/subjects/{sid}/topics", timeout=20).json()
        assert len(topics_before) >= 1
        r = session.delete(f"{API}/subjects/{sid}", timeout=30)
        assert r.status_code == 200
        # subject gone
        r2 = session.get(f"{API}/subjects/{sid}", timeout=20)
        assert r2.status_code == 404
        # topic gone
        if topics_before:
            tid = topics_before[0]["id"]
            rq = session.get(f"{API}/topics/{tid}/questions", timeout=20).json()
            assert rq == [], "Cascade should delete questions"

    def test_delete_subject_not_found(self, session):
        r = session.delete(f"{API}/subjects/no-such-id", timeout=20)
        assert r.status_code == 404
