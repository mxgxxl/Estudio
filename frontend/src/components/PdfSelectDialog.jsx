import { useEffect, useState } from "react";
import { X, Loader2, Sparkles } from "lucide-react";
import PdfPicker from "@/components/PdfPicker";

// Diálogo genérico "elige de qué PDFs generar" para resumen y flashcards.
// Solo se usa cuando el tema tiene >1 PDF (con 1 PDF el padre genera directo,
// sin fricción). Todos los PDFs vienen preseleccionados. `children` permite
// añadir controles extra (p. ej. el nº de tarjetas). Durante la carga muestra
// un mensaje claro porque la generación puede tardar (varias llamadas a IA).
export default function PdfSelectDialog({
    open,
    onClose,
    title,
    subtitle,
    pdfs,
    loading = false,
    loadingText = "Generando…",
    submitLabel = "Generar",
    onSubmit,
    children,
}) {
    const [selected, setSelected] = useState(() => new Set());

    // Al abrir, preselecciona todos los PDFs.
    useEffect(() => {
        if (open) setSelected(new Set((pdfs || []).map((p) => p.id)));
    }, [open, pdfs]);

    if (!open) return null;

    const toggle = (id) => {
        setSelected((prev) => {
            const next = new Set(prev);
            next.has(id) ? next.delete(id) : next.add(id);
            return next;
        });
    };
    const toggleAll = () => {
        setSelected((prev) =>
            prev.size === pdfs.length ? new Set() : new Set(pdfs.map((p) => p.id))
        );
    };

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4 overflow-y-auto"
            style={{ background: "rgba(35,33,31,0.45)" }}
            data-testid="pdf-select-dialog"
        >
            <div className="card-organic w-full max-w-lg fade-up my-8" style={{ background: "white" }}>
                <div
                    className="flex items-center justify-between p-5 border-b"
                    style={{ borderColor: "var(--border)" }}
                >
                    <div>
                        <h3 className="font-display text-xl font-bold">{title}</h3>
                        {subtitle && (
                            <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                                {subtitle}
                            </p>
                        )}
                    </div>
                    <button
                        onClick={onClose}
                        disabled={loading}
                        data-testid="pdf-select-close"
                        className="p-1.5 rounded-md hover:bg-[color:var(--bg-secondary)] disabled:opacity-50"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <div className="p-5 space-y-4">
                    <PdfPicker
                        pdfs={pdfs}
                        selected={selected}
                        onToggle={toggle}
                        onToggleAll={toggleAll}
                    />

                    {children}

                    <div className="flex gap-3 pt-2">
                        <button
                            type="button"
                            onClick={onClose}
                            disabled={loading}
                            className="flex-1 px-4 py-2.5 rounded-md border font-medium text-sm hover:bg-[color:var(--bg-secondary)] disabled:opacity-50"
                            style={{ borderColor: "var(--border)" }}
                        >
                            Cancelar
                        </button>
                        <button
                            type="button"
                            onClick={() => onSubmit([...selected])}
                            disabled={loading || selected.size === 0}
                            data-testid="pdf-select-submit"
                            className="btn-primary flex-1 flex items-center justify-center gap-2 text-sm"
                        >
                            {loading ? (
                                <>
                                    <Loader2 className="w-4 h-4 animate-spin" /> {loadingText}
                                </>
                            ) : (
                                <>
                                    <Sparkles className="w-4 h-4" /> {submitLabel}
                                </>
                            )}
                        </button>
                    </div>
                    {loading && (
                        <p className="text-xs text-center" style={{ color: "var(--text-muted)" }}>
                            Esto puede tardar hasta ~1 min. No cierres esta ventana.
                        </p>
                    )}
                </div>
            </div>
        </div>
    );
}
