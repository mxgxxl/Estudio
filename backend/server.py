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

app = FastAPI(title="Study App API")
api = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("studyapp")


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


async def generate_questions_with_claude(
    topic_name: str,
    source_text: str,
    num_questions: int,
    question_type: str = "mcq",
    num_options: int = 3,
) -> List[dict]:
    """Send the slides text to Claude Sonnet 4.5 and ask for MCQs or TF questions."""
    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=500, detail="EMERGENT_LLM_KEY no configurada")

    # Truncate very long PDFs (safe context)
    max_chars = 120_000
    if len(source_text) > max_chars:
        source_text = source_text[:max_chars]

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

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"qgen-{uuid.uuid4()}",
        system_message=system_msg,
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")

    # Retry on transient upstream failures (502/504/timeouts)
    import asyncio as _asyncio
    last_err = None
    response = None
    for attempt in range(3):
        try:
            response = await chat.send_message(UserMessage(text=user_prompt))
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
            msg = str(e).lower()
            is_transient = any(
                k in msg
                for k in ("502", "503", "504", "bad gateway", "timeout", "overloaded", "rate limit", "429")
            )
            logger.warning("Claude call failed (attempt %s/3): %s", attempt + 1, e)
            if not is_transient or attempt == 2:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "El servicio de IA está temporalmente saturado. "
                        "Vuelve a intentarlo en unos segundos. "
                        f"(Detalle: {str(e)[:160]})"
                    ),
                ) from e
            await _asyncio.sleep(2 ** attempt)
    if response is None:
        raise HTTPException(status_code=502, detail=f"Fallo al llamar a la IA: {last_err}")

    raw = _strip_code_fences(response)

    # Find JSON array in response if Claude added prose
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\[\s*{.*}\s*\]", raw, re.DOTALL)
        if not match:
            logger.error("No se pudo parsear JSON de Claude. Respuesta: %s", raw[:400])
            raise HTTPException(status_code=502, detail="La IA no devolvió JSON válido")
        data = json.loads(match.group(0))

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
            cleaned.append({
                "question": str(q.get("question", "")).strip(),
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
            if len(opts) != n:
                continue
            idx = q.get("correct_index", 0)
            try:
                idx = int(idx)
            except (TypeError, ValueError):
                idx = 0
            if idx < 0 or idx >= n:
                idx = 0
            cleaned.append({
                "question": str(q.get("question", "")).strip(),
                "options": [str(o).strip() for o in opts],
                "correct_index": idx,
                "explanation": str(q.get("explanation", "")).strip(),
                "question_type": "mcq",
                "num_options": n,
            })
    return cleaned


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@api.get("/")
async def root():
    return {"app": "Study App", "status": "ok"}


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
    res = await db.subjects.delete_one({"id": subject_id})
    await db.topics.delete_many({"subject_id": subject_id})
    await db.questions.delete_many({"subject_id": subject_id})
    await db.pdfs.delete_many({"topic_id": {"$in": []}})  # no-op
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


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
