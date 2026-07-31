import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
    BarChart3, BookOpen, Target, Clock, Star, Flame,
    Brain, FolderOpen, AlertTriangle, Zap, Loader2, RotateCcw,
} from "lucide-react";
import { getStats, getStatsBySubject, getStatsByTopic, getKnowledgeGaps } from "@/lib/api";

const FETCHERS = {
    overview: getStats,
    bySubject: getStatsBySubject,
    byTopic: getStatsByTopic,
    gaps: getKnowledgeGaps,
};

// Etiquetas legibles de los dos ejes de un intento (fuente única desde Fase 2;
// el viejo `mode` ya no se persiste). Defaults tolerantes por si un intento
// llegara sin ejes (no debería tras la migración del histórico).
const BEHAVIOR_LABELS = { practice: "Práctica", exam: "Examen" };
const SELECTION_LABELS = { all: "Todas", errors: "Errores", srs: "Repaso", favorites: "Favoritas" };
function attemptLabel(a) {
    const b = BEHAVIOR_LABELS[a.behavior] || "Práctica";
    const s = SELECTION_LABELS[a.selection] || "Todas";
    return `${b} · ${s}`;
}

const Tile = ({ label, value, icon: Icon, hint }) => (
    <div className="card-organic p-5">
        <div className="flex items-start justify-between">
            <span className="label-eyebrow">{label}</span>
            <Icon className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
        </div>
        <div className="font-display text-3xl font-bold mt-1">{value}</div>
        {hint && <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{hint}</div>}
    </div>
);

function AccuracyBar({ accuracy, color }) {
    const bg = color || (accuracy >= 70 ? "var(--sage)" : accuracy >= 50 ? "var(--warning)" : "var(--error)");
    return (
        <div className="w-28 sm:w-40">
            <div className="progress-track">
                <div className="progress-fill" style={{ width: `${accuracy}%`, background: bg }} />
            </div>
            <div className="text-xs mt-1 font-mono text-right" style={{ color: "var(--text-muted)" }}>{accuracy}%</div>
        </div>
    );
}

// Fallo aislado de una sección: mensaje + reintento, sin tocar el resto.
function SectionError({ onRetry }) {
    return (
        <div className="card-organic p-5 flex items-center justify-between gap-3" data-testid="section-error">
            <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
                No se pudo cargar esta sección.
            </span>
            <button
                onClick={onRetry}
                className="px-3 py-1.5 rounded-md border text-xs font-medium flex items-center gap-1.5 hover:bg-[color:var(--bg-secondary)]"
                style={{ borderColor: "var(--border)" }}
            >
                <RotateCcw className="w-3.5 h-3.5" /> Reintentar
            </button>
        </div>
    );
}

function SectionLoading() {
    return (
        <div className="card-organic p-6 flex items-center gap-2 text-sm" style={{ color: "var(--text-muted)" }}>
            <Loader2 className="w-4 h-4 animate-spin" /> Cargando…
        </div>
    );
}

