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

app = FastAPI(title="Anatomía Study API")
api = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("anatomia")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class Topic(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: Optional[str] = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Question(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    topic_id: str
    topic_name: str
    question: str
    options: List[str]  # always length 3
    correct_index: int  # 0..2
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
    topic_ids: List[str] = []
    question_ids: List[str]
    answers: List[int]  # selected option index per question, -1 if unanswered
    correct_count: int
    total: int
    score_10: float  # nota sobre 10
    duration_seconds: int
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


async def generate_questions_with_claude(topic_name: str, source_text: str, num_questions: int) -> List[dict]:
    """Send the slides text to Claude Sonnet 4.5 and ask for MCQs."""
    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=500, detail="EMERGENT_LLM_KEY no configurada")

    # Truncate very long PDFs (safe context)
    max_chars = 120_000
    if len(source_text) > max_chars:
        source_text = source_text[:max_chars]

    system_msg = (
        "Eres un profesor experto en anatomía humana. Tu tarea es generar preguntas "
        "tipo test de alta calidad EXCLUSIVAMENTE a partir del contenido de las "
        "diapositivas que se te proporcionan. Las preguntas deben ser claras, "
        "específicas y útiles para preparar un examen universitario de anatomía. "
        "Responde SIEMPRE en español. Devuelve SOLO JSON válido, sin texto extra."
    )

    user_prompt = f"""A partir del siguiente contenido de diapositivas del tema "{topic_name}", \
genera exactamente {num_questions} preguntas tipo test.

REGLAS ESTRICTAS:
- Cada pregunta debe tener EXACTAMENTE 3 opciones de respuesta.
- Solo UNA opción es correcta.
- Las preguntas y respuestas deben estar basadas únicamente en el contenido proporcionado.
- Varía la dificultad y los conceptos cubiertos.
- Incluye una explicación breve (1-2 frases) que justifique la respuesta correcta.
- Evita preguntas triviales o duplicadas.
- Devuelve SOLO un array JSON, sin markdown, sin comentarios.

FORMATO EXACTO:
[
  {{
    "question": "texto de la pregunta",
    "options": ["opción A", "opción B", "opción C"],
    "correct_index": 0,
    "explanation": "breve justificación"
  }}
]

CONTENIDO DE LAS DIAPOSITIVAS:
\"\"\"
{source_text}
\"\"\"
"""

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"qgen-{uuid.uuid4()}",
        system_message=system_msg,
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")

    response = await chat.send_message(UserMessage(text=user_prompt))
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
    for q in data:
        if not isinstance(q, dict):
            continue
        opts = q.get("options") or []
        if len(opts) != 3:
            continue
        idx = q.get("correct_index", 0)
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            idx = 0
        if idx not in (0, 1, 2):
            idx = 0
        cleaned.append({
            "question": str(q.get("question", "")).strip(),
            "options": [str(o).strip() for o in opts],
            "correct_index": idx,
            "explanation": str(q.get("explanation", "")).strip(),
        })
    return cleaned


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@api.get("/")
async def root():
    return {"app": "Anatomía", "status": "ok"}


# ---- Topics ----
@api.get("/topics")
async def list_topics():
    topics = await db.topics.find({}, {"_id": 0}).sort("created_at", 1).to_list(1000)
    # add question count + best score
    for t in topics:
        t["question_count"] = await db.questions.count_documents({"topic_id": t["id"]})
        # answered
        answered = await db.questions.count_documents({"topic_id": t["id"], "times_answered": {"$gt": 0}})
        t["answered_count"] = answered
        # accuracy
        agg = await db.questions.aggregate([
            {"$match": {"topic_id": t["id"]}},
            {"$group": {
                "_id": None,
                "ans": {"$sum": "$times_answered"},
                "ok": {"$sum": "$times_correct"},
            }},
        ]).to_list(1)
        if agg and agg[0]["ans"]:
            t["accuracy"] = round(100 * agg[0]["ok"] / agg[0]["ans"], 1)
        else:
            t["accuracy"] = 0.0
    return topics


@api.post("/topics/upload")
async def upload_topic_pdf(
    name: str = Form(...),
    num_questions: int = Form(20),
    file: UploadFile = File(...),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan ficheros PDF")
    if num_questions < 3 or num_questions > 80:
        raise HTTPException(status_code=400, detail="num_questions debe estar entre 3 y 80")

    pdf_bytes = await file.read()
    try:
        text = extract_pdf_text(pdf_bytes)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Error al leer el PDF: {e}") from e

    if len(text) < 200:
        raise HTTPException(status_code=400, detail="El PDF no contiene suficiente texto extraíble")

    topic = Topic(name=name.strip(), description=f"Generado desde {file.filename}")
    await db.topics.insert_one(topic.model_dump())

    try:
        generated = await generate_questions_with_claude(topic.name, text, num_questions)
    except Exception:
        await db.topics.delete_one({"id": topic.id})
        raise
    if not generated:
        # rollback topic if no questions
        await db.topics.delete_one({"id": topic.id})
        raise HTTPException(status_code=502, detail="La IA no generó preguntas válidas")

    docs = []
    for g in generated:
        q = Question(
            topic_id=topic.id,
            topic_name=topic.name,
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
        "questions_created": len(docs),
    }


@api.post("/topics/{topic_id}/generate-more")
async def generate_more_for_topic(topic_id: str, num_questions: int = Form(10), file: UploadFile = File(...)):
    topic_doc = await db.topics.find_one({"id": topic_id}, {"_id": 0})
    if not topic_doc:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan PDF")
    pdf_bytes = await file.read()
    text = extract_pdf_text(pdf_bytes)
    if len(text) < 200:
        raise HTTPException(status_code=400, detail="PDF sin texto suficiente")

    generated = await generate_questions_with_claude(topic_doc["name"], text, num_questions)
    docs = []
    for g in generated:
        q = Question(
            topic_id=topic_id,
            topic_name=topic_doc["name"],
            question=g["question"],
            options=g["options"],
            correct_index=g["correct_index"],
            explanation=g.get("explanation", ""),
        )
        docs.append(q.model_dump())
    if docs:
        await db.questions.insert_many(docs)
    return {"questions_created": len(docs)}


@api.delete("/topics/{topic_id}")
async def delete_topic(topic_id: str):
    res = await db.topics.delete_one({"id": topic_id})
    await db.questions.delete_many({"topic_id": topic_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    return {"ok": True}


@api.get("/topics/{topic_id}/questions")
async def topic_questions(topic_id: str):
    qs = await db.questions.find({"topic_id": topic_id}, {"_id": 0}).sort("created_at", 1).to_list(2000)
    return qs


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
    topic_ids: List[str] = []
    num_questions: int = 20
    time_limit_minutes: Optional[int] = None  # for exam mode


@api.post("/quiz/start")
async def quiz_start(req: QuizStartReq):
    query: dict = {}
    if req.topic_ids:
        query["topic_id"] = {"$in": req.topic_ids}

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

    # For each question, shuffle options but keep mapping of correct index
    payload = []
    for q in questions:
        order = [0, 1, 2]
        random.shuffle(order)
        shuffled_options = [q["options"][i] for i in order]
        new_correct = order.index(q["correct_index"])
        payload.append({
            "id": q["id"],
            "topic_id": q["topic_id"],
            "topic_name": q["topic_name"],
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
    topic_ids: List[str] = []
    answers: List[dict]  # [{"question_id": str, "selected": int, "correct_index": int}]
    duration_seconds: int
    time_limit_seconds: Optional[int] = None


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
        interval = 0.5  # review in ~12h
        ease = max(1.3, ease - 0.2)
    next_review = (datetime.now(timezone.utc) + timedelta(days=interval)).isoformat()
    return {"srs_ease": ease, "srs_interval_days": interval, "srs_next_review": next_review}


@api.post("/quiz/submit")
async def quiz_submit(req: QuizSubmitReq):
    correct = 0
    total = len(req.answers)
    for a in req.answers:
        qid = a.get("question_id")
        selected = int(a.get("selected", -1))
        correct_index = int(a.get("correct_index", -1))
        is_correct = selected == correct_index and selected != -1

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
        if is_correct:
            correct += 1

    score_10 = round((correct / total) * 10, 2) if total else 0.0
    attempt = Attempt(
        mode=req.mode,
        topic_ids=req.topic_ids,
        question_ids=[a.get("question_id") for a in req.answers],
        answers=[int(a.get("selected", -1)) for a in req.answers],
        correct_count=correct,
        total=total,
        score_10=score_10,
        duration_seconds=req.duration_seconds,
        time_limit_seconds=req.time_limit_seconds,
    )
    await db.attempts.insert_one(attempt.model_dump())
    return {
        "attempt_id": attempt.id,
        "correct": correct,
        "total": total,
        "score_10": score_10,
    }


# ---- Stats ----
@api.get("/stats")
async def stats_overview():
    total_topics = await db.topics.count_documents({})
    total_questions = await db.questions.count_documents({})
    total_attempts = await db.attempts.count_documents({})

    agg = await db.questions.aggregate([
        {"$group": {
            "_id": None,
            "ans": {"$sum": "$times_answered"},
            "ok": {"$sum": "$times_correct"},
        }},
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


@api.get("/stats/by-topic")
async def stats_by_topic():
    topics = await db.topics.find({}, {"_id": 0}).to_list(1000)
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
                "total_questions": row["total"],
                "answered": row["ans"],
                "correct": row["ok"],
                "accuracy": accuracy,
            })
        else:
            out.append({
                "topic_id": t["id"],
                "topic_name": t["name"],
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
