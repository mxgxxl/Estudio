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
`subjects`, `topics`, `pdfs` (texto extraído), `pdf_links`, `questions`, `attempts`, `flashcards`, `summaries`, `survival_records`, `paddle_events`.

Los **resúmenes de IA** (`summaries`) se **persisten por PDF** (no por tema): `{user_id, pdf_id, scope:"pdf", content, created_at, updated_at}`, con `content` = el JSON de Gemini (overview/key_concepts/sections/remember) tal cual. Como un PDF es muchos-a-muchos, su resumen es **compartido** por todos los temas que lo contengan. El "1 por PDF" se impone a nivel de app con **upsert** por `(user_id, pdf_id, scope)` (sin índice único, para dejar abierto `scope:"topic"`/varios por PDF en el futuro). Se **borra** cuando el PDF desaparece (borrado explícito y orfandad en `_delete_pdf_if_orphan`); desvincular sin quedar huérfano NO lo toca.
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
- **Migración (histórica)**: `backend/scripts/migrate_pdf_links.py` (aditiva, idempotente,
  `DRY_RUN=1`) creó `pdf_links` desde el antiguo `pdfs.topic_id`.
- ✅ **`pdfs.topic_id` RETIRADO**: la atadura PDF↔tema vive **exclusivamente** en `pdf_links`.
  Se eliminó el campo del modelo `PdfSource`, sus escrituras, los fallbacks de lectura
  transitorios (`_topic_pdf_ids`, `regenerate_from_pdf`, `unlink_pdf_from_topic`) y los 2
  índices (`pdfs.topic_id_1`, `pdfs.user_id_1_topic_id_1`). `unlink_pdf_from_topic` sin link
  que borrar responde **404** ("El PDF no está en este tema"). Verificación previa (puerta) y
  retirada de datos en scripts: `verify_topic_id_retirement.py` (solo-lectura; conteo crítico
  = PDFs con `topic_id` sin `pdf_link` que lo respalde, debe ser 0) y
  `migrate_drop_pdf_topic_id.py` (`$unset` del campo + drop de índices tolerante; `DRY_RUN=1`
  por defecto, real con `DRY_RUN=0`). Orden: desplegar código → correr la puerta → `$unset`.

### Variables de entorno
- Backend (base): `MONGO_URL`, `DB_NAME`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `CORS_ORIGINS`, `LOG_LEVEL` (por defecto `INFO`; súbelo a `DEBUG` para ver las trazas rutinarias, p. ej. las de Paddle).
- Backend (auth): `JWT_SECRET`, `ACCESS_TOKEN_EXPIRE_MINUTES`.
- Backend (límites IA): `FREE_AI_GENERATIONS_PER_MONTH` (30), `PREMIUM_AI_GENERATIONS_PER_MONTH` (2000), `FREE_AI_CORRECTIONS_PER_MONTH` (300), `PREMIUM_AI_CORRECTIONS_PER_MONTH` (5000).
- Backend (pagos Paddle): `PADDLE_ENV` (`sandbox`|`production`), `PADDLE_API_KEY`, `PADDLE_WEBHOOK_SECRET`, `PADDLE_PREMIUM_PRICE_ID`.
- Frontend: `REACT_APP_BACKEND_URL`, `REACT_APP_PADDLE_CLIENT_TOKEN`, `REACT_APP_PADDLE_ENV`, `REACT_APP_PADDLE_PREMIUM_PRICE_ID`.

## Endpoints

Todos cuelgan de un `APIRouter(prefix="/api")`. Diagnóstico: `GET /api/diag/llm`, `POST /api/diag/llm-test`. Recursos: subjects, topics, pdfs, questions, quiz (`start`/`submit`/`eval-dev`), stats (incl. `by-subject`, `by-topic`, `gaps`), flashcards, survival, summary. El frontend los consume desde `frontend/src/lib/api.js`.

**Temas (creación desacoplada de los PDFs):**
- `POST /api/subjects/{subject_id}/topics` — crea un tema **vacío** (solo `name`, JSON). No toca `pdfs`/`pdf_links`, **no llama a Gemini** → sin cuota. Es el camino que usa la UI para crear temas.
- El flujo real es en pasos: crear tema vacío → subir PDF (`POST /api/topics/{id}/pdfs/upload`) → generar preguntas (`POST /api/topics/{id}/generate`). El antiguo `POST /subjects/{subject_id}/topics/upload` (multipart, creaba tema + PDF + generaba en un paso, consumía cuota) **se retiró** por código muerto: no lo usaba el frontend y solo lo sostenían setups de test, ahora recableados al flujo real.

**PDFs / biblioteca (Fases 1-3):**
- `GET /api/pdfs` — biblioteca del usuario: todos sus PDFs (sin `text`) con `link_count` y `topic_ids`.
- `POST /api/pdfs` — sube un PDF a la biblioteca SIN tema (`link_count 0`). No llama a Gemini → sin cuota.
- `POST /api/topics/{topic_id}/pdfs/upload` — sube un PDF y lo vincula al tema (crea `pdfs` + `pdf_links`).
- `POST /api/topics/{topic_id}/pdfs/{pdf_id}/link` — asocia un PDF existente a un tema (idempotente).
- `DELETE /api/topics/{topic_id}/pdfs/{pdf_id}` — desvincula del tema; borra el PDF si era su último vínculo (`{ok, pdf_deleted}`).
- `DELETE /api/pdfs/{pdf_id}` — borra el PDF por completo (de todos los temas) y desliga sus preguntas.
- `GET /api/topics/{id}/pdfs` incluye `link_count` por PDF.

