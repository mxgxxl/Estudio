import { Check, Plus, Trash2 } from "lucide-react";

// Campos compartidos del formulario de pregunta, extraídos de
// CreateQuestionDialog y EditQuestionDialog (que duplicaban esta lógica).
//
// Es PRESENTACIONAL y parent-controlled: no tiene estado propio, no valida
// reglas de negocio y no llama a la API. El enunciado, el destino (asignatura/
// tema/PDF), la validación de submit y los toasts viven en cada diálogo padre.
//
// Encapsula: selector de tipo, opciones de mcq (añadir/quitar con reindexado de
// la correcta), par Verdadero/Falso, respuesta modelo de dev y explicación.
export const MIN_OPTS = 2;
export const MAX_OPTS = 5;

const TYPES = [
    { id: "mcq", label: "Opción múltiple" },
    { id: "tf", label: "Verdadero/Falso" },
    { id: "dev", label: "Desarrollo" },
];

export default function QuestionFields({
    questionType,
    onQuestionTypeChange,
    options = [],
    onOptionsChange,
    correctIndex = 0,
    onCorrectIndexChange,
    modelAnswer = "",
    onModelAnswerChange,
    explanation = "",
    onExplanationChange,
    disabled = false,
    // Prefijo de los data-testid. Cada diálogo pasa el suyo para conservar los
    // que ya existían (create-question-… / edit-…).
    testIdPrefix = "question",
}) {
    const isMcq = questionType === "mcq";
    const isTf = questionType === "tf";
    const isDev = questionType === "dev";

    // Sin handler de cambio, el tipo es inmutable: el selector se ve pero está
    // deshabilitado (caso de edición: no se cambia el tipo de una pregunta ya
    // creada, porque su schema —options/correct_index/model_answer— ya está fijado).
    const typeLocked = typeof onQuestionTypeChange !== "function";

    const setOption = (i, val) =>
        onOptionsChange?.(options.map((o, k) => (k === i ? val : o)));

    const addOption = () => {
        if (options.length >= MAX_OPTS) return;
        onOptionsChange?.([...options, ""]);
    };

    const removeOption = (i) => {
        if (options.length <= MIN_OPTS) return;
        onOptionsChange?.(options.filter((_, k) => k !== i));
        // Reajusta el índice de la correcta para no quedar fuera de rango: si se
        // borra la marcada, pasa a la primera; si se borra una anterior, baja uno.
        if (i === correctIndex) onCorrectIndexChange?.(0);
        else if (i < correctIndex) onCorrectIndexChange?.(correctIndex - 1);
    };

    return (
        <>
            {/* Tipo */}
            <div>
                <label className="label-eyebrow block mb-1.5">Tipo</label>
                <div className="flex gap-2">
                    {TYPES.map((t) => (
                        <button
                            key={t.id}
                            type="button"
                            onClick={() => onQuestionTypeChange?.(t.id)}
                            disabled={disabled || typeLocked}
                            data-testid={`${testIdPrefix}-type-${t.id}`}
                            className="flex-1 px-3 py-2 rounded-md text-sm font-medium border disabled:opacity-60"
                            style={{
                                borderColor: questionType === t.id ? "var(--brand)" : "var(--border)",
                                background: questionType === t.id ? "#fdf1ea" : "white",
                                color: questionType === t.id ? "var(--brand)" : "var(--text-secondary)",
                            }}
                        >
                            {t.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* MCQ: opciones */}
            {isMcq && (
                <div>
                    <label className="label-eyebrow block mb-1.5">Opciones (marca la correcta)</label>
                    <div className="space-y-2">
                        {options.map((opt, i) => (
                            <div key={i} className="flex items-center gap-2">
                                <button
                                    type="button"
                                    onClick={() => onCorrectIndexChange?.(i)}
                                    disabled={disabled}
                                    data-testid={`${testIdPrefix}-correct-${i}`}
                                    title="Marcar como correcta"
                                    className="w-6 h-6 rounded-full flex items-center justify-center shrink-0 border"
                                    style={{
                                        borderColor: correctIndex === i ? "var(--brand)" : "var(--border)",
                                        background: correctIndex === i ? "var(--brand)" : "white",
                                    }}
                                >
                                    {correctIndex === i && <Check className="w-3.5 h-3.5 text-white" />}
                                </button>
                                <input
                                    type="text"
                                    value={opt}
                                    onChange={(e) => setOption(i, e.target.value)}
                                    disabled={disabled}
                                    placeholder={`Opción ${String.fromCharCode(65 + i)}`}
                                    data-testid={`${testIdPrefix}-option-${i}`}
                                    className="flex-1 border rounded-md px-3 py-2 text-sm"
                                    style={{ borderColor: "var(--border)" }}
                                />
                                <button
                                    type="button"
                                    onClick={() => removeOption(i)}
                                    disabled={disabled || options.length <= MIN_OPTS}
                                    data-testid={`${testIdPrefix}-remove-option-${i}`}
                                    className="p-1.5 rounded hover:bg-[color:var(--bg-secondary)] disabled:opacity-30 shrink-0"
                                    aria-label="Quitar opción"
                                >
                                    <Trash2 className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
                                </button>
                            </div>
                        ))}
                    </div>
                    {options.length < MAX_OPTS && (
                        <button
                            type="button"
                            onClick={addOption}
                            disabled={disabled}
                            data-testid={`${testIdPrefix}-add-option`}
                            className="mt-2 text-sm flex items-center gap-1 px-2 py-1 rounded hover:bg-[color:var(--bg-secondary)]"
                            style={{ color: "var(--brand)" }}
                        >
                            <Plus className="w-4 h-4" /> Añadir opción
                        </button>
                    )}
                </div>
            )}

            {/* TF: correcta */}
            {isTf && (
                <div>
                    <label className="label-eyebrow block mb-1.5">Respuesta correcta</label>
                    <div className="flex gap-2">
                        {["Verdadero", "Falso"].map((lbl, i) => (
                            <button
                                key={lbl}
                                type="button"
                                onClick={() => onCorrectIndexChange?.(i)}
                                disabled={disabled}
                                data-testid={`${testIdPrefix}-tf-${i}`}
                                className="flex-1 px-3 py-2 rounded-md text-sm font-medium border"
                                style={{
                                    borderColor: correctIndex === i ? "var(--brand)" : "var(--border)",
                                    background: correctIndex === i ? "#fdf1ea" : "white",
                                    color: correctIndex === i ? "var(--brand)" : "var(--text-secondary)",
                                }}
                            >
                                {lbl}
                            </button>
                        ))}
                    </div>
                </div>
            )}

            {/* DEV: respuesta modelo */}
            {isDev && (
                <div>
                    <label className="label-eyebrow block mb-1.5">Respuesta modelo</label>
                    <textarea
                        value={modelAnswer}
                        onChange={(e) => onModelAnswerChange?.(e.target.value)}
                        disabled={disabled}
                        rows={4}
                        data-testid={`${testIdPrefix}-model-answer`}
                        className="w-full border rounded-md px-3 py-2 text-sm resize-none"
                        style={{ borderColor: "var(--border)" }}
                    />
                </div>
            )}

            {/* Explicación */}
            <div>
                <label className="label-eyebrow block mb-1.5">
                    Explicación <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>(opcional)</span>
                </label>
                <textarea
                    value={explanation}
                    onChange={(e) => onExplanationChange?.(e.target.value)}
                    disabled={disabled}
                    rows={2}
                    data-testid={`${testIdPrefix}-explanation`}
                    className="w-full border rounded-md px-3 py-2 text-sm resize-none"
                    style={{ borderColor: "var(--border)" }}
                />
            </div>
        </>
    );
}
