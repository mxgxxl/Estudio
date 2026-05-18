import { useState } from "react";
import { Upload, X, FileText, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { uploadTopic } from "@/lib/api";

export default function UploadDialog({ open, onClose, onCreated, subjectId }) {
    const [file, setFile] = useState(null);
    const [name, setName] = useState("");
    const [numQuestions, setNumQuestions] = useState(20);
    const [questionType, setQuestionType] = useState("mcq");
    const [numOptions, setNumOptions] = useState(3);
    const [loading, setLoading] = useState(false);

    if (!open) return null;

    const onSubmit = async (e) => {
        e.preventDefault();
        if (!file) return toast.error("Selecciona un PDF");
        if (!name.trim()) return toast.error("Introduce un nombre para el tema");
        if (!subjectId) return toast.error("Falta la asignatura");

        const fd = new FormData();
        fd.append("file", file);
        fd.append("name", name.trim());
        fd.append("num_questions", String(numQuestions));
        fd.append("question_type", questionType);
        fd.append("num_options", String(numOptions));

        setLoading(true);
        try {
            const res = await uploadTopic(subjectId, fd);
            toast.success(`Tema "${res.topic.name}" creado con ${res.questions_created} preguntas`);
            onCreated?.(res);
            onClose();
            setFile(null);
            setName("");
        } catch (err) {
            const msg = err?.response?.data?.detail || err.message || "Error al procesar";
            toast.error(typeof msg === "string" ? msg : "Error al procesar");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4 overflow-y-auto"
            style={{ background: "rgba(35,33,31,0.45)" }}
            data-testid="upload-dialog"
        >
            <div className="card-organic w-full max-w-lg fade-up my-8" style={{ background: "white" }}>
                <div
                    className="flex items-center justify-between p-5 border-b"
                    style={{ borderColor: "var(--border)" }}
                >
                    <div>
                        <h3 className="font-display text-xl font-bold">Nuevo tema</h3>
                        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                            Sube un PDF de temario y la IA generará las preguntas
                        </p>
                    </div>
                    <button
                        onClick={onClose}
                        disabled={loading}
                        data-testid="upload-dialog-close"
                        className="p-1.5 rounded-md hover:bg-[color:var(--bg-secondary)]"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>
                <form onSubmit={onSubmit} className="p-5 space-y-4">
                    <div>
                        <label className="label-eyebrow block mb-1.5">Nombre del tema</label>
                        <input
                            type="text"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            placeholder="Ej. Tema 1 — Introducción"
                            disabled={loading}
                            data-testid="topic-name-input"
                            className="w-full border rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[color:var(--brand)]/20 focus:border-[color:var(--brand)]"
                            style={{ borderColor: "var(--border)" }}
                        />
                    </div>

                    <div>
                        <label className="label-eyebrow block mb-1.5">PDF de apuntes / temario</label>
                        <label
                            className="border-2 border-dashed rounded-md p-5 flex flex-col items-center justify-center gap-2 cursor-pointer transition-colors hover:border-[color:var(--brand)]"
                            style={{ borderColor: file ? "var(--brand)" : "var(--border)" }}
                            data-testid="upload-dropzone"
                        >
                            <input
                                type="file"
                                accept="application/pdf"
                                className="hidden"
                                disabled={loading}
                                onChange={(e) => setFile(e.target.files?.[0] || null)}
                                data-testid="pdf-file-input"
                            />
                            {file ? (
                                <>
                                    <FileText className="w-7 h-7" style={{ color: "var(--brand)" }} />
                                    <span className="text-sm font-medium">{file.name}</span>
                                    <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                                        {(file.size / 1024).toFixed(0)} KB · click para cambiar
                                    </span>
                                </>
                            ) : (
                                <>
                                    <Upload className="w-7 h-7" style={{ color: "var(--text-muted)" }} />
                                    <span className="text-sm font-medium">Haz clic para seleccionar un PDF</span>
                                    <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                                        Solo se acepta .pdf
                                    </span>
                                </>
                            )}
                        </label>
                    </div>

                    <div>
                        <label className="label-eyebrow block mb-1.5">Tipo de preguntas</label>
                        <div className="grid grid-cols-2 gap-2">
                            {[
                                { id: "mcq", label: "Opción múltiple" },
                                { id: "tf", label: "Verdadero/Falso" },
                            ].map((t) => (
                                <button
                                    key={t.id}
                                    type="button"
                                    onClick={() => setQuestionType(t.id)}
                                    data-testid={`qtype-${t.id}`}
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
                                Nº de opciones por pregunta: <span className="font-mono">{numOptions}</span>
                            </label>
                            <input
                                type="range"
                                min="2"
                                max="5"
                                value={numOptions}
                                onChange={(e) => setNumOptions(parseInt(e.target.value))}
                                data-testid="num-options-range"
                                className="w-full accent-[color:var(--brand)]"
                            />
                        </div>
                    )}

                    <div>
                        <label className="label-eyebrow block mb-1.5">
                            Nº de preguntas a generar: <span className="font-mono">{numQuestions}</span>
                        </label>
                        <input
                            type="range"
                            min="5"
                            max="50"
                            value={numQuestions}
                            disabled={loading}
                            onChange={(e) => setNumQuestions(parseInt(e.target.value))}
                            data-testid="num-questions-slider"
                            className="w-full accent-[color:var(--brand)]"
                        />
                    </div>

                    <div className="flex gap-3 pt-2">
                        <button
                            type="button"
                            onClick={onClose}
                            disabled={loading}
                            data-testid="upload-cancel-btn"
                            className="flex-1 px-4 py-2.5 rounded-md border font-medium text-sm hover:bg-[color:var(--bg-secondary)]"
                            style={{ borderColor: "var(--border)" }}
                        >
                            Cancelar
                        </button>
                        <button
                            type="submit"
                            disabled={loading || !file}
                            data-testid="upload-submit-btn"
                            className="btn-primary flex-1 flex items-center justify-center gap-2 text-sm"
                        >
                            {loading ? (
                                <>
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                    Procesando con IA…
                                </>
                            ) : (
                                <>Generar preguntas</>
                            )}
                        </button>
                    </div>
                    {loading && (
                        <p className="text-xs text-center" style={{ color: "var(--text-muted)" }}>
                            Esto puede tardar entre 20s y 1 min dependiendo del PDF.
                        </p>
                    )}
                </form>
            </div>
        </div>
    );
}
