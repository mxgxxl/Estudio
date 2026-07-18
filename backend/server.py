"""
Anatomía - Backend
FastAPI + MongoDB + Google Gemini (google-genai SDK)
"""
import os
import io
import re
import json
import hmac
import hashlib
import uuid
import logging
import random
import httpx
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Literal

from fastapi import FastAPI, APIRouter, UploadFile, File, Form, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr
from passlib.context import CryptContext
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
# Duración del periodo: mes natural rodante de 30 días.
AI_PERIOD_DAYS = 30

# Paddle (Billing v4) — pasarela de pagos. Por defecto en sandbox.
PADDLE_ENV = os.environ.get("PADDLE_ENV", "sandbox")
PADDLE_API_KEY = os.environ.get("PADDLE_API_KEY", "")
PADDLE_WEBHOOK_SECRET = os.environ.get("PADDLE_WEBHOOK_SECRET", "")
PADDLE_PREMIUM_PRICE_ID = os.environ.get("PADDLE_PREMIUM_PRICE_ID", "")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
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
    "[AI-LIMITS] free=%s/mes premium=%s/mes period_days=%s",
    FREE_AI_GENERATIONS_PER_MONTH, PREMIUM_AI_GENERATIONS_PER_MONTH, AI_PERIOD_DAYS,
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
    topic_id: str
    filename: str
    text: str
    char_count: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


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
    mode: Literal["exam", "practice", "errors", "srs", "favorites"]
    subject_ids: List[str] = []
    topic_ids: List[str] = []
    question_ids: List[str]
    answers: List[int]
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


def _ai_limit_for_plan(plan: Optional[str]) -> int:
    """Límite de generaciones de IA por periodo según el plan."""
    if plan == "premium":
        return PREMIUM_AI_GENERATIONS_PER_MONTH
    return FREE_AI_GENERATIONS_PER_MONTH


async def check_and_consume_ai_quota(user: dict, cost: int = 1) -> dict:
    """Comprueba el plan y la cuota mensual de IA del usuario y consume `cost`.

    - Reinicia el periodo (used=0, period_start=now) si han pasado >= AI_PERIOD_DAYS
      desde ai_period_start, ANTES de comprobar el límite.
    - Si used + cost supera el límite del plan, lanza HTTPException 402.
    - Si pasa, incrementa `ai_generations_used` de forma atómica ($inc) y devuelve
      el estado {used, limit, remaining, period_start, plan}.

    OBLIGATORIO: invocar esta función antes de CUALQUIER llamada a Gemini.
    """
    uid = user["id"]
    plan = user.get("plan", "free")
    limit = _ai_limit_for_plan(plan)

    now = datetime.now(timezone.utc)
    used = int(user.get("ai_generations_used", 0) or 0)
    period_start = _parse_iso(user.get("ai_period_start"))

    # Reinicio del periodo si procede (o si nunca se inicializó).
    if period_start is None or (now - period_start) >= timedelta(days=AI_PERIOD_DAYS):
        used = 0
        period_start = now
        await db.users.update_one(
            {"id": uid},
            {"$set": {"ai_generations_used": 0, "ai_period_start": now.isoformat()}},
        )

    if used + cost > limit:
        raise HTTPException(
            status_code=402,
            detail="Has alcanzado el límite de generaciones de IA de este mes para tu plan",
        )

    # Consumo atómico.
    await db.users.update_one({"id": uid}, {"$inc": {"ai_generations_used": cost}})
    new_used = used + cost
    return {
        "used": new_used,
        "limit": limit,
        "remaining": max(0, limit - new_used),
        "period_start": period_start.isoformat(),
        "plan": plan,
    }


