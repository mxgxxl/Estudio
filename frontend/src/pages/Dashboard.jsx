import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import {
    Plus,
    Trash2,
    BookOpen,
    Target,
    Flame,
    Brain,
    BarChart3,
    Sparkles,
    Clock,
    ChevronRight,
    FolderOpen,
    Zap,
    Swords,
} from "lucide-react";
import { toast } from "sonner";
import { listSubjects, deleteSubject, getStats } from "@/lib/api";
import NewSubjectDialog from "@/components/NewSubjectDialog";

const StatCard = ({ icon: Icon, label, value }) => (
    <div className="card-organic p-5 fade-up">
        <div className="flex items-start justify-between">
            <span className="label-eyebrow">{label}</span>
            <div
                className="w-8 h-8 rounded-md flex items-center justify-center"
                style={{ background: "var(--bg-secondary)" }}
            >
                <Icon className="w-4 h-4" style={{ color: "var(--text-secondary)" }} />
            </div>
        </div>
        <div className="mt-2 font-display text-3xl font-bold">{value}</div>
    </div>
);

const QuickMode = ({ to, icon: Icon, title, desc, badge, testid }) => (
    <Link
        to={to}
        data-testid={testid}
        className="card-organic p-5 flex flex-col gap-3 group hover:-translate-y-0.5 transition-transform"
    >
        <div className="flex items-center justify-between">
            <div
                className="w-10 h-10 rounded-md flex items-center justify-center"
                style={{ background: "var(--bg-secondary)" }}
            >
                <Icon className="w-5 h-5" style={{ color: "var(--brand)" }} />
            </div>
            {badge !== undefined && badge !== null && (
                <span
                    className="text-xs font-bold px-2 py-0.5 rounded-sm font-mono"
                    style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
                >
                    {badge}
                </span>
            )}
        </div>
        <div>
            <div className="font-display font-bold text-lg">{title}</div>
            <div className="text-sm" style={{ color: "var(--text-muted)" }}>
                {desc}
            </div>
        </div>
        <div className="flex items-center text-sm font-medium gap-1 mt-auto" style={{ color: "var(--brand)" }}>
            Empezar
            <ChevronRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
        </div>
    </Link>
);