export default function Stats() {
    // Cada sección tiene su propio estado: carga y fallo son independientes.
    const [sec, setSec] = useState(() =>
        Object.fromEntries(Object.keys(FETCHERS).map((k) => [k, { data: null, loading: true, error: false }]))
    );

    const load = useCallback((key) => {
        setSec((s) => ({ ...s, [key]: { ...s[key], loading: true, error: false } }));
        return FETCHERS[key]()
            .then((d) => setSec((s) => ({ ...s, [key]: { data: d, loading: false, error: false } })))
            .catch(() => setSec((s) => ({ ...s, [key]: { data: null, loading: false, error: true } })));
    }, []);

    useEffect(() => {
        // Las 4 secciones se lanzan a la vez y cada una se pinta EN CUANTO llega
        // (allSettled: el fallo de una no bloquea ni borra las demás).
        Promise.allSettled(Object.keys(FETCHERS).map(load));
    }, [load]);

    const overview = sec.overview;
    const o = overview.data;
    const bySubject = sec.bySubject;
    const byTopic = sec.byTopic;
    const gaps = sec.gaps;

    return (
        <div className="max-w-5xl mx-auto px-5 md:px-8 py-8 md:py-12">
            <span className="label-eyebrow">Análisis</span>
            <h1 className="font-display text-3xl md:text-4xl font-bold mt-1 mb-8">Tu progreso</h1>

            {/* Global stats */}
            <section className="mb-10">
                {overview.loading ? (
                    <SectionLoading />
                ) : overview.error ? (
                    <SectionError onRetry={() => load("overview")} />
                ) : (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <Tile label="Asignaturas" value={o.total_subjects} icon={FolderOpen} />
                        <Tile label="Temas" value={o.total_topics} icon={BookOpen} />
                        <Tile label="Preguntas" value={o.total_questions} icon={Target} />
                        <Tile label="Precisión" value={`${o.accuracy}%`} icon={BarChart3} hint={`${o.answered_total} respuestas`} />
                        <Tile label="Intentos" value={o.total_attempts} icon={Clock} />
                        <Tile label="Favoritas" value={o.favorites} icon={Star} />
                        <Tile label="Errores pendientes" value={o.errors_pool} icon={Flame} />
                        <Tile label="Repaso SRS" value={o.due_srs} icon={Brain} hint="Pendientes hoy" />
                    </div>
                )}
                {!overview.loading && !overview.error && o.streak > 0 && (
                    <div className="mt-3 text-sm flex items-center gap-2" style={{ color: "var(--text-secondary)" }}>
                        <Flame className="w-4 h-4" style={{ color: "var(--warning)" }} />
                        Racha de <strong>{o.streak}</strong> {o.streak === 1 ? "día" : "días"}
                    </div>
                )}
            </section>

            {/* Gap detector */}
            {gaps.loading ? (
                <section className="mb-10">
                    <span className="label-eyebrow block mb-3">Lagunas detectadas</span>
                    <SectionLoading />
                </section>
            ) : gaps.error ? (
                <section className="mb-10"><SectionError onRetry={() => load("gaps")} /></section>
            ) : gaps.data?.weak_topics?.length > 0 && (
                <section className="mb-10">
                    <div className="flex items-center gap-2 mb-3">
                        <AlertTriangle className="w-4 h-4" style={{ color: "var(--error)" }} />
                        <span className="label-eyebrow">Lagunas detectadas</span>
                    </div>
                    <p className="text-sm mb-3" style={{ color: "var(--text-secondary)" }}>
                        Temas con menos del 60% de aciertos (mín. 3 respuestas por pregunta):
                    </p>
                    <div className="card-organic divide-y" style={{ borderColor: "var(--border)" }}>
                        {gaps.data.weak_topics.map(t => (
                            <Link key={t.topic_id} to={`/quiz/setup?topic=${t.topic_id}&mode=practice`}
                                className="flex items-center justify-between gap-3 p-4 hover:bg-[color:var(--bg-secondary)]">
                                <div className="flex-1 min-w-0">
                                    <div className="font-medium text-sm truncate">{t.topic_name}</div>
                                    <div className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                                        {t.answered} respuestas · {t.total_questions} preguntas
                                    </div>
                                </div>
                                <div className="flex items-center gap-3">
                                    <AccuracyBar accuracy={t.accuracy} />
                                    <span className="text-xs px-2 py-1 rounded-md font-medium"
                                        style={{ background: "#fbeeee", color: "var(--error)" }}>
                                        Repasar
                                    </span>
                                </div>
                            </Link>
                        ))}
                    </div>
                </section>
            )}

            {/* By subject - mapa de progreso */}
            {bySubject.loading ? (
                <section className="mb-10">
                    <span className="label-eyebrow block mb-3">Por asignatura</span>
                    <SectionLoading />
                </section>
            ) : bySubject.error ? (
                <section className="mb-10"><SectionError onRetry={() => load("bySubject")} /></section>
            ) : bySubject.data?.length > 0 && (
                <section className="mb-10">
                    <span className="label-eyebrow block mb-3">Por asignatura</span>
                    <div className="card-organic divide-y" style={{ borderColor: "var(--border)" }}>
                        {bySubject.data.map(row => (
                            <Link key={row.subject_id} to={`/asignaturas/${row.subject_id}`}
                                className="flex items-center gap-3 p-4 hover:bg-[color:var(--bg-secondary)]"
                                data-testid={`subject-row-${row.subject_id}`}>
                                <span className="w-3 h-10 rounded-sm shrink-0" style={{ background: row.color }} />
                                <div className="flex-1 min-w-0">
                                    <div className="font-display font-bold text-base truncate">{row.subject_name}</div>
                                    <div className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                                        {row.total_questions} preguntas · {row.answered} respondidas
                                    </div>
                                </div>
                                <AccuracyBar accuracy={row.accuracy} color={row.color} />
                            </Link>
                        ))}
                    </div>
                </section>
            )}

            {/* By topic - mapa de progreso con colores */}
            {byTopic.loading ? (
                <section className="mb-10">
                    <span className="label-eyebrow block mb-3">Mapa de progreso por tema</span>
                    <SectionLoading />
                </section>
            ) : byTopic.error ? (
                <section className="mb-10"><SectionError onRetry={() => load("byTopic")} /></section>
            ) : byTopic.data?.length > 0 && (
                <section className="mb-10">
                    <span className="label-eyebrow block mb-1">Mapa de progreso por tema</span>
                    <p className="text-xs mb-3" style={{ color: "var(--text-muted)" }}>
                        <span style={{ color: "var(--sage)" }}>■</span> Dominado ≥70% &nbsp;
                        <span style={{ color: "var(--warning)" }}>■</span> En progreso 50-69% &nbsp;
                        <span style={{ color: "var(--error)" }}>■</span> Repasar &lt;50%
                    </p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-4">
                        {byTopic.data.map(row => {
                            const color = row.accuracy >= 70 ? "var(--sage)" : row.accuracy >= 50 ? "var(--warning)" : "var(--error)";
                            const bg = row.accuracy >= 70 ? "#eef2ec" : row.accuracy >= 50 ? "#fdf5e6" : "#fbeeee";
                            return (
                                <Link key={row.topic_id} to={`/temas/${row.topic_id}`}
                                    className="flex items-center gap-3 p-3 rounded-md border hover:-translate-y-0.5 transition-transform"
                                    style={{ borderColor: color, background: bg }}
                                    data-testid={`topic-row-${row.topic_id}`}>
                                    <div className="w-2 h-8 rounded-sm shrink-0" style={{ background: color }} />
                                    <div className="flex-1 min-w-0">
                                        <div className="font-medium text-sm truncate">{row.topic_name}</div>
                                        <div className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                                            {row.total_questions} preg. · {row.answered} resp.
                                        </div>
                                    </div>
                                    <span className="font-display font-bold text-base" style={{ color }}>{row.accuracy}%</span>
                                </Link>
                            );
                        })}
                    </div>
                </section>
            )}

            {/* Actions */}
            <section className="flex flex-wrap gap-3 mb-10">
                <Link to="/supervivencia"
                    className="px-4 py-2.5 rounded-md border font-medium text-sm flex items-center gap-2 hover:bg-[color:var(--bg-secondary)]"
                    style={{ borderColor: "var(--border)" }}>
                    <Zap className="w-4 h-4" /> Modo supervivencia
                </Link>
            </section>

            {/* Last attempts (parte del overview) */}
            {!overview.loading && !overview.error && o.last_attempts?.length > 0 && (
                <section>
                    <span className="label-eyebrow block mb-3">Últimos 3 intentos</span>
                    <div className="card-organic divide-y" style={{ borderColor: "var(--border)" }}>
                        {o.last_attempts.map(a => (
                            <div key={a.id} className="flex items-center justify-between p-4">
                                <div>
                                    <div className="font-medium text-sm">{attemptLabel(a)}{a.penalty_factor && (
                                        <span className="text-xs font-mono ml-1" style={{ color: "var(--text-muted)" }}>· −1/{a.penalty_factor}</span>
                                    )}</div>
                                    <div className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                                        {new Date(a.created_at).toLocaleString("es-ES")}
                                    </div>
                                </div>
                                <div className="flex items-center gap-3">
                                    <span className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                                        {a.correct_count}/{a.total}
                                    </span>
                                    <span className="font-display font-bold text-lg"
                                        style={{ color: a.score_10 >= 5 ? "var(--sage)" : "var(--error)" }}>
                                        {a.score_10}
                                    </span>
                                </div>
                            </div>
                        ))}
                    </div>
                </section>
            )}
        </div>
    );
}
