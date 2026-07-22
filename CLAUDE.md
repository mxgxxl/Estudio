# CLAUDE.md — Studia

> Guía para Claude Code al trabajar en este repositorio. Lee este archivo entero antes de tocar código.

## Qué es y objetivo

**Studia** es una app de estudio que genera preguntas de examen y material de repaso a partir de PDFs de temario, usando IA (Google Gemini). El usuario sube apuntes, la IA crea cuestionarios (test, V/F, desarrollo), flashcards y resúmenes, y la app gestiona la práctica con corrección, penalización, repaso espaciado (SRS) y estadísticas.

**Objetivo actual:** convertirla en un **SaaS de oposiciones freemium**:
- Cuentas de usuario (registro / login).
- Plan gratis con **límites de uso** (sobre todo de generación con IA) y plan(es) de pago.
- **Suscripción** con pasarela de pagos (Paddle, Billing v4).
- Aislamiento total de datos por usuario (multiusuario real).

## Stack

| Capa | Tecnología |
|------|------------|
| Backend | FastAPI 0.110 + Uvicorn |
| Base de datos | MongoDB (driver async `motor`) |
| IA | Google Gemini vía `google-genai` SDK (modelo por defecto `gemini-2.5-flash`) |
| Frontend | React 19 + react-router-dom + Tailwind + shadcn/Radix UI + axios |
| PDF | `pypdf` para extracción de texto |
| Pagos | Paddle (Billing v4) vía Paddle.js (frontend) + webhooks firmados (backend) |
| Despliegue | `Procfile` (uvicorn); frontend CRA + craco |

Dependencias de auth ya en uso: `bcrypt`, `PyJWT`, `python-jose`, `passlib`. La integración de pagos con **Paddle** no usa SDK de servidor: el checkout va con **Paddle.js** en el frontend y el backend recibe **webhooks** (verificación de firma HMAC-SHA256 propia) y consulta la **API REST de Paddle** con `httpx`.

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
`subjects`, `topics`, `pdfs` (texto extraído), `pdf_links`, `questions`, `attempts`, `flashcards`, `survival_records`, `paddle_events`.
Las preguntas soportan `question_type` = `mcq` | `tf` | `dev`, penalización configurable y campos SRS (SM-2 simplificado).
Las **flashcards** llevan `pdf_source_id` (de qué PDF salieron, como las `questions`); `None` = tarjeta "sin fuente" (legacy anterior al campo o tema multi-PDF no atribuible). Migración de backfill: `backend/scripts/migrate_flashcard_source.py` (idempotente, `DRY_RUN=1`) rellena `pdf_source_id` solo en temas de **1 PDF** (atribución inequívoca).

**PDFs muchos-a-muchos (Fases 1-3).** Un PDF ya NO está atado a un tema: existe como
entidad independiente y se asocia a varios temas/asignaturas mediante la colección
intermedia **`pdf_links`** `{user_id, pdf_id, topic_id, subject_id}` (índice único
`(user_id, pdf_id, topic_id)`; `subject_id` desnormalizado del topic). El texto vive
una sola vez en `pdfs` (ahorra espacio en Atlas M0 al no duplicar). Reglas clave:
- Toda lectura de "los PDFs de un tema" pasa por el helper `_topic_pdf_ids(uid, topic_id)`
  (lee de `pdf_links`).
- **Cascada con orfandad**: al borrar un tema/asignatura o desvincular, el documento
  `pdfs` se borra SOLO si no le queda ningún vínculo (`_delete_pdf_if_orphan`). Un PDF de
  biblioteca con `link_count 0` es estable y seguro (ninguna cascada lo toca).
- Al borrar/desvincular un PDF, sus preguntas NO se borran: solo pierden la referencia
  (`pdf_source_id = None`).
- **Migración**: `backend/scripts/migrate_pdf_links.py` (aditiva, idempotente, `DRY_RUN=1`)
  crea `pdf_links` desde el antiguo `pdfs.topic_id`.