**Generación con selección de PDFs (preguntas / resumen / flashcards):** los tres flujos aceptan elegir de qué PDFs generar, con `pdf_ids` **opcional** (ausente/vacío = todos los PDFs del tema); siempre validado contra `_topic_pdf_ids` (solo PDFs del tema, del usuario).
- `POST /api/topics/{id}/generate` (preguntas) — body con `pdf_ids` + params; **aditivo** (nunca borra). **Atribución POR PDF** (como flashcards): reparte `num_questions` **proporcional al `char_count`** (`_distribute_cards`), hace **una llamada a Gemini por PDF en paralelo** (`asyncio.gather`, cada una con SOLO el texto de su PDF, sin cabecera de nombre de fichero) y cada pregunta guarda su `pdf_source_id` real (los PDFs con asignación 0 no se llaman). Con 1 PDF degenera a `[num_questions]` sobre esa fuente (misma conducta de siempre). Cuenta como **1 unidad de cuota** aunque haga N llamadas (`gen_kind="questions"`, consume antes del gather); **todo-o-nada** (si una fuente falla, refund + **502**; sin resultados parciales). El batcheo interno por `BATCH_SIZE=10` de `generate_questions_with_claude` ahora se aplica por PDF. Regresión del bug histórico: con 2+ PDFs se concatenaba el texto en una sola llamada y **todas** las preguntas caían en `pdfs[0]`.
- **Resúmenes persistidos por PDF** (acción individual por PDF, no multi-select): `POST /api/pdfs/{pdf_id}/summary` genera/regenera (upsert; regenerar sobrescribe) y **persiste**; `GET /api/pdfs/{pdf_id}/summary` sirve el cacheado (**coste 0**, 404 si no hay); `GET /api/topics/{id}/summaries` devuelve los de los PDFs del tema (vía `_topic_pdf_ids`, coste 0) para pintar TopicDetail. El prompt **no pasa el nombre del PDF** (los nombres de fichero son ruidosos; el texto es la única fuente de verdad). Consume **1 generación** de cuota (comprobada antes, refund si Gemini falla); servir de caché = 0. (Retirado el antiguo `POST /topics/{id}/summary` al vuelo.) `GET /api/summaries` es la **lista global** de todos mis resúmenes (coste 0) para la pestaña Resúmenes: cada fila trae `pdf_filename`, `subjects`/`topics` (**derivados vía `pdf_links`**; un resumen compartido pertenece a varias), `content` y fechas.
- `POST /api/topics/{id}/flashcards/generate` — body `{ pdf_ids?, num_cards? }`. **Reemplazo POR PDF**: genera una llamada a Gemini **por PDF en paralelo** (`asyncio.gather`), reparte `num_cards` **proporcional al `char_count`** (`_distribute_cards`), y cada tarjeta guarda su `pdf_source_id`. Regenerar un **subconjunto** solo reemplaza esas fuentes (conserva el resto + su progreso SRS/favoritos + las legacy `None`); regenerar **todos** barre el tema entero (incl. legacy). Cuenta como **1 unidad de cuota** aunque haga N llamadas; **todo-o-nada** (si una fuente falla, refund + 502).

Frontend: **`PdfPicker`** (selector presentacional de PDFs, todos preseleccionados) reutilizado por `GenerateDialog` (preguntas) y por **`PdfSelectDialog`** (resumen y flashcards). UX: con **≤1 PDF** se genera directo (un clic, sin fricción); con **>1 PDF** se abre el selector. Durante la generación se muestra feedback claro (spinner + "puede tardar hasta ~1 min") porque son varias llamadas a IA.

**Banco de preguntas (listado global reutilizable):**
- `GET /api/questions` — listado paginado del usuario con filtros: `subject_id`, `topic_id`, `pdf_source_id` (o `"none"` = sin PDF de origen), `question_type`, `status` (`all|errors|favorites|difficult|unpracticed|mastered|due`), `q` (búsqueda en enunciado, regex sin índice de texto), `sort` (`recent|most_failed`), `page`, `limit` (def. 30, máx. 100). Devuelve `{ items, total, page, limit }`.
- `GET /api/questions/ids` — mismos filtros; devuelve `{ ids, total, capped, sampled }` para "practicar esta selección". Por defecto `ids` capado a `QUESTIONS_IDS_CAP` (500, más recientes) con `total` **real** y `capped` avisando si hay más ("practicando 500 de 800"; **sin recortes silenciosos**). Con **`random_sample=N`** devuelve una **muestra aleatoria UNIFORME** de `min(N, CAP, total)` sobre TODO el conjunto filtrado vía `$sample` de Mongo (`[{$match: query}, {$sample}, {$project}]`; el `user_id` va en el `$match`, no se lo salta); `sampled=true`, `capped=false`. `random_sample < 1` → **422**.
- `POST /api/quiz/start` acepta `question_ids` opcional: si viene, el pool son esas preguntas (acotadas por `user_id`, ignora filtros de modo). Reutiliza el flujo `quiz/run`→`results`.
- `POST /api/questions` — **autoría manual** de una pregunta (sin IA, **sin cuota**; no llama a Gemini). Body `ManualQuestionCreate` `{ topic_id, question_type (mcq|tf|dev), question_text, options?, correct_answer?, dev_answer?, explanation?, num_options? }`. Validación cruzada por tipo (**422** con mensaje): mcq → `options` 2-5 no vacías + `correct_answer` en rango; tf → `correct_answer ∈ {0,1}`; dev → `dev_answer` obligatorio. Tema inexistente **o de otro usuario** → **404** (no 403, no revela existencia). El documento se construye con el **mismo modelo `Question`** que el generador (defaults SRS/estado idénticos, `pdf_source_id=None`, tf guarda `options:["Verdadero","Falso"]`), así es **indistinguible** de las generadas en quiz/banco. **No** se añade campo `source` ni `updated_at` (las generadas hoy no los tienen). Responde **201** con la pregunta (patrón `create_subject`: doble `model_dump()` para no filtrar el `_id`). Los campos de API se traducen al schema interno (`question_text→question`, `correct_answer→correct_index`, `dev_answer→model_answer`). **`pdf_source_id` opcional**: si viene, debe pertenecer al tema (y al usuario) — validado contra `_topic_pdf_ids(uid, topic_id)`, el mismo helper que generación/quiz; si no está vinculado → **422**. Ausente/None = pregunta libre (`pdf_source_id=None`).
- Helper compartido `_questions_query(...)`. Índices `(user_id, created_at)` y `(user_id, question_type)`.

Frontend: pantalla **Banco de preguntas** como pestaña de Biblioteca en `/biblioteca/preguntas` (`frontend/src/pages/QuestionBank.jsx`). Filtros + buscador + chips de estado; tarjetas con favorito/difícil, editar (`EditQuestionDialog`, PATCH `/questions/{id}`), ir al tema, borrar; botón "Practicar selección" (usa `/questions/ids` → `quiz/start` con `question_ids`, avisa si `capped`). El antiguo `/preguntas` **redirige** a `/biblioteca/preguntas`.
**Selección granular — TRES modos de práctica:** (1) **explícita** por checkbox en cada tarjeta + checkbox tri-estado "seleccionar página" (Radix `indeterminate`); la selección es **acumulable entre páginas** (un `Set` de ids) y practica **esos ids exactos** (sin llamar a `/ids`; aborta con toast si >500). (2) **"Todas las que coinciden"** (Gmail-style): cuando la página entera está marcada y hay más, aparece un enlace que activa un **flag** `selectAllFiltered` (**no** descarga filas) → practica vía `/questions/ids` con los filtros (respeta CAP + aviso `capped`). (3) **Aleatoria**: panel "Cantidad | Porcentaje" + input → `listQuestionIds({ randomSample: n })` (para %, `n = ceil(total*pct/100)`, acotado a 500) → `quiz/start` con esos ids. Cambiar un **filtro** (o el orden) **resetea** la selección; **paginar la conserva**. `quiz/start` ya baraja y recorta a `num_questions`, así que el orden de los `question_ids` es irrelevante.

**Creación manual (frontend) — `CreateQuestionDialog`** (`frontend/src/components/CreateQuestionDialog.jsx`, cliente `createQuestion` → `POST /questions`): diálogo reutilizable de alta a mano (sin IA, sin cuota). Selector de **tipo** (mcq/tf/dev) que cambia el formulario: mcq con opciones **añadir/quitar** (2-5, sin duplicadas, radio de correcta que se reindexa al borrar), tf Verdadero/Falso, dev respuesta modelo; explicación opcional. **Destino**: cascada asignatura→tema (o **tema fijo**), con **selector de PDF de origen opcional** acotado a los PDFs del tema (`GET /topics/{id}/pdfs`). Botones **"Guardar"** (cierra) y **"Guardar y crear otra"** (conserva tipo + destino, resetea el contenido, para alta en cadena); errores 404/422 se muestran sin cerrar. **Dos puntos de entrada**: (1) **Banco** — botón "Crear pregunta" junto a "Practicar selección", precargando asignatura/tema/PDF desde los filtros activos (ignora el centinela `none`), refresca con `load()`; (2) **TopicDetail** — botón "Crear pregunta" junto a "Generar preguntas", modo **tema fijo** con PDF elegible entre los del tema, refresca al crear. (`EditQuestionDialog` **no** se tocó; extraer un `QuestionFields` común es una fase 2 pendiente.)

**Filtro de PDFs en el estudio (`pdf_ids`, single-topic):** elegir de qué PDFs concretos sale el pool de un quiz.
- `POST /api/quiz/start` acepta `pdf_ids: Optional[List[str]]` en el body. **Ignorado si viene `question_ids`** (ese ya define el pool por sí solo). Ausente/vacío = **todos** los PDFs del tema (incluye huérfanos con `pdf_source_id=None`, retro-compat).
- `GET /api/quiz/available` acepta `pdf_ids` como query **repeatable** (`?pdf_ids=a&pdf_ids=b`), con la misma validación y semántica. Sigue devolviendo `count` (0 para el gating).
- **Constraint single-topic:** `pdf_ids` requiere `len(topic_ids) == 1` → **400** si no. `subject_ids` **no** se restringe (con un topic explícito el scope efectivo ya es ese tema, sea cual sea el subject que acompañe: es intersección, no ampliación).
- **Regla de huérfanos** (`pdf_source_id=None`): sin `pdf_ids` → **incluidos**; con `pdf_ids` explícito → **excluidos**.
- **Punto único de validación:** `_validate_quiz_pdf_ids(uid, pdf_ids, topic_ids)` (vacío/None → None; scope multi-topic → 400; algún id fuera de `_topic_pdf_ids(uid, topic_ids[0])` → 400). Ambos endpoints pasan por él.
- **Filtro en el pool:** `_quiz_pool_query` acepta `pdf_ids` opcional → `pdf_source_id: {$in: pdf_ids}` tras los filtros de subject/topic (el early-return de `question_ids` queda antes → ignorado gratis).
- **SRS intacto:** `_update_srs` sigue avanzando **solo** en `selection=="srs"`, verificado por regresión con `pdf_ids` en el pool.

