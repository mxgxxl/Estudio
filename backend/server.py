"""
Anatomía - Backend
FastAPI + MongoDB + Google Gemini (google-genai SDK)
"""
import os
import io
import re
import json
import asyncio
import hmac
import hashlib
import uuid
import logging
import random
import httpx
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Literal

from fastapi import FastAPI, APIRouter, UploadFile, File, Form, HTTPException, Depends, Request, Query
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr
import bcrypt
import jwt
from pypdf import PdfReader

from google import genai
from google.genai import types as genai_types

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# Mongo
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

gemini_client: Optional[genai.Client] = (
    genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
)

# Auth / JWT
JWT_SECRET = os.environ.get("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
# Caducidad del token de acceso (por defecto 7 días)
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))

# Límites de uso de IA (generaciones por mes natural rodante, por plan).
# Configurables por variable de entorno; valores por defecto razonables.
FREE_AI_GENERATIONS_PER_MONTH = int(os.environ.get("FREE_AI_GENERATIONS_PER_MONTH", "30"))
PREMIUM_AI_GENERATIONS_PER_MONTH = int(os.environ.get("PREMIUM_AI_GENERATIONS_PER_MONTH", "2000"))
# Correcciones (evaluar respuestas de desarrollo). Contador aparte, mucho más
# barato por unidad que una generación → límites más holgados.
FREE_AI_CORRECTIONS_PER_MONTH = int(os.environ.get("FREE_AI_CORRECTIONS_PER_MONTH", "300"))
PREMIUM_AI_CORRECTIONS_PER_MONTH = int(os.environ.get("PREMIUM_AI_CORRECTIONS_PER_MONTH", "5000"))
# Duración del periodo: mes natural rodante de 30 días (compartido por ambos).
AI_PERIOD_DAYS = 30

# Paddle (Billing v4) — pasarela de pagos. Por defecto en sandbox.
PADDLE_ENV = os.environ.get("PADDLE_ENV", "sandbox")
PADDLE_API_KEY = os.environ.get("PADDLE_API_KEY", "")
PADDLE_WEBHOOK_SECRET = os.environ.get("PADDLE_WEBHOOK_SECRET", "")
PADDLE_PREMIUM_PRICE_ID = os.environ.get("PADDLE_PREMIUM_PRICE_ID", "")

bearer_scheme = HTTPBearer(auto_error=False)

app = FastAPI(title="Study App API")
api = APIRouter(prefix="/api")

# Nivel de logging configurable por entorno (por defecto INFO).
# Sube a DEBUG (LOG_LEVEL=DEBUG) para ver las trazas rutinarias de Paddle.
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("studyapp")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

