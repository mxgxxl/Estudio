import { useState } from "react";
import { X, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { createSubject } from "@/lib/api";

const PRESET = [
    "#C65D47",
    "#7A8B76",
    "#6C8A9C",
    "#D4A373",
    "#9C7A8B",
    "#5C8A7A",
    "#B84A4A",
    "#8A857D",
];

export default function NewSubjectDialog({ open, onClose, onCreated }) {
    const [name, setName] = useState("");
    const [color, setColor] = useState(PRESET[0]);
    const [loading, setLoading] = useState(false);

    if (!open) return null;

    const onSubmit = async (e) => {
        e.preventDefault();
        if (!name.trim()) {
            toast.error("Introduce un nombre");
            return;
        }
        setLoading(true);
        try {
            const s = await createSubject({ name: name.trim(), color });
            toast.success(`Asignatura "${s.name}" creada`);
            onCreated?.(s);
            onClose();
            setName("");
        } catch (err) {
            toast.error(err?.response?.data?.detail || "Error al crear");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: "rgba(35,33,31,0.45)" }}
            data-testid="new-subject-dialog"
        >
            <div className="card-organic w-full max-w-md fade-up" style={{ background: "white" }}>
                <div
                    className="flex items-center justify-between p-5 border-b"
                    style={{ borderColor: "var(--border)" }}
                >
                    <div>
                        <h3 className="font-display text-xl font-bold">Nueva asignatura</h3>
                        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                            Crea una asignatura para organizar tus temas
                        </p>
                    </div>
                    <button
                        onClick={onClose}
                        disabled={loading}
                        data-testid="subject-dialog-close"
                        className="p-1.5 rounded-md hover:bg-[color:var(--bg-secondary)]"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>
                <form onSubmit={onSubmit} className="p-5 space-y-4">
                    <div>
                        <label className="label-eyebrow block mb-1.5">Nombre</label>
                        <input
                            type="text"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            placeholder="Ej. Histología, Bioquímica, Derecho Romano…"
                            disabled={loading}
                            data-testid="subject-name-input"
                            autoFocus
                            className="w-full border rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[color:var(--brand)]/20 focus:border-[color:var(--brand)]"
                            style={{ borderColor: "var(--border)" }}
                        />
                    </div>
                    <div>
                        <label className="label-eyebrow block mb-1.5">Color</label>
                        <div className="flex gap-2 flex-wrap">
                            {PRESET.map((c) => (
                                <button
                                    key={c}
                                    type="button"
                                    onClick={() => setColor(c)}
                                    className="w-8 h-8 rounded-md transition-transform hover:scale-110"
                                    style={{
                                        background: c,
                                        border: color === c ? "2px solid var(--text-primary)" : "2px solid transparent",
                                    }}
                                    data-testid={`color-${c}`}
                                />
                            ))}
                        </div>
                    </div>
                    <div className="flex gap-3 pt-2">
                        <button
                            type="button"
                            onClick={onClose}
                            disabled={loading}
                            data-testid="subject-cancel-btn"
                            className="flex-1 px-4 py-2.5 rounded-md border font-medium text-sm hover:bg-[color:var(--bg-secondary)]"
                            style={{ borderColor: "var(--border)" }}
                        >
                            Cancelar
                        </button>
                        <button
                            type="submit"
                            disabled={loading}
                            data-testid="subject-submit-btn"
                            className="btn-primary flex-1 flex items-center justify-center gap-2 text-sm"
                        >
                            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Crear asignatura"}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