**Steppers de creación rápida (solo frontend, endpoints existentes):** modales de pasos que crean material de una sentada sin salir de la pantalla. Dos componentes gemelos: **`CreateSubjectStepper`** (asignatura → tema → PDFs → generar) y **`CreateTopicStepper`** (tema → PDFs → generar, con un paso 0 opcional de "elegir asignatura" si no viene `preselectedSubjectId`). Comparten patrón: cada entidad se **persiste al avanzar su paso** (idempotente: "Atrás" no borra ni renombra; el input queda deshabilitado con "ya creada/creado"); los PDFs se **adjuntan de inmediato** (subir/biblioteca/quitar, mismo patrón que `CreateTopicDialog`); la generación envía `pdf_ids` de los adjuntos y tiene estados **generando / completado / error** (con "Reintentar"). Todo usa `POST /subjects`, `POST /subjects/{id}/topics`, `POST /topics/{id}/pdfs/upload`, `.../{pdf_id}/link`, `POST /topics/{id}/generate`.
- **Generación diferida (`PendingGenerationContext`, `src/context/`):** montado en `App.js`. Si el usuario **cierra el modal con la generación en curso**, `confirm(...)` y la promesa se **transfiere al context** (`trackGeneration(promise, {topicName, subjectName, subjectId})`); el stepper se desentiende (guard `genPromiseRef.current !== p`, sin `setState` tras cerrar). Al resolver: **toast** (sonner) de éxito/fallo + evento global **`studia:generation-complete`** para que las vistas montadas refresquen sus datos.
- **Puntos de entrada:**
  - **Ghost cards en `QuizSetup`** ("+ Nueva asignatura" → `CreateSubjectStepper`; "+ Nuevo tema" → `CreateTopicStepper`). `preselectedSubjectId` = la asignatura seleccionada si hay **exactamente 1** (si no, el topic stepper pregunta). `onComplete` suma la asignatura/tema nuevo a la selección **si era parcial** (en "todas/todos" ya entra) y refresca vía `loadData`; hay listener de `studia:generation-complete`.
  - **Flujo 4 — dropdown del Banco de preguntas** (`QuestionBank.jsx`): la **última opción** del `<select>` de temas es el centinela **`+ Nuevo tema`** (valor `__create__`); su `onChange` **abre el stepper y NO aplica filtro** (el `<select>` controlado revierte solo al no tocar `topicId`). `preselectedSubjectId` = la asignatura filtrada (o `null` en "Todas"). `onComplete` **auto-enfoca los filtros** en el tema recién creado (su asignatura + el tema; PDF/tipo/estado a "todos") y recarga. Se **extrajo `loadCatalogs`** (useCallback) para poder recargar asignaturas/temas/PDFs y que el tema nuevo aparezca **como opción antes de fijarlo**; y se **añadió el listener `studia:generation-complete`** (no existía en el Banco) para el caso de generación diferida.

**Cuota de IA — dos contadores (ciclo unificado):** el usuario tiene **`ai_generations_used`** (crear material: preguntas, flashcards, resúmenes) y **`ai_corrections_used`** (evaluar respuestas de desarrollo: `eval-dev` y `eval-dev-batch`), que **comparten `ai_period_start`** y se **reinician juntos** cada `AI_PERIOD_DAYS` (30). `check_and_consume_ai_quota(user, kind, cost, gen_kind)` / `_refund_ai_quota(user, kind, cost, gen_kind)` con `kind ∈ {generation, correction}`; el 402 diferencia "generaciones" vs "correcciones".

**Desglose por tipo de "crear material" (sub-contadores):** `ai_gen_questions_used`, `ai_gen_summaries_used`, `ai_gen_flashcards_used` desglosan el ciclo actual del agregado `ai_generations_used`. **INVARIANTE**: su suma == `ai_generations_used`, siempre. Se garantiza en el **único punto de verdad**: cuando `kind=="generation"`, `check_and_consume_ai_quota` **exige `gen_kind`** (∈ {questions, summaries, flashcards}; falta → `ValueError`, validado ANTES de cualquier `$inc`) y sube agregado **y** sub-contador en el **mismo `$inc` atómico**; `_refund_ai_quota` los decrementa juntos; el reset de ciclo (en el consume y en el display de `/usage/me`) pone agregado + 3 sub-contadores a 0 en la misma operación. Cada generación cuesta **1** y es atribuible a un único tipo (preguntas: `generate`/`regenerate`; flashcards: 1 por tanda aunque sean N PDFs; resúmenes: 1 por PDF), así que el desglose refleja **exactamente lo descontado**. Sin backfill: los sub-contadores nacen en 0 (default en modelo, lectura tolerante); el ciclo en curso al desplegar muestra agregado viejo con desglose parcial (cosmético de un ciclo). `GET /api/usage/me` expone `generations.by_type = {questions|summaries|flashcards: {used}}` (solo `used`; el límite es el agregado compartido).

> **REGLAS DE FUTURO (no romper):**
> 1. **Invariante y punto único.** "Crear material" se consume SIEMPRE por `check_and_consume_ai_quota(..., gen_kind=…)` (y se reembolsa por `_refund_ai_quota(..., gen_kind=…)`); nunca con un `$inc` suelto en un endpoint. `questions + summaries + flashcards` debe igualar SIEMPRE `ai_generations_used`. **Todo punto de consumo de generación nuevo DEBE pasar su `gen_kind`**; si falta, la guardia lanza `ValueError` (validado antes del `$inc`). Al **añadir un tipo futuro**: nuevo campo `ai_gen_<tipo>_used`, entrada en `_GEN_SUBFIELD` (que alimenta consumo, refund, reset y `by_type` a la vez) y pasar el `gen_kind` en su punto de consumo — así el desglose no se rompe en silencio.
> 2. **El renombrado es SOLO etiqueta de UI** ("crear material"). Los nombres internos **NO cambian**: `ai_generations_used` (BD), `generations` (API), `gen_kind`, `kind="generation"` siguen igual. No "completar" el renombrado tocando BD/API.

