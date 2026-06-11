import { useState } from "react";
import { Loader2, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import { startPremiumCheckout } from "@/lib/paddle";

// Aviso de "límite alcanzado" con botón "Hazte Premium" que abre el checkout de Paddle.
export default function PremiumDialog({ open, onClose, detail }) {
    const { user } = useAuth();
    const [loading, setLoading] = useState(false);

    const onPremium = async () => {
        setLoading(true);
        try {
            await startPremiumCheckout(user?.email);
            onClose?.();
        } catch (err) {
            if (err?.response?.status === 409) {
                toast.info("Ya tienes una suscripción Premium activa");
                onClose?.();
            } else {
                toast.error(err?.response?.data?.detail || "No se pudo iniciar el pago");
            }
        } finally {
            setLoading(false);
        }
    };

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
                        onClick={onPremium}
                        disabled={loading}
                        className="flex items-center gap-2 px-4 py-2 rounded-md text-sm font-semibold text-white transition-all disabled:opacity-60"
                        style={{ background: "var(--brand)" }}
                    >
                        {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                        Hazte Premium
                    </button>
                </div>
            </div>
        </div>
    );
}
