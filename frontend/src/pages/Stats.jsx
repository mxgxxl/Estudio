import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
    BarChart3, BookOpen, Target, Clock, Star, Flame,
    Brain, FolderOpen, AlertTriangle, History, Zap,
} from "lucide-react";
import { getStats, getStatsBySubject, getStatsByTopic, getKnowledgeGaps } from "@/lib/api";

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

export default function Stats() {
    const [stats, setStats] = useState(null);
    const [bySubject, setBySubject] = useState([]);
    const [byTopic, setByTopic] = useState([]);
    const [gaps, setGaps] = useState(null);

    useEffect(() => {
        Promise.all([getStats(), getStatsBySubject(), getStatsByTopic(), getKnowledgeGaps()])
            .then(([s, b, t, g]) => {
                setStats(s);
                setBySubject(b);
                setByTopic(t);
                setGaps(g);
            });
    }, []);

    if (!stats) return (
        <div className="max-w-5xl mx-auto px-5 md:px-8 py-10" style={{ color: "var(--text-muted)" }}>Cargando…</div>
    );

    return (
        <div className="max-w-5xl mx-auto px-5 md:px-8 py-8 md:py-12">
            <span className="label-eyebrow">Análisis</span>
            <h1 className="font-display text-3xl md:text-4xl font-bold mt-1 mb-8">Tu progreso</h1>

            {/* Global stats */}
            <section className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-10">
                <Tile label="Asignaturas" value={stats.total_subjects} icon={FolderOpen} />
                <Tile label="Temas" value={stats.total_topics} icon={BookOpen} />
                <Tile label="Preguntas" value={stats.total_questions} icon={Target} />
                <Tile label="Precisión" value={`${stats.accuracy}%`} icon={BarChart3} hint={`${stats.answered_total} respuestas`} />
                <Tile label="Intentos" value={stats.total_attempts} icon={Clock} />
                <Tile label="Favoritas" value={stats.favorites} icon={Star} />
                <Tile label="Errores pendientes" value={stats.errors_pool} icon={Flame} />
                <Tile label="Repaso SRS" value={stats.due_srs} icon={Brain} hint="Pendientes hoy" />
            </section>

            {/* Gap detector */}
            {gaps?.weak_topics?.length > 0 && (
                <section className="mb-10">
                    <div className="flex items-center gap-2 mb-3">
                        <AlertTriangle className="w-4 h-4" style={{ color: "var(--error)" }} />
                        <span className="label-eyebrow">Lagunas detectadas</span>
                    </div>
                    <p className="text-sm mb-3" style={{ color: "var(--text-secondary)" }}>
                        Temas con menos del 60% de aciertos (mín. 3 respuestas por pregunta):
                    </p>
                    <div className="card-organic divide-y" style={{ borderColor: "var(--border)" }}>
                        {gaps.weak_topics.map(t => (
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
            {bySubject.length > 0 && (
                <section className="mb-10">
                    <span className="label-eyebrow block mb-3">Por asignatura</span>
                    <div className="card-organic divide-y" style={{ borderColor: "var(--border)" }}>
                        {bySubject.map(row => (
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
            {byTopic.length > 0 && (
                <section className="mb-10">
                    <span className="label-eyebrow block mb-1">Mapa de progreso por tema</span>
                    <p className="text-xs mb-3" style={{ color: "var(--text-muted)" }}>
                        <span style={{ color: "var(--sage)" }}>■</span> Dominado ≥70% &nbsp;
                        <span style={{ color: "var(--warning)" }}>■</span> En progreso 50-69% &nbsp;
                        <span style={{ color: "var(--error)" }}>■</span> Repasar &lt;50%
                    </p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-4">
                        {byTopic.map(row => {
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

            {/* Last attempts */}
            {stats.last_attempts?.length > 0 && (
                <section>
                    <span className="label-eyebrow block mb-3">Últimos 3 intentos</span>
                    <div className="card-organic divide-y" style={{ borderColor: "var(--border)" }}>
                        {stats.last_attempts.map(a => (
                            <div key={a.id} className="flex items-center justify-between p-4">
                                <div>
                                    <div className="font-medium text-sm capitalize">{a.mode}{a.penalty_factor && (
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