Frontend: **`UsageBadge`** (cabecera) es **clicable** → navega a la **página de uso `/uso`** (`frontend/src/pages/Uso.jsx`), dueña del **detalle de cuota**: "Crear material" con su desglose (preguntas · resúmenes · flashcards) y "Correcciones" sin desglose. **Cuenta (`/cuenta`)** ya **no** duplica el detalle (solo plan + facturación) y **enlaza** a `/uso`. Renombrado de **etiqueta**: "Generaciones" → **"Crear material"** en la UI (los campos `ai_generations_used`/`generations` en BD y API **no cambian**). **1 corrección por respuesta evaluada** (individual y batch); las respuestas en blanco no se evalúan ni cuentan. Migración de backfill: `backend/scripts/migrate_corrections_counter.py` (idempotente, `DRY_RUN=1`) inicializa `ai_corrections_used=0` en usuarios existentes. **Coste real (medido en logs):** una generación de 10 preguntas ≈ 27k tokens; una corrección ≈ 900 tokens (~30× menos) → de ahí los límites de correcciones más holgados.

**Logging de tokens (INFO):** cada llamada a Gemini registra `[GEMINI-USAGE] op=<generate_questions|eval_dev|flashcards|summary> in=… out=… thoughts=… total=…` (de `response.usage_metadata`; `thoughts` = tokens de razonamiento de `gemini-2.5-flash`). Solo logging, sin persistir.

**Pagos Paddle (Billing v4):** `POST /api/billing/checkout`, `GET /api/billing/status` (incl. `cancel_scheduled`), `POST /api/billing/portal` (customer portal), `POST /api/webhooks/paddle` (sin auth; firma HMAC verificada, idempotente por `event_id`). **Uso IA:** `GET /api/usage/me` (devuelve `generations` —con `by_type` de desglose— y `corrections` + campos planos retrocompat = generaciones).

**Navegación — "Biblioteca" es una página paraguas con pestañas.** `frontend/src/pages/Biblioteca.jsx` (ruta `/biblioteca`) renderiza cabecera + barra de pestañas + `<Outlet/>`; las rutas hijas son `/biblioteca/pdfs` (`Library.jsx`), `/biblioteca/preguntas` (`QuestionBank.jsx`) y `/biblioteca/resumenes` (`LibrarySummaries.jsx`); `/biblioteca` redirige a `pdfs`. **Alias de compatibilidad**: la ruta antigua `/preguntas` redirige a `/biblioteca/preguntas` (`<Navigate replace>`), para no romper enlaces/marcadores. Separa "material que acumulas" (Biblioteca) de "actividad" (Estudiar). El nav superior (`Layout`) queda: Inicio · Estudiar · Biblioteca · Estadísticas · Cuenta (Supervivencia donde esté) — sin entradas sueltas de PDFs/Preguntas. `Library`/`QuestionBank` conservan intactos sus filtros/estado/acciones; solo se les quitó el contenedor externo y el título (los aporta el paraguas). La pestaña **Resúmenes** lista `GET /api/summaries` con filtros mínimos (asignatura por *membership* + buscador por nombre de PDF) y reutiliza `SummaryPanel` para leer + Regenerar (`POST /pdfs/{id}/summary`).

Frontend: pantalla **Biblioteca** (pestaña PDFs) en `/biblioteca/pdfs` (`frontend/src/pages/Library.jsx`). La creación de temas usa **`CreateTopicDialog`** (`frontend/src/components/CreateTopicDialog.jsx`): pide solo el nombre y, de forma **opcional**, adjunta PDFs (subir nuevos y/o elegir de la biblioteca) sin generar preguntas. Dentro del tema, `AddPdfDialog` sube/vincula PDFs y `GenerateDialog` genera las preguntas aparte. (El antiguo `UploadDialog`, que obligaba a subir PDF + generar al crear, se eliminó.)

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
- **Modos de estudio → dos ejes (rediseño COMPLETO; el viejo `mode` retirado del todo).** El estudio se parte en dos ejes independientes: **`selection`** (`all` | `errors` | `srs` | `favorites` — *qué preguntas*, único filtro de query, helper `_quiz_pool_query`) y **`behavior`** (`practice` | `exam` — *cómo se juega*: timer/penalización, client-side). `Attempt` persiste **solo** `selection` y `behavior` (fuente única). `_resolve_quiz_axes(selection, behavior)` normaliza con defaults tolerantes (`all`/`practice`).
  - **UI de dos ejes (Fase 3, `QuizSetup`):** dos selectores independientes — "¿Cómo quieres estudiar?" (behavior) y "¿Qué preguntas quieres?" (selection) — con subtítulo por eje + detalle **inline colapsable** (icono info; sin tooltip/popover nuevos, patrón de facto de la app). Cualquier combinación es válida (p. ej. Examen + Errores). El frontend envía `selection`+`behavior` (a `quiz_start`/`quiz_submit`/`sessionStorage`); `QuizRun` lee `quiz.behavior` (`isExam`) y `quiz.selection` (badge, vía `SELECTION_LABELS` de `frontend/src/lib/quizLabels.js`, fuente única de etiquetas ES reusada por Stats). Enlaces de entrada usan `?behavior=&selection=`; `QuizSetup` acepta `?mode=` **legacy** como fallback de LECTURA de la URL (marcadores viejos → ejes) y `QuizRun` tiene un fallback análogo para sesiones en `sessionStorage` en vuelo — ambos son lectura de cliente, no envían `mode` al backend.
  - **Gating por selección (arregla el "botón muerto"):** `GET /api/quiz/available?selection=&subject_ids=&topic_ids=&question_type=` cuenta las preguntas de la selección activa (coste 0). QuizSetup lo llama **debounced** al cambiar selección/filtros/tipo y **bloquea** el inicio con mensaje claro cuando no hay ("No tienes preguntas falladas en esta selección"), en vez de dejar que `quiz_start` acabe en 404. Para `selection=all` el conteo sigue siendo local (`counts_by_type`).
  - **Bloque "¿De qué PDFs?" (`QuizSetup.jsx`):** elegir de qué PDFs sale la sesión, visible **solo** con `singleTopicId && topicPdfs.length > 1` (patrón sin fricción: ≤1 PDF salta el bloque). Reutiliza **`PdfPicker`** (presentacional, parent-controlled) en un **diálogo propio de QuizSetup** — **no** `PdfSelectDialog` (su reset-on-open no encaja con selección persistente durante el setup). **Reglas de envío:** todos seleccionados (`size === length`) → **no** se manda `pdf_ids`; subconjunto → se manda; **vacío** (`size === 0`) → sin llamada al backend, botón bloqueado con "Selecciona al menos un PDF". **Gating:** `needsBackendCount` se extiende para cubrir `all` + subconjunto (el conteo local de `all` no conoce el subconjunto), y `selectedPdfIds` entra en las deps del efecto debounced de `/quiz/available`. **Persistencia solo local** (nada en URL/`sessionStorage`/marcadores). Al cambiar de tema o pasar a multi-topic scope → **reset a "todos"** (nunca arrastra la selección del tema anterior).
  - ✅ **Compat de `mode` RETIRADA (Paso B):** el backend ya **no** acepta `mode` en el request ni lo emite en la respuesta de `quiz_start`; se eliminaron `_derive_mode` y el mapeo `mode→ejes` de `_resolve_quiz_axes`. Un cliente viejo que aún mandara `mode` (improbable tras Fase 3) lo ve **ignorado** (Pydantic `extra=ignore`) y cae a los defaults `all`/`practice` — degradación suave, sin 422. Sin datos que migrar (Attempt no tiene `mode` desde Fase 2). Se mantienen los fallback de **lectura** de cliente (URL/sessionStorage) para no romper marcadores.
  - **SRS solo en Repaso:** `_update_srs` **solo avanza cuando `selection == "srs"`** (gate en `quiz_submit`, en el `$set` por pregunta). Responder en cualquier otra selección (examen incluido) **NO** toca `srs_ease`/`srs_interval_days`/`srs_next_review` — antes un simulacro reescribía intervalos ya establecidos; eso se corrige aquí.
  - ✅ **`mode` RETIRADO de `Attempt` (Fase 2):** ya no se persiste. El label de "intentos recientes" en `Stats.jsx` muestra **ambos ejes** ("Comportamiento · Selección", p. ej. "Examen · Errores"). Migración del histórico: `backend/scripts/migrate_attempt_axes.py` (idempotente, `DRY_RUN=1`): backfill de ejes desde el `mode` viejo + `$unset mode`, con puerta (0 attempts sin ejes antes del unset). No hay índices sobre `attempts.mode`. **Nada debe apoyarse en `mode`**; usar `selection`/`behavior`.
- **Dejar preguntas en blanco (examen).** El scoring (backend `quiz_submit`) trata la no respondida (`selected == -1`) como **neutra**: cuenta como `unanswered`, **no** como fallo, y **no penaliza** bajo ningún ratio (solo cuenta en el denominador de la nota). UX en `QuizRun.jsx`: botón **"Dejar en blanco"** siempre disponible en examen (con coletilla "(no penaliza)" **solo** si hay penalización), chip **"Sin responder"** en la pregunta actual y contador **"· N en blanco"** en el pie; al **Finalizar** con blancos, `window.confirm` "Te quedan N preguntas sin responder…" (solo examen; el auto-envío por tiempo agotado no pregunta; práctica no aplica). Resultados (`QuizResults`) muestra la blanca como estado propio "sin responder", no como fallo.
  - **Toggle "los blancos también restan" (examen, Fase 4).** Casilla en el apartado de penalización de `QuizSetup`, visible **solo en Examen** y **subordinada a la penalización** (solo con `penalty_factor > 0`; se reinicia si dejas de cumplirlo). Viaja como `blanks_count_as_wrong` (default `false`) por el mismo camino que `penalty_factor`: setup → `sessionStorage` → `quiz_submit`. **Conteos vs nota (separados a propósito):** el blanco SIEMPRE se cuenta como blanco (`unanswered`), nunca se funde en `wrong` (que son solo los fallos reales); su penalización, cuando el toggle está activo, se aplica **solo en la nota** — `penalized = wrong + (unanswered if blanks_as_wrong else 0)`, `raw = correct - penalized/pf`. Así `QuizResults` muestra los tiles **Fallos** (reales) y **Blanco** (reales) por separado, con la nota igualmente penalizada. **Blindaje backend**: `blanks_as_wrong = req.blanks_count_as_wrong and pf > 0` (sin penalización el blanco es neutro aunque llegue el flag). `quiz_submit` devuelve `blanks_penalized` (efectivo) para que el front sepa, de forma autoritativa, si los blancos han penalizado. **Presentación honesta según estado:** en `QuizRun` el botón/aviso de "Dejar en blanco" dice "(penaliza)" si `blanks_count_as_wrong`, "(no penaliza)" si hay penalización de fallos pero los blancos no cuentan, y nada sin penalización; el aviso al Finalizar añade "y penalizan como un fallo". En `QuizResults`, el tile **Blanco** marca "penalizan" y cada blanco lleva "· En blanco (penaliza)". **No** toca las stats por pregunta (un blanco no es un intento real) ni el trato de `dev` (un dev en blanco cuenta como fallo por `dev_score 0`, aparte).
