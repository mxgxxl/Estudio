import { Link } from "react-router-dom";
import { Sparkles, CheckSquare } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

// Color según el margen restante de un contador.
function counterColor(used, limit) {
    const remaining = Math.max(0, limit - used);
    if (remaining <= 0) return "var(--brand)";
    if (remaining <= Math.max(1, Math.ceil(limit * 0.1))) return "#C9821B"; // pocas
    return "var(--text-secondary)";
}

// Cabecera: dos micro-contadores en una sola pastilla —generaciones y
// correcciones— sin ensuciar. Solo desktop.
export default function UsageBadge() {
    const { usage } = useAuth();
    if (!usage) return null;

    // Retrocompat: si el backend antiguo no envía los bloques, cae a los planos.
    const gen = usage.generations || { used: usage.used ?? 0, limit: usage.limit ?? 0 };
    const corr = usage.corrections || { used: 0, limit: 0 };
    const plan = usage.plan || "free";
    const days = usage.days_until_reset;

    const title =
        `Plan ${plan} · ${gen.used}/${gen.limit} crear material · ${corr.used}/${corr.limit} correcciones` +
        (days != null ? ` · se renueva en ${days} día${days === 1 ? "" : "s"}` : "") +
        " · ver detalle";

    return (
        <Link
            to="/uso"
            className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium hover:opacity-80"
            style={{ background: "var(--bg-secondary)" }}
            title={title}
            data-testid="usage-badge"
        >
            <span className="flex items-center gap-1" style={{ color: counterColor(gen.used, gen.limit) }} data-testid="usage-generations">
                <Sparkles className="w-3.5 h-3.5" />
                {gen.used}/{gen.limit}
            </span>
            <span style={{ color: "var(--border)" }}>·</span>
            <span className="flex items-center gap-1" style={{ color: counterColor(corr.used, corr.limit) }} data-testid="usage-corrections">
                <CheckSquare className="w-3.5 h-3.5" />
                {corr.used}/{corr.limit}
            </span>
        </Link>
    );
}