async def _refund_ai_quota(user: dict, cost: int = 1) -> None:
    """Revierte un consumo previo (p. ej. si la llamada a Gemini falló).
    No debe penalizarse al usuario por un fallo nuestro."""
    try:
        await db.users.update_one({"id": user["id"]}, {"$inc": {"ai_generations_used": -cost}})
    except Exception as e:  # pragma: no cover - best effort
        logger.error("No se pudo revertir la cuota de IA del usuario %s: %s", user.get("id"), e)


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
        logger.debug(
            "[PADDLE] _apply_paddle_event type=%s status=%s -> plan=%s user_id=%s",
            event_type, status, updates.get("plan"), user["id"],
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
    res = await db.subjects.delete_one({"id": subject_id, "user_id": uid})
    await db.topics.delete_many({"subject_id": subject_id, "user_id": uid})
    await db.questions.delete_many({"subject_id": subject_id, "user_id": uid})
    if topic_ids:
        await db.pdfs.delete_many({"topic_id": {"$in": topic_ids}, "user_id": uid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Asignatura no encontrada")
    return {"ok": True}


@api.get("/subjects/{subject_id}/topics")
async def list_topics_for_subject(subject_id: str, current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    s = await db.subjects.find_one({"id": subject_id, "user_id": uid}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Asignatura no encontrada")
    topics = await db.topics.find({"subject_id": subject_id, "user_id": uid}, {"_id": 0}).sort("created_at", 1).to_list(1000)
    for t in topics:
        t["question_count"] = await db.questions.count_documents({"user_id": uid, "topic_id": t["id"]})
        t["answered_count"] = await db.questions.count_documents({"user_id": uid, "topic_id": t["id"], "times_answered": {"$gt": 0}})
        agg = await db.questions.aggregate([
            {"$match": {"user_id": uid, "topic_id": t["id"]}},
            {"$group": {"_id": None, "ans": {"$sum": "$times_answered"}, "ok": {"$sum": "$times_correct"}}},
        ]).to_list(1)
        t["accuracy"] = round(100 * agg[0]["ok"] / agg[0]["ans"], 1) if agg and agg[0]["ans"] else 0.0
        t["pdf_count"] = await db.pdfs.count_documents({"user_id": uid, "topic_id": t["id"]})
    return topics


# ---- Topics ----
@api.get("/topics")
async def list_topics(current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    topics = await db.topics.find({"user_id": uid}, {"_id": 0}).sort("created_at", 1).to_list(2000)
    for t in topics:
        t["question_count"] = await db.questions.count_documents({"user_id": uid, "topic_id": t["id"]})
        t["answered_count"] = await db.questions.count_documents({"user_id": uid, "topic_id": t["id"], "times_answered": {"$gt": 0}})
        agg = await db.questions.aggregate([
            {"$match": {"user_id": uid, "topic_id": t["id"]}},
            {"$group": {"_id": None, "ans": {"$sum": "$times_answered"}, "ok": {"$sum": "$times_correct"}}},
        ]).to_list(1)
        t["accuracy"] = round(100 * agg[0]["ok"] / agg[0]["ans"], 1) if agg and agg[0]["ans"] else 0.0
    return topics


@api.get("/topics/{topic_id}")
async def get_topic(topic_id: str, current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    t = await db.topics.find_one({"id": topic_id, "user_id": uid}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    t["question_count"] = await db.questions.count_documents({"user_id": uid, "topic_id": topic_id})
    t["pdf_count"] = await db.pdfs.count_documents({"user_id": uid, "topic_id": topic_id})
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
    pdfs = await db.pdfs.find({"topic_id": topic_id, "user_id": uid}, {"_id": 0}).to_list(100)
    if not pdfs:
        raise HTTPException(status_code=404, detail="No hay PDFs para este tema")
    parts = []
    for p in pdfs:
        parts.append(f"=== {p['filename']} ===\n{p['text']}")
    return {"topic_id": topic_id, "text": "\n\n".join(parts), "sources": [p["filename"] for p in pdfs]}


@api.post("/subjects/{subject_id}/topics/upload")
async def upload_topic_pdf(
    subject_id: str,
    name: str = Form(...),
    num_questions: int = Form(20),
    question_type: str = Form("mcq"),
    num_options: int = Form(3),
    custom_instructions: str = Form(""),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    uid = current_user["id"]
    subj = await db.subjects.find_one({"id": subject_id, "user_id": uid}, {"_id": 0})
    if not subj:
        raise HTTPException(status_code=404, detail="Asignatura no encontrada")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan ficheros PDF")
    if num_questions < 3 or num_questions > 80:
        raise HTTPException(status_code=400, detail="num_questions debe estar entre 3 y 80")
    qtype = question_type if question_type in ("mcq", "tf", "dev") else "mcq"
    nopts = max(2, min(5, int(num_options))) if qtype == "mcq" else 2

    pdf_bytes = await file.read()
    try:
        text = extract_pdf_text(pdf_bytes)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al leer el PDF: {e}") from e

    if len(text) < 200:
        raise HTTPException(status_code=400, detail="El PDF no contiene suficiente texto extraíble")

    # Comprobar plan + cuota ANTES de cualquier llamada a Gemini.
    await check_and_consume_ai_quota(current_user)

    topic = Topic(
        user_id=uid,
        subject_id=subject_id,
        name=name.strip(),
        description=f"Generado desde {file.filename}",
    )
    await db.topics.insert_one(topic.model_dump())

    pdf_source = PdfSource(
        user_id=uid,
        topic_id=topic.id,
        filename=file.filename,
        text=text,
        char_count=len(text),
    )
    await db.pdfs.insert_one(pdf_source.model_dump())

    try:
        generated = await generate_questions_with_claude(
            topic.name, text, num_questions, question_type=qtype, num_options=nopts,
            custom_instructions=custom_instructions or "",
        )
    except Exception:
        await _refund_ai_quota(current_user)
        await db.topics.delete_one({"id": topic.id})
        await db.pdfs.delete_one({"id": pdf_source.id})
        raise

    if not generated:
        await _refund_ai_quota(current_user)
        await db.topics.delete_one({"id": topic.id})
        await db.pdfs.delete_one({"id": pdf_source.id})
        raise HTTPException(status_code=502, detail="La IA no generó preguntas válidas")

    docs = []
    for g in generated:
        q = Question(
            user_id=uid,
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
            model_answer=g.get("model_answer", ""),
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
async def delete_topic(topic_id: str, current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    res = await db.topics.delete_one({"id": topic_id, "user_id": uid})
    await db.questions.delete_many({"topic_id": topic_id, "user_id": uid})
    await db.pdfs.delete_many({"topic_id": topic_id, "user_id": uid})
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
@api.get("/topics/{topic_id}/pdfs")
async def list_topic_pdfs(topic_id: str, current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    topic = await db.topics.find_one({"id": topic_id, "user_id": uid}, {"_id": 0})
    if not topic:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    pdfs = await db.pdfs.find({"topic_id": topic_id, "user_id": uid}, {"_id": 0, "text": 0}).sort("created_at", 1).to_list(100)
    for p in pdfs:
        p["question_count"] = await db.questions.count_documents({"user_id": uid, "pdf_source_id": p["id"]})
    return pdfs


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
    topic = await db.topics.find_one({"id": pdf["topic_id"], "user_id": uid}, {"_id": 0})
    if not topic:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    if req.num_questions < 3 or req.num_questions > 80:
        raise HTTPException(status_code=400, detail="num_questions debe estar entre 3 y 80")

    nopts = max(2, min(5, int(req.num_options))) if req.question_type == "mcq" else 2
    # Comprobar plan + cuota ANTES de llamar a Gemini.
    await check_and_consume_ai_quota(current_user)
    try:
        generated = await generate_questions_with_claude(
            topic["name"], pdf["text"], req.num_questions, question_type=req.question_type, num_options=nopts
        )
    except Exception:
        await _refund_ai_quota(current_user)
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
    uid = current_user["id"]
    res = await db.pdfs.delete_one({"id": pdf_id, "user_id": uid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="PDF no encontrado")
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

    pdfs = await db.pdfs.find(
        {"id": {"$in": req.pdf_ids}, "topic_id": topic_id, "user_id": uid}, {"_id": 0}
    ).to_list(100)
    if not pdfs:
        raise HTTPException(status_code=404, detail="No se encontraron PDFs")

    parts = []
    for p in pdfs:
        parts.append(f"=== Fuente: {p['filename']} ===\n{p['text']}")
    combined = "\n\n".join(parts)

    nopts = max(2, min(5, int(req.num_options))) if req.question_type == "mcq" else 2
    # Comprobar plan + cuota ANTES de llamar a Gemini.
    await check_and_consume_ai_quota(current_user)
    try:
        generated = await generate_questions_with_claude(
            topic["name"], combined, req.num_questions,
            question_type=req.question_type, num_options=nopts,
            custom_instructions=req.custom_instructions or "",
        )
    except Exception:
        await _refund_ai_quota(current_user)
        raise

    primary_pdf_id = pdfs[0]["id"]
    docs = []
    for g in generated:
        q = Question(
            user_id=uid,
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
            model_answer=g.get("model_answer", ""),
        )
        docs.append(q.model_dump())
    if docs:
        await db.questions.insert_many(docs)
    return {"questions_created": len(docs), "pdf_ids_used": [p["id"] for p in pdfs]}


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

    # Comprobar plan + cuota ANTES de llamar a Gemini.
    await check_and_consume_ai_quota(current_user)
    result = await evaluate_dev_answer(
        q["question"],
        q.get("model_answer", ""),
        req.user_answer,
        q.get("explanation", ""),
    )
    # evaluate_dev_answer no lanza: si falló internamente, revertir el consumo.
    if result.pop("_ai_error", False):
        await _refund_ai_quota(current_user)
    return result


# ---- Quiz ----
class QuizStartReq(BaseModel):
    mode: Literal["exam", "practice", "errors", "srs", "favorites"]
    subject_ids: List[str] = []
    topic_ids: List[str] = []
    num_questions: int = 20
    time_limit_minutes: Optional[int] = None
    question_type: Optional[Literal["mcq", "tf", "dev", "any"]] = "any"
    num_options: Optional[int] = None


@api.post("/quiz/start")
async def quiz_start(req: QuizStartReq, current_user: dict = Depends(get_current_user)):
    query: dict = {"user_id": current_user["id"]}
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
    return {"questions": payload, "mode": req.mode}


class QuizSubmitReq(BaseModel):
    mode: Literal["exam", "practice", "errors", "srs", "favorites"]
    subject_ids: List[str] = []
    topic_ids: List[str] = []
    answers: List[dict]
    duration_seconds: int
    time_limit_seconds: Optional[int] = None
    penalty_factor: Optional[int] = None
    question_type: Optional[str] = None


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
    correct = 0
    wrong = 0
    unanswered = 0
    total = len(req.answers)
    for a in req.answers:
        qid = a.get("question_id")
        selected = int(a.get("selected", -1))
        correct_index = int(a.get("correct_index", -1))
        qtype = a.get("question_type", "mcq")

        if selected == -1 and qtype != "dev":
            unanswered += 1
            continue

        if qtype == "dev":
            # Dev answers are evaluated separately; count as answered
            dev_score = float(a.get("dev_score", 0))
            is_correct = dev_score >= 5
        else:
            is_correct = selected == correct_index

        if is_correct:
            correct += 1
        else:
            wrong += 1

        q = await db.questions.find_one({"id": qid, "user_id": uid}, {"_id": 0})
        if not q:
            continue
        update = {
            "$inc": {"times_answered": 1, **(({"times_correct": 1}) if is_correct else {})},
            "$set": {
                "last_answered_at": _now_iso(),
                "last_correct": is_correct,
                **_update_srs(q, is_correct),
            },
        }
        await db.questions.update_one({"id": qid, "user_id": uid}, update)

    pf = req.penalty_factor
    if pf and pf > 0:
        raw = correct - (wrong / pf)
    else:
        raw = float(correct)
    if raw < 0:
        raw = 0.0
    score_10 = round((raw / total) * 10, 2) if total else 0.0
    raw_score = round(raw, 3)

    today = datetime.now(timezone.utc).date().isoformat()
    attempt = Attempt(
        user_id=uid,
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
    }


# ---- Stats ----
@api.get("/stats")
async def stats_overview(current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    total_subjects = await db.subjects.count_documents({"user_id": uid})
    total_topics = await db.topics.count_documents({"user_id": uid})
    total_questions = await db.questions.count_documents({"user_id": uid})
    total_attempts = await db.attempts.count_documents({"user_id": uid})

    agg = await db.questions.aggregate([
        {"$match": {"user_id": uid}},
        {"$group": {"_id": None, "ans": {"$sum": "$times_answered"}, "ok": {"$sum": "$times_correct"}}},
    ]).to_list(1)
    accuracy = 0.0
    answered = 0
    if agg and agg[0]["ans"]:
        accuracy = round(100 * agg[0]["ok"] / agg[0]["ans"], 1)
        answered = agg[0]["ans"]

    favorites = await db.questions.count_documents({"user_id": uid, "favorite": True})
    difficult = await db.questions.count_documents({"user_id": uid, "difficult": True})
    errors_pool = await db.questions.count_documents({"user_id": uid, "$expr": {"$gt": ["$times_answered", "$times_correct"]}})
    now = _now_iso()
    due_srs = await db.questions.count_documents({"user_id": uid, "srs_next_review": {"$lte": now}, "times_answered": {"$gt": 0}})

    # Streak calculation
    today = datetime.now(timezone.utc).date()
    streak = 0
    check_date = today
    for _ in range(365):
        day_str = check_date.isoformat()
        count = await db.attempts.count_documents({"user_id": uid, "streak_day": day_str})
        if count > 0:
            streak += 1
            check_date = check_date - timedelta(days=1)
        else:
            break

    last_attempts = await db.attempts.find({"user_id": uid}, {"_id": 0}).sort("created_at", -1).to_list(3)

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


@api.get("/stats/by-subject")
async def stats_by_subject(current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    subjects = await db.subjects.find({"user_id": uid}, {"_id": 0}).to_list(1000)
    out = []
    for s in subjects:
        agg = await db.questions.aggregate([
            {"$match": {"user_id": uid, "subject_id": s["id"]}},
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
async def stats_by_topic(current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    topics = await db.topics.find({"user_id": uid}, {"_id": 0}).to_list(2000)
    out = []
    for t in topics:
        agg = await db.questions.aggregate([
            {"$match": {"user_id": uid, "topic_id": t["id"]}},
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



# ---------------------------------------------------------------------------
# Flashcards
# ---------------------------------------------------------------------------
class Flashcard(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    topic_id: str
    topic_name: str
    subject_id: Optional[str] = None
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


@api.post("/topics/{topic_id}/flashcards/generate")
async def generate_topic_flashcards(topic_id: str, num_cards: int = 15, current_user: dict = Depends(get_current_user)):
    """Generate flashcards from the topic's PDF text using AI."""
    uid = current_user["id"]
    topic = await db.topics.find_one({"id": topic_id, "user_id": uid}, {"_id": 0})
    if not topic:
        raise HTTPException(status_code=404, detail="Tema no encontrado")

    pdfs = await db.pdfs.find({"topic_id": topic_id, "user_id": uid}, {"_id": 0}).to_list(100)
    if not pdfs:
        raise HTTPException(status_code=404, detail="No hay PDFs para este tema")

    combined = "\n\n".join([f"=== {p['filename']} ===\n{p['text']}" for p in pdfs])
    num_cards = max(5, min(30, num_cards))

    # Comprobar plan + cuota ANTES de llamar a Gemini.
    await check_and_consume_ai_quota(current_user)
    cards = await _generate_flashcards_from_text(topic["name"], combined, num_cards)
    if not cards:
        # _generate_flashcards_from_text devuelve [] en fallo: revertir el consumo.
        await _refund_ai_quota(current_user)
        raise HTTPException(status_code=502, detail="No se pudieron generar flashcards")

    docs = []
    for c in cards:
        fc = Flashcard(
            user_id=uid,
            topic_id=topic_id,
            topic_name=topic["name"],
            subject_id=topic.get("subject_id"),
            term=c["term"],
            definition=c["definition"],
            example=c.get("example", ""),
        )
        docs.append(fc.model_dump())

    # Replace existing flashcards for this topic
    await db.flashcards.delete_many({"topic_id": topic_id, "user_id": uid})
    if docs:
        await db.flashcards.insert_many(docs)
        # Re-fetch to avoid ObjectId serialization issues
        docs = await db.flashcards.find({"topic_id": topic_id, "user_id": uid}, {"_id": 0}).to_list(500)

    return {"flashcards_created": len(docs), "flashcards": docs}


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
    ai_period_start: str = Field(default_factory=_now_iso)
    # Suscripción (Paddle Billing v4)
    subscription_status: str = "free"  # free | active | canceled | past_due | trialing
    paddle_customer_id: Optional[str] = None
    paddle_subscription_id: Optional[str] = None
    subscription_current_period_end: Optional[str] = None
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


def _hash_password(password: str) -> str:
    return pwd_context.hash(password)


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
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
    limit = _ai_limit_for_plan(plan)
    now = datetime.now(timezone.utc)
    used = int(current_user.get("ai_generations_used", 0) or 0)
    period_start = _parse_iso(current_user.get("ai_period_start")) or now

    # Si el periodo ya expiró, mostrar el estado como reiniciado.
    if (now - period_start) >= timedelta(days=AI_PERIOD_DAYS):
        used = 0
        period_start = now

    reset_at = period_start + timedelta(days=AI_PERIOD_DAYS)
    days_until_reset = max(0, (reset_at - now).days)
    return {
        "plan": plan,
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "period_start": period_start.isoformat(),
        "days_until_reset": days_until_reset,
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
    return {
        "plan": current_user.get("plan", "free"),
        "subscription_status": current_user.get("subscription_status", "free"),
        "current_period_end": current_user.get("subscription_current_period_end"),
        "paddle_subscription_id": current_user.get("paddle_subscription_id"),
    }


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

    # DIAG-TEMP: ¿Paddle propaga custom_data a CADA tipo de evento (sobre todo a
    # subscription.activated)? Logueamos presencia y contenido para verificarlo con
    # un pago sandbox real en Railway. QUITAR este bloque tras la verificación.
    _cd = data.get("custom_data")
    logger.info(
        "[PADDLE][DIAG-TEMP] event_type=%s custom_data_present=%s custom_data=%r",
        event_type, _cd is not None, _cd,
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


@app.on_event("startup")
async def ensure_indices():
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
        # PDFs
        await db.pdfs.create_index("id", unique=True)
        await db.pdfs.create_index("topic_id")
        await db.pdfs.create_index([("user_id", 1), ("id", 1)])
        await db.pdfs.create_index([("user_id", 1), ("topic_id", 1)])
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
    except Exception as e:
        logger.warning("ensure_indices failed: %s", e)


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
# AI Topic Summary
# ---------------------------------------------------------------------------
@api.post("/topics/{topic_id}/summary")
async def generate_topic_summary(topic_id: str, current_user: dict = Depends(get_current_user)):
    """Generate a structured summary of a topic using AI."""
    uid = current_user["id"]
    topic = await db.topics.find_one({"id": topic_id, "user_id": uid}, {"_id": 0})
    if not topic:
        raise HTTPException(status_code=404, detail="Tema no encontrado")

    pdfs = await db.pdfs.find({"topic_id": topic_id, "user_id": uid}, {"_id": 0}).to_list(100)
    if not pdfs:
        raise HTTPException(status_code=404, detail="No hay PDFs para este tema")

    if not GEMINI_API_KEY or gemini_client is None:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY no configurada")

    # Comprobar plan + cuota ANTES de llamar a Gemini.
    await check_and_consume_ai_quota(current_user)

    combined = "\n\n".join([f"=== {p['filename']} ===\n{p['text'][:30000]}" for p in pdfs])[:80000]

    system_msg = (
        "Eres un profesor experto. Genera un resumen estructurado y esquemático del temario. "
        "Usa el vocabulario exacto del texto. Responde SIEMPRE en español. "
        "Devuelve SOLO JSON válido."
    )
    prompt = f"""Resume el siguiente temario del tema "{topic['name']}" de forma estructurada.

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
        raw = _strip_code_fences(response.text or "")
        summary = json.loads(raw)
        return summary
    except Exception as e:
        await _refund_ai_quota(current_user)
        logger.error("Summary generation error: %s", e)
        raise HTTPException(status_code=502, detail="Error al generar el resumen")


# ---------------------------------------------------------------------------
# Gap Detector
# ---------------------------------------------------------------------------
@api.get("/stats/gaps")
async def get_knowledge_gaps(current_user: dict = Depends(get_current_user)):
    """Identify topics and questions with accuracy below 60%."""
    uid = current_user["id"]
    topics = await db.topics.find({"user_id": uid}, {"_id": 0}).to_list(2000)
    weak_topics = []
    for t in topics:
        agg = await db.questions.aggregate([
            {"$match": {"user_id": uid, "topic_id": t["id"], "times_answered": {"$gt": 2}}},
            {"$group": {"_id": None, "ans": {"$sum": "$times_answered"}, "ok": {"$sum": "$times_correct"}, "total": {"$sum": 1}}},
        ]).to_list(1)
        if agg and agg[0]["ans"] > 0:
            accuracy = round(100 * agg[0]["ok"] / agg[0]["ans"], 1)
            if accuracy < 60:
                weak_topics.append({
                    "topic_id": t["id"],
                    "topic_name": t["name"],
                    "subject_id": t.get("subject_id"),
                    "accuracy": accuracy,
                    "answered": agg[0]["ans"],
                    "total_questions": agg[0]["total"],
                })

    # Also get weakest individual questions
    weak_questions = await db.questions.find(
        {"user_id": uid, "times_answered": {"$gt": 2}, "$expr": {"$lt": [{"$divide": ["$times_correct", "$times_answered"]}, 0.5]}},
        {"_id": 0, "id": 1, "question": 1, "topic_name": 1, "times_answered": 1, "times_correct": 1}
    ).sort([("times_answered", -1)]).to_list(20)

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
