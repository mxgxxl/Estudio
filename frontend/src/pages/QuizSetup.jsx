import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { Clock, Sparkles, Flame, Brain, Star, ArrowLeft, Play, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { listTopics, quizStart } from "@/lib/api";

const MODES = [
    { id: "practice", label: "Práctica", icon: Sparkles, desc: "Sin tiempo, feedback inmediato" },
    { id: "exam", label: "Examen", icon: Clock, desc: "Con cronómetro y nota final" },
    { id: "errors", label: "Errores", icon: Flame, desc: "Solo preguntas que has fallado" },
    { id: "srs", label: "Repaso", icon: Brain, desc: "Lo que toca según la repetición espaciada" },
    { id: "favorites", label: "Favoritas", icon: Star, desc: "Las preguntas marcadas como favoritas" },
];

export default function QuizSetup() {
    const navigate = useNavigate();
    const [params] = useSearchParams();
    const initialMode = params.get("mode") || "practice";
    const initialTopic = params.get("topic");

    const [topics, setTopics] = useState([]);
    const [mode, setMode] = useState(initialMode);
    const [selected, setSelected] = useState(new Set(initialTopic ? [initialTopic] : []));
    const [numQuestions, setNumQuestions] = useState(15);
    const [timeLimit, setTimeLimit] = useState(15); // minutes
    const [starting, setStarting] = useState(false);

    useEffect(() => {
        listTopics().then(setTopics).catch(() => toast.error("Error cargando temas"));
    }, []);

    const totalAvailable = useMemo(() => {
        if (selected.size === 0) return topics.reduce((a, t) => a + t.question_count, 0);
        return topics.filter((t) => selected.has(t.id)).reduce((a, t) => a + t.question_count, 0);
    }, [selected, topics]);

    const toggleTopic = (id) => {
        const next = new Set(selected);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        setSelected(next);
    };

    const handleStart = async () => {
        setStarting(true);
        try {
            const payload = {
                mode,
                topic_ids: Array.from(selected),
                num_questions: numQuestions,
                time_limit_minutes: mode === "exam" ? timeLimit : null,
            };
            const data = await quizStart(payload);
            if (!data.questions?.length) {
                toast.error("No hay preguntas disponibles");
                return;
            }
            sessionStorage.setItem(
                "current_quiz",
                JSON.stringify({
                    questions: data.questions,
                    mode,
                    topic_ids: Array.from(selected),
                    time_limit_seconds: mode === "exam" ? timeLimit * 60 : null,
                    started_at: Date.now(),
                }),
            );
            navigate("/quiz/run");
        } catch (e) {
            toast.error(e?.response?.data?.detail || "No hay preguntas para esos filtros");
        } finally {
            setStarting(false);
        }
    };

    return (
        <div className="max-w-4xl mx-auto px-5 md:px-8 py-8 md:py-12">
            <Link
                to="/"
                data-testid="back-home"
                className="inline-flex items-center gap-1 text-sm font-medium mb-4 hover:underline"
                style={{ color: "var(--text-secondary)" }}
            >
                <ArrowLeft className="w-4 h-4" /> Volver
            </Link>
            <span className="label-eyebrow">Configurar sesión</span>
            <h1 className="font-display text-3xl md:text-4xl font-bold mt-1 mb-8">
                ¿Qué quieres estudiar hoy?
            </h1>

            {/* Modo */}
            <div className="mb-8">
                <span className="label-eyebrow block mb-3">Modo</span>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
                    {MODES.map((m) => {
                        const Icon = m.icon;
                        const active = mode === m.id;
                        return (
                            <button
                                key={m.id}
                                onClick={() => setMode(m.id)}
                                data-testid={`mode-${m.id}`}
                                className="p-3 rounded-md border text-left transition-all"
                                style={{
                                    borderColor: active ? "var(--brand)" : "var(--border)",
                                    background: active ? "#fdf1ea" : "white",
                                }}
                            >
                                <Icon
                                    className="w-5 h-5 mb-1.5"
                                    style={{ color: active ? "var(--brand)" : "var(--text-secondary)" }}
                                />
                                <div className="font-display font-bold text-sm">{m.label}</div>
                                <div className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
                                    {m.desc}
                                </div>
                            </button>
                        );
                    })}
                </div>
            </div>

            {/* Temas */}
            <div className="mb-8">
                <div className="flex items-center justify-between mb-3">
                    <span className="label-eyebrow">Temas {selected.size === 0 && "(todos)"}</span>
                    {selected.size > 0 && (
                        <button
                            data-testid="clear-topics"
                            onClick={() => setSelected(new Set())}
                            className="text-xs font-medium hover:underline"
                            style={{ color: "var(--brand)" }}
                        >
                            Limpiar selección
                        </button>
                    )}
                </div>
                {topics.length === 0 ? (
                    <div className="card-organic p-5 text-sm" style={{ color: "var(--text-muted)" }}>
                        Aún no tienes temas. Sube un PDF desde el inicio.
                    </div>
                ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {topics.map((t) => {
                            const active = selected.has(t.id);
                            return (
                                <button
                                    key={t.id}
                                    onClick={() => toggleTopic(t.id)}
                                    data-testid={`topic-toggle-${t.id}`}
                                    className="p-3 rounded-md border flex items-center justify-between transition-all text-left"
                                    style={{
                                        borderColor: active ? "var(--brand)" : "var(--border)",
                                        background: active ? "#fdf1ea" : "white",
                                    }}
                                >
                                    <span className="font-medium text-sm">{t.name}</span>
                                    <span
                                        className="text-xs font-mono px-1.5 py-0.5 rounded-sm"
                                        style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
                                    >
                                        {t.question_count}
                                    </span>
                                </button>
                            );
                        })}
                    </div>
                )}
            </div>

            {/* Nº preguntas */}
            <div className="mb-6">
                <span className="label-eyebrow block mb-2">
                    Nº de preguntas: <span className="font-mono">{numQuestions}</span>{" "}
                    <span className="font-mono" style={{ color: "var(--text-muted)" }}>
                        (disponibles: {totalAvailable})
                    </span>
                </span>
                <input
                    type="range"
                    min="5"
                    max={Math.max(50, Math.min(totalAvailable, 100))}
                    value={numQuestions}
                    onChange={(e) => setNumQuestions(parseInt(e.target.value))}
                    data-testid="num-questions-range"
                    className="w-full accent-[color:var(--brand)]"
                />
            </div>

            {/* Tiempo */}
            {mode === "exam" && (
                <div className="mb-8">
                    <span className="label-eyebrow block mb-2">
                        Tiempo: <span className="font-mono">{timeLimit} min</span>
                    </span>
                    <input
                        type="range"
                        min="2"
                        max="90"
                        value={timeLimit}
                        onChange={(e) => setTimeLimit(parseInt(e.target.value))}
                        data-testid="time-limit-range"
                        className="w-full accent-[color:var(--brand)]"
                    />
                </div>
            )}

            <button
                onClick={handleStart}
                disabled={starting || totalAvailable === 0}
                data-testid="start-quiz-btn"
                className="btn-primary w-full flex items-center justify-center gap-2"
            >
                {starting ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                    <Play className="w-4 h-4" />
                )}
                Empezar sesión
            </button>
        </div>
    );
}