- ⚠️ **TODO-FASE3 pendiente** (buscar `TODO-FASE3` en `server.py`): retirar `pdfs.topic_id`
  (hoy `Optional`, conservado solo para rollback) y los **fallbacks transitorios** que leen
  por `topic_id` cuando un PDF aún no tiene vínculos (en `_topic_pdf_ids`, `regenerate` y
  `unlink`). Hacerlo solo cuando la migración esté garantizada en todos los entornos.

### Variables de entorno
- Backend (base): `MONGO_URL`, `DB_NAME`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `CORS_ORIGINS`, `LOG_LEVEL` (por defecto `INFO`; súbelo a `DEBUG` para ver las trazas rutinarias, p. ej. las de Paddle).
- Backend (auth): `JWT_SECRET`, `ACCESS_TOKEN_EXPIRE_MINUTES`.
- Backend (límites IA): `FREE_AI_GENERATIONS_PER_MONTH`, `PREMIUM_AI_GENERATIONS_PER_MONTH`.
- Backend (pagos Paddle): `PADDLE_ENV` (`sandbox`|`production`), `PADDLE_API_KEY`, `PADDLE_WEBHOOK_SECRET`, `PADDLE_PREMIUM_PRICE_ID`.
- Frontend: `REACT_APP_BACKEND_URL`, `REACT_APP_PADDLE_CLIENT_TOKEN`, `REACT_APP_PADDLE_ENV`, `REACT_APP_PADDLE_PREMIUM_PRICE_ID`.

## Endpoints

Todos cuelgan de un `APIRouter(prefix="/api")`. Diagnóstico: `GET /api/diag/llm`, `POST /api/diag/llm-test`. Recursos: subjects, topics, pdfs, questions, quiz (`start`/`submit`/`eval-dev`), stats (incl. `by-subject`, `by-topic`, `gaps`), flashcards, survival, summary. El frontend los consume desde `frontend/src/lib/api.js`.

**Temas (creación desacoplada de los PDFs):**
- `POST /api/subjects/{subject_id}/topics` — crea un tema **vacío** (solo `name`, JSON). No toca `pdfs`/`pdf_links`, **no llama a Gemini** → sin cuota. Es el camino que usa la UI para crear temas.
- `POST /api/subjects/{subject_id}/topics/upload` — **(legacy)** crea tema + PDF + genera preguntas en un solo paso (multipart, consume cuota). Ya **no se usa desde el frontend**; se conserva por compatibilidad y porque lo cubren los tests.

**PDFs / biblioteca (Fases 1-3):**
- `GET /api/pdfs` — biblioteca del usuario: todos sus PDFs (sin `text`) con `link_count` y `topic_ids`.
- `POST /api/pdfs` — sube un PDF a la biblioteca SIN tema (`link_count 0`). No llama a Gemini → sin cuota.
- `POST /api/topics/{topic_id}/pdfs/upload` — sube un PDF y lo vincula al tema (crea `pdfs` + `pdf_links`).
- `POST /api/topics/{topic_id}/pdfs/{pdf_id}/link` — asocia un PDF existente a un tema (idempotente).
- `DELETE /api/topics/{topic_id}/pdfs/{pdf_id}` — desvincula del tema; borra el PDF si era su último vínculo (`{ok, pdf_deleted}`).
- `DELETE /api/pdfs/{pdf_id}` — borra el PDF por completo (de todos los temas) y desliga sus preguntas.
- `GET /api/topics/{id}/pdfs` incluye `link_count` por PDF.

**Generación con selección de PDFs (preguntas / resumen / flashcards):** los tres flujos aceptan elegir de qué PDFs generar, con `pdf_ids` **opcional** (ausente/vacío = todos los PDFs del tema); siempre validado contra `_topic_pdf_ids` (solo PDFs del tema, del usuario).
- `POST /api/topics/{id}/generate` (preguntas) — body con `pdf_ids` + params; **aditivo** (nunca borra).
- `POST /api/topics/{id}/summary` — body opcional `{ pdf_ids? }`; se genera **al vuelo** (no se persiste). Una sola llamada a Gemini con el texto combinado.
- `POST /api/topics/{id}/flashcards/generate` — body `{ pdf_ids?, num_cards? }`. **Reemplazo POR PDF**: genera una llamada a Gemini **por PDF en paralelo** (`asyncio.gather`), reparte `num_cards` **proporcional al `char_count`** (`_distribute_cards`), y cada tarjeta guarda su `pdf_source_id`. Regenerar un **subconjunto** solo reemplaza esas fuentes (conserva el resto + su progreso SRS/favoritos + las legacy `None`); regenerar **todos** barre el tema entero (incl. legacy). Cuenta como **1 unidad de cuota** aunque haga N llamadas; **todo-o-nada** (si una fuente falla, refund + 502).

Frontend: **`PdfPicker`** (selector presentacional de PDFs, todos preseleccionados) reutilizado por `GenerateDialog` (preguntas) y por **`PdfSelectDialog`** (resumen y flashcards). UX: con **≤1 PDF** se genera directo (un clic, sin fricción); con **>1 PDF** se abre el selector. Durante la generación se muestra feedback claro (spinner + "puede tardar hasta ~1 min") porque son varias llamadas a IA.

**Banco de preguntas (listado global reutilizable):**
- `GET /api/questions` — listado paginado del usuario con filtros: `subject_id`, `topic_id`, `pdf_source_id` (o `"none"` = sin PDF de origen), `question_type`, `status` (`all|errors|favorites|difficult|unpracticed|mastered|due`), `q` (búsqueda en enunciado, regex sin índice de texto), `sort` (`recent|most_failed`), `page`, `limit` (def. 30, máx. 100). Devuelve `{ items, total, page, limit }`.
- `GET /api/questions/ids` — mismos filtros; devuelve `{ ids, total, capped }` para "practicar esta selección". `ids` capado a `QUESTIONS_IDS_CAP` (500) pero `total` es el **real** y `capped` avisa si hay más (la UI muestra "practicando 500 de 800"; **sin recortes silenciosos**).
- `POST /api/quiz/start` acepta `question_ids` opcional: si viene, el pool son esas preguntas (acotadas por `user_id`, ignora filtros de modo). Reutiliza el flujo `quiz/run`→`results`.
- Helper compartido `_questions_query(...)`. Índices `(user_id, created_at)` y `(user_id, question_type)`.

Frontend: pantalla **Banco de preguntas** en `/preguntas` (`frontend/src/pages/QuestionBank.jsx`, entrada "Preguntas" en el nav). Filtros + buscador + chips de estado; tarjetas con favorito/difícil, editar (`EditQuestionDialog`, PATCH `/questions/{id}`), ir al tema, borrar; botón "Practicar selección" (usa `/questions/ids` → `quiz/start` con `question_ids`, avisa si `capped`).

**Pagos Paddle (Billing v4):** `POST /api/billing/checkout`, `GET /api/billing/status` (incl. `cancel_scheduled`), `POST /api/billing/portal` (customer portal), `POST /api/webhooks/paddle` (sin auth; firma HMAC verificada, idempotente por `event_id`). **Uso IA:** `GET /api/usage/me`.

Frontend: pantalla **Biblioteca** en `/biblioteca` (`frontend/src/pages/Library.jsx`, entrada "Biblioteca" en el nav de `Layout`). La creación de temas usa **`CreateTopicDialog`** (`frontend/src/components/CreateTopicDialog.jsx`): pide solo el nombre y, de forma **opcional**, adjunta PDFs (subir nuevos y/o elegir de la biblioteca) sin generar preguntas. Dentro del tema, `AddPdfDialog` sube/vincula PDFs y `GenerateDialog` genera las preguntas aparte. (El antiguo `UploadDialog`, que obligaba a subir PDF + generar al crear, se eliminó.)

## Pagos / Suscripciones (Paddle Billing v4)

Sin SDK de servidor: **checkout con Paddle.js** (overlay) en el frontend y **webhooks firmados** en el backend. El plan (`premium`/`free`) se **deriva siempre** del estado de la suscripción (única fuente de verdad; helper `_plan_for_subscription_status`).

