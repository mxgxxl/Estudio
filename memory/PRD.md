# Studia — Multi-subject Study App

## Original Problem Statement
Voy a estudiar un examen de anatomía... [V1] luego ampliado: app de estudio de cualquier asignatura.
Última iteración: organización por asignaturas, regenerar preguntas desde un PDF en cualquier momento, configurar tipo de examen (MCQ / V-F), nº de opciones, nº de preguntas y sistema de corrección (penalización X mal = −1 bien).

## Architecture (v2)
- **Backend**: FastAPI + MongoDB. Colecciones: subjects, topics, pdfs, questions, attempts.
- Modelo de pregunta amplía: `question_type` (mcq|tf), `num_options` (2-5), `pdf_source_id`, `subject_id`.
- Migración automática de v1: temas/preguntas huérfanos → asignatura "Anatomía".
- **Frontend**: rutas `/`, `/asignaturas/:id`, `/temas/:id`, `/quiz/setup`, `/quiz/run`, `/quiz/results`, `/stats`.

## Implemented v2 (2026-05-18)
- Asignaturas: crear/listar/eliminar con color personalizado ✅
- Temas dentro de asignaturas; subida de PDF asociado ✅
- Almacén de PDF (texto extraído) para regenerar preguntas en cualquier momento ✅
- Generación con elección de tipo (MCQ con 2-5 opciones, o V/F) ✅
- Quiz: filtros por subject_id + topic_id + question_type ✅
- Sistema de corrección con penalización (sin / 2 / 3 / 4 → −1) ✅
- UI: tarjetas con color de asignatura, V/F renderizado en grid, opción "dejar en blanco" ✅
- Stats por asignatura ✅

## Backlog
- Reordenar preguntas / duplicar tema
- Exportar banco a JSON
- Modo flashcards
- Modo oscuro
- Auth multi-usuario

## Next Actions
- Probar carga real con un nuevo PDF de otra asignatura
- Considerar racha diaria