- Repaso espaciado, flashcards, modo supervivencia, estadísticas y detector de lagunas.
- **Autenticación** (registro/login/JWT) y **multiusuario real** (todo filtrado por `user_id`).
- **Límites de uso de IA por plan, en DOS contadores** (`check_and_consume_ai_quota(user, kind)` antes de cada llamada a Gemini; 402 diferenciado al superar): **generaciones** (crear material, free 30 / premium 2000) y **correcciones** (evaluar desarrollo, free 300 / premium 5000), con **ciclo unificado** (comparten `ai_period_start`, se reinician juntos). **Desglose por tipo** de "crear material" (sub-contadores preguntas/resúmenes/flashcards, invariante suma==agregado en el punto único) y **página de uso `/uso`** (badge clicable, dueña del detalle; Cuenta solo enlaza). Ver sección "Cuota de IA".
- **Pagos con Paddle (Billing v4)**: checkout con Paddle.js, webhook firmado, customer portal, cancelación programada reflejada en `/cuenta`.
- **PDFs muchos-a-muchos + biblioteca** (Fases 1-3): un PDF se reutiliza en varios temas; pestaña `/biblioteca/pdfs` para subir/gestionar PDFs sin tema.
- **Banco de preguntas** (`/biblioteca/preguntas`): listado global de todas las preguntas del usuario con filtros (asignatura/tema/PDF/tipo/estado), buscador y "practicar esta selección".
- **Navegación bajo "Biblioteca"** (página paraguas con pestañas **PDFs · Preguntas · Resúmenes**): consolida el "material que acumulas" separado de "Estudiar". La pestaña Resúmenes (`/biblioteca/resumenes`) lista `GET /api/summaries` con filtro por asignatura (membership) + buscador, y lee/regenera cada resumen reutilizando `SummaryPanel`. Nav superior limpio (sin entradas sueltas de PDFs/Preguntas); `/preguntas` redirige a `/biblioteca/preguntas`.
- **Modo desarrollo (respuesta abierta) completo (A-E):** crear preguntas dev desde `GenerateDialog`; `QuizSetup` consciente del tipo (disponibilidad por tipo vía `counts_by_type`, mínimo adecuado a sets pequeños); en **examen la corrección se difiere al envío** (`eval-dev-batch`, evaluación en paralelo, overlay "Corrigiendo…", sin 402 a mitad) y en **práctica es inline**; **feedback en resultados** (nota + feedback + puntos que faltaron); **editar la respuesta modelo** desde resultados (aviso "se aplica a próximos exámenes; la nota actual no cambia") y desde el banco (`EditQuestionDialog`). Respuestas en blanco = 0 sin gastar cuota.
  - **Scoring dev = crédito PROPORCIONAL (arreglo de la binarización).** En `quiz_submit` la nota parte de un acumulador float `points`: un acierto MCQ/VF suma `1.0`; un dev suma `dev_score/10` (0.0-1.0), incluido el blanco (`dev_score 0` → 0). Antes el `dev_score` (0-10) se colapsaba a 0/1 y el crédito parcial se perdía (dev de 4 daba 0). **Los dev están EXENTOS de penalización**: solo entran en `penalized` los fallos MCQ/VF (`wrong_nondev`) y, con `blanks_count_as_wrong`, los blancos MCQ/VF (`penalty_factor` es anti-azar de opción cerrada; no aplica a respuesta abierta). `raw = points − penalized/pf` (suelo 0), `score_10 = round((raw/total)*10, 2)`. Los **conteos enteros `correct`/`wrong`/`unanswered` NO cambian de semántica**: el umbral `dev_score >= 5` sigue definiendo "acertada" para tiles, stats por pregunta, SRS y "repasar errores"; un dev en blanco sigue siendo `wrong` (no `unanswered`). `raw_score` ahora puede tener decimales (`QuizResults` lo formatea a 2). Regresión fijada en `tests/test_quiz_submit_dev_scoring.py`.
- **Logging de consumo de tokens de Gemini** (INFO, sin persistir): `[GEMINI-USAGE] op=<generate_questions|eval_dev|flashcards|summary> in=… out=… thoughts=… total=…` (de `response.usage_metadata`; `thoughts` = tokens de razonamiento de `gemini-2.5-flash`). Dato medido: una generación ≈ 27k tokens; una corrección ≈ 900 (~30× menos).
- **Resúmenes de IA persistidos por PDF** (colección `summaries`): se generan/regeneran como **acción individual por PDF** (`POST /pdfs/{id}/summary`, upsert), se **sirven cacheados** (coste 0: `GET /pdfs/{id}/summary`, `GET /topics/{id}/summaries`) y sobreviven a recargas. Compartidos entre temas (keyed por `pdf_id`), se borran al desaparecer el PDF. En TopicDetail cada tarjeta de PDF tiene botón "Resumen IA"/"Ver resumen" + Regenerar (componente `SummaryPanel`). El prompt no pasa el nombre del fichero (ruidoso). **Exportación (100% frontend, sin cuota):** desde `SummaryPanel` (menú "Exportar") el resumen cacheado se descarga como **Markdown** (`.md`, Blob + anchor) o se genera un **PDF real** con el ítem **"Exportar a PDF"** (`exportSummaryAsPdf`): usa **jsPDF** (dependencia `jspdf`, **carga diferida** con `import()` dinámico → chunk lazy, no engorda el bundle inicial) renderizando **texto real** (seleccionable/buscable, NO imagen; sin `html2canvas`), con paginación (`doc.addPage()`) y fuente `helvetica` (acentos/ñ vía Latin-1; sin emojis). El PDF se abre como **blob en el visor nativo** del navegador (`window.open(url, "_blank")` sin `noopener`; ver + descargar); `URL.revokeObjectURL` diferido (~60s) para no cortar la carga del visor. Helpers en `frontend/src/lib/summaryExport.js` (`sanitizeFilename`, `summaryToMarkdown`, `summaryToHtml`, `downloadMarkdown`, `printSummaryAsPdf`), defensivos ante `content` objeto/string/incompleto. El export **incluye `key_concepts`** aunque el panel no lo muestre en pantalla. El nombre del fichero sale del PDF (`p.filename`/`pdf_filename`, sanitizado).
- **Estadísticas rápidas y robustas** (`/stats*`): consultas reescritas — racha con una sola `distinct` (no un bucle de hasta 365 consultas), `/stats` overview en paralelo (`asyncio.gather`), y **N+1 eliminado** en `by-subject`/`by-topic`/`gaps` (una agregación `$group`). Front `Stats.jsx` con `Promise.allSettled` + carga/errores por sección. Arreglado el **500 de `/stats/gaps`** (era `$divide` por cero con preguntas sin responder; ahora compara `2*ok < ans`). El suelo de latencia se resolvió **colocando backend y Atlas en la misma región** (ver "Infra").

## Qué falta / pendiente ❌ (por orden)

1. **Deuda menor:**
   - ~~TODO-FASE3 de PDFs: retirar `pdfs.topic_id`~~ → **hecho** (campo, escrituras, 3 fallbacks de lectura y 2 índices retirados; atadura exclusiva en `pdf_links`). Falta solo ejecutar el `$unset` de datos existentes con `migrate_drop_pdf_topic_id.py` (`DRY_RUN=0`) en cada entorno tras desplegar, previa puerta `verify_topic_id_retirement.py` en 0.
   - ~~Endpoint legacy `POST /subjects/{id}/topics/upload` huérfano~~ → **retirado** (código muerto: sin caller en el frontend; los setups de test se recablearon al flujo real de dos/tres pasos).
   - ~~Tests fósiles de Emergent~~ → **eliminados** (eran 3: `test_studyapp_backend.py`, `test_iteration4_gemini_only.py`, `test_iteration3_batching_penalty.py`; golpeaban un `BASE_URL` remoto vía `requests`). La suite in-process es de **~131 tests en verde** y ya **no requiere `--ignore`**: todo `backend/tests/` pasa en limpio.
   - Mejoras de biblioteca no incluidas: renombrar/previsualizar PDFs, etiquetas/carpetas, acciones en masa.
   - **Borrar un resumen suelto conservando el PDF**: hoy no existe (un resumen solo desaparece con su PDF; se regenera encima). No se necesita; añadir solo si surge la demanda.

## Infra / despliegue

- **Backend y frontend en Railway, región EU West (Amsterdam)**; **MongoDB Atlas en `eu-west-3` (París)**. Colocarlos en la misma zona fue lo que quitó el suelo de ~800 ms de latencia (antes el backend estaba en US West). Cualquier servicio nuevo debe ir a EU West.
- **Bases de datos:** producción/staging = **`studia_staging`**; desarrollo = **`studia_dev`** (variable `DB_NAME`).
- **Migraciones y scripts**: anteponer `DB_NAME` al comando para apuntar a la BD correcta, p. ej.:
  ```bash
  cd backend
  DB_NAME=studia_staging DRY_RUN=1 .venv/bin/python scripts/migrate_corrections_counter.py  # dry run
  DB_NAME=studia_staging .venv/bin/python scripts/migrate_corrections_counter.py            # real
  ```
  Scripts de migración vigentes en `backend/scripts/`: `migrate_pdf_links.py`, `migrate_flashcard_source.py`, `migrate_corrections_counter.py` (todos idempotentes + `DRY_RUN`).
- El dominio público de Railway **no cambia** al mover de región → `REACT_APP_BACKEND_URL` y el webhook de Paddle se mantienen.

## Reglas obligatorias

1. **No romper lo que ya funciona.** Probar tras cada cambio (pytest en `backend/tests/`, y comprobación manual / UI cuando aplique). Si algo deja de funcionar, parar y arreglarlo antes de seguir.
2. **Multiusuario por diseño.** Toda colección nueva o existente debe llevar `user_id`, y **toda** lectura/escritura debe filtrarse por el usuario autenticado. Nunca devolver ni modificar datos de otro usuario. Al migrar, asignar los datos huérfanos existentes con cuidado.
3. **Nunca llamar a Gemini sin comprobar antes el plan y el límite del usuario.** Toda ruta que invoque `gemini_client` debe primero verificar plan + cuota restante y rechazar (p. ej. `429`) si se excede. Sin excepción.
4. **Secretos solo en variables de entorno**, nunca en el código ni en commits. Usar `os.environ` / `.env` (ya en `.gitignore`). Nada de claves hardcodeadas.
5. **Commits pequeños y frecuentes.** Un cambio coherente por commit, con mensaje claro. Mantener el **prefijo `/api`** en todos los endpoints nuevos (registrarlos en el `APIRouter(prefix="/api")`).
6. **`pdf_ids` en quiz solo desde single-topic scope.** El control cross-topic vive en el **Banco de preguntas → "Practicar selección"** (que ya filtra por `pdf_source_id` y arranca con `question_ids`). No mezclar los dos caminos.

## Notas de trabajo

- El backend es un único `server.py`; al crecer el SaaS, conviene separar auth, billing y límites en módulos, pero sin romper imports ni rutas existentes.
- `test_result.md` contiene un bloque de protocolo de testing marcado como **DO NOT EDIT** — respétalo.
- Idioma del producto y de las preguntas generadas: **español**.
