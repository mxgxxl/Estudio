// Etiquetas legibles (ES) de los dos ejes de estudio: COMPORTAMIENTO (cómo se
// juega) × SELECCIÓN (qué preguntas). Fuente única de las etiquetas, reutilizada
// por QuizSetup (selectores), QuizRun (badge) y Stats (intentos recientes).
export const BEHAVIOR_LABELS = { practice: "Práctica", exam: "Examen" };
export const SELECTION_LABELS = { all: "Todas", errors: "Errores", srs: "Repaso", favorites: "Favoritas" };

// Etiqueta de un intento a partir de sus ejes: "Comportamiento · Selección".
// Defaults tolerantes por si llegara sin ejes (no debería tras la migración).
export function attemptLabel(a) {
    const b = BEHAVIOR_LABELS[a.behavior] || "Práctica";
    const s = SELECTION_LABELS[a.selection] || "Todas";
    return `${b} · ${s}`;
}
