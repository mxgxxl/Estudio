# CLAUDE.md — Studia

> Guía para Claude Code al trabajar en este repositorio. Lee este archivo entero antes de tocar código.

## Qué es y objetivo

**Studia** es una app de estudio que genera preguntas de examen y material de repaso a partir de PDFs de temario, usando IA (Google Gemini). El usuario sube apuntes, la IA crea cuestionarios (test, V/F, desarrollo), flashcards y resúmenes, y la app gestiona la práctica con corrección, penalización, repaso espaciado (SRS) y estadísticas.

**Objetivo actual:** convertirla en un **SaaS de oposiciones freemium**:
- Cuentas de usuario (registro / login).
- Plan gratis con **límites de uso** (sobre todo de generación con IA) y plan(es) de pago.
- **Suscripción** con pasarela de pagos (Stripe).
- Aislamiento total de datos por usuario (multiusuario real).

## Stack

| Capa | Tecnología |
|------|------------|
| Backend | FastAPI 0.110 + Uvicorn |
| Base de datos | MongoDB (driver async `motor`) |
| IA | Google Gemini vía `google-genai` SDK (modelo por defecto `gemini-2.5-flash`) |
| Frontend | React 19 + react-router-dom + Tailwind + shadcn/Radix UI + axios |
| PDF | `pypdf` para extracción de texto |
| Despliegue | `Procfile` (uvicorn); frontend CRA + craco |

Dependencias **ya instaladas pero aún sin usar** (preparadas para el SaaS): `bcrypt`, `PyJWT`, `python-jose`, `passlib`, `stripe`.

## Estructura

```
backend/
  server.py            # TODO el backend en un único archivo (~1.800 líneas): modelos, helpers, endpoints, Gemini
  requirements.txt
  Procfile             # web: uvicorn server:app --host 0.0.0.0 --port $PORT
  tests/               # pytest (backend)
frontend/
  src/
    lib/api.js         # cliente axios; baseURL = REACT_APP_BACKEND_URL + "/api"
    pages/             # Dashboard, SubjectDetail, TopicDetail, QuizSetup/Run/Results, Stats, FlashcardMode, SurvivalMode
    components/        # diálogos + ui/ (shadcn)
    App.js             # rutas
memory/PRD.md          # historial de producto
test_result.md         # protocolo de testing (NO editar el bloque marcado)
test_reports/          # resultados pytest por iteración
```

### Modelo de datos (colecciones MongoDB)
`subjects`, `topics`, `pdfs` (texto extraído), `questions`, `attempts`, `flashcards`, `survival_records`.
Las preguntas soportan `question_type` = `mcq` | `tf` | `dev`, penalización configurable y campos SRS (SM-2 simplificado).

### Variables de entorno
- Backend: `MONGO_URL`, `DB_NAME`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `CORS_ORIGINS`.
- Frontend: `REACT_APP_BACKEND_URL`.
- Pendientes para el SaaS: `JWT_SECRET`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, etc.

## Endpoints

Todos cuelgan de un `APIRouter(prefix="/api")`. Diagnóstico: `GET /api/diag/llm`, `POST /api/diag/llm-test`. Recursos: subjects, topics, pdfs, questions, quiz (`start`/`submit`/`eval-dev`), stats (incl. `by-subject`, `by-topic`, `gaps`), flashcards, survival, summary. El frontend los consume desde `frontend/src/lib/api.js`.

## Qué funciona ya ✅

- CRUD de asignaturas y temas; subida de PDF y almacenamiento del texto extraído.
- Generación con IA de preguntas (MCQ 2-5 opciones, V/F, desarrollo), flashcards y resúmenes desde el temario.
- Regenerar preguntas desde un PDF en cualquier momento.
- Cuestionarios con modos (examen, práctica, errores, SRS, favoritos), penalización y nota /10.
- Repaso espaciado, flashcards, modo supervivencia, estadísticas y detector de lagunas.

## Qué falta ❌ (el trabajo del SaaS)

1. **Autenticación**: no hay registro/login/JWT. Las libs están instaladas pero `server.py` no las usa.
2. **Multiusuario**: ninguna colección tiene `user_id`; todas las consultas son globales. **Hoy todos los datos son compartidos.**
3. **Límites de IA**: no se comprueba ningún plan ni cuota antes de llamar a Gemini.
4. **Pagos**: `stripe` está en deps pero no hay integración, ni planes, ni webhooks.
5. **Frontend**: no hay pantallas de auth, ni de plan/suscripción, ni gating por límites.

## Reglas obligatorias

1. **No romper lo que ya funciona.** Probar tras cada cambio (pytest en `backend/tests/`, y comprobación manual / UI cuando aplique). Si algo deja de funcionar, parar y arreglarlo antes de seguir.
2. **Multiusuario por diseño.** Toda colección nueva o existente debe llevar `user_id`, y **toda** lectura/escritura debe filtrarse por el usuario autenticado. Nunca devolver ni modificar datos de otro usuario. Al migrar, asignar los datos huérfanos existentes con cuidado.
3. **Nunca llamar a Gemini sin comprobar antes el plan y el límite del usuario.** Toda ruta que invoque `gemini_client` debe primero verificar plan + cuota restante y rechazar (p. ej. `429`) si se excede. Sin excepción.
4. **Secretos solo en variables de entorno**, nunca en el código ni en commits. Usar `os.environ` / `.env` (ya en `.gitignore`). Nada de claves hardcodeadas.
5. **Commits pequeños y frecuentes.** Un cambio coherente por commit, con mensaje claro. Mantener el **prefijo `/api`** en todos los endpoints nuevos (registrarlos en el `APIRouter(prefix="/api")`).

## Notas de trabajo

- El backend es un único `server.py`; al crecer el SaaS, conviene separar auth, billing y límites en módulos, pero sin romper imports ni rutas existentes.
- `test_result.md` contiene un bloque de protocolo de testing marcado como **DO NOT EDIT** — respétalo.
- Idioma del producto y de las preguntas generadas: **español**.