**Campos en `users`:** `plan`, `subscription_status` (`free`|`active`|`trialing`|`canceled`|`past_due`), `paddle_customer_id`, `paddle_subscription_id`, `subscription_current_period_end`, y **`subscription_scheduled_change`** (objeto `{action, effective_at, ...}` o `None`) — cuando `action == "cancel"` hay una **cancelación programada** a fin de periodo; `GET /billing/status` lo expone como `cancel_scheduled` y `/cuenta` muestra "se cancelará el …" manteniendo premium hasta `current_period_end`.

**Checkout:** `POST /billing/checkout` devuelve `price_id`, `customer_email` y `user_id`; el frontend abre el overlay inyectando **`custom_data: { user_id }`** para poder emparejar el webhook por ID propio.

**Webhook (`POST /api/webhooks/paddle`):** verifica la firma HMAC-SHA256 (cabecera `Paddle-Signature`, `ts:body`), es idempotente por `event_id` (colección `paddle_events`), y **localiza al usuario en este orden**: 1) `custom_data.user_id` (validado contra `users`), 2) `paddle_subscription_id`, 3) `paddle_customer_id`, 4) **email** (del payload o resuelto vía API de Paddle por `customer_id`). Procesa `subscription.*` (activa/actualiza/cancela y guarda ids + `current_period_end` + `scheduled_change`) y `transaction.completed` (informativo). Si no encuentra usuario, responde 200 (log) para que Paddle no reintente.

**Gestión/cancelación:** `POST /billing/portal` crea una **customer portal session** de Paddle (`POST /customers/{id}/portal-sessions`, bajo demanda, nunca cacheada) y devuelve el deep link `cancel_subscription` (fallback al overview). La cancelación la resuelve Paddle; el webhook `subscription.*` sincroniza el estado. Errores claros: 409 si no hay `paddle_customer_id`, 502 (con log) si falla la API / faltan permisos.

**Variables de entorno** — backend: `PADDLE_ENV` (`sandbox`|`production`), `PADDLE_API_KEY`, `PADDLE_WEBHOOK_SECRET`, `PADDLE_PREMIUM_PRICE_ID`. Frontend: `REACT_APP_PADDLE_CLIENT_TOKEN`, `REACT_APP_PADDLE_ENV`, `REACT_APP_PADDLE_PREMIUM_PRICE_ID`. La API key necesita el permiso *Customer portal sessions (Write)* para `/billing/portal`.

## Qué funciona ya ✅

- CRUD de asignaturas y temas; **crear temas vacíos** (sin PDF) y adjuntarles PDFs (nuevos o de la biblioteca) cuando se quiera. La subida de PDF y la generación de preguntas están desacopladas de la creación del tema.
- Generación con IA de preguntas (MCQ 2-5 opciones, V/F, desarrollo), flashcards y resúmenes desde el temario.
- Regenerar preguntas desde un PDF en cualquier momento.
- Cuestionarios con modos (examen, práctica, errores, SRS, favoritos), penalización y nota /10.
- Repaso espaciado, flashcards, modo supervivencia, estadísticas y detector de lagunas.
- **Autenticación** (registro/login/JWT) y **multiusuario real** (todo filtrado por `user_id`).
- **Límites de uso de IA** por plan (`check_and_consume_ai_quota` antes de cada llamada a Gemini; 402 al superar).
- **Pagos con Paddle (Billing v4)**: checkout con Paddle.js, webhook firmado, customer portal, cancelación programada reflejada en `/cuenta`.
- **PDFs muchos-a-muchos + biblioteca** (Fases 1-3): un PDF se reutiliza en varios temas; pantalla `/biblioteca` para subir/gestionar PDFs sin tema.
- **Banco de preguntas** (`/preguntas`): listado global de todas las preguntas del usuario con filtros (asignatura/tema/PDF/tipo/estado), buscador y "practicar esta selección".

## Qué falta / pendiente ❌

1. **TODO-FASE3 de PDFs** (ver arriba): retirar `pdfs.topic_id` y los fallbacks transitorios una vez la migración `pdf_links` esté consolidada en todos los entornos.
2. Mejoras de biblioteca no incluidas: renombrar/previsualizar PDFs, etiquetas/carpetas, acciones en masa.
3. (Histórico) El SaaS base —auth, multiusuario, límites de IA, pagos— ya está implementado; ver "Qué funciona ya".

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