logger.info("[LLM-DIAG] provider=gemini model=%s GEMINI_API_KEY_present=%s", GEMINI_MODEL, bool(GEMINI_API_KEY))
logger.info(
    "[AI-LIMITS] generations free=%s/mes premium=%s/mes | corrections free=%s/mes premium=%s/mes | period_days=%s",
    FREE_AI_GENERATIONS_PER_MONTH, PREMIUM_AI_GENERATIONS_PER_MONTH,
    FREE_AI_CORRECTIONS_PER_MONTH, PREMIUM_AI_CORRECTIONS_PER_MONTH, AI_PERIOD_DAYS,
)
logger.info(
    "[PADDLE] env=%s api_key_present=%s webhook_secret_present=%s price_id_present=%s",
    PADDLE_ENV, bool(PADDLE_API_KEY), bool(PADDLE_WEBHOOK_SECRET), bool(PADDLE_PREMIUM_PRICE_ID),
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
SUBJECT_COLORS = ["#C65D47", "#7A8B76", "#6C8A9C", "#D4A373", "#9C7A8B", "#5C8A7A", "#B84A4A", "#8A857D"]


class Subject(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    name: str
    color: str = "#C65D47"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Topic(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    subject_id: str
    name: str
    description: Optional[str] = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PdfSource(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    # La atadura PDF<->tema vive EXCLUSIVAMENTE en la colección pdf_links; un PDF ya
    # no lleva topic_id embebido (retirado tras consolidar pdf_links).
    filename: str
    text: str
    char_count: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PdfLink(BaseModel):
    """Asociación muchos-a-muchos entre un PDF y un tema (colección intermedia).

    Un PDF (pdfs) puede estar vinculado a varios temas/asignaturas mediante varias
    filas PdfLink. subject_id se desnormaliza (copiado del topic) para poder filtrar
    por asignatura sin joins."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    pdf_id: str
    topic_id: str
    subject_id: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Summary(BaseModel):
    """Resumen de IA persistido (colección summaries).

    Se keyea por `pdf_id` (NO por tema): como un PDF es muchos-a-muchos, su
    resumen es COMPARTIDO por todos los temas que lo contengan. `scope` deja el
    modelo preparado para futuros resúmenes de tema completo o varios por PDF; el
    "1 por PDF" de hoy se impone a nivel de app con upsert (sin índice único).
    `content` guarda el JSON estructurado de Gemini tal cual (overview/
    key_concepts/sections/remember)."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    pdf_id: str
    scope: str = "pdf"
    content: dict
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Question(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    topic_id: str
    topic_name: str
    subject_id: Optional[str] = None
    pdf_source_id: Optional[str] = None
    question_type: Literal["mcq", "tf", "dev"] = "mcq"
    num_options: int = 3
    question: str
    options: List[str]
    correct_index: int
    explanation: Optional[str] = ""
    model_answer: Optional[str] = ""   # Para preguntas de desarrollo
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
    user_id: str
    # Dos ejes: SELECCIÓN (qué preguntas) × COMPORTAMIENTO (cómo se juega). Fuente
    # ÚNICA. El viejo `mode` persistido se retiró en Fase 2 (histórico migrado a los
    # ejes). El `mode` de REQUEST sigue vivo por compat de entrada hasta Fase 3.
    selection: Literal["all", "errors", "srs", "favorites"] = "all"
    behavior: Literal["practice", "exam"] = "practice"
    subject_ids: List[str] = []
    topic_ids: List[str] = []
    question_ids: List[str]
    answers: List[int]
    # Snapshot por pregunta (ADITIVO, retrocompat: los intentos legacy no lo tienen).
    # Cada item: {question_id, question_type, question, options (orden MOSTRADO),
    # selected (índice en ese orden), correct_index (de la sesión), is_correct; y para
    # dev: user_answer, dev_score, feedback}. Permite reconstruir el intento pregunta
    # a pregunta pese al barajado de opciones (que no vive en question_ids/answers).
    items: Optional[List[dict]] = None
    correct_count: int
    wrong_count: int = 0
    unanswered_count: int = 0
    total: int
    penalty_factor: Optional[int] = None
    raw_score: float = 0.0
    score_10: float = 0.0
    question_type: Optional[str] = None
    duration_seconds: int = 0
    time_limit_seconds: Optional[int] = None
    streak_day: Optional[str] = None  # ISO date for streak tracking
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
        except Exception as e:
            logger.warning("PDF page extract error: %s", e)
    return _clean_pdf_text("\n\n".join(parts))


def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _build_prompts(topic_name: str, source_text: str, num_questions: int, question_type: str, num_options: int, custom_instructions: str = ""):
    """Builds the (system, user) prompt pair for a generation call."""
    custom_note = ""
    if custom_instructions:
        custom_note = f"\n\nINSTRUCCIONES ADICIONALES DEL PROFESOR (prioridad máxima): {custom_instructions}"

    system_msg = (
        "Eres un profesor experto. Tu tarea es generar preguntas de examen "
        "de alta calidad EXCLUSIVAMENTE a partir del temario que se te proporciona. "
        "Las preguntas, respuestas correctas e incorrectas deben usar el vocabulario "
        "exacto, términos técnicos y frases literales del temario proporcionado. "
        "NO parafrasees ni inventes datos: extrae directamente del texto. "
        "Responde SIEMPRE en español. "
        "Devuelve SOLO JSON válido, sin texto extra."
        + custom_note
    )
    if question_type == "tf":
        user_prompt = f"""A partir del siguiente temario del tema "{topic_name}", \
genera exactamente {num_questions} preguntas tipo VERDADERO/FALSO.

REGLAS ESTRICTAS:
- Cada pregunta es una AFIRMACIÓN que el alumno debe juzgar como verdadera o falsa.
- Varía entre afirmaciones verdaderas y falsas (aprox 50/50).
- Las afirmaciones deben usar frases o datos LITERALES del temario proporcionado.
- Las falsas deben modificar un dato específico del texto (un número, nombre o concepto concreto).
- Incluye una explicación breve (1-2 frases) con la referencia exacta del temario.
- Evita preguntas triviales o duplicadas.
- Devuelve SOLO un array JSON, sin markdown, sin comentarios.

FORMATO EXACTO:
[
  {{
    "question": "afirmación a juzgar",
    "correct": true,
    "explanation": "breve justificación citando el temario"
  }}
]

TEMARIO:
\"\"\"
{source_text}
\"\"\"
"""
    elif question_type == "dev":
        user_prompt = f"""A partir del siguiente temario del tema "{topic_name}", \
genera exactamente {num_questions} preguntas de DESARROLLO (respuesta abierta).

REGLAS ESTRICTAS:
- Cada pregunta debe requerir una respuesta elaborada de 3-6 frases.
- Las preguntas deben cubrir conceptos clave del temario.
- Proporciona una respuesta modelo completa basada LITERALMENTE en el temario.
- Incluye los puntos clave que debe mencionar el alumno.
- Evita preguntas duplicadas o triviales.
- Devuelve SOLO un array JSON, sin markdown, sin comentarios.

FORMATO EXACTO:
[
  {{
    "question": "pregunta de desarrollo",
    "model_answer": "respuesta modelo completa con los puntos clave",
    "key_points": ["punto 1", "punto 2", "punto 3"]
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
- Solo UNA opción es correcta. Las demás deben ser plausibles pero incorrectas según el temario.
- Las preguntas y respuestas deben usar el vocabulario y términos EXACTOS del temario.
- Las opciones incorrectas deben basarse en datos reales del temario pero modificando algún detalle.
- Varía la dificultad y los conceptos cubiertos.
- Incluye una explicación breve (1-2 frases) citando el texto del temario.
- Evita preguntas triviales o duplicadas.
- Devuelve SOLO un array JSON, sin markdown, sin comentarios.

FORMATO EXACTO:
[
  {{
    "question": "texto de la pregunta",
    "options": [{', '.join([f'"opción {chr(65 + i)}"' for i in range(n)])}],
    "correct_index": 0,
    "explanation": "breve justificación citando el temario"
  }}
]

TEMARIO:
\"\"\"
{source_text}
\"\"\"
"""
    return system_msg, user_prompt


def _parse_llm_response(raw: str, question_type: str, num_options: int) -> List[dict]:
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
                "model_answer": "",
            })
    elif question_type == "dev":
        for q in data:
            if not isinstance(q, dict):
                continue
            text = str(q.get("question", "")).strip()
            model_answer = str(q.get("model_answer", "")).strip()
            key_points = q.get("key_points", [])
            if not text or not model_answer:
                continue
            cleaned.append({
                "question": text,
                "options": [],
                "correct_index": 0,
                "explanation": "; ".join(key_points) if key_points else "",
                "question_type": "dev",
                "num_options": 0,
                "model_answer": model_answer,
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
                "model_answer": "",
            })
    return cleaned


def _log_gemini_usage(operation: str, response) -> None:
    """Loguea (INFO) el consumo de tokens de una respuesta de Gemini, etiquetado
    por tipo de operación, para poder dimensionar límites y coste real. El SDK
    google-genai expone response.usage_metadata (prompt/candidates/total token
    count). Solo logging; nunca debe romper la petición."""
    try:
        um = getattr(response, "usage_metadata", None)
        if um is None:
            logger.info("[GEMINI-USAGE] op=%s tokens=unavailable model=%s", operation, GEMINI_MODEL)
            return
        # thoughts_token_count = tokens de razonamiento (thinking) de
        # gemini-2.5-flash; explican el descuadre in+out vs total.
        logger.info(
            "[GEMINI-USAGE] op=%s in=%s out=%s thoughts=%s total=%s model=%s",
            operation,
            getattr(um, "prompt_token_count", None),
            getattr(um, "candidates_token_count", None),
            getattr(um, "thoughts_token_count", None),
            getattr(um, "total_token_count", None),
            GEMINI_MODEL,
        )
    except Exception as e:  # pragma: no cover - el logging jamás debe fallar la petición
        logger.warning("[GEMINI-USAGE] op=%s no se pudo leer usage_metadata: %s", operation, e)


async def _call_gemini(system_msg: str, user_prompt: str) -> str:
    logger.info("[LLM-CALL] provider=gemini model=%s prompt_chars=%s", GEMINI_MODEL, len(user_prompt))
    if gemini_client is None:
        raise RuntimeError("GEMINI_API_KEY no configurada — gemini_client es None")
    try:
        response = await gemini_client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_msg,
                response_mime_type="application/json",
                temperature=0.7,
            ),
        )
        _log_gemini_usage("generate_questions", response)
        text = response.text or ""
    except Exception as e:
        logger.error("[LLM-CALL-FAIL] provider=gemini exc=%s detail=%s", type(e).__name__, str(e)[:500])
        raise
    logger.info("[LLM-CALL-OK] provider=gemini response_chars=%s", len(text))
    return text


async def _generate_batch(
    topic_name: str,
    source_text: str,
    num_questions: int,
    question_type: str,
    num_options: int,
    custom_instructions: str = "",
) -> List[dict]:
    import asyncio as _asyncio
    system_msg, user_prompt = _build_prompts(
        topic_name, source_text, num_questions, question_type, num_options, custom_instructions
    )

    last_err: Optional[Exception] = None
    attempts = 5
    for attempt in range(attempts):
        try:
            resp = await _call_gemini(system_msg, user_prompt)
            parsed = _parse_llm_response(resp, question_type, num_options)
            if parsed:
                logger.info("[LLM-PARSED] provider=gemini questions=%s", len(parsed))
                return parsed
            logger.warning("[LLM-PARSE-EMPTY] attempt=%s/%s — parsed 0 questions", attempt + 1, attempts)
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            is_transient = any(
                k in msg for k in (
                    "429", "500", "502", "503", "504", "deadline",
                    "timeout", "unavailable", "internal", "resource exhausted",
                    "connection",
                )
            )
            logger.warning(
                "[LLM-RETRY] attempt=%s/%s transient=%s detail=%s",
                attempt + 1, attempts, is_transient, str(e)[:300],
            )
            if not is_transient and attempt == 0:
                break
        await _asyncio.sleep(min(8, 1.5 * (2 ** attempt)))
    if last_err:
        logger.error("[LLM-BATCH-FAIL] Gemini exhausted. Last error: %s", str(last_err)[:500])
    return []


async def generate_questions_with_claude(
    topic_name: str,
    source_text: str,
    num_questions: int,
    question_type: str = "mcq",
    num_options: int = 3,
    custom_instructions: str = "",
) -> List[dict]:
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY no configurada")

    max_chars = 120_000
    if len(source_text) > max_chars:
        source_text = source_text[:max_chars]

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
        items = await _generate_batch(topic_name, source_text, batch_n, question_type, num_options, custom_instructions)
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
    return all_questions


# Evaluate a development answer using Gemini
async def evaluate_dev_answer(question: str, model_answer: str, user_answer: str, key_points: str) -> dict:
    """Use Gemini to evaluate a development answer and return score + feedback."""
    if not GEMINI_API_KEY or gemini_client is None:
        return {"score": 0, "feedback": "IA no disponible para evaluar", "key_points_covered": [], "_ai_error": True}

    system_msg = (
        "Eres un corrector experto. Evalúa la respuesta del alumno comparándola con la respuesta modelo. "
        "Sé justo y constructivo. Responde SOLO con JSON válido."
    )
    prompt = f"""Evalúa esta respuesta de desarrollo:

PREGUNTA: {question}

RESPUESTA MODELO: {model_answer}

PUNTOS CLAVE ESPERADOS: {key_points}

RESPUESTA DEL ALUMNO: {user_answer}

Devuelve SOLO este JSON:
{{
  "score": <número del 0 al 10>,
  "feedback": "<retroalimentación constructiva de 2-3 frases>",
  "key_points_covered": ["<puntos que ha mencionado>"],
  "key_points_missing": ["<puntos que faltan>"]
}}"""

    try:
        response = await gemini_client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_msg,
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
        _log_gemini_usage("eval_dev", response)
        raw = _strip_code_fences(response.text or "")
        result = json.loads(raw)
        return result
    except Exception as e:
        logger.error("Dev answer eval error: %s", e)
        return {"score": 0, "feedback": "Error al evaluar", "key_points_covered": [], "key_points_missing": [], "_ai_error": True}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Auth dependency (definida pronto porque TODOS los endpoints de datos la usan
# como Depends en sus argumentos; debe existir antes de declararlos).
# ---------------------------------------------------------------------------
async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """Lee el Bearer token de la cabecera Authorization, lo valida y devuelve el usuario.
    Responde 401 si falta o es inválido."""
    cred_exc = HTTPException(
        status_code=401,
        detail="No autenticado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if creds is None or not creds.credentials:
        raise cred_exc
    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail="JWT_SECRET no configurada en el servidor")
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise cred_exc
    user_id = payload.get("sub")
    if not user_id:
        raise cred_exc
    user = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if user is None:
        raise cred_exc
    return user


# ---------------------------------------------------------------------------
# Límites de uso de IA — cuota mensual por usuario
# ---------------------------------------------------------------------------
def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    """Parsea una fecha ISO; devuelve None si falta o es inválida.
    Normaliza a UTC si viene sin tzinfo."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# Dos contadores independientes que comparten el MISMO periodo (ciclo unificado):
# - "generation": crear material (preguntas, flashcards, resúmenes).
# - "correction": evaluar respuestas de desarrollo (eval-dev / eval-dev-batch).
# Campo del contador por tipo; el periodo es siempre `ai_period_start`.
_QUOTA_FIELD = {"generation": "ai_generations_used", "correction": "ai_corrections_used"}

# Sub-contador de "crear material" por tipo de generación. La suma de los tres es
# SIEMPRE == ai_generations_used (invariante). Todos se reinician con el ciclo.
_GEN_SUBFIELD = {
    "questions": "ai_gen_questions_used",
    "summaries": "ai_gen_summaries_used",
    "flashcards": "ai_gen_flashcards_used",
}
# Sub-contadores a reiniciar junto al agregado al expirar el periodo.
_GEN_RESET = {f: 0 for f in _GEN_SUBFIELD.values()}


def _ai_limit(plan: Optional[str], kind: str) -> int:
    """Límite por periodo según plan y tipo de cuota (generación/corrección)."""
    premium = plan == "premium"
    if kind == "correction":
        return PREMIUM_AI_CORRECTIONS_PER_MONTH if premium else FREE_AI_CORRECTIONS_PER_MONTH
    return PREMIUM_AI_GENERATIONS_PER_MONTH if premium else FREE_AI_GENERATIONS_PER_MONTH


# Retrocompat: algunos sitios/tests podían llamar al límite de generaciones.
def _ai_limit_for_plan(plan: Optional[str]) -> int:
    return _ai_limit(plan, "generation")


async def check_and_consume_ai_quota(
    user: dict, kind: str = "generation", cost: int = 1, gen_kind: Optional[str] = None
) -> dict:
    """Comprueba el plan y la cuota del usuario para `kind` y consume `cost`.

    Ciclo unificado: ambos contadores comparten `ai_period_start`. Al expirar el
    periodo se reinician LOS DOS a 0 (una sola fecha de reinicio para el usuario),
    antes de comprobar el límite. Si used+cost supera el límite del tipo → 402
    (mensaje diferenciado). Si pasa, incrementa el contador del tipo de forma
    atómica ($inc) y devuelve {used, limit, remaining, period_start, plan, kind}.

    Desglose por tipo: cuando `kind == "generation"`, `gen_kind` es OBLIGATORIO
    (∈ {questions, summaries, flashcards}). El mismo $inc que sube el agregado
    sube su sub-contador, así la invariante suma==agregado se mantiene siempre.
    La validación va ANTES de cualquier $inc: un fallo de programación (gen_kind
    ausente/erróneo) NO deja cuota consumida a medias.

    OBLIGATORIO: invocar antes de CUALQUIER llamada a Gemini.
    """
    uid = user["id"]
    plan = user.get("plan", "free")
    field = _QUOTA_FIELD[kind]
    limit = _ai_limit(plan, kind)

    # Guardia de invariante: valida el tipo ANTES de tocar la cuota.
    subfield = None
    if kind == "generation":
        if gen_kind not in _GEN_SUBFIELD:
            raise ValueError(
                f"gen_kind obligatorio para kind='generation' (∈ {set(_GEN_SUBFIELD)}), recibido: {gen_kind!r}"
            )
        subfield = _GEN_SUBFIELD[gen_kind]

    now = datetime.now(timezone.utc)
    used = int(user.get(field, 0) or 0)
    period_start = _parse_iso(user.get("ai_period_start"))

    # Reinicio unificado del periodo (o si nunca se inicializó): AMBOS contadores y
    # los sub-contadores de desglose a 0, en la misma operación.
    if period_start is None or (now - period_start) >= timedelta(days=AI_PERIOD_DAYS):
        used = 0
        period_start = now
        await db.users.update_one(
            {"id": uid},
            {"$set": {
                "ai_generations_used": 0, "ai_corrections_used": 0,
                "ai_period_start": now.isoformat(), **_GEN_RESET,
            }},
        )

    if used + cost > limit:
        # Etiqueta de cara al usuario (coherente con la UI "Crear material").
        detalle = "correcciones" if kind == "correction" else "crear material"
        raise HTTPException(
            status_code=402,
            detail=f"Has alcanzado el límite de {detalle} con IA de este mes para tu plan",
        )

    # Consumo atómico: agregado + sub-contador del tipo en un solo $inc.
    inc = {field: cost}
    if subfield:
        inc[subfield] = cost
    await db.users.update_one({"id": uid}, {"$inc": inc})
    new_used = used + cost
    return {
        "used": new_used,
        "limit": limit,
        "remaining": max(0, limit - new_used),
        "period_start": period_start.isoformat(),
        "plan": plan,
        "kind": kind,
    }


async def _refund_ai_quota(
    user: dict, kind: str = "generation", cost: int = 1, gen_kind: Optional[str] = None
) -> None:
    """Revierte un consumo previo del contador `kind` (p. ej. si Gemini falló).
    No debe penalizarse al usuario por un fallo nuestro. Para generaciones, pasa el
    mismo `gen_kind` que en el consumo: decrementa agregado y sub-contador juntos
    (misma op) para no romper la invariante."""
    inc = {_QUOTA_FIELD[kind]: -cost}
    if kind == "generation" and gen_kind in _GEN_SUBFIELD:
        inc[_GEN_SUBFIELD[gen_kind]] = -cost
    try:
        await db.users.update_one({"id": user["id"]}, {"$inc": inc})
    except Exception as e:  # pragma: no cover - best effort
        logger.error("No se pudo revertir la cuota (%s) del usuario %s: %s", kind, user.get("id"), e)


# ---------------------------------------------------------------------------
# Pagos / Suscripción (Paddle Billing v4)
# ---------------------------------------------------------------------------
# El plan "premium" se deriva SIEMPRE del estado de la suscripción (única fuente
# de verdad). No se escribe plan="premium" a mano en ningún otro sitio.
_PREMIUM_STATUSES = ("active", "trialing")


def _plan_for_subscription_status(status: Optional[str]) -> str:
    """Deriva el plan ('premium'/'free') a partir del estado de la suscripción."""
    return "premium" if status in _PREMIUM_STATUSES else "free"


def _is_premium_active(user: dict) -> bool:
    return user.get("subscription_status") in _PREMIUM_STATUSES


def _verify_paddle_signature(raw_body: bytes, signature_header: str, secret: str) -> bool:
    """Verifica la firma de un webhook de Paddle Billing v4.

    La cabecera 'Paddle-Signature' tiene el formato 'ts=<unix>;h1=<hmac_hex>'.
    Se calcula HMAC-SHA256 de '<ts>:<raw_body>' usando el secret del conjunto de
    notificaciones (pdl_ntfset_...) y se compara con h1 en tiempo constante.
    """
    if not secret or not signature_header:
        return False
    parts: dict = {}
    for seg in signature_header.split(";"):
        if "=" in seg:
            k, v = seg.split("=", 1)
            parts[k.strip()] = v.strip()
    ts = parts.get("ts")
    h1 = parts.get("h1")
    if not ts or not h1:
        return False
    signed_payload = f"{ts}:".encode("utf-8") + raw_body
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, h1)


def _extract_customer_email(data: dict) -> Optional[str]:
    """Extrae el email del cliente SI viene embebido en el payload de Paddle.

    En Paddle Billing v4 el email del cliente está en data.customer.email (objeto
    customer anidado). Comprobamos también otras ubicaciones por robustez. OJO: en
    muchos eventos subscription.* el objeto customer NO viene (solo customer_id);
    en ese caso hay que resolverlo vía API (ver _resolve_customer_email)."""
    if not isinstance(data, dict):
        return None
    customer = data.get("customer") if isinstance(data.get("customer"), dict) else {}
    custom = data.get("custom_data") if isinstance(data.get("custom_data"), dict) else {}
    billing = data.get("billing_details") if isinstance(data.get("billing_details"), dict) else {}
    for c in (customer.get("email"), data.get("customer_email"), custom.get("email"), billing.get("email")):
        if c:
            return str(c)
    return None


def _extract_custom_user_id(data: dict) -> Optional[str]:
    """Extrae el user_id que inyectamos en custom_data del checkout.

    Devuelve un string no vacío o None. NO confía en el valor: la existencia real
    del usuario en `users` se verifica aparte con un find_one. El webhook ya validó
    la firma de Paddle antes de llegar aquí, pero validamos el campo igualmente."""
    if not isinstance(data, dict):
        return None
    custom = data.get("custom_data")
    if not isinstance(custom, dict):
        return None
    uid = custom.get("user_id")
    if isinstance(uid, str) and uid.strip():
        return uid.strip()
    return None


# Caché en memoria customer_id -> email para no llamar a la API de Paddle en cada evento.
_paddle_customer_email_cache: dict = {}


def _paddle_api_base() -> str:
    """Base de la API de Paddle según el entorno (sandbox/production)."""
    return "https://sandbox-api.paddle.com" if PADDLE_ENV == "sandbox" else "https://api.paddle.com"


async def _fetch_paddle_customer_email(customer_id: str) -> Optional[str]:
    """Resuelve el email de un cliente llamando a GET /customers/{id} de Paddle.
    Cachea el resultado. Devuelve None (con log) si no se puede resolver."""
    if not customer_id:
        return None
    if customer_id in _paddle_customer_email_cache:
        return _paddle_customer_email_cache[customer_id]
    if not PADDLE_API_KEY:
        logger.warning(
            "[PADDLE] no se puede resolver email: PADDLE_API_KEY no configurada (customer_id=%s)", customer_id
        )
        return None
    url = f"{_paddle_api_base()}/customers/{customer_id}"
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(url, headers={"Authorization": f"Bearer {PADDLE_API_KEY}"})
    except Exception as e:
        logger.warning("[PADDLE] error consultando customer %s: %s", customer_id, e)
        return None
    if resp.status_code != 200:
        logger.warning(
            "[PADDLE] GET /customers/%s devolvió HTTP %s: %s", customer_id, resp.status_code, resp.text[:300]
        )
        return None
    try:
        email = (resp.json().get("data") or {}).get("email")
    except Exception as e:
        logger.warning("[PADDLE] respuesta no-JSON al resolver customer %s: %s", customer_id, e)
        return None
    if email:
        _paddle_customer_email_cache[customer_id] = email
        logger.debug("[PADDLE] email resuelto vía API para customer_id=%s: %s", customer_id, email)
    else:
        logger.warning("[PADDLE] API de Paddle devolvió email vacío para customer_id=%s", customer_id)
    return email


async def _resolve_customer_email(data: dict) -> Optional[str]:
    """Obtiene el email del cliente: primero del payload, si no vía API por customer_id."""
    email = _extract_customer_email(data)
    if email:
        logger.debug("[PADDLE] email obtenido del payload (data.customer.email): %s", email)
        return email
    customer_id = data.get("customer_id") if isinstance(data, dict) else None
    logger.debug(
        "[PADDLE] email no venía en el payload; resolviendo vía API "
        "customer_id=%s PADDLE_API_KEY_present=%s",
        customer_id, bool(PADDLE_API_KEY),
    )
    if customer_id:
        return await _fetch_paddle_customer_email(customer_id)
    return None


async def _create_paddle_portal_session(customer_id: str, subscription_id: Optional[str]) -> dict:
    """Crea una sesión de customer portal en Paddle y devuelve el objeto `data`.

    La sesión se genera bajo demanda y NUNCA se cachea (son de un solo uso). Lanza
    HTTPException con un detalle claro y logueable (nunca un 500 opaco) si la API
    de Paddle no está configurada, falla, o rechaza por permisos (403)."""
    if not PADDLE_API_KEY:
        logger.warning("[PADDLE] portal-sessions: PADDLE_API_KEY no configurada")
        raise HTTPException(status_code=502, detail="La integración de pagos no está configurada en el servidor")
    url = f"{_paddle_api_base()}/customers/{customer_id}/portal-sessions"
    body: dict = {"subscription_ids": [subscription_id]} if subscription_id else {}
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(url, headers={"Authorization": f"Bearer {PADDLE_API_KEY}"}, json=body)
    except Exception as e:
        logger.warning("[PADDLE] portal-sessions error de red customer=%s: %s", customer_id, e)
        raise HTTPException(status_code=502, detail="No se pudo contactar con Paddle. Inténtalo de nuevo.") from e

    if resp.status_code == 403:
        logger.warning(
            "[PADDLE] portal-sessions 403 (¿falta el permiso 'Customer portal sessions (Write)' en la API key?) "
            "customer=%s body=%s", customer_id, resp.text[:300],
        )
        raise HTTPException(status_code=502, detail="No se pudo abrir el portal de gestión (permisos de Paddle)")
    if resp.status_code not in (200, 201):
        logger.warning(
            "[PADDLE] portal-sessions HTTP %s customer=%s body=%s", resp.status_code, customer_id, resp.text[:300]
        )
        raise HTTPException(status_code=502, detail="No se pudo abrir el portal de gestión de la suscripción")
    try:
        return resp.json().get("data") or {}
    except Exception as e:
        logger.warning("[PADDLE] portal-sessions respuesta no-JSON customer=%s: %s", customer_id, e)
        raise HTTPException(status_code=502, detail="Respuesta inesperada de Paddle") from e


def _extract_portal_url(portal_data: dict, subscription_id: Optional[str]) -> Optional[str]:
    """Del objeto `data` de portal-sessions, extrae el deep link para CANCELAR la
    suscripción; si no lo hay, cae al overview general del portal."""
    urls = portal_data.get("urls") if isinstance(portal_data, dict) else None
    if not isinstance(urls, dict):
        return None
    # Deep link por suscripción (cancelar). Preferimos la del subscription_id del
    # usuario; si no coincide, la primera que traiga cancel_subscription.
    subs = urls.get("subscriptions")
    if isinstance(subs, list):
        chosen = None
        for s in subs:
            if not isinstance(s, dict) or not s.get("cancel_subscription"):
                continue
            if subscription_id and s.get("id") == subscription_id:
                return s["cancel_subscription"]
            if chosen is None:
                chosen = s["cancel_subscription"]
        if chosen:
            return chosen
    # Fallback: overview general del portal.
    general = urls.get("general")
    if isinstance(general, dict) and general.get("overview"):
        return general["overview"]
    return None


async def _apply_paddle_event(user: dict, event_type: str, data: dict) -> None:
    """Aplica el efecto de un evento de Paddle al documento del usuario."""
    updates: dict = {}

    if event_type and event_type.startswith("subscription."):
        # El estado real viene en data.status (active|trialing|canceled|past_due|...).
        status = data.get("status") or ("canceled" if event_type == "subscription.canceled" else "active")
        updates["subscription_status"] = status
        updates["plan"] = _plan_for_subscription_status(status)
        if data.get("id"):
            updates["paddle_subscription_id"] = data["id"]
        if data.get("customer_id"):
            updates["paddle_customer_id"] = data["customer_id"]
        period_end = (data.get("current_billing_period") or {}).get("ends_at")
        if period_end:
            updates["subscription_current_period_end"] = period_end
        # Cambio programado (cancelación a fin de periodo, etc.). Se guarda SIEMPRE
        # en eventos subscription.* — incluido None — para reflejar una baja
        # programada y también LIMPIARLA si el usuario reactiva la suscripción.
        updates["subscription_scheduled_change"] = data.get("scheduled_change") or None
        logger.debug(
            "[PADDLE] _apply_paddle_event type=%s status=%s -> plan=%s scheduled_change=%s user_id=%s",
            event_type, status, updates.get("plan"), updates.get("subscription_scheduled_change"), user["id"],
        )

    elif event_type == "transaction.completed":
        # Solo informativo: guardamos ids si vienen, sin decidir el plan.
        if data.get("customer_id"):
            updates["paddle_customer_id"] = data["customer_id"]
        if data.get("subscription_id"):
            updates["paddle_subscription_id"] = data["subscription_id"]
        logger.debug(
            "[PADDLE] _apply_paddle_event type=%s (informativo, no cambia plan) user_id=%s",
            event_type, user["id"],
        )

    if updates:
        result = await db.users.update_one({"id": user["id"]}, {"$set": updates})
        logger.debug(
            "[PADDLE] update Mongo user_id=%s fields=%s matched=%s modified=%s",
            user["id"], list(updates.keys()), result.matched_count, result.modified_count,
        )
    else:
        logger.debug(
            "[PADDLE] evento sin cambios que aplicar type=%s user_id=%s", event_type, user["id"]
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@api.get("/")
async def root():
    return {"app": "Study App", "status": "ok"}


@api.get("/diag/llm")
async def diag_llm():
    return {
        "provider": "gemini",
        "model": GEMINI_MODEL,
        "GEMINI_API_KEY_present": bool(GEMINI_API_KEY),
    }


@api.post("/diag/llm-test")
async def diag_llm_test():
    if gemini_client is None:
        return {"ok": False, "detail": "GEMINI_API_KEY not configured"}
    try:
        resp = await gemini_client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents="Responde con la palabra exacta: OK",
        )
        text = resp.text or ""
        return {"ok": True, "model": GEMINI_MODEL, "response_head": text[:80]}
    except Exception as e:
        return {
            "ok": False,
            "model": GEMINI_MODEL,
            "exc_type": type(e).__name__,
            "detail": str(e)[:400],
        }


# ---- Subjects ----
@api.get("/subjects")
async def list_subjects(current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    subjects = await db.subjects.find({"user_id": uid}, {"_id": 0}).sort("created_at", 1).to_list(1000)
    for s in subjects:
        s["topic_count"] = await db.topics.count_documents({"user_id": uid, "subject_id": s["id"]})
        s["question_count"] = await db.questions.count_documents({"user_id": uid, "subject_id": s["id"]})
        agg = await db.questions.aggregate([
            {"$match": {"user_id": uid, "subject_id": s["id"]}},
            {"$group": {"_id": None, "ans": {"$sum": "$times_answered"}, "ok": {"$sum": "$times_correct"}}},
        ]).to_list(1)
        s["accuracy"] = round(100 * agg[0]["ok"] / agg[0]["ans"], 1) if agg and agg[0]["ans"] else 0.0
    return subjects


class SubjectCreate(BaseModel):
    name: str
    color: Optional[str] = None


@api.post("/subjects")
async def create_subject(req: SubjectCreate, current_user: dict = Depends(get_current_user)):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nombre vacío")
    color = req.color or random.choice(SUBJECT_COLORS)
    s = Subject(user_id=current_user["id"], name=name, color=color)
    await db.subjects.insert_one(s.model_dump())
    return s.model_dump()


@api.get("/subjects/{subject_id}")
async def get_subject(subject_id: str, current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    s = await db.subjects.find_one({"id": subject_id, "user_id": uid}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Asignatura no encontrada")
    s["topic_count"] = await db.topics.count_documents({"user_id": uid, "subject_id": subject_id})
    s["question_count"] = await db.questions.count_documents({"user_id": uid, "subject_id": subject_id})
    return s


class SubjectUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


@api.patch("/subjects/{subject_id}")
async def update_subject(subject_id: str, req: SubjectUpdate, current_user: dict = Depends(get_current_user)):
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="Nada que actualizar")
    res = await db.subjects.update_one({"id": subject_id, "user_id": current_user["id"]}, {"$set": fields})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Asignatura no encontrada")
    return {"ok": True}


@api.delete("/subjects/{subject_id}")
async def delete_subject(subject_id: str, current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    topic_ids = [t["id"] async for t in db.topics.find({"subject_id": subject_id, "user_id": uid}, {"_id": 0, "id": 1})]
    # PDFs afectados (de todos los temas de la asignatura) ANTES de borrar vínculos.
    pdf_ids: set = set()
    for tid in topic_ids:
        pdf_ids.update(await _topic_pdf_ids(uid, tid))
    res = await db.subjects.delete_one({"id": subject_id, "user_id": uid})
    await db.topics.delete_many({"subject_id": subject_id, "user_id": uid})
    await db.questions.delete_many({"subject_id": subject_id, "user_id": uid})
    if topic_ids:
        await db.pdf_links.delete_many({"user_id": uid, "topic_id": {"$in": topic_ids}})
    # Borra cada PDF SOLO si quedó huérfano (podría seguir vinculado a otro tema
    # fuera de esta asignatura).
    for pid in pdf_ids:
        await _delete_pdf_if_orphan(uid, pid)
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Asignatura no encontrada")
    return {"ok": True}


async def _counts_by_type(uid: str, topic_ids: Optional[List[str]] = None) -> dict:
    """Preguntas por tema desglosadas por tipo, en UNA agregación.
    Devuelve { topic_id: {"mcq": n, "tf": n, "dev": n} }. Lo usa QuizSetup para
    mostrar disponibilidad por tipo y no proponer un examen dev que no existe."""
    match: dict = {"user_id": uid}
    if topic_ids is not None:
        match["topic_id"] = {"$in": topic_ids}
    rows = await db.questions.aggregate([
        {"$match": match},
        {"$group": {"_id": {"topic_id": "$topic_id", "qt": "$question_type"}, "n": {"$sum": 1}}},
    ]).to_list(None)
    out: dict = {}
    for r in rows:
        tid = r["_id"]["topic_id"]
        qt = r["_id"]["qt"]
        d = out.setdefault(tid, {"mcq": 0, "tf": 0, "dev": 0})
        if qt in d:
            d[qt] += r["n"]
    return out


@api.get("/subjects/{subject_id}/topics")
async def list_topics_for_subject(subject_id: str, current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    s = await db.subjects.find_one({"id": subject_id, "user_id": uid}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Asignatura no encontrada")
    topics = await db.topics.find({"subject_id": subject_id, "user_id": uid}, {"_id": 0}).sort("created_at", 1).to_list(1000)
    cbt = await _counts_by_type(uid, [t["id"] for t in topics])
    for t in topics:
        t["question_count"] = await db.questions.count_documents({"user_id": uid, "topic_id": t["id"]})
        t["answered_count"] = await db.questions.count_documents({"user_id": uid, "topic_id": t["id"], "times_answered": {"$gt": 0}})
        agg = await db.questions.aggregate([
            {"$match": {"user_id": uid, "topic_id": t["id"]}},
            {"$group": {"_id": None, "ans": {"$sum": "$times_answered"}, "ok": {"$sum": "$times_correct"}}},
        ]).to_list(1)
        t["accuracy"] = round(100 * agg[0]["ok"] / agg[0]["ans"], 1) if agg and agg[0]["ans"] else 0.0
        t["pdf_count"] = len(await _topic_pdf_ids(uid, t["id"]))
        t["counts_by_type"] = cbt.get(t["id"], {"mcq": 0, "tf": 0, "dev": 0})
    return topics


# ---- Topics ----
@api.get("/topics")
async def list_topics(current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    topics = await db.topics.find({"user_id": uid}, {"_id": 0}).sort("created_at", 1).to_list(2000)
    cbt = await _counts_by_type(uid, [t["id"] for t in topics])
    for t in topics:
        t["question_count"] = await db.questions.count_documents({"user_id": uid, "topic_id": t["id"]})
        t["answered_count"] = await db.questions.count_documents({"user_id": uid, "topic_id": t["id"], "times_answered": {"$gt": 0}})
        agg = await db.questions.aggregate([
            {"$match": {"user_id": uid, "topic_id": t["id"]}},
            {"$group": {"_id": None, "ans": {"$sum": "$times_answered"}, "ok": {"$sum": "$times_correct"}}},
        ]).to_list(1)
        t["accuracy"] = round(100 * agg[0]["ok"] / agg[0]["ans"], 1) if agg and agg[0]["ans"] else 0.0
        t["counts_by_type"] = cbt.get(t["id"], {"mcq": 0, "tf": 0, "dev": 0})
    return topics


@api.get("/topics/{topic_id}")
async def get_topic(topic_id: str, current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    t = await db.topics.find_one({"id": topic_id, "user_id": uid}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    t["question_count"] = await db.questions.count_documents({"user_id": uid, "topic_id": topic_id})
    t["pdf_count"] = len(await _topic_pdf_ids(uid, topic_id))
    agg = await db.questions.aggregate([
        {"$match": {"user_id": uid, "topic_id": topic_id}},
        {"$group": {"_id": None, "ans": {"$sum": "$times_answered"}, "ok": {"$sum": "$times_correct"}}},
    ]).to_list(1)
    t["accuracy"] = round(100 * agg[0]["ok"] / agg[0]["ans"], 1) if agg and agg[0]["ans"] else 0.0
    if t.get("subject_id"):
        s = await db.subjects.find_one({"id": t["subject_id"], "user_id": uid}, {"_id": 0})
        t["subject"] = s
    return t


@api.get("/topics/{topic_id}/text")
async def get_topic_text(topic_id: str, current_user: dict = Depends(get_current_user)):
    """Return combined PDF text for a topic (used in study mode with temario visible)."""
    uid = current_user["id"]
    topic = await db.topics.find_one({"id": topic_id, "user_id": uid}, {"_id": 0})
    if not topic:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    pdf_ids = await _topic_pdf_ids(uid, topic_id)
    pdfs = await db.pdfs.find({"id": {"$in": pdf_ids}, "user_id": uid}, {"_id": 0}).to_list(100)
    if not pdfs:
        raise HTTPException(status_code=404, detail="No hay PDFs para este tema")
    parts = []
    for p in pdfs:
        parts.append(f"=== {p['filename']} ===\n{p['text']}")
    return {"topic_id": topic_id, "text": "\n\n".join(parts), "sources": [p["filename"] for p in pdfs]}


class CreateTopicReq(BaseModel):
    name: str


@api.post("/subjects/{subject_id}/topics")
async def create_topic(
    subject_id: str,
    req: CreateTopicReq,
    current_user: dict = Depends(get_current_user),
):
    """Crea un tema VACÍO (sin PDF). No llama a Gemini → no consume cuota.
    Los PDFs y la generación de preguntas se añaden luego dentro del tema."""
    uid = current_user["id"]
    subj = await db.subjects.find_one({"id": subject_id, "user_id": uid}, {"_id": 0})
    if not subj:
        raise HTTPException(status_code=404, detail="Asignatura no encontrada")
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="El nombre del tema es obligatorio")
    topic = Topic(user_id=uid, subject_id=subject_id, name=name)
    await db.topics.insert_one(topic.model_dump())
    return topic.model_dump()


@api.delete("/topics/{topic_id}")
async def delete_topic(topic_id: str, current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    # PDFs afectados ANTES de borrar los vínculos (para el chequeo de orfandad).
    pdf_ids = await _topic_pdf_ids(uid, topic_id)
    res = await db.topics.delete_one({"id": topic_id, "user_id": uid})
    await db.questions.delete_many({"topic_id": topic_id, "user_id": uid})
    await db.pdf_links.delete_many({"user_id": uid, "topic_id": topic_id})
    # Borra cada PDF SOLO si ya no le queda ningún vínculo (huérfano).
    for pid in pdf_ids:
        await _delete_pdf_if_orphan(uid, pid)
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    return {"ok": True}


@api.get("/topics/{topic_id}/questions")
async def topic_questions(topic_id: str, current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    topic = await db.topics.find_one({"id": topic_id, "user_id": uid}, {"_id": 0})
    if not topic:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    qs = await db.questions.find({"topic_id": topic_id, "user_id": uid}, {"_id": 0}).sort("created_at", 1).to_list(5000)
    return qs


# ---- PDF sources ----
# Helpers de la relación muchos-a-muchos PDF<->tema (colección pdf_links).
async def _topic_pdf_ids(uid: str, topic_id: str) -> List[str]:
    """IDs de los PDFs asociados a un tema, leídos de pdf_links (única fuente)."""
    links = await db.pdf_links.find(
        {"user_id": uid, "topic_id": topic_id}, {"_id": 0, "pdf_id": 1}
    ).to_list(1000)
    return [l["pdf_id"] for l in links]


async def _link_pdf_to_topic(uid: str, pdf_id: str, topic_id: str, subject_id: Optional[str]) -> None:
    """Asocia (idempotente) un PDF a un tema creando una pdf_link si no existe."""
    link = PdfLink(user_id=uid, pdf_id=pdf_id, topic_id=topic_id, subject_id=subject_id)
    await db.pdf_links.update_one(
        {"user_id": uid, "pdf_id": pdf_id, "topic_id": topic_id},
        {"$setOnInsert": link.model_dump()},
        upsert=True,
    )


async def _delete_pdf_if_orphan(uid: str, pdf_id: str) -> bool:
    """Borra el documento `pdfs` SOLO si no le queda ninguna pdf_link (huérfano).
    Devuelve True si lo borró. No toca las preguntas (las gestiona el llamador)."""
    remaining = await db.pdf_links.count_documents({"user_id": uid, "pdf_id": pdf_id})
    if remaining == 0:
        await db.pdfs.delete_one({"id": pdf_id, "user_id": uid})
        # El resumen es por PDF: al desaparecer el PDF, se borra con él (sin huérfanos).
        await db.summaries.delete_many({"user_id": uid, "pdf_id": pdf_id})
        return True
    return False


@api.get("/topics/{topic_id}/pdfs")
async def list_topic_pdfs(topic_id: str, current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    topic = await db.topics.find_one({"id": topic_id, "user_id": uid}, {"_id": 0})
    if not topic:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    pdf_ids = await _topic_pdf_ids(uid, topic_id)
    pdfs = await db.pdfs.find(
        {"id": {"$in": pdf_ids}, "user_id": uid}, {"_id": 0, "text": 0}
    ).sort("created_at", 1).to_list(100)
    for p in pdfs:
        p["question_count"] = await db.questions.count_documents({"user_id": uid, "pdf_source_id": p["id"]})
        # link_count: en cuántos temas está este PDF (para el aviso de borrado en la UI).
        p["link_count"] = await db.pdf_links.count_documents({"user_id": uid, "pdf_id": p["id"]})
    return pdfs


@api.get("/pdfs")
async def list_all_pdfs(current_user: dict = Depends(get_current_user)):
    """Biblioteca de PDFs del usuario: todos sus PDFs (sin texto), cada uno con
    link_count (en cuántos temas está) y topic_ids. Alimenta el selector
    'De mi biblioteca' del diálogo de añadir PDF (Fase 2). No es una pantalla."""
    uid = current_user["id"]
    pdfs = await db.pdfs.find({"user_id": uid}, {"_id": 0, "text": 0}).sort("created_at", 1).to_list(2000)
    # Un solo find de vínculos y agrupamos en memoria (evita N consultas).
    links = await db.pdf_links.find({"user_id": uid}, {"_id": 0, "pdf_id": 1, "topic_id": 1}).to_list(10000)
    topics_by_pdf: dict = {}
    for l in links:
        topics_by_pdf.setdefault(l["pdf_id"], []).append(l["topic_id"])
    for p in pdfs:
        tids = topics_by_pdf.get(p["id"], [])
        p["topic_ids"] = tids
        p["link_count"] = len(tids)
        p["question_count"] = await db.questions.count_documents({"user_id": uid, "pdf_source_id": p["id"]})
    return pdfs


@api.post("/pdfs")
async def upload_pdf_to_library(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    """Sube un PDF a la biblioteca del usuario SIN vincularlo a ningún tema (Fase 3).
    Queda con link_count 0 hasta que se asocie a un tema. No llama a Gemini, así que
    no consume cuota de IA."""
    uid = current_user["id"]
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan ficheros PDF")
    pdf_bytes = await file.read()
    try:
        text = extract_pdf_text(pdf_bytes)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al leer el PDF: {e}") from e
    if len(text) < 200:
        raise HTTPException(status_code=400, detail="El PDF no contiene suficiente texto extraíble")
    pdf_source = PdfSource(
        user_id=uid,
        filename=file.filename,
        text=text,
        char_count=len(text),
    )
    await db.pdfs.insert_one(pdf_source.model_dump())
    return {
        "id": pdf_source.id,
        "filename": pdf_source.filename,
        "char_count": pdf_source.char_count,
        "created_at": pdf_source.created_at,
        "question_count": 0,
        "link_count": 0,
        "topic_ids": [],
    }


class RegenerateReq(BaseModel):
    num_questions: int = 10
    question_type: Literal["mcq", "tf", "dev"] = "mcq"
    num_options: int = 3


@api.post("/pdfs/{pdf_id}/regenerate")
async def regenerate_from_pdf(pdf_id: str, req: RegenerateReq, current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    pdf = await db.pdfs.find_one({"id": pdf_id, "user_id": uid}, {"_id": 0})
    if not pdf:
        raise HTTPException(status_code=404, detail="PDF no encontrado")
    # Resolver el tema al que regenerar vía pdf_links (única fuente de la atadura).
    link = await db.pdf_links.find_one({"user_id": uid, "pdf_id": pdf_id}, {"_id": 0, "topic_id": 1})
    resolved_topic_id = link["topic_id"] if link else None
    topic = await db.topics.find_one({"id": resolved_topic_id, "user_id": uid}, {"_id": 0})
    if not topic:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    if req.num_questions < 3 or req.num_questions > 80:
        raise HTTPException(status_code=400, detail="num_questions debe estar entre 3 y 80")

    nopts = max(2, min(5, int(req.num_options))) if req.question_type == "mcq" else 2
    # Comprobar plan + cuota ANTES de llamar a Gemini.
    await check_and_consume_ai_quota(current_user, gen_kind="questions")
    try:
        generated = await generate_questions_with_claude(
            topic["name"], pdf["text"], req.num_questions, question_type=req.question_type, num_options=nopts
        )
    except Exception:
        await _refund_ai_quota(current_user, gen_kind="questions")
        raise
    docs = []
    for g in generated:
        q = Question(
            user_id=uid,
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
            model_answer=g.get("model_answer", ""),
        )
        docs.append(q.model_dump())
    if docs:
        await db.questions.insert_many(docs)
    return {"questions_created": len(docs)}


@api.delete("/pdfs/{pdf_id}")
async def delete_pdf(pdf_id: str, current_user: dict = Depends(get_current_user)):
    """Borra el PDF por completo (de TODOS los temas): elimina sus pdf_links, el
    documento pdfs y desliga sus preguntas."""
    uid = current_user["id"]
    res = await db.pdfs.delete_one({"id": pdf_id, "user_id": uid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="PDF no encontrado")
    await db.pdf_links.delete_many({"user_id": uid, "pdf_id": pdf_id})
    await db.summaries.delete_many({"user_id": uid, "pdf_id": pdf_id})
    await db.questions.update_many({"pdf_source_id": pdf_id, "user_id": uid}, {"$set": {"pdf_source_id": None}})
    return {"ok": True}


@api.post("/topics/{topic_id}/pdfs/upload")
async def add_pdf_to_topic(topic_id: str, file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    topic = await db.topics.find_one({"id": topic_id, "user_id": uid}, {"_id": 0})
    if not topic:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan ficheros PDF")
    pdf_bytes = await file.read()
    try:
        text = extract_pdf_text(pdf_bytes)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al leer el PDF: {e}") from e
    if len(text) < 200:
        raise HTTPException(status_code=400, detail="El PDF no contiene suficiente texto extraíble")
    pdf_source = PdfSource(
        user_id=uid,
        filename=file.filename,
        text=text,
        char_count=len(text),
    )
    await db.pdfs.insert_one(pdf_source.model_dump())
    await _link_pdf_to_topic(uid, pdf_source.id, topic_id, topic.get("subject_id"))
    return {
        "id": pdf_source.id,
        "filename": pdf_source.filename,
        "char_count": pdf_source.char_count,
        "created_at": pdf_source.created_at,
        "question_count": 0,
        "link_count": 1,
    }


@api.post("/topics/{topic_id}/pdfs/{pdf_id}/link")
async def link_existing_pdf(topic_id: str, pdf_id: str, current_user: dict = Depends(get_current_user)):
    """Asocia un PDF ya existente (de la biblioteca del usuario) a un tema, sin
    volver a subirlo. Idempotente. Devuelve el PDF con su question_count/link_count
    para pintarlo en la lista del tema."""
    uid = current_user["id"]
    topic = await db.topics.find_one({"id": topic_id, "user_id": uid}, {"_id": 0})
    if not topic:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    pdf = await db.pdfs.find_one({"id": pdf_id, "user_id": uid}, {"_id": 0, "text": 0})
    if not pdf:
        raise HTTPException(status_code=404, detail="PDF no encontrado")
    await _link_pdf_to_topic(uid, pdf_id, topic_id, topic.get("subject_id"))
    pdf["question_count"] = await db.questions.count_documents({"user_id": uid, "pdf_source_id": pdf_id})
    pdf["link_count"] = await db.pdf_links.count_documents({"user_id": uid, "pdf_id": pdf_id})
    return pdf


@api.delete("/topics/{topic_id}/pdfs/{pdf_id}")
async def unlink_pdf_from_topic(topic_id: str, pdf_id: str, current_user: dict = Depends(get_current_user)):
    """Quita un PDF de un tema (desvincula). NO borra el PDF si sigue vinculado a
    otros temas; si era el último vínculo queda huérfano y se borra, desligando sus
    preguntas (que se conservan, solo pierden la referencia al PDF).

    Devuelve {ok, pdf_deleted}: pdf_deleted indica si el PDF se eliminó por completo
    (era su último tema) o solo se quitó de este."""
    uid = current_user["id"]
    topic = await db.topics.find_one({"id": topic_id, "user_id": uid}, {"_id": 0})
    if not topic:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    res = await db.pdf_links.delete_one({"user_id": uid, "pdf_id": pdf_id, "topic_id": topic_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="El PDF no está en este tema")
    pdf_deleted = await _delete_pdf_if_orphan(uid, pdf_id)
    if pdf_deleted:
        await db.questions.update_many(
            {"user_id": uid, "pdf_source_id": pdf_id}, {"$set": {"pdf_source_id": None}}
        )
    return {"ok": True, "pdf_deleted": pdf_deleted}


class GenerateFromPdfsReq(BaseModel):
    pdf_ids: List[str]
    num_questions: int = 10
    question_type: Literal["mcq", "tf", "dev"] = "mcq"
    num_options: int = 3
    custom_instructions: Optional[str] = None


@api.post("/topics/{topic_id}/generate")
async def generate_from_topic_pdfs(topic_id: str, req: GenerateFromPdfsReq, current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    topic = await db.topics.find_one({"id": topic_id, "user_id": uid}, {"_id": 0})
    if not topic:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    if not req.pdf_ids:
        raise HTTPException(status_code=400, detail="Selecciona al menos un PDF")
    if req.num_questions < 3 or req.num_questions > 80:
        raise HTTPException(status_code=400, detail="num_questions debe estar entre 3 y 80")

    # Solo se aceptan PDFs realmente asociados a este tema (vía pdf_links).
    allowed = set(await _topic_pdf_ids(uid, topic_id))
    wanted = [pid for pid in req.pdf_ids if pid in allowed]
    pdfs = await db.pdfs.find(
        {"id": {"$in": wanted}, "user_id": uid}, {"_id": 0}
    ).to_list(100)
    if not pdfs:
        raise HTTPException(status_code=404, detail="No se encontraron PDFs")

    nopts = max(2, min(5, int(req.num_options))) if req.question_type == "mcq" else 2

    # Reparto POR PDF (como flashcards): cada pregunta se atribuye al PDF del que
    # realmente sale. Repartimos num_questions proporcional al char_count y hacemos
    # una llamada a Gemini por PDF, en paralelo. Los PDFs con 0 asignadas no se llaman.
    alloc = _distribute_cards(req.num_questions, [max(0, int(p.get("char_count", 0))) for p in pdfs])
    targets = [(p, n) for p, n in zip(pdfs, alloc) if n > 0]

    # Comprobar plan + cuota ANTES de llamar a Gemini (1 unidad para toda la
    # operación, aunque genere de N PDFs).
    await check_and_consume_ai_quota(current_user, gen_kind="questions")

    # Una llamada por PDF (con SOLO su texto; sin cabecera de nombre de fichero),
    # en PARALELO (la espera ≈ la más lenta, no la suma).
    results = await asyncio.gather(
        *[
            generate_questions_with_claude(
                topic["name"], p["text"], n,
                question_type=req.question_type, num_options=nopts,
                custom_instructions=req.custom_instructions or "",
            )
            for p, n in targets
        ],
        return_exceptions=True,
    )

    docs = []
    for (p, _n), res in zip(targets, results):
        # Todo-o-nada: si alguna fuente falla (excepción o [] por error de la IA),
        # revertimos la cuota y abortamos (sin resultados parciales).
        if isinstance(res, Exception) or not res:
            await _refund_ai_quota(current_user, gen_kind="questions")
            raise HTTPException(status_code=502, detail="No se pudieron generar preguntas")
        for g in res:
            q = Question(
                user_id=uid,
                topic_id=topic_id,
                topic_name=topic["name"],
                subject_id=topic.get("subject_id"),
                pdf_source_id=p["id"],
                question_type=g["question_type"],
                num_options=g["num_options"],
                question=g["question"],
                options=g["options"],
                correct_index=g["correct_index"],
                explanation=g.get("explanation", ""),
                model_answer=g.get("model_answer", ""),
            )
            docs.append(q.model_dump())

    if not docs:
        await _refund_ai_quota(current_user, gen_kind="questions")
        raise HTTPException(status_code=502, detail="No se pudieron generar preguntas")

    await db.questions.insert_many(docs)
    return {"questions_created": len(docs), "pdf_ids_used": [p["id"] for p, _n in targets]}


# ---- Questions ----
@api.post("/questions/{question_id}/favorite")
async def toggle_favorite(question_id: str, current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    q = await db.questions.find_one({"id": question_id, "user_id": uid}, {"_id": 0})
    if not q:
        raise HTTPException(status_code=404, detail="Pregunta no encontrada")
    new_val = not q.get("favorite", False)
    await db.questions.update_one({"id": question_id, "user_id": uid}, {"$set": {"favorite": new_val}})
    return {"favorite": new_val}


@api.post("/questions/{question_id}/difficult")
async def toggle_difficult(question_id: str, current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    q = await db.questions.find_one({"id": question_id, "user_id": uid}, {"_id": 0})
    if not q:
        raise HTTPException(status_code=404, detail="Pregunta no encontrada")
    new_val = not q.get("difficult", False)
    await db.questions.update_one({"id": question_id, "user_id": uid}, {"$set": {"difficult": new_val}})
    return {"difficult": new_val}


class EditQuestionReq(BaseModel):
    question: Optional[str] = None
    options: Optional[List[str]] = None
    correct_index: Optional[int] = None
    explanation: Optional[str] = None
    model_answer: Optional[str] = None


@api.patch("/questions/{question_id}")
async def edit_question(question_id: str, req: EditQuestionReq, current_user: dict = Depends(get_current_user)):
    """Edit a question manually."""
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="Nada que actualizar")
    res = await db.questions.update_one({"id": question_id, "user_id": current_user["id"]}, {"$set": fields})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Pregunta no encontrada")
    return {"ok": True}


@api.delete("/questions/{question_id}")
async def delete_question(question_id: str, current_user: dict = Depends(get_current_user)):
    res = await db.questions.delete_one({"id": question_id, "user_id": current_user["id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Pregunta no encontrada")
    return {"ok": True}


class ManualQuestionCreate(BaseModel):
    """Autoría manual de una pregunta (sin IA). Los campos de la API se traducen
    al schema interno de `Question` (question_text→question, correct_answer→
    correct_index, dev_answer→model_answer) para ser indistinguible de las
    generadas. La validación cruzada por tipo va en el handler (422 con mensaje)."""
    topic_id: str
    question_type: str
    question_text: str
    options: Optional[List[str]] = None
    correct_answer: Optional[int] = None
    dev_answer: Optional[str] = None
    explanation: Optional[str] = None
    num_options: Optional[int] = None
    # PDF de origen opcional; si viene, debe ser un PDF del tema (y del usuario).
    pdf_source_id: Optional[str] = None


@api.post("/questions", status_code=201)
async def create_manual_question(req: ManualQuestionCreate, current_user: dict = Depends(get_current_user)):
    """Crea una pregunta escrita por el usuario. NO llama a Gemini ni consume
    cuota. Mismo documento que las generadas por IA (sin campo `source`, que hoy
    tampoco tienen), para que sean indistinguibles en quizzes y banco."""
    uid = current_user["id"]

    qtype = req.question_type
    if qtype not in ("mcq", "tf", "dev"):
        raise HTTPException(status_code=422, detail="question_type debe ser 'mcq', 'tf' o 'dev'")

    text = (req.question_text or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="El enunciado no puede estar vacío")

    # El tema debe existir y pertenecer al usuario. 404 (no 403) para no revelar
    # la existencia de temas de otros usuarios.
    topic = await db.topics.find_one({"id": req.topic_id, "user_id": uid}, {"_id": 0})
    if not topic:
        raise HTTPException(status_code=404, detail="Tema no encontrado")

    # PDF de origen opcional: si viene, debe estar vinculado a ESTE tema (y al
    # usuario). Mismo helper que generación/quiz → una pregunta manual no puede
    # atribuirse a un PDF ajeno o de otro tema. None = pregunta libre.
    pdf_source_id = req.pdf_source_id
    if pdf_source_id is not None:
        if pdf_source_id not in await _topic_pdf_ids(uid, req.topic_id):
            raise HTTPException(status_code=422, detail="El PDF de origen no pertenece a este tema")

    options: List[str] = []
    correct_index = 0
    model_answer = ""
    num_options = 2

    if qtype == "mcq":
        opts = [str(o).strip() for o in (req.options or [])]
        if len(opts) < 2 or len(opts) > 5:
            raise HTTPException(status_code=422, detail="Una pregunta de opción múltiple necesita entre 2 y 5 opciones")
        if any(not o for o in opts):
            raise HTTPException(status_code=422, detail="Las opciones no pueden estar vacías")
        if req.correct_answer is None or not (0 <= req.correct_answer < len(opts)):
            raise HTTPException(status_code=422, detail="correct_answer debe ser el índice (0-based) de una de las opciones")
        options = opts
        correct_index = req.correct_answer
        num_options = len(opts)
    elif qtype == "tf":
        if req.correct_answer not in (0, 1):
            raise HTTPException(status_code=422, detail="En verdadero/falso, correct_answer debe ser 0 (verdadero) o 1 (falso)")
        options = ["Verdadero", "Falso"]
        correct_index = req.correct_answer
        num_options = 2
    else:  # dev
        model_answer = (req.dev_answer or "").strip()
        if not model_answer:
            raise HTTPException(status_code=422, detail="Una pregunta de desarrollo necesita una respuesta modelo (dev_answer)")
        options = []
        correct_index = 0
        num_options = 0

    q = Question(
        user_id=uid,
        topic_id=req.topic_id,
        topic_name=topic["name"],
        subject_id=topic.get("subject_id"),
        pdf_source_id=pdf_source_id,
        question_type=qtype,
        num_options=num_options,
        question=text,
        options=options,
        correct_index=correct_index,
        explanation=(req.explanation or "").strip(),
        model_answer=model_answer,
    )
    # Insertar una copia y devolver otra limpia: insert_one inyecta `_id`
    # (ObjectId no serializable) en el dict que recibe (patrón de create_subject).
    await db.questions.insert_one(q.model_dump())
    return q.model_dump()


# ---- Banco de preguntas (listado global con filtros) ----
# Cap de ids devueltos por /questions/ids: es el tamaño máximo de pool
# "practicable" de una vez. Si el filtro tiene más, se avisa en la UI con el
# total real (nada de recortes silenciosos).
QUESTIONS_IDS_CAP = 500

_QUESTION_STATUSES = ("all", "errors", "favorites", "difficult", "unpracticed", "mastered", "due")


def _questions_query(uid: str, *, subject_id=None, topic_id=None, pdf_source_id=None,
                     question_type=None, status="all", q=None) -> dict:
    """Construye el filtro Mongo del banco de preguntas (siempre por user_id).

    Compartido por GET /questions y GET /questions/ids para no duplicar lógica.
    """
    query: dict = {"user_id": uid}
    if subject_id:
        query["subject_id"] = subject_id
    if topic_id:
        query["topic_id"] = topic_id
    if pdf_source_id:
        # "none" = preguntas cuyo PDF de origen se borró/desvinculó (pdf_source_id None).
        query["pdf_source_id"] = None if pdf_source_id == "none" else pdf_source_id
    if question_type in ("mcq", "tf", "dev"):
        query["question_type"] = question_type

    if status == "errors":
        query["$expr"] = {"$gt": ["$times_answered", "$times_correct"]}
    elif status == "favorites":
        query["favorite"] = True
    elif status == "difficult":
        query["difficult"] = True
    elif status == "unpracticed":
        query["times_answered"] = 0
    elif status == "mastered":
        # Todo acertado y practicada al menos una vez.
        query["times_answered"] = {"$gt": 0}
        query["$expr"] = {"$eq": ["$times_answered", "$times_correct"]}
    elif status == "due":
        query["srs_next_review"] = {"$lte": _now_iso()}
        query["times_answered"] = {"$gt": 0}

    if q and q.strip():
        # Búsqueda por subcadena en el enunciado (regex escapada, sin distinguir
        # mayúsculas). Sin índice de texto: escaneo del subconjunto del usuario.
        query["question"] = {"$regex": re.escape(q.strip()), "$options": "i"}
    return query


@api.get("/questions")
async def list_questions(
    subject_id: Optional[str] = None,
    topic_id: Optional[str] = None,
    pdf_source_id: Optional[str] = None,
    question_type: Optional[str] = None,
    status: str = "all",
    q: Optional[str] = None,
    sort: str = "recent",
    page: int = 1,
    limit: int = 30,
    current_user: dict = Depends(get_current_user),
):
    """Banco de preguntas: listado global del usuario con filtros y paginación."""
    uid = current_user["id"]
    if status not in _QUESTION_STATUSES:
        status = "all"
    page = max(1, int(page))
    limit = max(1, min(100, int(limit)))

    query = _questions_query(
        uid, subject_id=subject_id, topic_id=topic_id, pdf_source_id=pdf_source_id,
        question_type=question_type, status=status, q=q,
    )

    total = await db.questions.count_documents(query)
    # "más falladas" primero (fallos absolutos = answered - correct), luego reciente.
    sort_spec = [("created_at", -1)] if sort != "most_failed" else [
        ("times_answered", -1), ("created_at", -1)
    ]
    cursor = (
        db.questions.find(query, {"_id": 0})
        .sort(sort_spec)
        .skip((page - 1) * limit)
        .limit(limit)
    )
    items = await cursor.to_list(limit)
    return {"items": items, "total": total, "page": page, "limit": limit}


@api.get("/questions/ids")
async def list_question_ids(
    subject_id: Optional[str] = None,
    topic_id: Optional[str] = None,
    pdf_source_id: Optional[str] = None,
    question_type: Optional[str] = None,
    status: str = "all",
    q: Optional[str] = None,
    random_sample: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
):
    """IDs de las preguntas del filtro (para 'practicar esta selección').

    Dos modos:
    - Por defecto: los QUESTIONS_IDS_CAP más recientes, con `total` real y `capped`
      para que la UI avise ("practicando 500 de 800") sin recortes silenciosos.
    - `random_sample=N`: muestra ALEATORIA UNIFORME de tamaño N (acotado al CAP)
      sobre TODO el conjunto filtrado, vía `$sample` de Mongo. Devuelve exactamente
      min(N, CAP, total) ids; `capped=false` (se pidió una cantidad concreta).
    El filtro (incl. `user_id`) es el mismo en ambos modos: el $sample NO se lo salta.
    """
    uid = current_user["id"]
    if status not in _QUESTION_STATUSES:
        status = "all"
    query = _questions_query(
        uid, subject_id=subject_id, topic_id=topic_id, pdf_source_id=pdf_source_id,
        question_type=question_type, status=status, q=q,
    )
    total = await db.questions.count_documents(query)

    if random_sample is not None:
        if random_sample < 1:
            raise HTTPException(status_code=422, detail="random_sample debe ser >= 1")
        size = min(random_sample, QUESTIONS_IDS_CAP)
        rows = await db.questions.aggregate([
            {"$match": query},
            {"$sample": {"size": size}},
            {"$project": {"_id": 0, "id": 1}},
        ]).to_list(size)
        ids = [r["id"] for r in rows]
        return {"ids": ids, "total": total, "capped": False, "sampled": True}

    rows = await (
        db.questions.find(query, {"_id": 0, "id": 1})
        .sort([("created_at", -1)])
        .limit(QUESTIONS_IDS_CAP)
        .to_list(QUESTIONS_IDS_CAP)
    )
    ids = [r["id"] for r in rows]
    return {"ids": ids, "total": total, "capped": total > len(ids), "sampled": False}


# ---- Development question evaluation ----
class EvalDevReq(BaseModel):
    question_id: str
    user_answer: str


@api.post("/quiz/eval-dev")
async def eval_dev_answer(req: EvalDevReq, current_user: dict = Depends(get_current_user)):
    """Evaluate a development answer using AI."""
    q = await db.questions.find_one({"id": req.question_id, "user_id": current_user["id"]}, {"_id": 0})
    if not q:
        raise HTTPException(status_code=404, detail="Pregunta no encontrada")
    if q.get("question_type") != "dev":
        raise HTTPException(status_code=400, detail="Solo para preguntas de desarrollo")

    # Comprobar plan + cuota de CORRECCIONES ANTES de llamar a Gemini.
    await check_and_consume_ai_quota(current_user, kind="correction")
    result = await evaluate_dev_answer(
        q["question"],
        q.get("model_answer", ""),
        req.user_answer,
        q.get("explanation", ""),
    )
    # evaluate_dev_answer no lanza: si falló internamente, revertir el consumo.
    if result.pop("_ai_error", False):
        await _refund_ai_quota(current_user, kind="correction")
    return result


class DevBatchItem(BaseModel):
    question_id: str
    user_answer: str = ""


class EvalDevBatchReq(BaseModel):
    answers: List[DevBatchItem]


@api.post("/quiz/eval-dev-batch")
async def eval_dev_batch(req: EvalDevBatchReq, current_user: dict = Depends(get_current_user)):
    """Corrige VARIAS respuestas de desarrollo de una vez (envío de un examen).

    - Cuota de CORRECCIONES: **1 por respuesta evaluada** (no en blanco), igual
      que la corrección individual → sin incentivo perverso examen vs práctica.
    - Las respuestas en blanco NO se evalúan: 0 puntos, sin gastar cuota. Si TODAS
      están en blanco, no se consume nada.
    - Se comprueba la cuota UNA vez, al principio → nunca hay 402 a mitad de examen.
    - Robustez: evalúa en paralelo; si TODAS las evaluadas fallan, reembolsa y 502;
      los fallos parciales devuelven 0 + aviso y se reembolsan (sin cargo).
    """
    uid = current_user["id"]
    if not req.answers:
        return {"results": []}

    ids = [a.question_id for a in req.answers]
    qmap = {
        q["id"]: q
        for q in await db.questions.find({"id": {"$in": ids}, "user_id": uid}, {"_id": 0}).to_list(500)
    }

    results_by_id: dict = {}
    to_eval = []  # (question_id, question_doc, user_answer)
    for a in req.answers:
        q = qmap.get(a.question_id)
        if not q or q.get("question_type") != "dev":
            results_by_id[a.question_id] = {"question_id": a.question_id, "score": 0, "feedback": "", "key_points_missing": []}
        elif not a.user_answer.strip():
            results_by_id[a.question_id] = {"question_id": a.question_id, "score": 0, "feedback": "Sin responder", "key_points_missing": []}
        else:
            to_eval.append((a.question_id, q, a.user_answer))

    # Nada que evaluar (todo en blanco / inválido) → sin cuota.
    if not to_eval:
        return {"results": [results_by_id[a.question_id] for a in req.answers]}

    # 1 corrección por respuesta a evaluar (no en blanco). Cuota comprobada UNA
    # vez, antes de llamar a Gemini → nunca hay 402 a mitad de examen.
    await check_and_consume_ai_quota(current_user, kind="correction", cost=len(to_eval))
    evals = await asyncio.gather(*[
        evaluate_dev_answer(q["question"], q.get("model_answer", ""), ua, q.get("explanation", ""))
        for (_qid, q, ua) in to_eval
    ])

    any_ok = False
    num_failed = 0
    for (qid, _q, _ua), res in zip(to_eval, evals):
        if res.pop("_ai_error", False):
            num_failed += 1
            results_by_id[qid] = {"question_id": qid, "score": 0, "feedback": "No se pudo evaluar", "key_points_missing": []}
        else:
            any_ok = True
            results_by_id[qid] = {
                "question_id": qid,
                "score": res.get("score", 0),
                "feedback": res.get("feedback", ""),
                "key_points_missing": res.get("key_points_missing", []),
            }

    # No se cobra por evaluación fallida: se reembolsan las que fallaron.
    if num_failed:
        await _refund_ai_quota(current_user, kind="correction", cost=num_failed)
    if not any_ok:
        raise HTTPException(status_code=502, detail="No se pudieron evaluar las respuestas de desarrollo")

    return {"results": [results_by_id[a.question_id] for a in req.answers]}


# ---- Quiz ----
# Dos ejes del estudio: SELECCIÓN (qué preguntas) × COMPORTAMIENTO (cómo se juega),
# fuente única. El backend solo usa `selection` para elegir preguntas; `behavior`
# se persiste. (El viejo `mode` que conflaciaba ambos quedó retirado por completo.)
_QUIZ_SELECTIONS = ("all", "errors", "srs", "favorites")
_QUIZ_BEHAVIORS = ("practice", "exam")


def _resolve_quiz_axes(selection: Optional[str], behavior: Optional[str]):
    """Normaliza (selection, behavior) con defaults tolerantes (all/practice)."""
    sel = selection if selection in _QUIZ_SELECTIONS else "all"
    beh = behavior if behavior in _QUIZ_BEHAVIORS else "practice"
    return sel, beh


async def _validate_quiz_pdf_ids(
    uid: str, pdf_ids: Optional[List[str]], topic_ids: Optional[List[str]]
) -> Optional[List[str]]:
    """Valida el filtro de PDFs de un estudio (single-topic scope).

    - vacío/None → None (no filtra).
    - requiere EXACTAMENTE un tema (`len(topic_ids) == 1`): con topic explícito el
      scope ya es ese tema, sea cual sea el subject que acompañe. 0 o >1 → 400.
    - todos los pdf_ids deben pertenecer a ese tema (`_topic_pdf_ids`). Si no → 400.
    """
    if not pdf_ids:
        return None
    if not topic_ids or len(topic_ids) != 1:
        raise HTTPException(status_code=400, detail="Filtrar por PDFs requiere un único tema")
    allowed = set(await _topic_pdf_ids(uid, topic_ids[0]))
    if any(p not in allowed for p in pdf_ids):
        raise HTTPException(status_code=400, detail="Algún PDF no pertenece a este tema")
    return pdf_ids


def _quiz_pool_query(
    uid: str, *, selection: str = "all",
    subject_ids: Optional[List[str]] = None, topic_ids: Optional[List[str]] = None,
    question_type: Optional[str] = None, num_options: Optional[int] = None,
    question_ids: Optional[List[str]] = None, pdf_ids: Optional[List[str]] = None,
) -> dict:
    """Query Mongo del pool de preguntas para un estudio, compartida por
    `quiz_start` (obtiene el pool) y `quiz_available` (lo cuenta para el gating).
    La SELECCIÓN es el único eje que filtra; `behavior` no interviene aquí."""
    query: dict = {"user_id": uid}
    if question_ids:
        # Pool explícito (banco de preguntas). Se acota siempre por user_id.
        # `pdf_ids` se ignora aquí a propósito: question_ids ya define el pool.
        query["id"] = {"$in": question_ids}
        if question_type and question_type != "any":
            query["question_type"] = question_type
        return query
    if subject_ids:
        query["subject_id"] = {"$in": subject_ids}
    if topic_ids:
        query["topic_id"] = {"$in": topic_ids}
    if pdf_ids:
        # Filtrar por PDFs de origen concretos (single-topic; validado aparte).
        # Ausente/vacío = todos los PDFs, incl. huérfanos (pdf_source_id None);
        # explícito = solo esos PDFs, lo que EXCLUYE los huérfanos.
        query["pdf_source_id"] = {"$in": pdf_ids}
    if question_type and question_type != "any":
        query["question_type"] = question_type
    if num_options:
        query["num_options"] = int(num_options)
    if selection == "errors":
        query["$expr"] = {"$gt": ["$times_answered", "$times_correct"]}
    elif selection == "favorites":
        query["favorite"] = True
    elif selection == "srs":
        query["srs_next_review"] = {"$lte": _now_iso()}
    return query


class QuizStartReq(BaseModel):
    # Ejes del estudio (si faltan, defaults all/practice en _resolve_quiz_axes).
    selection: Optional[Literal["all", "errors", "srs", "favorites"]] = None
    behavior: Optional[Literal["practice", "exam"]] = None
    subject_ids: List[str] = []
    topic_ids: List[str] = []
    num_questions: int = 20
    time_limit_minutes: Optional[int] = None
    question_type: Optional[Literal["mcq", "tf", "dev", "any"]] = "any"
    num_options: Optional[int] = None
    # "Practicar esta selección" del banco: si viene, el pool son EXACTAMENTE
    # estas preguntas (del usuario); se ignoran los filtros de modo/asignatura.
    question_ids: Optional[List[str]] = None
    # Filtro de PDFs de origen (single-topic). Ausente/vacío = todos (incl.
    # huérfanos). Ignorado si viene question_ids. Validado en el handler.
    pdf_ids: Optional[List[str]] = None


@api.post("/quiz/start")
async def quiz_start(req: QuizStartReq, current_user: dict = Depends(get_current_user)):
    selection, behavior = _resolve_quiz_axes(req.selection, req.behavior)
    # question_ids define el pool por sí solo → pdf_ids se ignora (ni se valida).
    pdf_ids = None if req.question_ids else await _validate_quiz_pdf_ids(
        current_user["id"], req.pdf_ids, req.topic_ids
    )
    query = _quiz_pool_query(
        current_user["id"], selection=selection,
        subject_ids=req.subject_ids, topic_ids=req.topic_ids,
        question_type=req.question_type, num_options=req.num_options,
        question_ids=req.question_ids, pdf_ids=pdf_ids,
    )

    questions = await db.questions.find(query, {"_id": 0}).to_list(5000)
    if not questions:
        raise HTTPException(status_code=404, detail="No hay preguntas para los filtros seleccionados")

    random.shuffle(questions)
    questions = questions[: req.num_questions]

    payload = []
    for q in questions:
        qtype = q.get("question_type", "mcq")
        n = int(q.get("num_options") or len(q.get("options", []) or []))

        if qtype == "dev":
            payload.append({
                "id": q["id"],
                "topic_id": q["topic_id"],
                "topic_name": q["topic_name"],
                "subject_id": q.get("subject_id"),
                "question_type": "dev",
                "num_options": 0,
                "question": q["question"],
                "options": [],
                "correct_index": 0,
                "explanation": q.get("explanation", ""),
                "model_answer": q.get("model_answer", ""),
                "favorite": q.get("favorite", False),
                "difficult": q.get("difficult", False),
            })
        elif qtype == "tf":
            payload.append({
                "id": q["id"],
                "topic_id": q["topic_id"],
                "topic_name": q["topic_name"],
                "subject_id": q.get("subject_id"),
                "question_type": "tf",
                "num_options": n,
                "question": q["question"],
                "options": q["options"],
                "correct_index": q["correct_index"],
                "explanation": q.get("explanation", ""),
                "model_answer": "",
                "favorite": q.get("favorite", False),
                "difficult": q.get("difficult", False),
            })
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
                "question_type": "mcq",
                "num_options": n,
                "question": q["question"],
                "options": shuffled_options,
                "correct_index": new_correct,
                "explanation": q.get("explanation", ""),
                "model_answer": "",
                "favorite": q.get("favorite", False),
                "difficult": q.get("difficult", False),
            })
    return {
        "questions": payload,
        "selection": selection,
        "behavior": behavior,
    }


@api.get("/quiz/available")
async def quiz_available(
    selection: str = "all",
    subject_ids: List[str] = Query(default=[]),
    topic_ids: List[str] = Query(default=[]),
    question_type: Optional[str] = "any",
    pdf_ids: List[str] = Query(default=[]),
    current_user: dict = Depends(get_current_user),
):
    """Cuántas preguntas hay para la SELECCIÓN y filtros dados (coste 0, sin IA).
    Alimenta el gating de QuizSetup: permite bloquear el inicio con un mensaje
    claro cuando una selección (errores/repaso/favoritas) no tiene preguntas, en
    vez de dejar un botón muerto que acabe en 404."""
    sel = selection if selection in _QUIZ_SELECTIONS else "all"
    validated_pdf_ids = await _validate_quiz_pdf_ids(current_user["id"], pdf_ids, topic_ids)
    query = _quiz_pool_query(
        current_user["id"], selection=sel,
        subject_ids=subject_ids, topic_ids=topic_ids, question_type=question_type,
        pdf_ids=validated_pdf_ids,
    )
    count = await db.questions.count_documents(query)
    return {"count": count, "selection": sel}


class QuizSubmitReq(BaseModel):
    # Ejes del estudio (defaults all/practice en _resolve_quiz_axes si faltan).
    selection: Optional[Literal["all", "errors", "srs", "favorites"]] = None
    behavior: Optional[Literal["practice", "exam"]] = None
    subject_ids: List[str] = []
    topic_ids: List[str] = []
    answers: List[dict]
    duration_seconds: int
    time_limit_seconds: Optional[int] = None
    penalty_factor: Optional[int] = None
    # Examen: si True (y hay penalización), un blanco cuenta como fallo y penaliza
    # por el mismo ratio. Subordinado a la penalización (blindado en el backend).
    blanks_count_as_wrong: bool = False
    question_type: Optional[str] = None
    # Snapshot por pregunta (orden mostrado/barajado de la sesión) para poder
    # reconstruir el intento pregunta a pregunta. Opcional (cliente viejo → None).
    snapshot: Optional[List[dict]] = None


def _build_attempt_items(snapshot: List[dict], question_ids: List[str]) -> List[dict]:
    """Normaliza el snapshot del cliente en los `items` del Attempt.

    - Exige que los `question_id` del snapshot coincidan (mismo conjunto y orden)
      con los `question_ids` del intento; si no, 400 (evita snapshots incoherentes).
    - Recalcula `is_correct` en el backend para mcq/tf (no se fía del cliente).
    - Para dev conserva user_answer/dev_score/feedback (solo display).
    """
    snap_ids = [s.get("question_id") for s in snapshot]
    if snap_ids != question_ids:
        raise HTTPException(status_code=400, detail="El snapshot no coincide con las preguntas del intento")
    items: List[dict] = []
    for s in snapshot:
        qtype = s.get("question_type", "mcq")
        item = {
            "question_id": s.get("question_id"),
            "question_type": qtype,
            "question": s.get("question", ""),
            "options": list(s.get("options", []) or []),
            "selected": int(s.get("selected", -1)),
            "correct_index": int(s.get("correct_index", -1)),
        }
        if qtype == "dev":
            # Un dev es "acierto" con nota >= 5 (mismo umbral que el scoring).
            item["is_correct"] = float(s.get("dev_score", 0)) >= 5
            item["user_answer"] = s.get("user_answer", "")
            item["dev_score"] = float(s.get("dev_score", 0))
            item["feedback"] = s.get("feedback", "")
        else:
            item["is_correct"] = item["selected"] == item["correct_index"] and item["selected"] >= 0
        items.append(item)
    return items


def _update_srs(q: dict, correct: bool) -> dict:
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
async def quiz_submit(req: QuizSubmitReq, current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    selection, behavior = _resolve_quiz_axes(req.selection, req.behavior)
    pf = req.penalty_factor
    # El blanco solo puede "restar" si hay penalización activa (blindaje backend:
    # la UI ya subordina el toggle a la penalización, pero no confiamos en ella).
    blanks_as_wrong = bool(req.blanks_count_as_wrong) and bool(pf) and pf > 0
    correct = 0
    wrong = 0
    unanswered = 0
    # Fallos MCQ/VF: los ÚNICOS que penalizan (los dev están exentos, ver abajo).
    wrong_nondev = 0
    # Crédito para la nota: 1.0 por acierto MCQ/VF; dev_score/10 (0.0-1.0) por dev.
    # Es la fuente de `raw`/`score_10` (los conteos enteros son solo para tiles/SRS).
    points = 0.0
    total = len(req.answers)
    for a in req.answers:
        qid = a.get("question_id")
        selected = int(a.get("selected", -1))
        correct_index = int(a.get("correct_index", -1))
        qtype = a.get("question_type", "mcq")

        if selected == -1 and qtype != "dev":
            # El blanco SIEMPRE se cuenta como blanco (unanswered), aunque penalice:
            # así Resultados puede mostrarlo aparte de los fallos reales. Su
            # penalización (si el toggle está activo) se aplica en `raw`, más abajo.
            # No toca las stats por pregunta (un blanco no es un intento real).
            unanswered += 1
            continue

        if qtype == "dev":
            # Dev answers are evaluated separately; count as answered.
            dev_score = float(a.get("dev_score", 0))
            is_correct = dev_score >= 5
            # Crédito PROPORCIONAL: un dev aporta dev_score/10 a la nota, incluido el
            # blanco (dev_score 0 → 0). El umbral >=5 solo define "acertada" para los
            # conteos/tiles/SRS. Los dev NO entran en `wrong_nondev` → exentos de
            # penalización (esta es anti-azar de MCQ/VF, no aplica a respuesta abierta).
            points += dev_score / 10.0
        else:
            is_correct = selected == correct_index
            if is_correct:
                points += 1.0
            else:
                wrong_nondev += 1

        if is_correct:
            correct += 1
        else:
            wrong += 1

        q = await db.questions.find_one({"id": qid, "user_id": uid}, {"_id": 0})
        if not q:
            continue
        set_fields = {"last_answered_at": _now_iso(), "last_correct": is_correct}
        # El estado SRS (ease/interval/next_review) SOLO avanza en la selección de
        # Repaso. En cualquier otra (examen, errores, favoritas, todas) responder NO
        # toca el SRS ya establecido de la pregunta.
        if selection == "srs":
            set_fields.update(_update_srs(q, is_correct))
        update = {
            "$inc": {"times_answered": 1, **(({"times_correct": 1}) if is_correct else {})},
            "$set": set_fields,
        }
        await db.questions.update_one({"id": qid, "user_id": uid}, update)

    # Solo penalizan los fallos MCQ/VF (`wrong_nondev`; los dev están exentos) y, con
    # el toggle activo, los blancos MCQ/VF (unanswered; los dev en blanco llegan como
    # wrong con dev_score=0 y NO cuentan aquí). La nota parte de `points` (crédito
    # proporcional), no del conteo entero de aciertos.
    penalized = wrong_nondev + (unanswered if blanks_as_wrong else 0)
    if pf and pf > 0:
        raw = points - (penalized / pf)
    else:
        raw = points
    if raw < 0:
        raw = 0.0
    score_10 = round((raw / total) * 10, 2) if total else 0.0
    raw_score = round(raw, 3)

    today = datetime.now(timezone.utc).date().isoformat()
    attempt_question_ids = [a.get("question_id") for a in req.answers]
    # Snapshot por pregunta (opcional): valida contra los question_ids del intento y
    # recalcula is_correct en el backend. Cliente viejo sin snapshot → items None.
    attempt_items = (
        _build_attempt_items(req.snapshot, attempt_question_ids)
        if req.snapshot is not None else None
    )
    attempt = Attempt(
        user_id=uid,
        selection=selection,
        behavior=behavior,
        subject_ids=req.subject_ids,
        topic_ids=req.topic_ids,
        question_ids=attempt_question_ids,
        answers=[int(a.get("selected", -1)) for a in req.answers],
        items=attempt_items,
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
        streak_day=today,
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
        # Efectivo (blindado): si los blancos han penalizado como fallo en esta nota.
        "blanks_penalized": blanks_as_wrong,
    }


# ---- Stats ----
def _current_streak(streak_days: List[str]) -> int:
    """Racha de días consecutivos con actividad hasta hoy, calculada en memoria.

    Antes se hacía un count_documents por día en un bucle (hasta 365 viajes a
    Atlas). Ahora se recibe la lista de días con intentos (una sola consulta
    `distinct`) y se cuentan los consecutivos desde hoy hacia atrás."""
    days = {d for d in streak_days if d}
    streak = 0
    check = datetime.now(timezone.utc).date()
    while check.isoformat() in days:
        streak += 1
        check -= timedelta(days=1)
    return streak


@api.get("/stats")
async def stats_overview(current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    now = _now_iso()

    # Todas las consultas son independientes → se lanzan en paralelo (una sola
    # tanda) en vez de ~10 viajes secuenciales a Atlas.
    (
        total_subjects, total_topics, total_questions, total_attempts,
        agg, favorites, difficult, errors_pool, due_srs,
        streak_days, last_attempts,
    ) = await asyncio.gather(
        db.subjects.count_documents({"user_id": uid}),
        db.topics.count_documents({"user_id": uid}),
        db.questions.count_documents({"user_id": uid}),
        db.attempts.count_documents({"user_id": uid}),
        db.questions.aggregate([
            {"$match": {"user_id": uid}},
            {"$group": {"_id": None, "ans": {"$sum": "$times_answered"}, "ok": {"$sum": "$times_correct"}}},
        ]).to_list(1),
        db.questions.count_documents({"user_id": uid, "favorite": True}),
        db.questions.count_documents({"user_id": uid, "difficult": True}),
        db.questions.count_documents({"user_id": uid, "$expr": {"$gt": ["$times_answered", "$times_correct"]}}),
        db.questions.count_documents({"user_id": uid, "srs_next_review": {"$lte": now}, "times_answered": {"$gt": 0}}),
        db.attempts.distinct("streak_day", {"user_id": uid}),
        db.attempts.find({"user_id": uid}, {"_id": 0}).sort("created_at", -1).to_list(3),
    )

    accuracy = 0.0
    answered = 0
    if agg and agg[0]["ans"]:
        accuracy = round(100 * agg[0]["ok"] / agg[0]["ans"], 1)
        answered = agg[0]["ans"]

    streak = _current_streak(streak_days)

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
        "streak": streak,
        "last_attempts": last_attempts,
    }


@api.get("/attempts")
async def list_attempts(
    page: int = 1,
    limit: int = 20,
    behavior: Optional[str] = None,
    selection: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Historial de intentos del usuario, paginado (created_at desc). Filas LIGERAS
    (sin el snapshot `items`): lo justo para la lista, con nombres de asignatura/tema
    resueltos en batch. `has_items` indica si el intento tiene desglose por pregunta."""
    uid = current_user["id"]
    page = max(1, int(page))
    limit = max(1, min(100, int(limit)))
    query: dict = {"user_id": uid}
    if behavior in ("practice", "exam"):
        query["behavior"] = behavior
    if selection in _QUIZ_SELECTIONS:
        query["selection"] = selection

    total = await db.attempts.count_documents(query)
    rows = await (
        db.attempts.find(query, {"_id": 0})
        .sort([("created_at", -1)])
        .skip((page - 1) * limit)
        .limit(limit)
        .to_list(limit)
    )

    # Resolver nombres de asignatura/tema en batch (sin N+1).
    subj_ids = {sid for r in rows for sid in (r.get("subject_ids") or [])}
    topic_ids = {tid for r in rows for tid in (r.get("topic_ids") or [])}
    sname, tname = {}, {}
    if subj_ids:
        subs = await db.subjects.find({"user_id": uid, "id": {"$in": list(subj_ids)}}, {"_id": 0, "id": 1, "name": 1}).to_list(2000)
        sname = {s["id"]: s["name"] for s in subs}
    if topic_ids:
        tps = await db.topics.find({"user_id": uid, "id": {"$in": list(topic_ids)}}, {"_id": 0, "id": 1, "name": 1}).to_list(4000)
        tname = {t["id"]: t["name"] for t in tps}

    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "created_at": r.get("created_at"),
            "selection": r.get("selection", "all"),
            "behavior": r.get("behavior", "practice"),
            "score_10": r.get("score_10", 0.0),
            "correct_count": r.get("correct_count", 0),
            "wrong_count": r.get("wrong_count", 0),
            "unanswered_count": r.get("unanswered_count", 0),
            "total": r.get("total", 0),
            "duration_seconds": r.get("duration_seconds", 0),
            "penalty_factor": r.get("penalty_factor"),
            "question_type": r.get("question_type"),
            "subjects": [{"id": sid, "name": sname.get(sid)} for sid in (r.get("subject_ids") or []) if sid],
            "topics": [{"id": tid, "name": tname.get(tid)} for tid in (r.get("topic_ids") or []) if tid],
            "has_items": bool(r.get("items")),
        })
    return {"items": items, "total": total, "page": page, "limit": limit}


