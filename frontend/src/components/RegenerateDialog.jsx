import { useState } from "react";
import { X, Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { regenerateFromPdf } from "@/lib/api";

export default function RegenerateDialog({ open, onClose, onDone, pdf }) {
    const [numQuestions, setNumQuestions] = useState(10);
    const [questionType, setQuestionType] = useState("mcq");
    const [numOptions, setNumOptions] = useState(3);
    const [loading, setLoading] = useState(false);

    if (!open || !pdf) return null;

    const onSubmit = async (e) => {
        e.preventDefault();
        setLoading(true);
        try {
            const res = await regenerateFromPdf(pdf.id, {
                num_questions: numQuestions,
                question_type: questionType,
                num_options: numOptions,
            });
            toast.success(`${res.questions_created} preguntas nuevas generadas`);
            onDone?.(res);
            onClose();
        } catch (err) {
            toast.error(err?.response?.data?.detail || "Error al generar");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4 overflow-y-auto"
            style={{ background: "rgba(35,33,31,0.45)" }}
            data-testid="regen-dialog"
        >
            <div className="card-organic w-full max-w-md fade-up my-8" style={{ background: "white" }}>
                <div
                    className="flex items-center justify-between p-5 border-b"
                    style={{ borderColor: "var(--border)" }}
                >
                    <div>
                        <h3 className="font-display text-xl font-bold">Generar más preguntas</h3>
                        <p className="text-sm truncate" style={{ color: "var(--text-muted)" }}>
                            Desde: {pdf.filename}
                        </p>
                    </div>
                    <button
                        onClick={onClose}
                        disabled={loading}
                        data-testid="regen-close"
                        className="p-1.5 rounded-md hover:bg-[color:var(--bg-secondary)]"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>
                <form onSubmit={onSubmit} className="p-5 space-y-4">
                    <div>
                        <label className="label-eyebrow block mb-1.5">Tipo</label>
                        <div className="grid grid-cols-2 gap-2">
                            {[
                                { id: "mcq", label: "Opción múltiple" },
                                { id: "tf", label: "Verdadero/Falso" },
                            ].map((t) => (
                                <button
                                    key={t.id}
                                    type="button"
                                    onClick={() => setQuestionType(t.id)}
                                    data-testid={`regen-qtype-${t.id}`}
                                    className="px-3 py-2 rounded-md border text-sm font-medium transition-all"
                                    style={{
                                        borderColor: questionType === t.id ? "var(--brand)" : "var(--border)",
                                        background: questionType === t.id ? "#fdf1ea" : "white",
                                    }}
                                >
                                    {t.label}
                                </button>
                            ))}
                        </div>
                    </div>
                    {questionType === "mcq" && (
                        <div>
                            <label className="label-eyebrow block mb-1.5">
                                Nº de opciones: <span className="font-mono">{numOptions}</span>
                            </label>
                            <input
                                type="range"
                                min="2"
                                max="5"
                                value={numOptions}
                                onChange={(e) => setNumOptions(parseInt(e.target.value))}
                                data-testid="regen-num-options"
                                className="w-full accent-[color:var(--brand)]"
                            />
                        </div>
                    )}
                    <div>
                        <label className="label-eyebrow block mb-1.5">
                            Nº de preguntas: <span className="font-mono">{numQuestions}</span>
                        </label>
                        <input
                            type="range"
                            min="3"
                            max="40"
                            value={numQuestions}
                            onChange={(e) => setNumQuestions(parseInt(e.target.value))}
                            data-testid="regen-num-questions"
                            className="w-full accent-[color:var(--brand)]"
                        />
                    </div>

                    <div className="flex gap-3 pt-2">
                        <button
                            type="button"
                            onClick={onClose}
                            disabled={loading}
                            className="flex-1 px-4 py-2.5 rounded-md border font-medium text-sm hover:bg-[color:var(--bg-secondary)]"
                            style={{ borderColor: "var(--border)" }}
                        >
                            Cancelar
                        </button>
                        <button
                            type="submit"
                            disabled={loading}
                            data-testid="regen-submit"
                            className="btn-primary flex-1 flex items-center justify-center gap-2 text-sm"
                        >
                            {loading ? (
                                <>
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                    Generando…
                                </>
                            ) : (
                                <>
                                    <Sparkles className="w-4 h-4" /> Generar
                                </>
                            )}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
