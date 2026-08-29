# UI_AUDIT.md — Auditoría de interfaz de Studia

> Base: `saas-oposiciones` @ `6768db0` (tras el merge del PR #3). Suite: 228 tests en verde.
> Fecha: 2026-08-29.

## Metodología y límites

Esta es una **auditoría a nivel de código**: se ha leído `design_guidelines.json`
y se ha contrastado con el uso real recorriendo `frontend/src/pages/` y
`frontend/src/components/`. Cada hallazgo lleva evidencia `archivo:línea` o un
conteo reproducible con `grep`.

**Lo que esta auditoría NO puede ver**, y que M debe completar con revisión
visual en dispositivo:
- Cómo se ve realmente cada pantalla (contraste percibido, densidad, jerarquía).
- Comportamiento táctil: tamaño de los objetivos de pulsación, scroll, teclado
  virtual tapando inputs.
- Rendimiento percibido (parpadeos, saltos de layout al cargar).
- Accesibilidad real (lectores de pantalla, foco visible, orden de tabulación).

Hay una sección vacía al final para esas notas.

---

## Contraste con `design_guidelines.json`

| Declarado en guidelines | Realidad en el código |
|---|---|
| Fuentes Manrope (títulos) + IBM Plex Sans (cuerpo) | ✅ Cumplido (`index.css:1,28,40`) |
| Paleta earthy con tokens | ⚠️ Parcial: hay tokens CSS (`var(--brand)`, `var(--border)`…) **y** hex sueltos (ver #8) |
| «Sharp or slightly rounded corners (max `rounded-md`)» | ⚠️ Incumplido: `rounded-xl` ×6, `rounded-lg` ×5, `rounded-full` ×34 |
| «Use standard Shadcn components for complex interactions» | ❌ Incumplido casi por completo (ver #1, #2) |
| «Page transitions: fade in… (framer-motion)» | ❌ **framer-motion no está instalado** (ausente de `package.json`) |
| «Add data-testid to all interactive elements» | ✅ Ampliamente cumplido |
| Botón: `hover:-translate-y-0.5`, sombra suave | ✅ Cumplido en `.btn-primary` (`index.css:84-105`) |

---

## Hallazgos

| # | Pantalla / componente | Hallazgo | Severidad | Esfuerzo | Recomendación |
|---|---|---|---|---|---|
| 1 | Transversal (diálogos) | `components/ui/dialog.jsx` existe pero **ninguna pantalla lo importa** (solo `ui/command.jsx`, interno de shadcn). Los 16 diálogos reales usan un overlay propio `fixed inset-0 z-50` | Estructural | M | Decidir estándar (ver «Decisiones para M») y **borrar o adoptar** `ui/dialog.jsx`. Hoy es código muerto que confunde |
| 2 | Login, Register vs resto | **Solo** `Login.jsx:4-7` y `Register.jsx:4-7` usan `Button`/`Input`/`Label`/`Card` de shadcn. El resto de la app usa Tailwind ad hoc + la clase propia `.btn-primary` (44 usos en 20 ficheros) | Estructural | L | Unificar en una dirección. Auth se ve distinto del resto de la app |
| 3 | Dashboard, SubjectDetail, TopicDetail, QuizRun, steppers | `window.confirm` nativo en acciones destructivas y de salida: `Dashboard.jsx:100`, `SubjectDetail.jsx:46`, `TopicDetail.jsx:96`, `QuizRun.jsx:461,481`, `CreateSubjectStepper.jsx:97`, `CreateTopicStepper.jsx:104` — mientras Library y QuestionBank sí tienen diálogo propio (`Library.jsx:319`, `QuestionBank.jsx:599`) | Media | M | Un `ConfirmDialog` compartido. Hoy borrar una asignatura usa el diálogo del navegador y borrar un PDF uno de la app |
| 4 | QuizRun, FlashcardMode | `toast.error("Error")` sin contexto: `QuizRun.jsx:433,441`, `FlashcardMode.jsx:195` | Cosmética | S | Mensaje concreto por acción |
| 5 | Dashboard | Único sitio que se **traga** el error de carga en `console.error` (`Dashboard.jsx:86`); las demás pantallas hacen `toast.error`. Si falla la carga, la portada queda vacía sin explicación | Media | S | Alinear con el resto: toast + estado de error |
| 6 | Transversal (carga) | 7 pantallas sin spinner (`Biblioteca`, `Dashboard`, `LibrarySummaries`, `Login`, `Register`, `SubjectDetail`, `Uso`), y textos distintos para lo mismo: «Cargando…», «Cargando uso…» (`Uso.jsx:31`), «Cargando estado…» | Media | M | Un `<LoadingState/>` y un `<EmptyState/>` compartidos |
| 7 | Transversal (tipografía) | **12+ combinaciones distintas** de cabecera con `font-display`: `text-xl font-bold` (×11), `text-2xl font-bold` (×4), `text-3xl md:text-4xl font-bold mt-1` (×2), `font-bold text-lg` (×3)… sin escala definida | Media | M | Fijar 3-4 niveles (h1/h2/h3/eyebrow) como clases en `index.css`, junto a `.label-eyebrow` que ya existe |
| 8 | Transversal (color) | Hex hardcodeados conviviendo con tokens: `#fdf1ea` ×30, `#fbeeee` ×8, `#eef2ec` ×8, `#5c8a7a` ×5. El rojo de error aparece de **tres formas**: `var(--error, #B84A4A)` (`Library.jsx:347`, `QuestionBank.jsx:613`), `#b84a4a` literal (`CreateSubjectStepper.jsx:284,521`) y `var(--error)` a secas | Media | M | Promover los hex repetidos a tokens (`--brand-soft`, `--error-soft`, `--success-soft`) y sustituir |
| 9 | Transversal (radios) | `rounded-xl` ×6 y `rounded-lg` ×5 contra el «max `rounded-md`» de las guidelines (`rounded-md` ×191) | Cosmética | S | Normalizar a `rounded-md`; `rounded-full` en avatares/pills es legítimo |
| 10 | QuestionBank, Library, QuizRun, LibrarySummaries, Login, Register | **Responsive casi ausente en las pantallas más densas**: `QuestionBank.jsx` 733 líneas con **1** breakpoint; `Library.jsx` 368/1; `QuizRun.jsx` 673/2; `LibrarySummaries`, `Login` y `Register` con **0**. En `Layout.jsx:80,91` el nav sí oculta etiquetas en móvil | Estructural | L | **Prioritario si el uso principal es móvil.** QuizRun es la pantalla de estudio y QuestionBank la de gestión: son las dos que más sufren |
| 11 | Dashboard, TopicDetail, SubjectDetail | El evento `studia:generation-complete` (generación diferida) solo lo escuchan `QuizSetup.jsx:330` y `QuestionBank.jsx:149`. Si el usuario cierra un stepper con la generación en curso y está en otra pantalla, esa vista no se refresca | Media | S | Añadir el listener donde se listan preguntas/temas, o subirlo a un hook compartido |
| 12 | QuestionBank | `handleTopicCreated` (`:155`) y `handleQuestionCreated` (`:170`) hacen casi lo mismo (recargar catálogos + enfocar filtros) | Cosmética | S | Unificar en un solo helper si aparece un tercer caso |
| 13 | QuizSetup | 9 estados vacíos distintos en una sola pantalla (899 líneas, la mayor de la app) | Media | M | Extraer `<EmptyState/>` (ver #6) y trocear la pantalla |
| 14 | CreateSubjectStepper / CreateTopicStepper | 573 y 568 líneas, **casi gemelos**: normalizando los nombres, solo ~257 líneas difieren | Estructural | L | Extraer los pasos comunes (adjuntar PDFs, generar con estados). Es la mayor duplicación viva del frontend |
| 15 | Transversal (toasts) | 78 `toast.error` frente a 24 `toast.success` y 2 `toast.info`; mensajes duplicados literalmente en sitios distintos («No hay preguntas disponibles» ×2, «Error al eliminar» ×2) | Cosmética | S | Centralizar los mensajes recurrentes |

---

## Patrones transversales

**Diálogos.** Dos sistemas conviven: el overlay propio (16 ficheros) y shadcn
(instalado, sin usar). El overlay repite en cada sitio el mismo bloque:
`fixed inset-0 z-50 flex items-center justify-center p-4` + `card-organic
w-full max-w-md|max-w-lg fade-up`. Sea cual sea el estándar elegido, conviene
un `<Modal/>` que encapsule overlay, cabecera con título y botón de cierre, y
pie de acciones.

**Confirmaciones.** Tres niveles hoy: `window.confirm` (7 sitios), diálogo
propio con botón rojo (Library, QuestionBank) y, en los steppers, un `confirm`
para decidir si la generación sigue en segundo plano. Unificarlo es también una
cuestión de confianza: el `confirm` del navegador rompe la ilusión de app.

**Estados.** No hay componentes compartidos de carga, vacío ni error; cada
pantalla los resuelve a mano, y de ahí salen los hallazgos #5, #6 y #13.

**Color y tipografía.** Existe una capa de tokens (`index.css`) bien usada
—`var(--text-muted)` ×193, `var(--border)` ×143, `var(--brand)` ×141— pero
conviven con hex sueltos. El problema no es el sistema: es que está a medio
aplicar.

---

## Priorización

### Quick wins (esfuerzo S) — recomendado empezar aquí
1. **#5** Dashboard: mostrar el error de carga en vez de tragarlo.
2. **#4** Sustituir los tres `toast.error("Error")` por mensajes con contexto.
3. **#11** Añadir el listener `studia:generation-complete` donde falta.
4. **#9** Normalizar `rounded-xl`/`rounded-lg` a `rounded-md`.
5. **#15** Unificar los mensajes de toast duplicados.
6. **#12** Fundir los dos `handleCreated` de QuestionBank.

### Fundacionales (esfuerzo M) — habilitan el resto
7. **#1 + Decisión 1**: elegir estándar de diálogo y extraer `<Modal/>`.
8. **#3** `<ConfirmDialog/>` compartido y retirada de `window.confirm`.
9. **#6 + #13** `<LoadingState/>` y `<EmptyState/>`.
10. **#7** Escala tipográfica en `index.css`.
11. **#8** Promover los hex repetidos a tokens.

### Rediseños por pantalla (esfuerzo L)
12. **#10** Responsive de QuizRun y QuestionBank — **el de mayor impacto si el
    uso real es en móvil**.
13. **#2** Unificar Login/Register con el resto (o al revés).
14. **#14** Desduplicar los dos steppers.
15. Trocear QuizSetup (899 líneas) y QuestionBank (733).

---

## Decisiones para M

1. **¿Diálogos: shadcn o el overlay propio?** El overlay es el estándar de
   facto (16 ficheros) y funciona; shadcn daría accesibilidad (foco atrapado,
   `Esc`, `aria-*`) sin escribirla a mano. Migrar es esfuerzo L; adoptar el
   overlay como oficial y borrar `ui/dialog.jsx` es S. **No dejar las dos.**
2. **¿Login/Register se alinean con la app, o la app con shadcn?** Hoy son las
   dos únicas pantallas con otro lenguaje visual.
3. **¿El responsive es prioridad?** Depende de si el uso real es móvil. Si lo
   es, #10 debería adelantarse a todo lo demás.
4. **¿Se mantiene `design_guidelines.json` como fuente de verdad?** Declara
   framer-motion, que no está instalado, y un `max rounded-md` que no se
   respeta. O se actualiza el documento, o se corrige el código.
5. **¿Sistema de componentes propio?** Los hallazgos #1, #3, #6 y #13 apuntan
   todos a lo mismo: falta una capa de primitivas (`Modal`, `ConfirmDialog`,
   `EmptyState`, `LoadingState`). Construirla primero abarata todo lo demás.

---

## Notas de M (dispositivo)

<!-- Rellenar tras la revisión visual en móvil/escritorio. Sugerencia: una
     línea por pantalla, apuntando qué se ve mal y en qué tamaño. -->

- Dashboard:
- SubjectDetail:
- TopicDetail:
- QuizSetup:
- QuizRun:
- QuizResults:
- Stats / historial / detalle de intento:
- FlashcardMode:
- SurvivalMode:
- Biblioteca (PDFs / Preguntas / Resúmenes):
- Uso:
- Cuenta:
- Login / Register:
