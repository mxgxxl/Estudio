import { Sparkles, X } from "lucide-react";
import { toast } from "sonner";

// Aviso de "límite alcanzado" con botón placeholder "Hazte Premium".
// La lógica de pago llega en el Bloque 4 (Stripe); aquí solo es informativo.
export default function PremiumDialog({ open, onClose, detail }) {
    if (!open) return null;

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: "rgba(0,0,0,0.4)" }}
            onClick={onClose}
            data-testid="premium-dialog"
        >
            <div
                className="w-full max-w-md rounded-lg shadow-xl p-6 relative"
                style={{ background: "var(--bg-primary)", border: "1px solid var(--border)" }}
                onClick={(e) => e.stopPropagation()}
            >
                <button
                    type="button"
                    onClick={onClose}
                    className="absolute top-4 right-4 text-[color:var(--text-muted)] hover:text-[color:var(--text-primary)]"
                    aria-label="Cerrar"
                >
                    <X className="w-5 h-5" />
                </button>

                <div
                    className="w-12 h-12 rounded-full flex items-center justify-center mb-4"
                    style={{ background: "var(--bg-secondary)", color: "var(--brand)" }}
                >
                    <Sparkles className="w-6 h-6" />
                </div>

                <h2 className="font-display font-bold text-xl mb-2">
                    Has alcanzado el límite del plan gratuito
                </h2>
                <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>
                    {detail ||
                        "Has agotado tus generaciones de IA de este mes. Pásate a Premium para seguir generando preguntas, flashcards y resúmenes."}
                </p>

                <div className="flex items-center justify-end gap-2">
                    <button
                        type="button"
                        onClick={onClose}
                        className="px-4 py-2 rounded-md text-sm font-medium transition-all text-[color:var(--text-secondary)] hover:bg-[color:var(--bg-secondary)]"
                    >
                        Ahora no
                    </button>
                    <button
                        type="button"
                        data-testid="go-premium-btn"
                        onClick={() => toast.info("Los pagos llegarán muy pronto 🚀")}
                        className="flex items-center gap-2 px-4 py-2 rounded-md text-sm font-semibold text-white transition-all"
                        style={{ background: "var(--brand)" }}
                    >
                        <Sparkles className="w-4 h-4" />
                        Hazte Premium
                    </button>
                </div>
            </div>
        </div>
    );
}
