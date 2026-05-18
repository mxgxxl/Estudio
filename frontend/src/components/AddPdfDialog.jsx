import { useState } from "react";
import { Upload, X, FileText, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { addPdfToTopic } from "@/lib/api";

export default function AddPdfDialog({ open, onClose, onUploaded, topicId }) {
    const [file, setFile] = useState(null);
    const [loading, setLoading] = useState(false);

    if (!open) return null;

    const onSubmit = async (e) => {
        e.preventDefault();
        if (!file) return toast.error("Selecciona un PDF");
        const fd = new FormData();
        fd.append("file", file);
        setLoading(true);
        try {
            const pdf = await addPdfToTopic(topicId, fd);
            toast.success(`PDF "${pdf.filename}" añadido`);
            onUploaded?.(pdf);
            onClose();
            setFile(null);
        } catch (err) {
            toast.error(err?.response?.data?.detail || "Error al subir PDF");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: "rgba(35,33,31,0.45)" }}
            data-testid="add-pdf-dialog"
        >
            <div className="card-organic w-full max-w-md fade-up" style={{ background: "white" }}>
                <div
                    className="flex items-center justify-between p-5 border-b"
                    style={{ borderColor: "var(--border)" }}
                >
                    <div>
                        <h3 className="font-display text-xl font-bold">Añadir PDF</h3>
                        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                            Solo se sube. Después podrás generar preguntas.
                        </p>
                    </div>
                    <button
                        onClick={onClose}
                        disabled={loading}
                        data-testid="add-pdf-close"
                        className="p-1.5 rounded-md hover:bg-[color:var(--bg-secondary)]"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>
                <form onSubmit={onSubmit} className="p-5 space-y-4">
                    <label
                        className="border-2 border-dashed rounded-md p-5 flex flex-col items-center justify-center gap-2 cursor-pointer transition-colors hover:border-[color:var(--brand)]"
                        style={{ borderColor: file ? "var(--brand)" : "var(--border)" }}
                        data-testid="add-pdf-dropzone"
                    >
                        <input
                            type="file"
                            accept="application/pdf"
                            className="hidden"
                            disabled={loading}
                            onChange={(e) => setFile(e.target.files?.[0] || null)}
                            data-testid="add-pdf-input"
                        />
                        {file ? (
                            <>
                                <FileText className="w-7 h-7" style={{ color: "var(--brand)" }} />
                                <span className="text-sm font-medium">{file.name}</span>
                                <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                                    {(file.size / 1024).toFixed(0)} KB
                                </span>
                            </>
                        ) : (
                            <>
                                <Upload className="w-7 h-7" style={{ color: "var(--text-muted)" }} />
                                <span className="text-sm font-medium">Selecciona un PDF</span>
                            </>
                        )}
                    </label>
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
                            disabled={loading || !file}
                            data-testid="add-pdf-submit"
                            className="btn-primary flex-1 flex items-center justify-center gap-2 text-sm"
                        >
                            {loading ? (
                                <>
                                    <Loader2 className="w-4 h-4 animate-spin" /> Subiendo…
                                </>
                            ) : (
                                "Subir PDF"
                            )}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
