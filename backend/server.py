"""
Anatomía - Backend
FastAPI + MongoDB + Claude Sonnet 4.5 (via emergentintegrations)
"""
import os
import io
import re
import json
import uuid
import logging
import random
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Literal

from fastapi import FastAPI, APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from pypdf import PdfReader

from emergentintegrations.llm.chat import LlmChat, UserMessage

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# Mongo
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

app = FastAPI(title="Study App API")
api = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("studyapp")

# Diagnostic at boot: which keys are present (no values logged)
logger.info(
    "[LLM-DIAG] keys present: EMERGENT_LLM_KEY=%s ANTHROPIC_API_KEY=%s OPENAI_API_KEY=%s GEMINI_API_KEY=%s",
    bool(EMERGENT_LLM_KEY),
    bool(ANTHROPIC_API_KEY),
    bool(OPENAI_API_KEY),
    bool(GEMINI_API_KEY),
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
SUBJECT_COLORS = ["#C65D47", "#7A8B76", "#6C8A9C", "#D4A373", "#9C7A8B", "#5C8A7A", "#B84A4A", "#8A857D"]


class Subject(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    color: str = "#C65D47"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Topic(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    subject_id: str
    name: str
    description: Optional[str] = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PdfSource(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    topic_id: str
    filename: str
    text: str  # extracted text, reused for regeneration
    char_count: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Question(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    topic_id: str
    topic_name: str
    subject_id: Optional[str] = None
    pdf_source_id: Optional[str] = None
    question_type: Literal["mcq", "tf"] = "mcq"
    num_options: int = 3
    question: str
    options: List[str]
    correct_index: int
    explanation: Optional[str] = ""
    favorite: bool = False
    difficult: bool = False
    times_answered: int = 0
    times_correct: int = 0
    # SRS (SM-2 simplified)
    srs_interval_days: float = 0
    srs_ease: float = 2.5
    srs_next_review: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_answered_at: Optional[str] = None
    last_correct: Optional[bool] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Attempt(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mode: Literal["exam", "practice", "errors", "srs", "favorites"]
    subject_ids: List[str] = []
    topic_ids: List[str] = []
    question_ids: List[str]
    answers: List[int]  # selected option index per question, -1 if unanswered
    correct_count: int
    wrong_count: int = 0
    unanswered_count: int = 0
    total: int
    penalty_factor: Optional[int] = None  # e.g., 3 => 3 wrong = -1 correct. None = no penalty.
    raw_score: float = 0.0  # correct - wrong/penalty_factor (if penalty applied), else == correct
    score_10: float = 0.0
    question_type: Optional[str] = None  # filter used at start
    duration_seconds: int = 0
    time_limit_seconds: Optional[int] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _clean_pdf_text(text: str) -> str:
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception as e:  # noqa: BLE001
            logger.warning("PDF page extract error: %s", e)
    return _clean_pdf_text("\n\n".join(parts))


def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _build_prompts(topic_name: str, source_text: str, num_questions: int, question_type: str, num_options: int):
    """Builds the (system, user) prompt pair for a generation call."""
    system_msg = (
        "Eres un profesor experto. Tu tarea es generar preguntas de examen "
        "de alta calidad EXCLUSIVAMENTE a partir del temario que se te proporciona. "
        "Las preguntas deben ser claras, específicas y útiles para preparar un examen "
        "universitario o de oposición. Responde SIEMPRE en español. "
        "Devuelve SOLO JSON válido, sin texto extra."
    )
    if question_type == "tf":
        user_prompt = f"""A partir del siguiente temario del tema "{topic_name}", \
genera exactamente {num_questions} preguntas tipo VERDADERO/FALSO.

REGLAS ESTRICTAS:
- Cada pregunta es una AFIRMACIÓN que el alumno debe juzgar como verdadera o falsa.
- Varía entre afirmaciones verdaderas y falsas (aprox 50/50).
- Las afirmaciones deben estar basadas únicamente en el contenido proporcionado.
- Las falsas deben ser plausibles (cambiar un dato específico, no algo absurdo).
- Incluye una explicación breve (1-2 frases) que justifique la respuesta.
- Evita preguntas triviales o duplicadas.
- Devuelve SOLO un array JSON, sin markdown, sin comentarios.

FORMATO EXACTO:
[
  {{
    "question": "afirmación a juzgar",
    "correct": true,
    "explanation": "breve justificación"
  }}
]

TEMARIO:
\"\"\"
{source_text}
\"\"\"
"""
    else:
        n = max(2, min(5, int(num_options)))
        user_prompt = f"""A partir del siguiente temario del tema "{topic_name}", \
genera exactamente {num_questions} preguntas tipo test.

REGLAS ESTRICTAS:
- Cada pregunta debe tener EXACTAMENTE {n} opciones de respuesta.
- Solo UNA opción es correcta. Las demás deben ser plausibles pero claramente incorrectas según el temario.
- Las preguntas y respuestas deben estar basadas únicamente en el contenido proporcionado.
- Varía la dificultad y los conceptos cubiertos.
- Incluye una explicación breve (1-2 frases) que justifique la respuesta correcta.
- Evita preguntas triviales o duplicadas.
- Devuelve SOLO un array JSON, sin markdown, sin comentarios.

FORMATO EXACTO:
[
  {{
    "question": "texto de la pregunta",
    "options": [{', '.join([f'"opción {chr(65 + i)}"' for i in range(n)])}],
    "correct_index": 0,
    "explanation": "breve justificación"
  }}
]

TEMARIO:
\"\"\"
{source_text}
\"\"\"
"""
    return system_msg, user_prompt


def _parse_llm_response(raw: str, question_type: str, num_options: int) -> List[dict]:
    """Parse and normalise LLM response into validated question dicts."""
    raw = _strip_code_fences(raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\[\s*{.*}\s*\]", raw, re.DOTALL)
        if not match:
            logger.error("No JSON found. Resp head: %s", raw[:400])
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as je:
            logger.error("JSON parse failed: %s. Head: %s", je, raw[:400])
            return []
    if not isinstance(data, list):
        return []

    cleaned: List[dict] = []
    if question_type == "tf":
        for q in data:
            if not isinstance(q, dict):
                continue
            correct = q.get("correct")
            if isinstance(correct, str):
                correct = correct.strip().lower() in ("true", "verdadero", "v", "sí", "si", "1")
            if not isinstance(correct, bool):
                continue
            text = str(q.get("question", "")).strip()
            if not text:
                continue
            cleaned.append({
                "question": text,
                "options": ["Verdadero", "Falso"],
                "correct_index": 0 if correct else 1,
                "explanation": str(q.get("explanation", "")).strip(),
                "question_type": "tf",
                "num_options": 2,
            })
    else:
        n = max(2, min(5, int(num_options)))
        for q in data:
            if not isinstance(q, dict):
                continue
            opts = q.get("options") or []
            if not isinstance(opts, list) or len(opts) != n:
                continue
            try:
                idx = int(q.get("correct_index", 0))
            except (TypeError, ValueError):
                idx = 0
            if idx < 0 or idx >= n:
                idx = 0
            text = str(q.get("question", "")).strip()
            if not text:
                continue
            cleaned.append({
                "question": text,
                "options": [str(o).strip() for o in opts],
                "correct_index": idx,
                "explanation": str(q.get("explanation", "")).strip(),
                "question_type": "mcq",
                "num_options": n,
            })
    return cleaned


async def _call_llm_once(system_msg: str, user_prompt: str, provider: str, model: str) -> str:
    # Use the user's personal key for the matching provider if available
    if provider == "gemini" and GEMINI_API_KEY:
        api_key = GEMINI_API_KEY
        key_source = "GEMINI_API_KEY"
    elif provider == "anthropic" and ANTHROPIC_API_KEY:
        api_key = ANTHROPIC_API_KEY
        key_source = "ANTHROPIC_API_KEY"
    elif provider == "openai" and OPENAI_API_KEY:
        api_key = OPENAI_API_KEY
        key_source = "OPENAI_API_KEY"
    else:
        api_key = EMERGENT_LLM_KEY
        key_source = "EMERGENT_LLM_KEY"
    logger.info(
        "[LLM-CALL] provider=%s model=%s key=%s prompt_chars=%s",
        provider, model, key_source, len(user_prompt),
    )
    chat = LlmChat(
        api_key=api_key,
        session_id=f"qgen-{uuid.uuid4()}",
        system_message=system_msg,
    ).with_model(provider, model)
    try:
        response = await chat.send_message(UserMessage(text=user_prompt))
    except Exception as e:
        logger.error(
            "[LLM-CALL-FAIL] provider=%s model=%s key=%s exc_type=%s detail=%s",
            provider, model, key_source, type(e).__name__, str(e)[:500],
        )
        raise
    logger.info(
        "[LLM-CALL-OK] provider=%s model=%s key=%s response_chars=%s",
        provider, model, key_source, len(response or ""),
    )
    return response


async def _generate_batch(
    topic_name: str,
    source_text: str,
    num_questions: int,
    question_type: str,
    num_options: int,
) -> List[dict]:
    """Generate a single batch (with retries + fallback chain)."""
    import asyncio as _asyncio
    system_msg, user_prompt = _build_prompts(
        topic_name, source_text, num_questions, question_type, num_options
    )

    # Build the provider chain.
    # If the user has a personal Gemini key, prefer it (uses THEIR quota, not the
    # universal budget). Otherwise, use the universal chain.
    if GEMINI_API_KEY:
        plans = [
            ("gemini", "gemini-2.5-flash", 5),  # primary: user's own quota
            ("anthropic", "claude-sonnet-4-5-20250929", 2),  # fallback: universal budget
            ("openai", "gpt-5.1", 2),
        ]
    else:
        plans = [
            ("anthropic", "claude-sonnet-4-5-20250929", 5),
            ("openai", "gpt-5.1", 2),
            ("gemini", "gemini-2.5-flash", 2),
        ]

    last_err: Optional[Exception] = None
    for provider, model, attempts in plans:
        logger.info("[LLM-PLAN] trying provider=%s model=%s max_attempts=%s", provider, model, attempts)
        for attempt in range(attempts):
            try:
                resp = await _call_llm_once(system_msg, user_prompt, provider, model)
                parsed = _parse_llm_response(resp, question_type, num_options)
                if parsed:
                    logger.info(
                        "[LLM-PARSED] provider=%s model=%s questions=%s",
                        provider, model, len(parsed),
                    )
                    return parsed
                logger.warning(
                    "[LLM-PARSE-EMPTY] provider=%s model=%s attempt=%s/%s — parsed 0 questions",
                    provider, model, attempt + 1, attempts,
                )
            except Exception as e:  # noqa: BLE001
                last_err = e
                msg = str(e).lower()
                is_transient = any(
                    k in msg for k in (
                        "502", "503", "504", "bad gateway", "timeout",
                        "overloaded", "rate limit", "429", "connection",
                    )
                )
                logger.warning(
                    "[LLM-RETRY] provider=%s model=%s attempt=%s/%s transient=%s detail=%s",
                    provider, model, attempt + 1, attempts, is_transient, str(e)[:300],
                )
                if not is_transient and attempt == 0:
                    # for non-transient errors on first attempt, escalate to next provider
                    logger.info("[LLM-ESCALATE] non-transient error, escalating to next provider")
                    break
            await _asyncio.sleep(min(8, 1.5 * (2 ** attempt)))
    if last_err:
        logger.error("[LLM-BATCH-FAIL] all providers exhausted. Last error: %s", str(last_err)[:500])
    return []


async def generate_questions_with_claude(
    topic_name: str,
    source_text: str,
    num_questions: int,
    question_type: str = "mcq",
    num_options: int = 3,
) -> List[dict]:
    """Robustly generate `num_questions` items in small batches with retries+fallback."""
    if not EMERGENT_LLM_KEY and not GEMINI_API_KEY and not ANTHROPIC_API_KEY and not OPENAI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="No hay API key de IA configurada (EMERGENT_LLM_KEY o GEMINI_API_KEY)",
        )

    # Truncate very long PDFs (safe context)
    max_chars = 120_000
    if len(source_text) > max_chars:
        source_text = source_text[:max_chars]

    # Split big requests into batches of <=10 to reduce risk of partial failures
    BATCH_SIZE = 10
    if num_questions <= BATCH_SIZE:
        batches = [num_questions]
    else:
        batches = []
        remaining = num_questions
        while remaining > 0:
            n = min(BATCH_SIZE, remaining)
            batches.append(n)
            remaining -= n

    all_questions: List[dict] = []
    batch_errors = 0
    for i, batch_n in enumerate(batches):
        logger.info("Generating batch %s/%s (%s questions)…", i + 1, len(batches), batch_n)
        items = await _generate_batch(topic_name, source_text, batch_n, question_type, num_options)
        if items:
            all_questions.extend(items)
        else:
            batch_errors += 1
            logger.warning("Batch %s yielded no questions", i + 1)

    if not all_questions:
        raise HTTPException(
            status_code=502,
            detail=(
                "El servicio de IA no pudo generar preguntas. "
                "El proveedor puede estar saturado. Vuelve a intentarlo en unos segundos."
            ),
        )
    if batch_errors and batch_errors == len(batches):
        # Should be unreachable given the all_questions check above, kept for safety
        raise HTTPException(status_code=502, detail="Fallo total al generar preguntas")
    return all_questions


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@api.get("/")
async def root():
    return {"app": "Study App", "status": "ok"}


@api.get("/diag/llm")
async def diag_llm():
    """Diagnostic endpoint: which API keys are present (no values)."""
    return {
        "EMERGENT_LLM_KEY_present": bool(EMERGENT_LLM_KEY),
        "ANTHROPIC_API_KEY_present": bool(ANTHROPIC_API_KEY),
        "OPENAI_API_KEY_present": bool(OPENAI_API_KEY),
        "GEMINI_API_KEY_present": bool(GEMINI_API_KEY),
        "default_provider_chain": [
            "anthropic/claude-sonnet-4-5-20250929",
            "openai/gpt-5.1",
            "gemini/gemini-2.5-flash",
        ],
    }


@api.post("/diag/llm-test")
async def diag_llm_test():
    """Quick LLM ping: try Anthropic, OpenAI, Gemini and return which succeeded."""
    results = {}
    plans = [
        ("anthropic", "claude-sonnet-4-5-20250929", ANTHROPIC_API_KEY or EMERGENT_LLM_KEY, "ANTHROPIC_API_KEY" if ANTHROPIC_API_KEY else "EMERGENT_LLM_KEY"),
        ("openai", "gpt-5.1", OPENAI_API_KEY or EMERGENT_LLM_KEY, "OPENAI_API_KEY" if OPENAI_API_KEY else "EMERGENT_LLM_KEY"),
        ("gemini", "gemini-2.5-flash", GEMINI_API_KEY or EMERGENT_LLM_KEY, "GEMINI_API_KEY" if GEMINI_API_KEY else "EMERGENT_LLM_KEY"),
    ]
    for provider, model, api_key, key_source in plans:
        try:
            chat = LlmChat(
                api_key=api_key,
                session_id=f"diag-{uuid.uuid4()}",
                system_message="Responde con la palabra exacta: OK",
            ).with_model(provider, model)
            resp = await chat.send_message(UserMessage(text="Di OK"))
            results[f"{provider}/{model}"] = {
                "ok": True,
                "key": key_source,
                "response_head": (resp or "")[:80],
            }
        except Exception as e:  # noqa: BLE001
            results[f"{provider}/{model}"] = {
                "ok": False,
                "key": key_source,
                "exc_type": type(e).__name__,
                "detail": str(e)[:400],
            }
    return results


# ---- Migration helper (called on demand) ----
async def _ensure_default_subject_and_migrate() -> str:
    """If there are topics without subject_id, create a default subject and assign them."""
    orphan = await db.topics.find_one({"subject_id": {"$in": [None, ""]}}, {"_id": 0})
    if orphan is None:
        orphan = await db.topics.find_one({"subject_id": {"$exists": False}}, {"_id": 0})
    if orphan is None:
        return ""

    default = await db.subjects.find_one({"name": "Anatomía"}, {"_id": 0})
    if not default:
        s = Subject(name="Anatomía", color="#C65D47")
        await db.subjects.insert_one(s.model_dump())
        default_id = s.id
    else:
        default_id = default["id"]

    await db.topics.update_many(
        {"$or": [{"subject_id": {"$exists": False}}, {"subject_id": {"$in": [None, ""]}}]},
        {"$set": {"subject_id": default_id}},
    )
    await db.questions.update_many(
        {"$or": [{"subject_id": {"$exists": False}}, {"subject_id": {"$in": [None, ""]}}]},
        {"$set": {"subject_id": default_id, "question_type": "mcq", "num_options": 3}},
    )
    return default_id


# ---- Subjects ----
@api.get("/subjects")
async def list_subjects():
    await _ensure_default_subject_and_migrate()
    subjects = await db.subjects.find({}, {"_id": 0}).sort("created_at", 1).to_list(1000)
    for s in subjects:
        s["topic_count"] = await db.topics.count_documents({"subject_id": s["id"]})
        s["question_count"] = await db.questions.count_documents({"subject_id": s["id"]})
        agg = await db.questions.aggregate([
            {"$match": {"subject_id": s["id"]}},
            {"$group": {"_id": None, "ans": {"$sum": "$times_answered"}, "ok": {"$sum": "$times_correct"}}},
        ]).to_list(1)
        s["accuracy"] = round(100 * agg[0]["ok"] / agg[0]["ans"], 1) if agg and agg[0]["ans"] else 0.0
    return subjects


class SubjectCreate(BaseModel):
    name: str
    color: Optional[str] = None


@api.post("/subjects")
async def create_subject(req: SubjectCreate):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nombre vacío")
    color = req.color or random.choice(SUBJECT_COLORS)
    s = Subject(name=name, color=color)
    await db.subjects.insert_one(s.model_dump())
    return s.model_dump()


@api.get("/subjects/{subject_id}")
async def get_subject(subject_id: str):
    s = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Asignatura no encontrada")
    s["topic_count"] = await db.topics.count_documents({"subject_id": subject_id})
    s["question_count"] = await db.questions.count_documents({"subject_id": subject_id})
    return s


class SubjectUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


@api.patch("/subjects/{subject_id}")
async def update_subject(subject_id: str, req: SubjectUpdate):
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="Nada que actualizar")
    res = await db.subjects.update_one({"id": subject_id}, {"$set": fields})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Asignatura no encontrada")
    return {"ok": True}


@api.delete("/subjects/{subject_id}")
async def delete_subject(subject_id: str):
    # Collect topic ids first so we can cascade pdfs properly
    topic_ids = [t["id"] async for t in db.topics.find({"subject_id": subject_id}, {"_id": 0, "id": 1})]
    res = await db.subjects.delete_one({"id": subject_id})
    await db.topics.delete_many({"subject_id": subject_id})
    await db.questions.delete_many({"subject_id": subject_id})
    if topic_ids:
        await db.pdfs.delete_many({"topic_id": {"$in": topic_ids}})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Asignatura no encontrada")
    return {"ok": True}


@api.get("/subjects/{subject_id}/topics")
async def list_topics_for_subject(subject_id: str):
    s = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Asignatura no encontrada")
    topics = await db.topics.find({"subject_id": subject_id}, {"_id": 0}).sort("created_at", 1).to_list(1000)
    for t in topics:
        t["question_count"] = await db.questions.count_documents({"topic_id": t["id"]})
        t["answered_count"] = await db.questions.count_documents({"topic_id": t["id"], "times_answered": {"$gt": 0}})
        agg = await db.questions.aggregate([
            {"$match": {"topic_id": t["id"]}},
            {"$group": {"_id": None, "ans": {"$sum": "$times_answered"}, "ok": {"$sum": "$times_correct"}}},
        ]).to_list(1)
        t["accuracy"] = round(100 * agg[0]["ok"] / agg[0]["ans"], 1) if agg and agg[0]["ans"] else 0.0
        t["pdf_count"] = await db.pdfs.count_documents({"topic_id": t["id"]})
    return topics


# ---- Topics ----
@api.get("/topics")
async def list_topics():
    """Global topics list. Kept for backwards compat / Stats page."""
    await _ensure_default_subject_and_migrate()
    topics = await db.topics.find({}, {"_id": 0}).sort("created_at", 1).to_list(2000)
    for t in topics:
        t["question_count"] = await db.questions.count_documents({"topic_id": t["id"]})
        t["answered_count"] = await db.questions.count_documents({"topic_id": t["id"], "times_answered": {"$gt": 0}})
        agg = await db.questions.aggregate([
            {"$match": {"topic_id": t["id"]}},
            {"$group": {"_id": None, "ans": {"$sum": "$times_answered"}, "ok": {"$sum": "$times_correct"}}},
        ]).to_list(1)
        t["accuracy"] = round(100 * agg[0]["ok"] / agg[0]["ans"], 1) if agg and agg[0]["ans"] else 0.0
    return topics


@api.get("/topics/{topic_id}")
async def get_topic(topic_id: str):
    t = await db.topics.find_one({"id": topic_id}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    t["question_count"] = await db.questions.count_documents({"topic_id": topic_id})
    t["pdf_count"] = await db.pdfs.count_documents({"topic_id": topic_id})
    agg = await db.questions.aggregate([
        {"$match": {"topic_id": topic_id}},
        {"$group": {"_id": None, "ans": {"$sum": "$times_answered"}, "ok": {"$sum": "$times_correct"}}},
    ]).to_list(1)
    t["accuracy"] = round(100 * agg[0]["ok"] / agg[0]["ans"], 1) if agg and agg[0]["ans"] else 0.0
    if t.get("subject_id"):
        s = await db.subjects.find_one({"id": t["subject_id"]}, {"_id": 0})
        t["subject"] = s
    return t


@api.post("/subjects/{subject_id}/topics/upload")
async def upload_topic_pdf(
    subject_id: str,
    name: str = Form(...),
    num_questions: int = Form(20),
    question_type: str = Form("mcq"),
    num_options: int = Form(3),
    file: UploadFile = File(...),
):
    subj = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subj:
        raise HTTPException(status_code=404, detail="Asignatura no encontrada")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan ficheros PDF")
    if num_questions < 3 or num_questions > 80:
        raise HTTPException(status_code=400, detail="num_questions debe estar entre 3 y 80")
    qtype = question_type if question_type in ("mcq", "tf") else "mcq"
    nopts = max(2, min(5, int(num_options))) if qtype == "mcq" else 2

    pdf_bytes = await file.read()
    try:
        text = extract_pdf_text(pdf_bytes)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Error al leer el PDF: {e}") from e

    if len(text) < 200:
        raise HTTPException(status_code=400, detail="El PDF no contiene suficiente texto extraíble")

    topic = Topic(
        subject_id=subject_id,
        name=name.strip(),
        description=f"Generado desde {file.filename}",
    )
    await db.topics.insert_one(topic.model_dump())

    pdf_source = PdfSource(
        topic_id=topic.id,
        filename=file.filename,
        text=text,
        char_count=len(text),
    )
    await db.pdfs.insert_one(pdf_source.model_dump())

    try:
        generated = await generate_questions_with_claude(
            topic.name, text, num_questions, question_type=qtype, num_options=nopts
        )
    except Exception:
        await db.topics.delete_one({"id": topic.id})
        await db.pdfs.delete_one({"id": pdf_source.id})
        raise

    if not generated:
        await db.topics.delete_one({"id": topic.id})
        await db.pdfs.delete_one({"id": pdf_source.id})
        raise HTTPException(status_code=502, detail="La IA no generó preguntas válidas")

    docs = []
    for g in generated:
        q = Question(
            topic_id=topic.id,
            topic_name=topic.name,
            subject_id=subject_id,
            pdf_source_id=pdf_source.id,
            question_type=g["question_type"],
            num_options=g["num_options"],
            question=g["question"],
            options=g["options"],
            correct_index=g["correct_index"],
            explanation=g.get("explanation", ""),
        )
        docs.append(q.model_dump())
    if docs:
        await db.questions.insert_many(docs)

    return {
        "topic": topic.model_dump(),
        "pdf_id": pdf_source.id,
        "questions_created": len(docs),
    }


@api.delete("/topics/{topic_id}")
async def delete_topic(topic_id: str):
    res = await db.topics.delete_one({"id": topic_id})
    await db.questions.delete_many({"topic_id": topic_id})
    await db.pdfs.delete_many({"topic_id": topic_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    return {"ok": True}


@api.get("/topics/{topic_id}/questions")
async def topic_questions(topic_id: str):
    qs = await db.questions.find({"topic_id": topic_id}, {"_id": 0}).sort("created_at", 1).to_list(5000)
    return qs


# ---- PDF sources ----
@api.get("/topics/{topic_id}/pdfs")
async def list_topic_pdfs(topic_id: str):
    pdfs = await db.pdfs.find({"topic_id": topic_id}, {"_id": 0, "text": 0}).sort("created_at", 1).to_list(100)
    for p in pdfs:
        p["question_count"] = await db.questions.count_documents({"pdf_source_id": p["id"]})
    return pdfs


class RegenerateReq(BaseModel):
    num_questions: int = 10
    question_type: Literal["mcq", "tf"] = "mcq"
    num_options: int = 3


@api.post("/pdfs/{pdf_id}/regenerate")
async def regenerate_from_pdf(pdf_id: str, req: RegenerateReq):
    pdf = await db.pdfs.find_one({"id": pdf_id}, {"_id": 0})
    if not pdf:
        raise HTTPException(status_code=404, detail="PDF no encontrado")
    topic = await db.topics.find_one({"id": pdf["topic_id"]}, {"_id": 0})
    if not topic:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    if req.num_questions < 3 or req.num_questions > 80:
        raise HTTPException(status_code=400, detail="num_questions debe estar entre 3 y 80")

    nopts = max(2, min(5, int(req.num_options))) if req.question_type == "mcq" else 2
    generated = await generate_questions_with_claude(
        topic["name"], pdf["text"], req.num_questions, question_type=req.question_type, num_options=nopts
    )
    docs = []
    for g in generated:
        q = Question(
            topic_id=topic["id"],
            topic_name=topic["name"],
            subject_id=topic.get("subject_id"),
            pdf_source_id=pdf_id,
            question_type=g["question_type"],
            num_options=g["num_options"],
            question=g["question"],
            options=g["options"],
            correct_index=g["correct_index"],
            explanation=g.get("explanation", ""),
        )
        docs.append(q.model_dump())
    if docs:
        await db.questions.insert_many(docs)
    return {"questions_created": len(docs)}


@api.delete("/pdfs/{pdf_id}")
async def delete_pdf(pdf_id: str):
    res = await db.pdfs.delete_one({"id": pdf_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="PDF no encontrado")
    # questions remain (pdf_source_id is just a reference)
    await db.questions.update_many({"pdf_source_id": pdf_id}, {"$set": {"pdf_source_id": None}})
    return {"ok": True}


@api.post("/topics/{topic_id}/pdfs/upload")
async def add_pdf_to_topic(topic_id: str, file: UploadFile = File(...)):
    """Add a new PDF to an existing topic WITHOUT generating questions immediately."""
    topic = await db.topics.find_one({"id": topic_id}, {"_id": 0})
    if not topic:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan ficheros PDF")
    pdf_bytes = await file.read()
    try:
        text = extract_pdf_text(pdf_bytes)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Error al leer el PDF: {e}") from e
    if len(text) < 200:
        raise HTTPException(status_code=400, detail="El PDF no contiene suficiente texto extraíble")
    pdf_source = PdfSource(
        topic_id=topic_id,
        filename=file.filename,
        text=text,
        char_count=len(text),
    )
    await db.pdfs.insert_one(pdf_source.model_dump())
    return {
        "id": pdf_source.id,
        "topic_id": topic_id,
        "filename": pdf_source.filename,
        "char_count": pdf_source.char_count,
        "created_at": pdf_source.created_at,
        "question_count": 0,
    }


class GenerateFromPdfsReq(BaseModel):
    pdf_ids: List[str]
    num_questions: int = 10
    question_type: Literal["mcq", "tf"] = "mcq"
    num_options: int = 3


@api.post("/topics/{topic_id}/generate")
async def generate_from_topic_pdfs(topic_id: str, req: GenerateFromPdfsReq):
    """Generate questions for a topic by combining text from selected PDFs."""
    topic = await db.topics.find_one({"id": topic_id}, {"_id": 0})
    if not topic:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    if not req.pdf_ids:
        raise HTTPException(status_code=400, detail="Selecciona al menos un PDF")
    if req.num_questions < 3 or req.num_questions > 80:
        raise HTTPException(status_code=400, detail="num_questions debe estar entre 3 y 80")

    pdfs = await db.pdfs.find(
        {"id": {"$in": req.pdf_ids}, "topic_id": topic_id}, {"_id": 0}
    ).to_list(100)
    if not pdfs:
        raise HTTPException(status_code=404, detail="No se encontraron PDFs")

    # Combine PDF texts with clear separators
    parts = []
    for p in pdfs:
        parts.append(f"=== Fuente: {p['filename']} ===\n{p['text']}")
    combined = "\n\n".join(parts)

    nopts = max(2, min(5, int(req.num_options))) if req.question_type == "mcq" else 2
    generated = await generate_questions_with_claude(
        topic["name"], combined, req.num_questions, question_type=req.question_type, num_options=nopts
    )

    primary_pdf_id = pdfs[0]["id"]
    docs = []
    for g in generated:
        q = Question(
            topic_id=topic_id,
            topic_name=topic["name"],
            subject_id=topic.get("subject_id"),
            pdf_source_id=primary_pdf_id,
            question_type=g["question_type"],
            num_options=g["num_options"],
            question=g["question"],
            options=g["options"],
            correct_index=g["correct_index"],
            explanation=g.get("explanation", ""),
        )
        docs.append(q.model_dump())
    if docs:
        await db.questions.insert_many(docs)
    return {"questions_created": len(docs), "pdf_ids_used": [p["id"] for p in pdfs]}


# ---- Questions ----
@api.post("/questions/{question_id}/favorite")
async def toggle_favorite(question_id: str):
    q = await db.questions.find_one({"id": question_id}, {"_id": 0})
    if not q:
        raise HTTPException(status_code=404, detail="Pregunta no encontrada")
    new_val = not q.get("favorite", False)
    await db.questions.update_one({"id": question_id}, {"$set": {"favorite": new_val}})
    return {"favorite": new_val}


@api.post("/questions/{question_id}/difficult")
async def toggle_difficult(question_id: str):
    q = await db.questions.find_one({"id": question_id}, {"_id": 0})
    if not q:
        raise HTTPException(status_code=404, detail="Pregunta no encontrada")
    new_val = not q.get("difficult", False)
    await db.questions.update_one({"id": question_id}, {"$set": {"difficult": new_val}})
    return {"difficult": new_val}


@api.delete("/questions/{question_id}")
async def delete_question(question_id: str):
    res = await db.questions.delete_one({"id": question_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Pregunta no encontrada")
    return {"ok": True}


# ---- Quiz ----
class QuizStartReq(BaseModel):
    mode: Literal["exam", "practice", "errors", "srs", "favorites"]
    subject_ids: List[str] = []
    topic_ids: List[str] = []
    num_questions: int = 20
    time_limit_minutes: Optional[int] = None
    question_type: Optional[Literal["mcq", "tf", "any"]] = "any"
    num_options: Optional[int] = None  # filter exact num_options for mcq, None = any


@api.post("/quiz/start")
async def quiz_start(req: QuizStartReq):
    query: dict = {}
    if req.subject_ids:
        query["subject_id"] = {"$in": req.subject_ids}
    if req.topic_ids:
        query["topic_id"] = {"$in": req.topic_ids}
    if req.question_type and req.question_type != "any":
        query["question_type"] = req.question_type
    if req.num_options:
        query["num_options"] = int(req.num_options)

    if req.mode == "errors":
        query["$expr"] = {"$gt": ["$times_answered", "$times_correct"]}
    elif req.mode == "favorites":
        query["favorite"] = True
    elif req.mode == "srs":
        now = _now_iso()
        query["srs_next_review"] = {"$lte": now}

    questions = await db.questions.find(query, {"_id": 0}).to_list(5000)
    if not questions:
        raise HTTPException(status_code=404, detail="No hay preguntas para los filtros seleccionados")

    random.shuffle(questions)
    questions = questions[: req.num_questions]

    payload = []
    for q in questions:
        n = int(q.get("num_options") or len(q.get("options", []) or []))
        if q.get("question_type") == "tf":
            shuffled_options = q["options"]
            new_correct = q["correct_index"]
        else:
            order = list(range(n))
            random.shuffle(order)
            shuffled_options = [q["options"][i] for i in order]
            new_correct = order.index(q["correct_index"])
        payload.append({
            "id": q["id"],
            "topic_id": q["topic_id"],
            "topic_name": q["topic_name"],
            "subject_id": q.get("subject_id"),
            "question_type": q.get("question_type", "mcq"),
            "num_options": n,
            "question": q["question"],
            "options": shuffled_options,
            "correct_index": new_correct,
            "explanation": q.get("explanation", ""),
            "favorite": q.get("favorite", False),
            "difficult": q.get("difficult", False),
        })
    return {"questions": payload, "mode": req.mode}


class QuizSubmitReq(BaseModel):
    mode: Literal["exam", "practice", "errors", "srs", "favorites"]
    subject_ids: List[str] = []
    topic_ids: List[str] = []
    answers: List[dict]  # [{"question_id": str, "selected": int, "correct_index": int}]
    duration_seconds: int
    time_limit_seconds: Optional[int] = None
    penalty_factor: Optional[int] = None  # None = no penalty; otherwise X wrong = -1 correct
    question_type: Optional[str] = None


def _update_srs(q: dict, correct: bool) -> dict:
    """Simplified SM-2."""
    ease = float(q.get("srs_ease", 2.5))
    interval = float(q.get("srs_interval_days", 0))
    if correct:
        if interval < 1:
            interval = 1
        elif interval < 6:
            interval = 3
        else:
            interval = round(interval * ease, 2)
        ease = max(1.3, ease + 0.1)
    else:
        interval = 0.5
        ease = max(1.3, ease - 0.2)
    next_review = (datetime.now(timezone.utc) + timedelta(days=interval)).isoformat()
    return {"srs_ease": ease, "srs_interval_days": interval, "srs_next_review": next_review}


@api.post("/quiz/submit")
async def quiz_submit(req: QuizSubmitReq):
    correct = 0
    wrong = 0
    unanswered = 0
    total = len(req.answers)
    for a in req.answers:
        qid = a.get("question_id")
        selected = int(a.get("selected", -1))
        correct_index = int(a.get("correct_index", -1))
        if selected == -1:
            unanswered += 1
            continue
        is_correct = selected == correct_index
        if is_correct:
            correct += 1
        else:
            wrong += 1

        q = await db.questions.find_one({"id": qid}, {"_id": 0})
        if not q:
            continue
        update = {
            "$inc": {"times_answered": 1, **({"times_correct": 1} if is_correct else {})},
            "$set": {
                "last_answered_at": _now_iso(),
                "last_correct": is_correct,
                **_update_srs(q, is_correct),
            },
        }
        await db.questions.update_one({"id": qid}, update)

    # Score calculation with optional penalty
    pf = req.penalty_factor
    if pf and pf > 0:
        raw = correct - (wrong / pf)
    else:
        raw = float(correct)
    if raw < 0:
        raw = 0.0
    score_10 = round((raw / total) * 10, 2) if total else 0.0
    raw_score = round(raw, 3)

    attempt = Attempt(
        mode=req.mode,
        subject_ids=req.subject_ids,
        topic_ids=req.topic_ids,
        question_ids=[a.get("question_id") for a in req.answers],
        answers=[int(a.get("selected", -1)) for a in req.answers],
        correct_count=correct,
        wrong_count=wrong,
        unanswered_count=unanswered,
        total=total,
        penalty_factor=pf,
        raw_score=raw_score,
        score_10=score_10,
        question_type=req.question_type,
        duration_seconds=req.duration_seconds,
        time_limit_seconds=req.time_limit_seconds,
    )
    await db.attempts.insert_one(attempt.model_dump())
    return {
        "attempt_id": attempt.id,
        "correct": correct,
        "wrong": wrong,
        "unanswered": unanswered,
        "total": total,
        "raw_score": raw_score,
        "score_10": score_10,
        "penalty_factor": pf,
    }


# ---- Stats ----
@api.get("/stats")
async def stats_overview():
    await _ensure_default_subject_and_migrate()
    total_subjects = await db.subjects.count_documents({})
    total_topics = await db.topics.count_documents({})
    total_questions = await db.questions.count_documents({})
    total_attempts = await db.attempts.count_documents({})

    agg = await db.questions.aggregate([
        {"$group": {"_id": None, "ans": {"$sum": "$times_answered"}, "ok": {"$sum": "$times_correct"}}},
    ]).to_list(1)
    accuracy = 0.0
    answered = 0
    if agg and agg[0]["ans"]:
        accuracy = round(100 * agg[0]["ok"] / agg[0]["ans"], 1)
        answered = agg[0]["ans"]

    favorites = await db.questions.count_documents({"favorite": True})
    difficult = await db.questions.count_documents({"difficult": True})
    errors_pool = await db.questions.count_documents({"$expr": {"$gt": ["$times_answered", "$times_correct"]}})
    now = _now_iso()
    due_srs = await db.questions.count_documents({"srs_next_review": {"$lte": now}, "times_answered": {"$gt": 0}})

    last_attempts = await db.attempts.find({}, {"_id": 0}).sort("created_at", -1).to_list(10)

    return {
        "total_subjects": total_subjects,
        "total_topics": total_topics,
        "total_questions": total_questions,
        "total_attempts": total_attempts,
        "answered_total": answered,
        "accuracy": accuracy,
        "favorites": favorites,
        "difficult": difficult,
        "errors_pool": errors_pool,
        "due_srs": due_srs,
        "last_attempts": last_attempts,
    }


@api.get("/stats/by-subject")
async def stats_by_subject():
    subjects = await db.subjects.find({}, {"_id": 0}).to_list(1000)
    out = []
    for s in subjects:
        agg = await db.questions.aggregate([
            {"$match": {"subject_id": s["id"]}},
            {"$group": {
                "_id": None,
                "ans": {"$sum": "$times_answered"},
                "ok": {"$sum": "$times_correct"},
                "total": {"$sum": 1},
            }},
        ]).to_list(1)
        if agg:
            row = agg[0]
            accuracy = round(100 * row["ok"] / row["ans"], 1) if row["ans"] else 0.0
            out.append({
                "subject_id": s["id"],
                "subject_name": s["name"],
                "color": s.get("color", "#C65D47"),
                "total_questions": row["total"],
                "answered": row["ans"],
                "correct": row["ok"],
                "accuracy": accuracy,
            })
        else:
            out.append({
                "subject_id": s["id"],
                "subject_name": s["name"],
                "color": s.get("color", "#C65D47"),
                "total_questions": 0,
                "answered": 0,
                "correct": 0,
                "accuracy": 0.0,
            })
    return out


@api.get("/stats/by-topic")
async def stats_by_topic():
    topics = await db.topics.find({}, {"_id": 0}).to_list(2000)
    out = []
    for t in topics:
        agg = await db.questions.aggregate([
            {"$match": {"topic_id": t["id"]}},
            {"$group": {
                "_id": None,
                "ans": {"$sum": "$times_answered"},
                "ok": {"$sum": "$times_correct"},
                "total": {"$sum": 1},
            }},
        ]).to_list(1)
        if agg:
            row = agg[0]
            accuracy = round(100 * row["ok"] / row["ans"], 1) if row["ans"] else 0.0
            out.append({
                "topic_id": t["id"],
                "topic_name": t["name"],
                "subject_id": t.get("subject_id"),
                "total_questions": row["total"],
                "answered": row["ans"],
                "correct": row["ok"],
                "accuracy": accuracy,
            })
        else:
            out.append({
                "topic_id": t["id"],
                "topic_name": t["name"],
                "subject_id": t.get("subject_id"),
                "total_questions": 0,
                "answered": 0,
                "correct": 0,
                "accuracy": 0.0,
            })
    return out


# Register
app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def ensure_indices():
    """Create indices for scaling to many subjects / topics / PDFs / questions."""
    try:
        # subjects
        await db.subjects.create_index("id", unique=True)
        # topics
        await db.topics.create_index("id", unique=True)
        await db.topics.create_index("subject_id")
        # pdfs
        await db.pdfs.create_index("id", unique=True)
        await db.pdfs.create_index("topic_id")
        # questions
        await db.questions.create_index("id", unique=True)
        await db.questions.create_index("topic_id")
        await db.questions.create_index("subject_id")
        await db.questions.create_index("pdf_source_id")
        await db.questions.create_index("favorite")
        await db.questions.create_index("difficult")
        await db.questions.create_index("srs_next_review")
        await db.questions.create_index("question_type")
        await db.questions.create_index([("times_answered", 1), ("times_correct", 1)])
        # attempts
        await db.attempts.create_index("id", unique=True)
        await db.attempts.create_index([("created_at", -1)])
        logger.info("MongoDB indices ensured.")
    except Exception as e:  # noqa: BLE001
        logger.warning("ensure_indices failed: %s", e)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
