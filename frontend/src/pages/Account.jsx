import { useCallback, useEffect, useState } from "react";
import { Sparkles, Loader2, CheckCircle2, CreditCard } from "lucide-react";
import { toast } from "sonner";
import { billingStatus } from "@/lib/api";
import { startPremiumCheckout } from "@/lib/paddle";
import { useAuth } from "@/context/AuthContext";

const STATUS_LABEL = {
    free: "Gratis",
    active: "Activa",
    trialing: "Periodo de prueba",
    canceled: "Cancelada",
    past_due: "Pago pendiente",
};

function formatDate(iso) {
    if (!iso) return null;
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    return d.toLocaleDateString("es-ES", { day: "numeric", month: "long", year: "numeric" });
}

export default function Account() {
    const { user, usage } = useAuth();
    const [status, setStatus] = useState(null);
    const [loading, setLoading] = useState(true);
    const [checkingOut, setCheckingOut] = useState(false);

    const refresh = useCallback(() => {
        return billingStatus()
            .then((s) => setStatus(s))
            .catch(() => setStatus(null))
            .finally(() => setLoading(false));
    }, []);

    useEffect(() => {
        refresh();
    }, [refresh]);

    // Tras completar el pago, refrescamos el estado (con margen para el webhook).
    useEffect(() => {
        const onCheckout = () => {
            refresh();
            setTimeout(refresh, 2500);
        };
        window.addEventListener("studia:checkout-completed", onCheckout);
        return () => window.removeEventListener("studia:checkout-completed", onCheckout);
    }, [refresh]);

    const onPremium = async () => {
        setCheckingOut(true);
        try {
            await startPremiumCheckout(user?.email);
        } catch (err) {
            if (err?.response?.status === 409) {
                toast.info("Ya tienes una suscripción Premium activa");
                refresh();
            } else {
                toast.error(err?.response?.data?.detail || "No se pudo iniciar el pago");
            }
        } finally {
            setCheckingOut(false);
        }
    };

    const plan = status?.plan || user?.plan || "free";
    const isPremium = plan === "premium";
    const subStatus = status?.subscription_status || "free";
    const periodEnd = formatDate(status?.current_period_end);

    return (
        <div className="max-w-3xl mx-auto px-5 md:px-8 py-8">
            <div className="flex items-center gap-2 mb-6">
                <CreditCard className="w-5 h-5" style={{ color: "var(--text-muted)" }} />
                <h1 className="font-display font-bold text-2xl">Mi cuenta</h1>
            </div>

            {/* Datos del usuario */}
            <div className="card-organic p-5 mb-5">
                <span className="label-eyebrow">Cuenta</span>
                <div className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>{user?.email}</div>
            </div>

            {/* Suscripción */}
            <div className="card-organic p-5">
                <div className="flex items-center justify-between mb-4">
                    <span className="label-eyebrow">Suscripción</span>
                    <span
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold"
                        style={{
                            background: isPremium ? "var(--brand)" : "var(--bg-secondary)",
                            color: isPremium ? "#fff" : "var(--text-secondary)",
                        }}
                        data-testid="account-plan-badge"
                    >
                        {isPremium && <Sparkles className="w-3.5 h-3.5" />}
                        {isPremium ? "Premium" : "Plan gratuito"}
                    </span>
                </div>

                {loading ? (
                    <div className="flex items-center gap-2 text-sm" style={{ color: "var(--text-muted)" }}>
                        <Loader2 className="w-4 h-4 animate-spin" /> Cargando estado…
                    </div>
                ) : (
                    <dl className="text-sm space-y-2">
                        <div className="flex justify-between">
                            <dt style={{ color: "var(--text-muted)" }}>Estado</dt>
                            <dd className="font-medium">{STATUS_LABEL[subStatus] || subStatus}</dd>
                        </div>
                        {periodEnd && (
                            <div className="flex justify-between">
                                <dt style={{ color: "var(--text-muted)" }}>
                                    {subStatus === "canceled" ? "Acceso hasta" : "Renueva el"}
                                </dt>
                                <dd className="font-medium">{periodEnd}</dd>
                            </div>
                        )}
                        {usage && (
                            <div className="flex justify-between">
                                <dt style={{ color: "var(--text-muted)" }}>Generaciones de IA este mes</dt>
                                <dd className="font-medium">{usage.used} / {usage.limit}</dd>
                            </div>
                        )}
                    </dl>
                )}

                {!isPremium && (
                    <button
                        type="button"
                        onClick={onPremium}
                        disabled={checkingOut}
                        data-testid="account-go-premium"
                        className="mt-5 w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-md text-sm font-semibold text-white transition-all disabled:opacity-60"
                        style={{ background: "var(--brand)" }}
                    >
                        {checkingOut ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                        Hazte Premium
                    </button>
                )}

                {isPremium && (
                    <div
                        className="mt-5 flex items-center gap-2 text-sm rounded-md p-3"
                        style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
                    >
                        <CheckCircle2 className="w-4 h-4" style={{ color: "var(--sage)" }} />
                        Tienes acceso completo a las generaciones de IA del plan Premium.
                    </div>
                )}
            </div>
        </div>
    );
}
