import { useEffect } from "react";
import { Sparkles, CheckSquare, HelpCircle, BookOpenCheck, Layers } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

// Barra de progreso de un contador (used/limit).
function Bar({ used, limit }) {
    const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
    const low = limit > 0 && limit - used <= Math.max(1, Math.ceil(limit * 0.1));
    const color = used >= limit && limit > 0 ? "var(--brand)" : low ? "#C9821B" : "var(--sage)";
    return (
        <div className="h-2 rounded-full overflow-hidden" style={{ background: "var(--bg-secondary)" }}>
            <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
        </div>
    );
}

// Página de uso de IA: única fuente de verdad del detalle de cuota. "Crear
// material" se abre en su desglose por tipo (preguntas · resúmenes · flashcards
// del ciclo actual); "Correcciones" se muestra sin desglose (una sola fuente).
export default function Uso() {
    const { usage, refreshUsage } = useAuth();

    // Al entrar, refresca para reflejar consumos recientes.
    useEffect(() => {
        refreshUsage();
    }, [refreshUsage]);

    if (!usage) {
        return (
            <div className="max-w-3xl mx-auto px-5 md:px-8 py-10" style={{ color: "var(--text-muted)" }}>
                Cargando uso…
            </div>
        );
    }

    const gen = usage.generations || { used: usage.used ?? 0, limit: usage.limit ?? 0 };
    const corr = usage.corrections || { used: 0, limit: 0 };
    const byType = gen.by_type || {};
    const days = usage.days_until_reset;

    const TYPES = [
        { key: "questions", label: "Preguntas", icon: HelpCircle },
        { key: "summaries", label: "Resúmenes", icon: BookOpenCheck },
        { key: "flashcards", label: "Flashcards", icon: Layers },
    ];

    return (
        <div className="max-w-3xl mx-auto px-5 md:px-8 py-8 md:py-12">
            <span className="label-eyebrow">Tu consumo de IA</span>
            <h1 className="font-display text-3xl md:text-4xl font-bold mt-1 mb-2">Uso de IA</h1>
            <p className="text-sm mb-8" style={{ color: "var(--text-secondary)" }}>
                Plan <span className="font-medium">{usage.plan || "free"}</span>
                {days != null && (
                    <> · se renueva en {days} día{days === 1 ? "" : "s"}</>
                )}
            </p>

            {/* Crear material — con desglose por tipo */}
            <section className="card-organic p-5 md:p-6 mb-5" data-testid="usage-create">
                <div className="flex items-center justify-between mb-3">
                    <span className="label-eyebrow flex items-center gap-2">
                        <Sparkles className="w-4 h-4" style={{ color: "var(--brand)" }} /> Crear material
                    </span>
                    <span className="font-mono text-sm" data-testid="usage-create-total">
                        {gen.used} / {gen.limit}
                    </span>
                </div>
                <Bar used={gen.used} limit={gen.limit} />

                <div className="mt-5 space-y-3">
                    <div className="text-xs font-medium" style={{ color: "var(--text-muted)" }}>
                        Desglose de este ciclo
                    </div>
                    {TYPES.map(({ key, label, icon: Icon }) => (
                        <div key={key} className="flex items-center justify-between text-sm" data-testid={`usage-type-${key}`}>
                            <span className="flex items-center gap-2" style={{ color: "var(--text-secondary)" }}>
                                <Icon className="w-4 h-4" style={{ color: "var(--brand)" }} />
                                {label}
                            </span>
                            <span className="font-mono">{byType[key]?.used ?? 0}</span>
                        </div>
                    ))}
                </div>
            </section>

            {/* Correcciones — sin desglose (una sola fuente) */}
            <section className="card-organic p-5 md:p-6" data-testid="usage-corrections">
                <div className="flex items-center justify-between mb-3">
                    <span className="label-eyebrow flex items-center gap-2">
                        <CheckSquare className="w-4 h-4" style={{ color: "var(--brand)" }} /> Correcciones
                    </span>
                    <span className="font-mono text-sm" data-testid="usage-corrections-total">
                        {corr.used} / {corr.limit}
                    </span>
                </div>
                <Bar used={corr.used} limit={corr.limit} />
                <p className="text-xs mt-3" style={{ color: "var(--text-muted)" }}>
                    Evaluación de respuestas de desarrollo (1 por respuesta corregida).
                </p>
            </section>
        </div>
    );
}
