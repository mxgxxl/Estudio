import { FileText, Check } from "lucide-react";

// Selector de PDFs reutilizable (preguntas / resumen / flashcards).
// Presentacional: el estado (Set de ids seleccionados) lo maneja el padre.
// Convención de UX: todos preseleccionados por defecto (el padre lo inicializa).
export default function PdfPicker({ pdfs, selected, onToggle, onToggleAll, label = "Fuentes" }) {
    const all = pdfs.length > 0 && selected.size === pdfs.length;
    return (
        <div>
            <div className="flex items-center justify-between mb-2">
                <span className="label-eyebrow">
                    {label} ({selected.size} de {pdfs.length})
                </span>
                {pdfs.length > 1 && (
                    <button
                        type="button"
                        onClick={onToggleAll}
                        data-testid="toggle-all-pdfs"
                        className="text-xs font-medium hover:underline"
                        style={{ color: "var(--brand)" }}
                    >
                        {all ? "Ninguno" : "Todos"}
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
                                onClick={() => onToggle(p.id)}
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
                                    <div className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
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
    );
}
