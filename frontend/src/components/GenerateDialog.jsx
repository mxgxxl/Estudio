import { useEffect, useState } from "react";
import { X, Loader2, Sparkles, FileText, Check } from "lucide-react";
import { toast } from "sonner";
import { generateFromTopicPdfs } from "@/lib/api";

export default function GenerateDialog({ open, onClose, onDone, topic, pdfs, defaultSelected }) {
    const [selected, setSelected] = useState(new Set());
    const [numQuestions, setNumQuestions] = useState(10);
    const [questionType, setQuestionType] = useState("mcq");
    const [numOptions, setNumOptions] = useState(3);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        if (open) {
            if (defaultSelected && defaultSelected.length) {
                setSelected(new Set(defaultSelected));
            } else if (pdfs && pdfs.length) {
                setSelected(new Set(pdfs.map((p) => p.id)));
            } else {
                setSelected(new Set());
            }
        }
    }, [open, defaultSelected, pdfs]);

    if (!open) return null;

    const toggle = (id) => {
        const next = new Set(selected);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        setSelected(next);
    };

    const toggleAll = () => {
        if (selected.size === pdfs.length) setSelected(new Set());
        else setSelected(new Set(pdfs.map((p) => p.id)));
    };

    const onSubmit = async (e) => {
        e.preventDefault();
        if (selected.size === 0) return toast.error("Selecciona al menos un PDF");
        setLoading(true);
        try {
            const res = await generateFromTopicPdfs(topic.id, {
                pdf_ids: Array.from(selected),
                num_questions: numQuestions,
                question_type: questionType,
                num_options: numOptions,
            });
            toast.success(`${res.questions_created} preguntas generadas`);
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
            data-testid="generate-dialog"
        >
            <div className="card-organic w-full max-w-lg fade-up my-8" style={{ background: "white" }}>
                <div
                    className="flex items-center justify-between p-5 border-b"
                    style={{ borderColor: "var(--border)" }}
                >
                    <div>
                        <h3 className="font-display text-xl font-bold">Generar preguntas</h3>
                        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                            Elige de qué PDFs y cómo
                        </p>
                    </div>
                    <button
                        onClick={onClose}
                        disabled={loading}
                        data-testid="generate-close"
                        className="p-1.5 rounded-md hover:bg-[color:var(--bg-secondary)]"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>
                <form onSubmit={onSubmit} className="p-5 space-y-4">
                    <div>
                        <div className="flex items-center justify-between mb-2">
                            <span className="label-eyebrow">
                                Fuentes ({selected.size} de {pdfs.length})
                            </span>
                            {pdfs.length > 1 && (
                                <button
                                    type="button"
                                    onClick={toggleAll}
                                    data-testid="toggle-all-pdfs"
                                    className="text-xs font-medium hover:underline"
                                    style={{ color: "var(--brand)" }}
                                >
                                    {selected.size === pdfs.length ? "Ninguno" : "Todos"}
                                </button>
                            )}
                        </div>
                        {pdfs.length === 0 ? (
                            <div
                                className="rounded-md p-4 text-sm text-center"
                                style={{ background: "var(--bg-secondary)", color: "var(--text-muted)" }}
                            >
                                No hay PDFs en este tema. Añade uno primero.
                            </div>
                        ) : (
                            <div className="space-y-1.5 max-h-64 overflow-y-auto">
                                {pdfs.map((p) => {
                                    const active = selected.has(p.id);
                                    return (
                                        <button
                                            type="button"
                                            key={p.id}
                                            onClick={() => toggle(p.id)}
                                            data-testid={`pdf-pick-${p.id}`}
                                            className="w-full flex items-center gap-3 p-3 rounded-md border text-left transition-all"
                                            style={{
                                                borderColor: active ? "var(--brand)" : "var(--border)",
                                                background: active ? "#fdf1ea" : "white",
                                            }}
                                        >
                                            <div
                                                className="w-5 h-5 rounded-sm flex items-center justify-center shrink-0 border"
                                                style={{
                                                    borderColor: active ? "var(--brand)" : "var(--border)",
                                                    background: active ? "var(--brand)" : "white",
                                                }}
                                            >
                                                {active && <Check className="w-3.5 h-3.5 text-white" />}
                                            </div>
                                            <FileText className="w-4 h-4 shrink-0" style={{ color: "var(--text-muted)" }} />
                                            <div className="flex-1 min-w-0">
                                                <div className="text-sm font-medium truncate">{p.filename}</div>
                                                <div
                                                    className="text-xs font-mono"
                                                    style={{ color: "var(--text-muted)" }}
                                                >
                                                    {Math.round(p.char_count / 1000)}k caracteres ·{" "}
                                                    {p.question_count} preguntas ya
                                                </div>
                                            </div>
                                        </button>
                                    );
                                })}
                            </div>
                        )}
                    </div>

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
                                    data-testid={`gen-qtype-${t.id}`}
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
                                data-testid="gen-num-options"
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
                            data-testid="gen-num-questions"
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
                            disabled={loading || selected.size === 0 || pdfs.length === 0}
                            data-testid="generate-submit"
                            className="btn-primary flex-1 flex items-center justify-center gap-2 text-sm"
                        >
                            {loading ? (
                                <>
                                    <Loader2 className="w-4 h-4 animate-spin" /> Generando…
                                </>
                            ) : (
                                <>
                                    <Sparkles className="w-4 h-4" /> Generar
                                </>
                            )}
                        </button>
                    </div>
                    {loading && (
                        <p className="text-xs text-center" style={{ color: "var(--text-muted)" }}>
                            Esto puede tardar entre 20s y 1 min.
                        </p>
                    )}
                </form>
            </div>
        </div>
    );
}
