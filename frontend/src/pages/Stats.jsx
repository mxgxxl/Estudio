import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
    BarChart3,
    BookOpen,
    Target,
    Clock,
    Star,
    Flame,
    Brain,
    FolderOpen,
} from "lucide-react";
import { getStats, getStatsBySubject, getStatsByTopic } from "@/lib/api";

const Tile = ({ label, value, icon: Icon, hint }) => (
    <div className="card-organic p-5">
        <div className="flex items-start justify-between">
            <span className="label-eyebrow">{label}</span>
            <Icon className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
        </div>
        <div className="font-display text-3xl font-bold mt-1">{value}</div>
        {hint && (
            <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                {hint}
            </div>
        )}
    </div>
);

export default function Stats() {
    const [stats, setStats] = useState(null);
    const [bySubject, setBySubject] = useState([]);
    const [byTopic, setByTopic] = useState([]);

    useEffect(() => {
        Promise.all([getStats(), getStatsBySubject(), getStatsByTopic()]).then(([s, b, t]) => {
            setStats(s);
            setBySubject(b);
            setByTopic(t);
        });
    }, []);

    if (!stats) {
        return (
            <div className="max-w-5xl mx-auto px-5 md:px-8 py-10" style={{ color: "var(--text-muted)" }}>
                Cargando…
            </div>
        );
    }

    return (
        <div className="max-w-5xl mx-auto px-5 md:px-8 py-8 md:py-12">
            <span className="label-eyebrow">Análisis</span>
            <h1 className="font-display text-3xl md:text-4xl font-bold mt-1 mb-8">Tu progreso</h1>

            <section className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-10">
                <Tile label="Asignaturas" value={stats.total_subjects} icon={FolderOpen} />
                <Tile label="Temas" value={stats.total_topics} icon={BookOpen} />
                <Tile label="Preguntas" value={stats.total_questions} icon={Target} />
                <Tile
                    label="Precisión"
                    value={`${stats.accuracy}%`}
                    icon={BarChart3}
                    hint={`${stats.answered_total} respuestas`}
                />
                <Tile label="Intentos" value={stats.total_attempts} icon={Clock} />
                <Tile label="Favoritas" value={stats.favorites} icon={Star} />
                <Tile label="Errores pendientes" value={stats.errors_pool} icon={Flame} />
                <Tile label="Repaso SRS" value={stats.due_srs} icon={Brain} hint="Pendientes hoy" />
            </section>

            {bySubject.length > 0 && (
                <section className="mb-10">
                    <span className="label-eyebrow block mb-3">Por asignatura</span>
                    <div className="card-organic divide-y" style={{ borderColor: "var(--border)" }}>
                        {bySubject.map((row) => (
                            <Link
                                key={row.subject_id}
                                to={`/asignaturas/${row.subject_id}`}
                                className="flex items-center gap-3 p-4 hover:bg-[color:var(--bg-secondary)]"
                                data-testid={`subject-row-${row.subject_id}`}
                            >
                                <span
                                    className="w-3 h-10 rounded-sm shrink-0"
                                    style={{ background: row.color }}
                                />
                                <div className="flex-1 min-w-0">
                                    <div className="font-display font-bold text-base truncate">
                                        {row.subject_name}
                                    </div>
                                    <div className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                                        {row.total_questions} preguntas · {row.answered} respondidas · {row.correct}{" "}
                                        aciertos
                                    </div>
                                </div>
                                <div className="w-28 sm:w-40">
                                    <div className="progress-track">
                                        <div
                                            className="progress-fill"
                                            style={{
                                                width: `${row.accuracy}%`,
                                                background: row.color,
                                            }}
                                        />
                                    </div>
                                    <div
                                        className="text-xs mt-1 font-mono text-right"
                                        style={{ color: "var(--text-muted)" }}
                                    >
                                        {row.accuracy}%
                                    </div>
                                </div>
                            </Link>
                        ))}
                    </div>
                </section>
            )}

            {byTopic.length > 0 && (
                <section className="mb-10">
                    <span className="label-eyebrow block mb-3">Por tema</span>
                    <div className="card-organic divide-y" style={{ borderColor: "var(--border)" }}>
                        {byTopic.map((row) => (
                            <Link
                                key={row.topic_id}
                                to={`/temas/${row.topic_id}`}
                                className="flex items-center justify-between gap-3 p-4 hover:bg-[color:var(--bg-secondary)]"
                                data-testid={`topic-row-${row.topic_id}`}
                            >
                                <div className="flex-1 min-w-0">
                                    <div className="font-display font-bold text-base truncate">
                                        {row.topic_name}
                                    </div>
                                    <div className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                                        {row.total_questions} preguntas · {row.answered} respondidas · {row.correct}{" "}
                                        aciertos
                                    </div>
                                </div>
                                <div className="w-28 sm:w-40">
                                    <div className="progress-track">
                                        <div
                                            className="progress-fill"
                                            style={{
                                                width: `${row.accuracy}%`,
                                                background:
                                                    row.accuracy >= 70
                                                        ? "var(--sage)"
                                                        : row.accuracy >= 50
                                                          ? "var(--warning)"
                                                          : "var(--error)",
                                            }}
                                        />
                                    </div>
                                    <div
                                        className="text-xs mt-1 font-mono text-right"
                                        style={{ color: "var(--text-muted)" }}
                                    >
                                        {row.accuracy}%
                                    </div>
                                </div>
                            </Link>
                        ))}
                    </div>
                </section>
            )}

            {stats.last_attempts?.length > 0 && (
                <section>
                    <span className="label-eyebrow block mb-3">Últimos intentos</span>
                    <div className="card-organic divide-y" style={{ borderColor: "var(--border)" }}>
                        {stats.last_attempts.map((a) => (
                            <div key={a.id} className="flex items-center justify-between p-4">
                                <div>
                                    <div className="font-medium text-sm capitalize">
                                        {a.mode}{" "}
                                        {a.penalty_factor && (
                                            <span
                                                className="text-xs font-mono ml-1"
                                                style={{ color: "var(--text-muted)" }}
                                            >
                                                · −1/{a.penalty_factor}
                                            </span>
                                        )}
                                    </div>
                                    <div className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                                        {new Date(a.created_at).toLocaleString("es-ES")}
                                    </div>
                                </div>
                                <div className="flex items-center gap-3">
                                    <span className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                                        {a.correct_count}/{a.total}
                                    </span>
                                    <span
                                        className="font-display font-bold text-lg"
                                        style={{
                                            color: a.score_10 >= 5 ? "var(--sage)" : "var(--error)",
                                        }}
                                    >
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
