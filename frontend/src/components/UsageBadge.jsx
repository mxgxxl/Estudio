import { Sparkles } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

// Contador "X de Y generaciones usadas este mes" en la cabecera.
export default function UsageBadge() {
    const { usage } = useAuth();
    if (!usage) return null;

    const { used = 0, limit = 0, plan = "free" } = usage;
    const remaining = Math.max(0, limit - used);
    const exhausted = remaining <= 0;
    const low = !exhausted && remaining <= Math.max(1, Math.ceil(limit * 0.1));

    const color = exhausted
        ? "var(--brand)"
        : low
        ? "#C9821B"
        : "var(--text-secondary)";

    return (
        <div
            className="hidden md:flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium"
            style={{ background: "var(--bg-secondary)", color }}
            title={`Plan ${plan} · ${used} de ${limit} generaciones de IA usadas este mes`}
            data-testid="usage-badge"
        >
            <Sparkles className="w-3.5 h-3.5" />
            <span>
                {used} / {limit} generaciones
            </span>
        </div>
    );
}