export default function Dashboard() {
    const [subjects, setSubjects] = useState([]);
    const [stats, setStats] = useState(null);
    const [newOpen, setNewOpen] = useState(false);
    const [loading, setLoading] = useState(true);
    const navigate = useNavigate();

    const load = async () => {
        setLoading(true);
        try {
            const [s, st] = await Promise.all([listSubjects(), getStats()]);
            setSubjects(s);
            setStats(st);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        load();
    }, []);

    const handleDelete = async (e, id, name) => {
        e.preventDefault();
        e.stopPropagation();
        if (
            !window.confirm(`¿Eliminar la asignatura "${name}" y TODOS sus temas y preguntas?`)
        )
            return;
        try {
            await deleteSubject(id);
            toast.success("Asignatura eliminada");
            load();
        } catch {
            toast.error("Error al eliminar");
        }
    };

    return (
        <div className="max-w-6xl mx-auto px-5 md:px-8 py-8 md:py-12">
            <section className="mb-10 fade-up">
                <span className="label-eyebrow">Panel principal</span>
                <h1
                    className="font-display font-bold tracking-tight mt-2"
                    style={{ fontSize: "clamp(2rem, 5vw, 3.5rem)", lineHeight: 1.05 }}
                >
                    Estudia cualquier asignatura con
                    <br />
                    preguntas <em style={{ color: "var(--brand)", fontStyle: "italic" }}>generadas por ti</em>.
                </h1>
                <p className="mt-4 text-base md:text-lg max-w-2xl" style={{ color: "var(--text-secondary)" }}>
                    Crea asignaturas, sube tus apuntes en PDF y la IA generará preguntas tipo test o verdadero/falso. Configura cada examen con su sistema de corrección.
                </p>
                <div className="mt-6 flex flex-wrap gap-3">
                    <button
                        onClick={() => setNewOpen(true)}
                        className="btn-primary flex items-center gap-2"
                        data-testid="new-subject-btn"
                    >
                        <Plus className="w-4 h-4" />
                        Nueva asignatura
                    </button>
                    <button
                        onClick={() => navigate("/quiz/setup")}
                        data-testid="start-study-btn"
                        className="px-5 py-2.5 rounded-md border font-medium text-sm flex items-center gap-2 hover:bg-[color:var(--bg-secondary)]"
                        style={{ borderColor: "var(--border)" }}
                    >
                        <Sparkles className="w-4 h-4" />
                        Empezar a estudiar
                    </button>
                </div>
            </section>

            <section className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-10">
                <StatCard icon={FolderOpen} label="Asignaturas" value={stats?.total_subjects ?? "—"} />
                <StatCard icon={BookOpen} label="Temas" value={stats?.total_topics ?? "—"} />
                <StatCard icon={Target} label="Preguntas" value={stats?.total_questions ?? "—"} />
                <StatCard icon={BarChart3} label="Precisión" value={stats ? `${stats.accuracy}%` : "—"} />
                <StatCard icon={Zap} label="Racha" value={stats ? `${stats.streak ?? 0}d` : "—"} />
            </section>

            <section className="mb-12">
                <div className="flex items-end justify-between mb-4">
                    <div>
                        <span className="label-eyebrow">Modos rápidos</span>
                        <h2 className="font-display text-2xl md:text-3xl font-bold mt-1">Empieza una sesión</h2>
                    </div>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                    <QuickMode
                        to="/quiz/setup?mode=practice"
                        icon={Sparkles}
                        title="Práctica"
                        desc="Sin tiempo, feedback inmediato"
                        testid="quick-practice"
                    />
                    <QuickMode
                        to="/quiz/setup?mode=exam"
                        icon={Clock}
                        title="Examen"
                        desc="Cronómetro y nota final"
                        testid="quick-exam"
                    />
                    <QuickMode
                        to="/quiz/setup?mode=errors"
                        icon={Flame}
                        title="Repasar errores"
                        desc="Preguntas que has fallado"
                        badge={stats?.errors_pool ?? 0}
                        testid="quick-errors"
                    />
                    <QuickMode
                        to="/quiz/setup?mode=srs"
                        icon={Brain}
                        title="Repetición espaciada"
                        desc="Lo que toca repasar hoy"
                        badge={stats?.due_srs ?? 0}
                        testid="quick-srs"
                    />
                    <QuickMode
                        to="/supervivencia"
                        icon={Zap}
                        title="Supervivencia"
                        desc="3 vidas · racha de puntos"
                        testid="quick-survival"
                    />
                </div>
            </section>

            <section>
                <div className="flex items-end justify-between mb-4">
                    <div>
                        <span className="label-eyebrow">Tus asignaturas</span>
                        <h2 className="font-display text-2xl md:text-3xl font-bold mt-1">Biblioteca de estudio</h2>
                    </div>
                    <button
                        onClick={() => setNewOpen(true)}
                        data-testid="add-subject-btn"
                        className="text-sm font-medium flex items-center gap-1 hover:underline"
                        style={{ color: "var(--brand)" }}
                    >
                        <Plus className="w-4 h-4" /> Añadir asignatura
                    </button>
                </div>

                {loading ? (
                    <div className="card-organic p-8 text-center" style={{ color: "var(--text-muted)" }}>
                        Cargando…
                    </div>
                ) : subjects.length === 0 ? (
                    <div className="card-organic p-10 text-center fade-up">
                        <FolderOpen className="w-10 h-10 mx-auto mb-3" style={{ color: "var(--brand)" }} />
                        <h3 className="font-display text-xl font-bold">No hay asignaturas todavía</h3>
                        <p className="mt-1 text-sm" style={{ color: "var(--text-muted)" }}>
                            Crea tu primera asignatura para empezar a añadir temas.
                        </p>
                        <button
                            onClick={() => setNewOpen(true)}
                            data-testid="empty-add-subject-btn"
                            className="btn-primary mt-5 inline-flex items-center gap-2"
                        >
                            <Plus className="w-4 h-4" /> Crear asignatura
                        </button>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                        {subjects.map((s) => (
                            <Link
                                key={s.id}
                                to={`/asignaturas/${s.id}`}
                                data-testid={`subject-card-${s.id}`}
                                className="card-organic p-5 flex flex-col gap-3 fade-up hover:-translate-y-0.5 transition-transform"
                            >
                                <div className="flex items-start justify-between gap-2">
                                    <div className="flex items-center gap-2 min-w-0">
                                        <span
                                            className="w-3 h-3 rounded-full shrink-0"
                                            style={{ background: s.color }}
                                        />
                                        <span className="font-display font-bold text-lg truncate">{s.name}</span>
                                    </div>
                                    <button
                                        onClick={(e) => handleDelete(e, s.id, s.name)}
                                        data-testid={`delete-subject-${s.id}`}
                                        className="p-1.5 rounded hover:bg-[color:var(--bg-secondary)]"
                                        title="Eliminar asignatura"
                                    >
                                        <Trash2 className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
                                    </button>
                                </div>
                                <div className="flex items-center gap-4 text-sm" style={{ color: "var(--text-secondary)" }}>
                                    <span className="flex items-center gap-1">
                                        <BookOpen className="w-3.5 h-3.5" /> {s.topic_count} temas
                                    </span>
                                    <span className="flex items-center gap-1">
                                        <Target className="w-3.5 h-3.5" /> {s.question_count} preguntas
                                    </span>
                                    <span className="flex items-center gap-1">
                                        <BarChart3 className="w-3.5 h-3.5" /> {s.accuracy}%
                                    </span>
                                </div>
                                <div className="progress-track">
                                    <div
                                        className="progress-fill"
                                        style={{
                                            width: `${s.accuracy}%`,
                                            background: s.color,
                                        }}
                                    />
                                </div>
                            </Link>
                        ))}
                    </div>
                )}
            </section>

            <NewSubjectDialog open={newOpen} onClose={() => setNewOpen(false)} onCreated={load} />
        </div>
    );
}
