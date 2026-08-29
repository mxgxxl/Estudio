# NEXT_SESSION_MAC.md

> Traspaso entre sesiones y máquinas. Actualizar al cierre de cada tarea.
> Fuente de verdad técnica: CLAUDE.md. Este archivo es el estado operativo.

## Estado actual
- Rama de integración: saas-oposiciones @ b17a937 (local == origin)
- Suite: 218 tests en verde (pytest backend/tests/)
- main: historia NO relacionada (raíz a731aaf), sin este trabajo. No mergeable.
  Tratarla como historia muerta; saas-oposiciones es la rama real.
- 2026-08-29 · ensure_indices endurecido: fail-fast en el arranque, con 3 reintentos
  acotados antes de rendirse (rama fix/startup-fail-fast). Es hardening técnico a
  raíz del incidente del 28-08, no una decisión de producto: por eso NO figura en
  docs/PRODUCT_DECISIONS.md.

## Cerrado en Flujos 5+6 (autoría manual de preguntas)
- POST /api/questions (272925f) + pdf_source_id opcional (895c20c)
- CreateQuestionDialog (91d1ff0) + wiring TopicDetail/Banco (dcc5205)
- Auto-enfoque de filtros del Banco (45887fc)
- CLAUDE.md sincronizado (b17a937)
- Desviación aceptada: dos botones, NO diálogo de bifurcación (2026-08-05)

## Pendiente inmediato
1. Verificación manual en dispositivo (4 casos de alta manual en /biblioteca/preguntas)
2. Migración pdfs.topic_id: $unset en staging (SOLO Mac, requiere BD)

## Política migración pdfs.topic_id (decidida)
Orden obligatorio: desplegar b17a937 en staging → puerta → $unset.
1. DB_NAME=studia_staging .venv/bin/python scripts/verify_topic_id_retirement.py
   El conteo crítico DEBE ser 0. Si >0: PARAR, listar los huérfanos y reportar
   a M caso a caso. NO auto-reparar pdf_links.
2. Si ==0: DRY_RUN=1 de migrate_drop_pdf_topic_id.py (ver cuántos toca).
3. Solo entonces DRY_RUN=0, con OK final de M.

## Decisiones de producto registradas (fecha + razón)
- 2026-08-05 (ratificada 2026-08-28) · Bifurcación IA/a-mano = dos botones
  (no modal): un clic menos, sin pérdida de alcance. dcc5205.
- 2026-08-28 · source:"manual" DIFERIDO: se mantiene paridad estricta con las
  preguntas IA. Decisión con coste creciente: si se añade en el futuro, lo creado
  hasta entonces queda sin marcar (backfill imposible). Revisar ANTES de la fase
  de etiquetas/carpetas de biblioteca o si el volumen de preguntas manuales deja
  de ser trivial.
- 2026-08-28 · Toast detail en crudo (CreateQuestionDialog.jsx:185): deuda menor,
  casi inalcanzable; se arreglará junto al próximo toque de frontend.

## Frentes siguientes (sin orden de compromiso)
- Deuda: EditQuestionDialog/CreateQuestionDialog duplican campos → extraer QuestionFields.
- Mejoras biblioteca: renombrar/previsualizar PDFs, etiquetas/carpetas, acciones en masa.
- Visor de PDF: necesario (M, 2026-08-29); pendiente decidir almacenamiento
  del original → docs/PRODUCT_DECISIONS.md.
- Resolver main (historia paralela): decidir borrado definitivo cuando nada lo referencie.
