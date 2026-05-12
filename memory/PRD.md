# Anatomía — Study App

## Original Problem Statement
Voy a estudiar un examen de anatomía. Necesito una App de estudio completa, para hacer exámenes y repasar errores. Las preguntas y las posibles respuestas deben estar sacadas de las diapositivas de cada tema (3 opciones, 1 correcta). Añadir todas las funcionalidades necesarias para mejorar el estudio. Poder generar más preguntas añadiendo más temas más adelante.

## User Choices (2026-05-12)
- Generación con IA: **Claude Sonnet 4.5** (claude-sonnet-4-5-20250929) via Emergent LLM Key
- Funcionalidades: Examen cronometrado + Práctica libre + Repaso de errores + SRS + Favoritas/difíciles + Stats
- Sin login (uso personal, multi-dispositivo)
- Subida de PDFs desde la app

## Architecture
- **Backend**: FastAPI + MongoDB. PDF via `pypdf`, LLM via `emergentintegrations` (Anthropic Claude Sonnet 4.5).
- **Frontend**: React 19 + Tailwind + shadcn. Organic earthy palette (#C65D47 terracotta + sage + bone). Manrope (display) + IBM Plex Sans (body).

## Implemented (2026-05-12)
- Subida de PDF → extracción de texto → generación de preguntas tipo test (3 opciones, 1 correcta + explicación) ✅
- CRUD de temas y preguntas; añadir más preguntas a un tema existente ✅
- Modos: Práctica, Examen cronometrado, Errores, SRS (SM-2 simplificado), Favoritas ✅
- Quiz runner con opciones aleatorizadas, feedback inmediato en práctica, cronómetro en examen ✅
- Página de resultados con revisión pregunta a pregunta + nota /10 ✅
- Marcar favoritas / difíciles, eliminar preguntas ✅
- Dashboard con stats globales y vista por tema, últimos intentos ✅
- Filtros en TopicDetail (todas/favoritas/difíciles/falladas) ✅

## Backlog (P1/P2)
- P1: Exportar/importar banco de preguntas (JSON)
- P1: Modo "flashcards" pure (sin opciones, solo recordar)
- P2: Estadísticas de tiempo por pregunta
- P2: Multi-usuario con autenticación
- P2: Imágenes en preguntas (anatomía visual)
- P2: Modo oscuro

## Next Actions
- Esperar feedback del usuario tras la primera sesión real
- Sugerir activación de subida masiva si tiene muchos PDFs