@api.get("/attempts/{attempt_id}")
async def get_attempt(attempt_id: str, current_user: dict = Depends(get_current_user)):
    """Detalle de un intento (con `items` si los tiene). User-scoped: 404 si es de
    otro usuario o no existe (no revela su existencia). Los intentos legacy sin
    snapshot responden igualmente (sin desglose por pregunta)."""
    uid = current_user["id"]
    attempt = await db.attempts.find_one({"id": attempt_id, "user_id": uid}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=404, detail="Intento no encontrado")
    return attempt


def _group_stats_by(field: str):
    """Pipeline de agregación que agrupa las preguntas del usuario por `field`
    (subject_id o topic_id) y suma respuestas/aciertos/total en UNA consulta."""
    return [
        {"$group": {
            "_id": f"${field}",
            "ans": {"$sum": "$times_answered"},
            "ok": {"$sum": "$times_correct"},
            "total": {"$sum": 1},
        }},
    ]


@api.get("/stats/by-subject")
async def stats_by_subject(current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    # 2 consultas fijas (antes: 1 + una agregación por asignatura, N+1).
    subjects, agg = await asyncio.gather(
        db.subjects.find({"user_id": uid}, {"_id": 0}).to_list(1000),
        db.questions.aggregate(
            [{"$match": {"user_id": uid}}, *_group_stats_by("subject_id")]
        ).to_list(None),
    )
    by_id = {r["_id"]: r for r in agg}
    out = []
    for s in subjects:
        row = by_id.get(s["id"])
        ans = row["ans"] if row else 0
        ok = row["ok"] if row else 0
        out.append({
            "subject_id": s["id"],
            "subject_name": s["name"],
            "color": s.get("color", "#C65D47"),
            "total_questions": row["total"] if row else 0,
            "answered": ans,
            "correct": ok,
            "accuracy": round(100 * ok / ans, 1) if ans else 0.0,
        })
    return out


@api.get("/stats/by-topic")
async def stats_by_topic(current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    # 2 consultas fijas (antes: 1 + una agregación por tema, N+1).
    topics, agg = await asyncio.gather(
        db.topics.find({"user_id": uid}, {"_id": 0}).to_list(2000),
        db.questions.aggregate(
            [{"$match": {"user_id": uid}}, *_group_stats_by("topic_id")]
        ).to_list(None),
    )
    by_id = {r["_id"]: r for r in agg}
    out = []
    for t in topics:
        row = by_id.get(t["id"])
        ans = row["ans"] if row else 0
        ok = row["ok"] if row else 0
        out.append({
            "topic_id": t["id"],
            "topic_name": t["name"],
            "subject_id": t.get("subject_id"),
            "total_questions": row["total"] if row else 0,
            "answered": ans,
            "correct": ok,
            "accuracy": round(100 * ok / ans, 1) if ans else 0.0,
        })
    return out



# ---------------------------------------------------------------------------
# Flashcards
# ---------------------------------------------------------------------------
class Flashcard(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    topic_id: str
    topic_name: str
    subject_id: Optional[str] = None
    # PDF del que se extrajo la tarjeta (alineado con Question.pdf_source_id).
    # None = tarjeta "sin fuente": las legacy anteriores a este campo y las de
    # temas multi-PDF que no se pudieron atribuir en el backfill.
    pdf_source_id: Optional[str] = None
    term: str
    definition: str
    example: Optional[str] = ""
    favorite: bool = False
    times_reviewed: int = 0
    times_correct: int = 0
    srs_interval_days: float = 0
    srs_ease: float = 2.5
    srs_next_review: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _distribute_cards(total: int, weights: List[int]) -> List[int]:
    """Reparte `total` tarjetas entre PDFs proporcionalmente a sus `weights`
    (char_count), usando el método del resto mayor para sumar EXACTAMENTE
    `total`. Garantiza >= 1 por PDF cuando el presupuesto lo permite
    (total >= nº de PDFs), para que ninguna fuente seleccionada quede sin
    representación; un anexo diminuto recibe pocas, no cero."""
    n = len(weights)
    if n == 0 or total <= 0:
        return [0] * n
    total_w = sum(weights)
    if total_w <= 0:  # todos con char_count 0: reparto uniforme
        weights = [1] * n
        total_w = n
    raw = [total * w / total_w for w in weights]
    counts = [int(x) for x in raw]  # suelo
    remainder = total - sum(counts)
    # Reparte el resto por mayor parte fraccionaria.
    order = sorted(range(n), key=lambda i: raw[i] - counts[i], reverse=True)
    for i in range(remainder):
        counts[order[i % n]] += 1
    # Mínimo 1 por PDF si cabe: sube los ceros quitando de los mayores.
    if total >= n:
        for i in range(n):
            if counts[i] == 0:
                j = max(range(n), key=lambda k: counts[k])
                if counts[j] > 1:
                    counts[j] -= 1
                    counts[i] += 1
    return counts


async def _generate_flashcards_from_text(topic_name: str, source_text: str, num_cards: int) -> List[dict]:
    """Use Gemini to extract key concepts as flashcards from PDF text."""
    if not GEMINI_API_KEY or gemini_client is None:
        return []

    max_chars = 80_000
    if len(source_text) > max_chars:
        source_text = source_text[:max_chars]

    system_msg = (
        "Eres un profesor experto. Extrae los conceptos clave del temario como tarjetas de estudio. "
        "Usa el vocabulario exacto del texto. Responde SOLO con JSON válido."
    )
    prompt = f"""Del siguiente temario del tema "{topic_name}", extrae exactamente {num_cards} conceptos clave como flashcards.

REGLAS:
- El "term" debe ser un concepto, término técnico, estructura, proceso o dato clave del temario.
- La "definition" debe ser la explicación literal del temario (2-4 frases).
- El "example" es opcional: un ejemplo concreto del texto si existe, si no deja vacío.
- Cubre los conceptos más importantes del tema, no repitas.
- Devuelve SOLO el array JSON.

FORMATO:
[
  {{
    "term": "nombre del concepto",
    "definition": "definición extraída del temario",
    "example": "ejemplo del texto o vacío"
  }}
]

TEMARIO:
\"\"\"
{source_text}
\"\"\"
"""
    try:
        response = await gemini_client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_msg,
                response_mime_type="application/json",
                temperature=0.5,
            ),
        )
        _log_gemini_usage("flashcards", response)
        raw = _strip_code_fences(response.text or "")
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        cards = []
        for item in data:
            if not isinstance(item, dict):
                continue
            term = str(item.get("term", "")).strip()
            definition = str(item.get("definition", "")).strip()
            if term and definition:
                cards.append({
                    "term": term,
                    "definition": definition,
                    "example": str(item.get("example", "")).strip(),
                })
        return cards
    except Exception as e:
        logger.error("Flashcard generation error: %s", e)
        return []


@api.get("/topics/{topic_id}/flashcards")
async def get_topic_flashcards(topic_id: str, current_user: dict = Depends(get_current_user)):
    """Return existing flashcards for a topic."""
    uid = current_user["id"]
    topic = await db.topics.find_one({"id": topic_id, "user_id": uid}, {"_id": 0})
    if not topic:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    cards = await db.flashcards.find({"topic_id": topic_id, "user_id": uid}, {"_id": 0}).sort("created_at", 1).to_list(500)
    return cards


class GenerateFlashcardsReq(BaseModel):
    # None/vacío = todos los PDFs del tema (caso común, "1 clic").
    pdf_ids: Optional[List[str]] = None
    num_cards: int = 15


@api.post("/topics/{topic_id}/flashcards/generate")
async def generate_topic_flashcards(
    topic_id: str,
    req: GenerateFlashcardsReq = GenerateFlashcardsReq(),
    current_user: dict = Depends(get_current_user),
):
    """Genera flashcards desde los PDFs elegidos del tema (o todos por defecto).

    Reemplazo POR PDF: se generan por fuente (una llamada a Gemini por PDF, en
    paralelo) y cada tarjeta guarda su `pdf_source_id`. Al regenerar:
    - subconjunto → solo se reemplazan las tarjetas de esos PDFs (conserva el
      resto y su progreso SRS/favoritos, incl. las legacy sin fuente);
    - todos los PDFs del tema → se reemplaza el tema entero (barre también las
      legacy `pdf_source_id=None`), como el "Regenerar" de siempre.
    La operación cuenta como 1 unidad de cuota aunque haga N llamadas.
    """
    uid = current_user["id"]
    topic = await db.topics.find_one({"id": topic_id, "user_id": uid}, {"_id": 0})
    if not topic:
        raise HTTPException(status_code=404, detail="Tema no encontrado")

    all_ids = await _topic_pdf_ids(uid, topic_id)
    if not all_ids:
        raise HTTPException(status_code=404, detail="No hay PDFs para este tema")

    # Solo se aceptan PDFs realmente asociados al tema; vacío/ausente = todos.
    if req.pdf_ids:
        selected_ids = [pid for pid in req.pdf_ids if pid in set(all_ids)]
        if not selected_ids:
            raise HTTPException(status_code=404, detail="No se encontraron PDFs")
    else:
        selected_ids = list(all_ids)
    is_full = set(selected_ids) == set(all_ids)

    pdfs = await db.pdfs.find({"id": {"$in": selected_ids}, "user_id": uid}, {"_id": 0}).to_list(100)
    if not pdfs:
        raise HTTPException(status_code=404, detail="No se encontraron PDFs")

    num_cards = max(5, min(30, req.num_cards))
    alloc = _distribute_cards(num_cards, [max(0, int(p.get("char_count", 0))) for p in pdfs])

    # Comprobar plan + cuota ANTES de llamar a Gemini (1 unidad para toda la
    # operación, aunque genere de N PDFs).
    await check_and_consume_ai_quota(current_user, gen_kind="flashcards")

    # Una llamada a Gemini por PDF, en PARALELO (la espera ≈ la más lenta, no la
    # suma). Los PDFs con 0 tarjetas asignadas no se llaman.
    targets = [(p, n) for p, n in zip(pdfs, alloc) if n > 0]
    results = await asyncio.gather(
        *[_generate_flashcards_from_text(topic["name"], p["text"], n) for p, n in targets],
        return_exceptions=True,
    )

    docs = []
    for (p, _n), res in zip(targets, results):
        # Todo-o-nada: si alguna fuente falla (excepción o [] por error de la
        # IA), no dejamos un estado a medias; revertimos la cuota y abortamos.
        if isinstance(res, Exception) or not res:
            await _refund_ai_quota(current_user, gen_kind="flashcards")
            raise HTTPException(status_code=502, detail="No se pudieron generar flashcards")
        for c in res:
            fc = Flashcard(
                user_id=uid,
                topic_id=topic_id,
                topic_name=topic["name"],
                subject_id=topic.get("subject_id"),
                pdf_source_id=p["id"],
                term=c["term"],
                definition=c["definition"],
                example=c.get("example", ""),
            )
            docs.append(fc.model_dump())

    if not docs:
        await _refund_ai_quota(current_user, gen_kind="flashcards")
        raise HTTPException(status_code=502, detail="No se pudieron generar flashcards")

    # Reemplazo selectivo: solo las tarjetas de los PDFs regenerados. Si se
    # regeneran TODOS, se barre el tema completo (incluidas las legacy None).
    if is_full:
        await db.flashcards.delete_many({"topic_id": topic_id, "user_id": uid})
    else:
        await db.flashcards.delete_many(
            {"topic_id": topic_id, "user_id": uid, "pdf_source_id": {"$in": selected_ids}}
        )
    await db.flashcards.insert_many(docs)

    # Devuelve TODAS las del tema (las nuevas + las conservadas), ordenadas.
    all_cards = await db.flashcards.find(
        {"topic_id": topic_id, "user_id": uid}, {"_id": 0}
    ).sort("created_at", 1).to_list(500)
    return {"flashcards_created": len(docs), "flashcards": all_cards}


@api.post("/flashcards/{card_id}/review")
async def review_flashcard(card_id: str, correct: bool, current_user: dict = Depends(get_current_user)):
    """Mark a flashcard as correct or incorrect and update SRS."""
    uid = current_user["id"]
    card = await db.flashcards.find_one({"id": card_id, "user_id": uid}, {"_id": 0})
    if not card:
        raise HTTPException(status_code=404, detail="Flashcard no encontrada")

    srs = _update_srs(card, correct)
    await db.flashcards.update_one(
        {"id": card_id, "user_id": uid},
        {
            "$inc": {"times_reviewed": 1, **(({"times_correct": 1}) if correct else {})},
            "$set": {"last_reviewed_at": _now_iso(), **srs},
        },
    )
    return {"ok": True}


@api.post("/flashcards/{card_id}/favorite")
async def toggle_flashcard_favorite(card_id: str, current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    card = await db.flashcards.find_one({"id": card_id, "user_id": uid}, {"_id": 0})
    if not card:
        raise HTTPException(status_code=404, detail="Flashcard no encontrada")
    new_val = not card.get("favorite", False)
    await db.flashcards.update_one({"id": card_id, "user_id": uid}, {"$set": {"favorite": new_val}})
    return {"favorite": new_val}


@api.delete("/flashcards/{card_id}")
async def delete_flashcard(card_id: str, current_user: dict = Depends(get_current_user)):
    res = await db.flashcards.delete_one({"id": card_id, "user_id": current_user["id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Flashcard no encontrada")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Auth — modelos, helpers, dependencia y endpoints
# ---------------------------------------------------------------------------
class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: str
    plan: str = "free"
    ai_generations_used: int = 0
    ai_corrections_used: int = 0
    # Desglose por tipo de "crear material" del ciclo actual. INVARIANTE:
    # questions + summaries + flashcards == ai_generations_used (se mantiene en el
    # único punto de consumo/refund/reset). Default 0; lectura tolerante.
    ai_gen_questions_used: int = 0
    ai_gen_summaries_used: int = 0
    ai_gen_flashcards_used: int = 0
    ai_period_start: str = Field(default_factory=_now_iso)  # periodo compartido por ambos contadores
    # Suscripción (Paddle Billing v4)
    subscription_status: str = "free"  # free | active | canceled | past_due | trialing
    paddle_customer_id: Optional[str] = None
    paddle_subscription_id: Optional[str] = None
    subscription_current_period_end: Optional[str] = None
    # Cambio programado de Paddle (p. ej. cancelación a fin de periodo). Objeto
    # {action, effective_at, resume_at} o None si no hay ninguno pendiente.
    subscription_scheduled_change: Optional[dict] = None
    created_at: str = Field(default_factory=_now_iso)


class UserInDB(User):
    password_hash: str


class RegisterReq(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class LoginReq(BaseModel):
    email: EmailStr
    password: str


class TokenResp(BaseModel):
    access_token: str
    token_type: str = "bearer"


# Hashing de contraseñas con la librería `bcrypt` directa (sin passlib, que está
# sin mantenimiento). Produce/verifica hashes `$2b$12$` estándar, compatibles con
# los que passlib generó antes, así que NO invalida las contraseñas existentes.
# bcrypt solo usa los primeros 72 bytes; truncamos explícitamente para replicar el
# comportamiento previo de passlib y evitar errores con contraseñas muy largas.
def _hash_password(password: str) -> str:
    pw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


@api.post("/auth/register", response_model=User, status_code=201)
async def register(req: RegisterReq):
    email = req.email.lower().strip()
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=409, detail="El email ya está registrado")
    user = UserInDB(email=email, password_hash=_hash_password(req.password))
    await db.users.insert_one(user.model_dump())
    return user


@api.post("/auth/login", response_model=TokenResp)
async def login(req: LoginReq):
    email = req.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if user is None or not _verify_password(req.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    token = _create_access_token(user["id"])
    return TokenResp(access_token=token)


@api.get("/auth/me", response_model=User)
async def me(current_user: dict = Depends(get_current_user)):
    return current_user


@api.get("/usage/me")
async def usage_me(current_user: dict = Depends(get_current_user)):
    """Estado de uso de IA del usuario para mostrar el contador en el frontend.

    Es de solo lectura: refleja el reinicio del periodo si ya ha expirado, pero
    NO consume ni escribe (el reinicio real se hace al consumir)."""
    plan = current_user.get("plan", "free")
    now = datetime.now(timezone.utc)
    gen_used = int(current_user.get("ai_generations_used", 0) or 0)
    corr_used = int(current_user.get("ai_corrections_used", 0) or 0)
    # Desglose por tipo (lectura tolerante: usuarios sin los campos → 0).
    by_type = {t: int(current_user.get(f, 0) or 0) for t, f in _GEN_SUBFIELD.items()}
    period_start = _parse_iso(current_user.get("ai_period_start")) or now

    # Ciclo unificado: si el periodo ya expiró, mostrar TODO como reiniciado.
    if (now - period_start) >= timedelta(days=AI_PERIOD_DAYS):
        gen_used = 0
        corr_used = 0
        by_type = {t: 0 for t in _GEN_SUBFIELD}
        period_start = now

    reset_at = period_start + timedelta(days=AI_PERIOD_DAYS)
    days_until_reset = max(0, (reset_at - now).days)

    def _block(used: int, limit: int) -> dict:
        return {"used": used, "limit": limit, "remaining": max(0, limit - used)}

    gen_limit = _ai_limit(plan, "generation")
    corr_limit = _ai_limit(plan, "correction")
    generations = _block(gen_used, gen_limit)
    # Desglose del agregado "crear material": solo `used` por tipo (el límite es
    # compartido, no hay límite por tipo). Invariante: suma == generations.used.
    generations["by_type"] = {t: {"used": u} for t, u in by_type.items()}
    return {
        "plan": plan,
        "period_start": period_start.isoformat(),
        "days_until_reset": days_until_reset,
        "generations": generations,
        "corrections": _block(corr_used, corr_limit),
        # Retrocompat (= generaciones) para no romper el front durante el deploy.
        "used": gen_used,
        "limit": gen_limit,
        "remaining": max(0, gen_limit - gen_used),
    }


# ---------------------------------------------------------------------------
# Billing (Paddle) — checkout, estado y webhook
# ---------------------------------------------------------------------------
@api.post("/billing/checkout")
async def billing_checkout(current_user: dict = Depends(get_current_user)):
    """Datos que el frontend necesita para abrir el Paddle Overlay Checkout.
    Si el usuario ya es Premium activo, devuelve 409."""
    if _is_premium_active(current_user):
        raise HTTPException(status_code=409, detail="Ya tienes una suscripción Premium activa")
    if not PADDLE_PREMIUM_PRICE_ID:
        raise HTTPException(status_code=500, detail="PADDLE_PREMIUM_PRICE_ID no configurado en el servidor")
    return {
        "price_id": PADDLE_PREMIUM_PRICE_ID,
        "client_token_env": PADDLE_ENV,
        "customer_email": current_user["email"],
        # user_id para inyectarlo como custom_data en el checkout y poder emparejar
        # el webhook por ID propio (sin depender de la resolución por email).
        "user_id": current_user["id"],
    }


@api.get("/billing/status")
async def billing_status(current_user: dict = Depends(get_current_user)):
    """Estado de la suscripción del usuario para el panel de cuenta."""
    sc = current_user.get("subscription_scheduled_change")
    cancel_scheduled = bool(isinstance(sc, dict) and sc.get("action") == "cancel")
    return {
        "plan": current_user.get("plan", "free"),
        "subscription_status": current_user.get("subscription_status", "free"),
        "current_period_end": current_user.get("subscription_current_period_end"),
        "paddle_subscription_id": current_user.get("paddle_subscription_id"),
        # True si hay una cancelación programada (baja a fin de periodo). El usuario
        # sigue premium hasta current_period_end.
        "cancel_scheduled": cancel_scheduled,
    }


@api.post("/billing/portal")
async def billing_portal(current_user: dict = Depends(get_current_user)):
    """Genera un enlace autenticado al customer portal de Paddle para que el usuario
    gestione/cancele su suscripción. Devuelve el deep link de cancelar (o el overview
    general si no hay suscripción). La sesión se crea bajo demanda y no se cachea.

    La cancelación en sí la resuelve Paddle; nuestro webhook (subscription.canceled)
    ya sincroniza el plan a 'free' cuando corresponde."""
    customer_id = current_user.get("paddle_customer_id")
    if not customer_id:
        logger.warning("[PADDLE] portal: usuario %s sin paddle_customer_id", current_user["id"])
        raise HTTPException(
            status_code=409,
            detail="Aún no hay una suscripción de Paddle asociada a tu cuenta.",
        )
    subscription_id = current_user.get("paddle_subscription_id")
    portal_data = await _create_paddle_portal_session(customer_id, subscription_id)
    url = _extract_portal_url(portal_data, subscription_id)
    if not url:
        logger.warning("[PADDLE] portal: respuesta sin URLs utilizables customer=%s", customer_id)
        raise HTTPException(status_code=502, detail="No se pudo obtener el enlace del portal de gestión")
    logger.debug("[PADDLE] portal-session creada user_id=%s customer=%s", current_user["id"], customer_id)
    return {"portal_url": url}


@api.post("/webhooks/paddle")
async def paddle_webhook(request: Request):
    """Recibe los webhooks de Paddle Billing v4.

    - SIN auth ni cuota. Verifica la firma con PADDLE_WEBHOOK_SECRET.
    - Idempotente por event_id (colección paddle_events).
    - Si no encuentra al usuario, responde 200 (log warning) para que Paddle
      no reintente indefinidamente.
    """
    raw = await request.body()
    signature = request.headers.get("Paddle-Signature", "")

    # Log de entrada: qué llegó, antes de verificar la firma (útil para depurar).
    logger.debug(
        "[PADDLE] webhook recibido env=%s body_bytes=%s signature_present=%s secret_present=%s",
        PADDLE_ENV, len(raw), bool(signature), bool(PADDLE_WEBHOOK_SECRET),
    )

    if not _verify_paddle_signature(raw, signature, PADDLE_WEBHOOK_SECRET):
        logger.warning(
            "[PADDLE] firma de webhook inválida signature_present=%s secret_present=%s",
            bool(signature), bool(PADDLE_WEBHOOK_SECRET),
        )
        raise HTTPException(status_code=401, detail="Firma de webhook inválida")

    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="JSON inválido")

    event_id = payload.get("event_id")
    event_type = payload.get("event_type")
    data = payload.get("data") or {}
    logger.debug(
        "[PADDLE] webhook firmado OK event_id=%s type=%s customer_id=%s subscription_id=%s",
        event_id, event_type, data.get("customer_id"), data.get("id") or data.get("subscription_id"),
    )

    # Idempotencia: si ya procesamos este event_id, no repetimos.
    if event_id and await db.paddle_events.find_one({"event_id": event_id}):
        logger.debug("[PADDLE] evento duplicado ignorado event_id=%s type=%s", event_id, event_type)
        return {"ok": True, "duplicate": True}

    # Localizar al usuario. Prioridad: IDs propios/guardados (fiables y sin llamada
    # externa) y, SOLO si todos fallan, el email como fallback (que puede requerir
    # la API de Paddle). Así el emparejamiento no depende de la resolución por email.
    user = None
    matched_by = None

    # 1) custom_data.user_id que inyectamos nosotros en el checkout. Es el método
    #    más robusto: viaja dentro del propio evento (ya firmado por Paddle).
    #    Se valida que sea string no vacío y que EXISTA en users.
    cd_user_id = _extract_custom_user_id(data)
    if cd_user_id:
        user = await db.users.find_one({"id": cd_user_id})
        if user is not None:
            matched_by = "custom_data.user_id"
        else:
            logger.warning(
                "[PADDLE] custom_data.user_id=%s no existe en users event_id=%s type=%s",
                cd_user_id, event_id, event_type,
            )

    # 2) subscription_id ya guardado en un usuario.
    if user is None and data.get("id"):
        user = await db.users.find_one({"paddle_subscription_id": data["id"]})
        if user is not None:
            matched_by = "paddle_subscription_id(data.id)"
    if user is None and data.get("subscription_id"):
        user = await db.users.find_one({"paddle_subscription_id": data["subscription_id"]})
        if user is not None:
            matched_by = "paddle_subscription_id(data.subscription_id)"

    # 3) customer_id ya guardado en un usuario.
    if user is None and data.get("customer_id"):
        user = await db.users.find_one({"paddle_customer_id": data["customer_id"]})
        if user is not None:
            matched_by = "paddle_customer_id"

    # 4) Fallback final: email. Solo se resuelve (posible llamada a la API de
    #    Paddle) si los IDs anteriores no emparejaron.
    email = None
    if user is None:
        email = await _resolve_customer_email(data)
        if email:
            user = await db.users.find_one({"email": email.lower().strip()})
            if user is not None:
                matched_by = "email"
        else:
            logger.warning(
                "[PADDLE] no se pudo resolver email (fallback) event_id=%s type=%s customer_id=%s",
                event_id, event_type, data.get("customer_id"),
            )

    if user is None:
        logger.warning(
            "[PADDLE] usuario no encontrado event_id=%s type=%s email=%s custom_data.user_id=%s "
            "intentos_ids: sub_id(data.id)=%s subscription_id=%s customer_id=%s",
            event_id, event_type, email, cd_user_id,
            data.get("id"), data.get("subscription_id"), data.get("customer_id"),
        )
        if event_id:
            await db.paddle_events.insert_one(
                {"event_id": event_id, "event_type": event_type, "user_id": None, "processed_at": _now_iso()}
            )
        return {"ok": True, "user_found": False}

    logger.debug(
        "[PADDLE] usuario emparejado por=%s user_id=%s event_id=%s type=%s",
        matched_by, user["id"], event_id, event_type,
    )

    await _apply_paddle_event(user, event_type, data)

    if event_id:
        await db.paddle_events.insert_one(
            {"event_id": event_id, "event_type": event_type, "user_id": user["id"], "processed_at": _now_iso()}
        )
    logger.debug("[PADDLE] procesado event_id=%s type=%s user_id=%s", event_id, event_type, user["id"])
    return {"ok": True}


# --- CORS ---
_BASELINE_ORIGINS = [
    "https://impartial-passion-production-9090.up.railway.app",
]
_raw = os.environ.get("CORS_ORIGINS", "*")
_env_origins = [o.strip() for o in _raw.split(",") if o.strip()]
_allow_all = "*" in _env_origins
_explicit_origins = sorted({*(o for o in _env_origins if o != "*"), *_BASELINE_ORIGINS})

if _allow_all:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=".*",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info("[CORS] allow_origin_regex=.* (wildcard) baseline_extra=%s", _BASELINE_ORIGINS)
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_explicit_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info("[CORS] explicit origins=%s", _explicit_origins)


# Reintentos del arranque: acotados y parametrizables (los tests inyectan valores
# reducidos y un `sleep` falso para recorrer el camino de fallo sin esperas reales).
STARTUP_INDEX_ATTEMPTS = int(os.environ.get("STARTUP_INDEX_ATTEMPTS", "3"))
STARTUP_INDEX_BACKOFF_SECONDS = float(os.environ.get("STARTUP_INDEX_BACKOFF_SECONDS", "2"))


async def ensure_indices():
    """Crea los índices. PROPAGA el error si no puede: un backend sin sus índices
    (p. ej. sin el único de `users.email`) es peor que uno que no arranca, porque
    admite datos corruptos —emails duplicados— sin que nadie se entere. Incidente
    del 2026-08-28: credenciales de Atlas inválidas, WARNING silencioso y servicio
    "arrancado" con todas las operaciones de BD dando 500."""
    try:
        await db.users.create_index("id", unique=True)
        await db.users.create_index("email", unique=True)
        # Subjects
        await db.subjects.create_index("id", unique=True)
        await db.subjects.create_index([("user_id", 1), ("id", 1)])
        # Topics
        await db.topics.create_index("id", unique=True)
        await db.topics.create_index("subject_id")
        await db.topics.create_index([("user_id", 1), ("id", 1)])
        await db.topics.create_index([("user_id", 1), ("subject_id", 1)])
        # PDFs (la atadura a temas vive en pdf_links, no en pdfs.topic_id)
        await db.pdfs.create_index("id", unique=True)
        await db.pdfs.create_index([("user_id", 1), ("id", 1)])
        # PDF links (relación muchos-a-muchos PDF<->tema)
        await db.pdf_links.create_index("id", unique=True)
        await db.pdf_links.create_index([("user_id", 1), ("topic_id", 1)])
        await db.pdf_links.create_index([("user_id", 1), ("pdf_id", 1)])
        # Único: evita duplicar la misma asociación y da idempotencia a la migración.
        await db.pdf_links.create_index(
            [("user_id", 1), ("pdf_id", 1), ("topic_id", 1)], unique=True
        )
        # Questions
        await db.questions.create_index("id", unique=True)
        await db.questions.create_index("topic_id")
        await db.questions.create_index("subject_id")
        await db.questions.create_index("pdf_source_id")
        await db.questions.create_index("favorite")
        await db.questions.create_index("difficult")
        await db.questions.create_index("srs_next_review")
        await db.questions.create_index("question_type")
        await db.questions.create_index([("times_answered", 1), ("times_correct", 1)])
        await db.questions.create_index([("user_id", 1), ("id", 1)])
        await db.questions.create_index([("user_id", 1), ("subject_id", 1)])
        await db.questions.create_index([("user_id", 1), ("topic_id", 1)])
        await db.questions.create_index([("user_id", 1), ("pdf_source_id", 1)])
        # Banco de preguntas: orden por reciente y filtro por tipo (con user_id).
        await db.questions.create_index([("user_id", 1), ("created_at", -1)])
        await db.questions.create_index([("user_id", 1), ("question_type", 1)])
        # Attempts
        await db.attempts.create_index("id", unique=True)
        await db.attempts.create_index([("created_at", -1)])
        await db.attempts.create_index("streak_day")
        await db.attempts.create_index([("user_id", 1), ("id", 1)])
        await db.attempts.create_index([("user_id", 1), ("created_at", -1)])
        await db.attempts.create_index([("user_id", 1), ("streak_day", 1)])
        # Flashcards
        await db.flashcards.create_index("id", unique=True)
        await db.flashcards.create_index("topic_id")
        await db.flashcards.create_index("subject_id")
        await db.flashcards.create_index("srs_next_review")
        await db.flashcards.create_index([("user_id", 1), ("id", 1)])
        await db.flashcards.create_index([("user_id", 1), ("topic_id", 1)])
        await db.flashcards.create_index([("user_id", 1), ("subject_id", 1)])
        # Summaries (resúmenes de IA persistidos, por PDF). Sin índice único en
        # (pdf, scope): el "1 por PDF" se impone por app (upsert), dejando el
        # modelo abierto a scope="topic" / varios por PDF en el futuro.
        await db.summaries.create_index("id", unique=True)
        await db.summaries.create_index([("user_id", 1), ("pdf_id", 1)])
        await db.summaries.create_index([("user_id", 1), ("pdf_id", 1), ("scope", 1)])
        # Survival records — la unicidad ahora es por (user_id, scope_type, scope_id)
        await db.survival_records.create_index("id", unique=True)
        await db.survival_records.create_index("score")
        await db.survival_records.create_index([("user_id", 1), ("id", 1)])
        await db.survival_records.create_index(
            [("user_id", 1), ("scope_type", 1), ("scope_id", 1)], unique=True
        )
        # Eliminar el antiguo índice único global (scope_type, scope_id) si existe:
        # en multiusuario impediría que dos usuarios tuvieran récord del mismo scope.
        try:
            await db.survival_records.drop_index("scope_type_1_scope_id_1")
        except Exception:
            pass
        logger.info("MongoDB indices ensured.")
    except Exception:
        # Traza completa: el WARNING de una línea del incidente no permitía ver
        # que la causa era de credenciales/conexión.
        logger.exception("ensure_indices failed: no se pudieron crear los índices")
        raise


async def ensure_indices_with_retry(attempts=None, backoff_seconds=None, sleep=None):
    """Ejecuta `ensure_indices` con reintentos ACOTADOS (nunca en bucle infinito).

    Un fallo transitorio de red al arrancar no debe tumbar el servicio, pero uno
    persistente SÍ: si se agotan los intentos, lanza y el arranque falla (uvicorn
    sale y Railway reinicia / lo marca no saludable). `attempts`, `backoff_seconds`
    y `sleep` son inyectables para poder testear el camino de fallo sin esperas."""
    attempts = STARTUP_INDEX_ATTEMPTS if attempts is None else attempts
    attempts = max(1, int(attempts))
    backoff = STARTUP_INDEX_BACKOFF_SECONDS if backoff_seconds is None else backoff_seconds
    sleeper = asyncio.sleep if sleep is None else sleep

    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            await ensure_indices()
            return
        except Exception as e:
            last_error = e
            logger.error("ensure_indices: intento %d/%d fallido: %s", attempt, attempts, e)
            if attempt < attempts:
                await sleeper(backoff)

    logger.critical(
        "ensure_indices: agotados %d intentos; el arranque FALLA a propósito "
        "(un backend sin índices puede corromper datos en silencio).", attempts
    )
    raise RuntimeError(
        f"No se pudieron crear los índices de MongoDB tras {attempts} intentos"
    ) from last_error


@app.on_event("startup")
async def startup_ensure_indices():
    """Punto de arranque: si los índices no se pueden crear, NO arrancamos."""
    await ensure_indices_with_retry()


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()


# ---------------------------------------------------------------------------
# Survival Mode Records
# ---------------------------------------------------------------------------
class SurvivalRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    scope_type: Literal["topic", "subject"]  # topic or subject
    scope_id: str
    scope_name: str
    score: int
    questions_answered: int
    lives_lost: int
    question_type: str  # mcq, tf, any
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@api.get("/survival/records")
async def get_survival_records(current_user: dict = Depends(get_current_user)):
    """Get all survival mode records."""
    records = await db.survival_records.find({"user_id": current_user["id"]}, {"_id": 0}).sort("score", -1).to_list(500)
    return records


@api.get("/survival/records/{scope_type}/{scope_id}")
async def get_survival_record(scope_type: str, scope_id: str, current_user: dict = Depends(get_current_user)):
    """Get best record for a topic or subject."""
    record = await db.survival_records.find_one(
        {"scope_type": scope_type, "scope_id": scope_id, "user_id": current_user["id"]},
        {"_id": 0}
    )
    return record or {}


class SaveSurvivalRecordReq(BaseModel):
    scope_type: Literal["topic", "subject"]
    scope_id: str
    scope_name: str
    score: int
    questions_answered: int
    lives_lost: int
    question_type: str


@api.post("/survival/records")
async def save_survival_record(req: SaveSurvivalRecordReq, current_user: dict = Depends(get_current_user)):
    """Save survival record only if it beats the current best."""
    uid = current_user["id"]
    existing = await db.survival_records.find_one(
        {"scope_type": req.scope_type, "scope_id": req.scope_id, "user_id": uid},
        {"_id": 0}
    )
    if existing and existing["score"] >= req.score:
        return {"saved": False, "best_score": existing["score"], "new_record": False}

    record = SurvivalRecord(
        user_id=uid,
        scope_type=req.scope_type,
        scope_id=req.scope_id,
        scope_name=req.scope_name,
        score=req.score,
        questions_answered=req.questions_answered,
        lives_lost=req.lives_lost,
        question_type=req.question_type,
    )
    if existing:
        await db.survival_records.replace_one(
            {"scope_type": req.scope_type, "scope_id": req.scope_id, "user_id": uid},
            record.model_dump()
        )
    else:
        await db.survival_records.insert_one(record.model_dump())

    return {"saved": True, "best_score": req.score, "new_record": True}


# ---------------------------------------------------------------------------
# AI Summaries (persistidos, por PDF)
# ---------------------------------------------------------------------------
async def _gemini_summary_content(text: str) -> dict:
    """Llama a Gemini para resumir el texto de UN PDF y devuelve el JSON tal cual.

    Reutiliza el mismo system_msg y prompt del resumen histórico. NO pasa el
    nombre del PDF: los nombres de fichero son ruidosos ("Tema_3_v2_FINAL (1).pdf")
    y el texto es la única fuente de verdad; un título malo solo despistaría. (El
    prompt viejo usaba el nombre del TEMA, que sí era limpio y curado.) No gestiona
    cuota: de eso se encarga el endpoint (comprobar/consumir/reembolsar)."""
    combined = (text or "")[:80000]
    system_msg = (
        "Eres un profesor experto. Genera un resumen estructurado y esquemático del temario. "
        "Usa el vocabulario exacto del texto. Responde SIEMPRE en español. "
        "Devuelve SOLO JSON válido."
    )
    prompt = f"""Resume el siguiente temario de forma estructurada.

Devuelve SOLO este JSON:
{{
  "overview": "párrafo introductorio de 2-3 frases resumiendo el tema",
  "key_concepts": [
    {{"concept": "nombre del concepto", "explanation": "explicación breve de 1-2 frases"}}
  ],
  "sections": [
    {{"title": "título de sección", "points": ["punto clave 1", "punto clave 2"]}}
  ],
  "remember": ["dato clave para recordar 1", "dato clave 2", "dato clave 3"]
}}

Incluye 5-8 conceptos clave, 3-5 secciones con 3-5 puntos cada una, y 3-5 datos para recordar.

TEMARIO:
\"\"\"
{combined}
\"\"\"
"""
    response = await gemini_client.aio.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            system_instruction=system_msg,
            response_mime_type="application/json",
            temperature=0.3,
        ),
    )
    _log_gemini_usage("summary", response)
    raw = _strip_code_fences(response.text or "")
    return json.loads(raw)


@api.post("/pdfs/{pdf_id}/summary")
async def generate_pdf_summary(pdf_id: str, current_user: dict = Depends(get_current_user)):
    """Genera (o regenera) el resumen de UN PDF y lo persiste.

    El resumen se keyea por pdf_id (scope="pdf") y es compartido por todos los
    temas que contengan ese PDF. Regenerar sobrescribe. Consume 1 generación de
    cuota (comprobada ANTES; reembolsada si Gemini falla)."""
    uid = current_user["id"]
    pdf = await db.pdfs.find_one({"id": pdf_id, "user_id": uid}, {"_id": 0})
    if not pdf:
        raise HTTPException(status_code=404, detail="PDF no encontrado")
    if not GEMINI_API_KEY or gemini_client is None:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY no configurada")

    # Comprobar plan + cuota ANTES de llamar a Gemini.
    await check_and_consume_ai_quota(current_user, gen_kind="summaries")
    try:
        content = await _gemini_summary_content(pdf.get("text", ""))
    except Exception as e:
        await _refund_ai_quota(current_user, gen_kind="summaries")
        logger.error("Summary generation error: %s", e)
        raise HTTPException(status_code=502, detail="Error al generar el resumen")

    now = datetime.now(timezone.utc).isoformat()
    new_doc = Summary(user_id=uid, pdf_id=pdf_id, content=content)
    # Upsert: 1 resumen por (user, pdf, scope). Regenerar sobrescribe content.
    await db.summaries.update_one(
        {"user_id": uid, "pdf_id": pdf_id, "scope": "pdf"},
        {
            "$set": {"content": content, "updated_at": now},
            "$setOnInsert": {
                "id": new_doc.id,
                "user_id": uid,
                "pdf_id": pdf_id,
                "scope": "pdf",
                "created_at": now,
            },
        },
        upsert=True,
    )
    return await db.summaries.find_one(
        {"user_id": uid, "pdf_id": pdf_id, "scope": "pdf"}, {"_id": 0}
    )


@api.get("/pdfs/{pdf_id}/summary")
async def get_pdf_summary(pdf_id: str, current_user: dict = Depends(get_current_user)):
    """Resumen cacheado de un PDF (coste 0). 404 si aún no se ha generado."""
    uid = current_user["id"]
    s = await db.summaries.find_one(
        {"user_id": uid, "pdf_id": pdf_id, "scope": "pdf"}, {"_id": 0}
    )
    if not s:
        raise HTTPException(status_code=404, detail="Este PDF no tiene resumen")
    return s


@api.get("/topics/{topic_id}/summaries")
async def list_topic_summaries(topic_id: str, current_user: dict = Depends(get_current_user)):
    """Resúmenes cacheados de los PDFs de un tema (coste 0), para pintar TopicDetail.
    "Los resúmenes de un tema" = los de sus PDFs (resueltos con _topic_pdf_ids)."""
    uid = current_user["id"]
    topic = await db.topics.find_one({"id": topic_id, "user_id": uid}, {"_id": 0})
    if not topic:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    pdf_ids = await _topic_pdf_ids(uid, topic_id)
    if not pdf_ids:
        return []
    return await db.summaries.find(
        {"user_id": uid, "pdf_id": {"$in": pdf_ids}, "scope": "pdf"}, {"_id": 0}
    ).to_list(200)


@api.get("/summaries")
async def list_all_summaries(current_user: dict = Depends(get_current_user)):
    """Lista global de TODOS los resúmenes del usuario (coste 0), para la pestaña
    Resúmenes de Biblioteca.

    Un resumen se keyea por pdf_id y es compartido: sus asignaturas/temas se
    DERIVAN vía pdf_links (no hay topic_id en el summary), así que un mismo
    resumen puede pertenecer a varias. Cada fila incluye nombre de PDF, la lista
    de subjects/topics, el content y las fechas. Ordenado por updated_at desc."""
    uid = current_user["id"]
    sums = await db.summaries.find(
        {"user_id": uid, "scope": "pdf"}, {"_id": 0}
    ).to_list(2000)
    if not sums:
        return []

    pdf_ids = list({s["pdf_id"] for s in sums})
    pdfs = await db.pdfs.find(
        {"user_id": uid, "id": {"$in": pdf_ids}}, {"_id": 0, "id": 1, "filename": 1}
    ).to_list(2000)
    fname = {p["id"]: p["filename"] for p in pdfs}

    links = await db.pdf_links.find(
        {"user_id": uid, "pdf_id": {"$in": pdf_ids}}, {"_id": 0}
    ).to_list(10000)
    subj_ids = list({l["subject_id"] for l in links if l.get("subject_id")})
    topic_ids = list({l["topic_id"] for l in links})
    subjects = await db.subjects.find(
        {"user_id": uid, "id": {"$in": subj_ids}}, {"_id": 0, "id": 1, "name": 1}
    ).to_list(2000)
    topics = await db.topics.find(
        {"user_id": uid, "id": {"$in": topic_ids}}, {"_id": 0, "id": 1, "name": 1}
    ).to_list(4000)
    sname = {s["id"]: s["name"] for s in subjects}
    tname = {t["id"]: t["name"] for t in topics}

    # Agrupa asignaturas/temas por pdf_id (dedup con dict {id: name}).
    by_pdf_subj: dict = {}
    by_pdf_topic: dict = {}
    for l in links:
        pid = l["pdf_id"]
        if l.get("subject_id"):
            by_pdf_subj.setdefault(pid, {})[l["subject_id"]] = sname.get(l["subject_id"])
        by_pdf_topic.setdefault(pid, {})[l["topic_id"]] = tname.get(l["topic_id"])

    out = []
    for s in sums:
        pid = s["pdf_id"]
        out.append({
            "id": s["id"],
            "pdf_id": pid,
            "pdf_filename": fname.get(pid),
            "subjects": [{"id": k, "name": v} for k, v in by_pdf_subj.get(pid, {}).items()],
            "topics": [{"id": k, "name": v} for k, v in by_pdf_topic.get(pid, {}).items()],
            "content": s["content"],
            "created_at": s.get("created_at"),
            "updated_at": s.get("updated_at"),
        })
    out.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
    return out


# ---------------------------------------------------------------------------
# Gap Detector
# ---------------------------------------------------------------------------
@api.get("/stats/gaps")
async def get_knowledge_gaps(current_user: dict = Depends(get_current_user)):
    """Identify topics and questions with accuracy below 60%."""
    uid = current_user["id"]
    # 3 consultas fijas (antes: 1 + una agregación por tema, N+1): temas,
    # agregación por tema de las preguntas practicadas, y preguntas débiles.
    topics, agg, weak_questions = await asyncio.gather(
        db.topics.find({"user_id": uid}, {"_id": 0}).to_list(2000),
        db.questions.aggregate([
            {"$match": {"user_id": uid, "times_answered": {"$gt": 2}}},
            {"$group": {"_id": "$topic_id", "ans": {"$sum": "$times_answered"}, "ok": {"$sum": "$times_correct"}, "total": {"$sum": 1}}},
        ]).to_list(None),
        db.questions.find(
            # Preguntas con <50% de acierto. Se compara SIN dividir
            # (2*ok < ans  ⟺  ok/ans < 0.5) para evitar el "can't $divide by
            # zero" de Mongo: el $expr se evalúa en el escaneo sin garantía de
            # cortocircuitar times_answered>2, así que dividir por times_answered
            # rompía con las preguntas sin responder (times_answered=0).
            {"user_id": uid, "times_answered": {"$gt": 2},
             "$expr": {"$lt": [{"$multiply": ["$times_correct", 2]}, "$times_answered"]}},
            {"_id": 0, "id": 1, "question": 1, "topic_name": 1, "times_answered": 1, "times_correct": 1}
        ).sort([("times_answered", -1)]).to_list(20),
    )

    tmap = {t["id"]: t for t in topics}
    weak_topics = []
    for r in agg:
        if r["ans"] <= 0:
            continue
        accuracy = round(100 * r["ok"] / r["ans"], 1)
        if accuracy >= 60:
            continue
        t = tmap.get(r["_id"])
        if not t:
            continue
        weak_topics.append({
            "topic_id": t["id"],
            "topic_name": t["name"],
            "subject_id": t.get("subject_id"),
            "accuracy": accuracy,
            "answered": r["ans"],
            "total_questions": r["total"],
        })

    for q in weak_questions:
        q["accuracy"] = round(100 * q["times_correct"] / q["times_answered"], 1) if q["times_answered"] else 0

    weak_topics.sort(key=lambda x: x["accuracy"])
    return {"weak_topics": weak_topics[:10], "weak_questions": weak_questions}


# ---------------------------------------------------------------------------
# Register router — DEBE ir al final, tras definir TODOS los endpoints, porque
# FastAPI hace un snapshot de las rutas en include_router (cualquier @api.* que
# se declare después no quedaría registrado).
# ---------------------------------------------------------------------------
app.include_router(api)
