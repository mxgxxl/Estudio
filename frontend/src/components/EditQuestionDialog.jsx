import { useEffect, useState } from "react";
import { X, Loader2, Check } from "lucide-react";
import { toast } from "sonner";
import { editQuestion } from "@/lib/api";

// Edición simple de una pregunta (enunciado, opciones + correcta, explicación /
// respuesta modelo). Reutiliza PATCH /questions/{id}. Se abre cuando `question`
// no es null; devuelve los campos actualizados por onSaved para refrescar la lista.
export default function EditQuestionDialog({ question, onClose, onSaved, notice }) {
    const [text, setText] = useState("");
    const [options, setOptions] = useState([]);
    const [correctIndex, setCorrectIndex] = useState(0);
    const [explanation, setExplanation] = useState("");
    const [modelAnswer, setModelAnswer] = useState("");
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (!question) return;
        setText(question.question || "");
        setOptions(question.options || []);
        setCorrectIndex(question.correct_index ?? 0);
        setExplanation(question.explanation || "");
        setModelAnswer(question.model_answer || "");
    }, [question]);

    if (!question) return null;

    const isDev = question.question_type === "dev";
    const isTf = question.question_type === "tf";

    const setOption = (i, val) => setOptions((prev) => prev.map((o, k) => (k === i ? val : o)));

    const onSubmit = async (e) => {
        e.preventDefault();
        if (!text.trim()) return toast.error("El enunciado no puede estar vacío");
        if (!isDev && options.some((o) => !o.trim())) {
            return toast.error("Las opciones no pueden estar vacías");
        }

        // Solo mandamos lo que aplica al tipo.
        const payload = { question: text.trim(), explanation };
        if (isDev) {
            payload.model_answer = modelAnswer;
        } else {
            payload.options = options.map((o) => o.trim());
            payload.correct_index = correctIndex;
        }

        setSaving(true);
        try {
            await editQuestion(question.id, payload);
            toast.success("Pregunta actualizada");
            onSaved?.({ id: question.id, ...payload });
        } catch (err) {
            toast.error(err?.response?.data?.detail || "No se pudo guardar");
        } finally {
            setSaving(false);
        }
    };

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4 overflow-y-auto"
            style={{ background: "rgba(35,33,31,0.45)" }}
            data-testid="edit-question-dialog"
        >
            <div className="card-organic w-full max-w-lg fade-up my-8" style={{ background: "white" }}>
                <div className="flex items-center justify-between p-5 border-b" style={{ borderColor: "var(--border)" }}>
                    <h3 className="font-display text-xl font-bold">Editar pregunta</h3>
                    <button onClick={onClose} disabled={saving} data-testid="edit-question-close" className="p-1.5 rounded-md hover:bg-[color:var(--bg-secondary)]">
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <form onSubmit={onSubmit} className="p-5 space-y-4">
                    {notice && (
                        <div
                            className="text-xs rounded-md p-2.5"
                            style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
                            data-testid="edit-question-notice"
                        >
                            {notice}
                        </div>
                    )}
                    <div>
                        <label className="label-eyebrow block mb-1.5">Enunciado</label>
                        <textarea
                            value={text}
                            onChange={(e) => setText(e.target.value)}
                            disabled={saving}
                            rows={3}
                            data-testid="edit-question-text"
                            className="w-full border rounded-md px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1"
                            style={{ borderColor: "var(--border)" }}
                        />
                    </div>

                    {!isDev && (
                        <div>
                            <label className="label-eyebrow block mb-1.5">
                                Opciones {isTf ? "(marca la correcta)" : "(marca la correcta)"}
                            </label>
                            <div className="space-y-2">
                                {options.map((opt, i) => (
                                    <div key={i} className="flex items-center gap-2">
                                        <button
                                            type="button"
                                            onClick={() => setCorrectIndex(i)}
                                            data-testid={`edit-correct-${i}`}
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
                                            disabled={saving || isTf}
                                            className="flex-1 border rounded-md px-3 py-2 text-sm disabled:bg-[color:var(--bg-secondary)]"
                                            style={{ borderColor: "var(--border)" }}
                                        />
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {isDev && (
                        <div>
                            <label className="label-eyebrow block mb-1.5">Respuesta modelo</label>
                            <textarea
                                value={modelAnswer}
                                onChange={(e) => setModelAnswer(e.target.value)}
                                disabled={saving}
                                rows={4}
                                className="w-full border rounded-md px-3 py-2 text-sm resize-none"
                                style={{ borderColor: "var(--border)" }}
                            />
                        </div>
                    )}

                    <div>
                        <label className="label-eyebrow block mb-1.5">
                            Explicación <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>(opcional)</span>
                        </label>
                        <textarea
                            value={explanation}
                            onChange={(e) => setExplanation(e.target.value)}
                            disabled={saving}
                            rows={2}
                            className="w-full border rounded-md px-3 py-2 text-sm resize-none"
                            style={{ borderColor: "var(--border)" }}
                        />
                    </div>

                    <div className="flex gap-3 pt-2">
                        <button type="button" onClick={onClose} disabled={saving} className="flex-1 px-4 py-2.5 rounded-md border font-medium text-sm hover:bg-[color:var(--bg-secondary)]" style={{ borderColor: "var(--border)" }}>
                            Cancelar
                        </button>
                        <button type="submit" disabled={saving} data-testid="edit-question-save" className="btn-primary flex-1 flex items-center justify-center gap-2 text-sm">
                            {saving ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</> : "Guardar"}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
