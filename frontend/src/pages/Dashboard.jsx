import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import {
    Plus,
    Trash2,
    BookOpen,
    Target,
    Star,
    Flame,
    Brain,
    BarChart3,
    Sparkles,
    Clock,
    ChevronRight,
} from "lucide-react";
import { toast } from "sonner";
import { listTopics, deleteTopic, getStats } from "@/lib/api";
import UploadDialog from "@/components/UploadDialog";

const StatCard = ({ icon: Icon, label, value, accent }) => (
    <div className="card-organic p-5 fade-up">
        <div className="flex items-start justify-between">
            <span className="label-eyebrow">{label}</span>
            <div
                className="w-8 h-8 rounded-md flex items-center justify-center"
                style={{ background: accent || "var(--bg-secondary)" }}
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
        <div
            className="flex items-center text-sm font-medium gap-1 mt-auto"
            style={{ color: "var(--brand)" }}
        >
            Empezar
            <ChevronRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
        </div>
    </Link>
);

export default function Dashboard() {
    const [topics, setTopics] = useState([]);
    const [stats, setStats] = useState(null);
    const [uploadOpen, setUploadOpen] = useState(false);
    const [loading, setLoading] = useState(true);
    const navigate = useNavigate();

    const load = async () => {
        setLoading(true);
        try {
            const [t, s] = await Promise.all([listTopics(), getStats()]);
            setTopics(t);
            setStats(s);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        load();
    }, []);

    const handleDelete = async (id, name) => {
        if (!window.confirm(`¿Eliminar el tema "${name}" y todas sus preguntas?`)) return;
        try {
            await deleteTopic(id);
            toast.success("Tema eliminado");
            load();
        } catch (e) {
            toast.error("Error al eliminar");
        }
    };

    return (
        <div className="max-w-6xl mx-auto px-5 md:px-8 py-8 md:py-12">
            {/* Hero */}
            <section className="mb-10 fade-up">
                <span className="label-eyebrow">Panel principal</span>
                <h1
                    className="font-display font-bold tracking-tight mt-2"
                    style={{ fontSize: "clamp(2rem, 5vw, 3.5rem)", lineHeight: 1.05 }}
                >
                    Estudia anatomía con
                    <br />
                    preguntas <em style={{ color: "var(--brand)", fontStyle: "italic" }}>generadas por ti</em>.
                </h1>
                <p className="mt-4 text-base md:text-lg max-w-2xl" style={{ color: "var(--text-secondary)" }}>
                    Sube las diapositivas de cada tema y la IA crea preguntas tipo test con 3 opciones. Practica, repasa errores y refuerza con repetición espaciada.
                </p>
                <div className="mt-6 flex flex-wrap gap-3">
                    <button
                        onClick={() => setUploadOpen(true)}
                        className="btn-primary flex items-center gap-2"
                        data-testid="new-topic-btn"
                    >
                        <Plus className="w-4 h-4" />
                        Nuevo tema (PDF)
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

            {/* Stats */}
            <section className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-10">
                <StatCard icon={BookOpen} label="Temas" value={stats?.total_topics ?? "—"} />
                <StatCard icon={Target} label="Preguntas" value={stats?.total_questions ?? "—"} />
                <StatCard
                    icon={BarChart3}
                    label="Precisión"
                    value={stats ? `${stats.accuracy}%` : "—"}
                />
                <StatCard icon={Clock} label="Intentos" value={stats?.total_attempts ?? "—"} />
            </section>

            {/* Quick modes */}
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
                </div>
            </section>

            {/* Topics */}
            <section>
                <div className="flex items-end justify-between mb-4">
                    <div>
                        <span className="label-eyebrow">Tus temas</span>
                        <h2 className="font-display text-2xl md:text-3xl font-bold mt-1">
                            Biblioteca de estudio
                        </h2>
                    </div>
                    <button
                        onClick={() => setUploadOpen(true)}
                        data-testid="add-topic-btn"
                        className="text-sm font-medium flex items-center gap-1 hover:underline"
                        style={{ color: "var(--brand)" }}
                    >
                        <Plus className="w-4 h-4" /> Añadir tema
                    </button>
                </div>

                {loading ? (
                    <div className="card-organic p-8 text-center" style={{ color: "var(--text-muted)" }}>
                        Cargando…
                    </div>
                ) : topics.length === 0 ? (
                    <div className="card-organic p-10 text-center fade-up">
                        <BookOpen className="w-10 h-10 mx-auto mb-3" style={{ color: "var(--brand)" }} />
                        <h3 className="font-display text-xl font-bold">No hay temas todavía</h3>
                        <p className="mt-1 text-sm" style={{ color: "var(--text-muted)" }}>
                            Sube tu primer PDF de diapositivas y empezamos a generar preguntas.
                        </p>
                        <button
                            onClick={() => setUploadOpen(true)}
                            data-testid="empty-add-topic-btn"
                            className="btn-primary mt-5 inline-flex items-center gap-2"
                        >
                            <Plus className="w-4 h-4" /> Subir PDF
                        </button>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                        {topics.map((t) => (
                            <div
                                key={t.id}
                                className="card-organic p-5 flex flex-col gap-3 fade-up"
                                data-testid={`topic-card-${t.id}`}
                            >
                                <div className="flex items-start justify-between">
                                    <Link
                                        to={`/temas/${t.id}`}
                                        className="font-display font-bold text-lg hover:underline"
                                    >
                                        {t.name}
                                    </Link>
                                    <button
                                        onClick={() => handleDelete(t.id, t.name)}
                                        data-testid={`delete-topic-${t.id}`}
                                        className="p-1.5 rounded hover:bg-[color:var(--bg-secondary)]"
                                        title="Eliminar tema"
                                    >
                                        <Trash2 className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
                                    </button>
                                </div>
                                <div className="flex items-center gap-4 text-sm" style={{ color: "var(--text-secondary)" }}>
                                    <span className="flex items-center gap-1">
                                        <Target className="w-3.5 h-3.5" /> {t.question_count} preguntas
                                    </span>
                                    <span className="flex items-center gap-1">
                                        <BarChart3 className="w-3.5 h-3.5" /> {t.accuracy}%
                                    </span>
                                </div>
                                <div className="progress-track">
                                    <div
                                        className="progress-fill"
                                        style={{
                                            width: `${
                                                t.question_count
                                                    ? Math.min(100, (t.answered_count / t.question_count) * 100)
                                                    : 0
                                            }%`,
                                        }}
                                    />
                                </div>
                                <div className="flex gap-2 mt-1">
                                    <Link
                                        to={`/quiz/setup?mode=practice&topic=${t.id}`}
                                        data-testid={`practice-topic-${t.id}`}
                                        className="flex-1 text-center text-sm font-medium px-3 py-2 rounded-md border hover:bg-[color:var(--bg-secondary)]"
                                        style={{ borderColor: "var(--border)" }}
                                    >
                                        Practicar
                                    </Link>
                                    <Link
                                        to={`/quiz/setup?mode=exam&topic=${t.id}`}
                                        data-testid={`exam-topic-${t.id}`}
                                        className="flex-1 text-center text-sm font-medium px-3 py-2 rounded-md text-white"
                                        style={{ background: "var(--brand)" }}
                                    >
                                        Examen
                                    </Link>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </section>

            <UploadDialog
                open={uploadOpen}
                onClose={() => setUploadOpen(false)}
                onCreated={load}
            />
        </div>
    );
}
