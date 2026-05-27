import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import {
    Clock,
    Sparkles,
    Flame,
    Brain,
    Star,
    ArrowLeft,
    Play,
    Loader2,
    AlertCircle,
} from "lucide-react";
import { toast } from "sonner";
import { listSubjects, listSubjectTopics, quizStart } from "@/lib/api";

const MODES = [
    { id: "practice", label: "Práctica", icon: Sparkles, desc: "Sin tiempo, feedback inmediato" },
    { id: "exam", label: "Examen", icon: Clock, desc: "Con cronómetro y nota final" },
    { id: "errors", label: "Errores", icon: Flame, desc: "Solo preguntas falladas" },
    { id: "srs", label: "Repaso", icon: Brain, desc: "Repetición espaciada" },
    { id: "favorites", label: "Favoritas", icon: Star, desc: "Las marcadas" },
];

const QTYPES = [
    { id: "any", label: "Cualquier tipo" },
    { id: "mcq", label: "Opción múltiple" },
    { id: "tf", label: "Verdadero/Falso" },
    { id: "dev", label: "Desarrollo (IA evalúa)" },
];

const PENALTIES = [
    { id: 0, label: "Sin penalización" },
    { id: 1, label: "1 mal = −1 bien" },
    { id: 2, label: "2 mal = −1 bien" },
    { id: 3, label: "3 mal = −1 bien" },
    { id: 4, label: "4 mal = −1 bien" },
];

export default function QuizSetup() {
    const navigate = useNavigate();
    const [params] = useSearchParams();
    const initialMode = params.get("mode") || "practice";
    const initialSubject = params.get("subject");
    const initialTopic = params.get("topic");

    const [subjects, setSubjects] = useState([]);
    const [allTopics, setAllTopics] = useState({}); // {subjectId: [topics]}
    const [selectedSubjects, setSelectedSubjects] = useState(
        new Set(initialSubject ? [initialSubject] : []),
    );
    const [selectedTopics, setSelectedTopics] = useState(
        new Set(initialTopic ? [initialTopic] : []),
    );
    const [mode, setMode] = useState(initialMode);
    const [questionType, setQuestionType] = useState("any");
    const [numQuestions, setNumQuestions] = useState(15);
    const [timeLimit, setTimeLimit] = useState(15);
    const [penalty, setPenalty] = useState(0);
    const [starting, setStarting] = useState(false);

    useEffect(() => {
        listSubjects()
            .then((subs) => {
                setSubjects(subs);
                // Load topics for each subject
                return Promise.all(
                    subs.map((s) =>
                        listSubjectTopics(s.id).then((ts) => ({ id: s.id, topics: ts })),
                    ),
                );
            })
            .then((arr) => {
                const map = {};
                arr.forEach((x) => (map[x.id] = x.topics));
                setAllTopics(map);
            })
            .catch(() => toast.error("Error cargando datos"));
    }, []);

    // If user selects a subject, deselect specific topics from other subjects
    const toggleSubject = (sid) => {
        const next = new Set(selectedSubjects);
        if (next.has(sid)) next.delete(sid);
        else next.add(sid);
        setSelectedSubjects(next);
    };

    const toggleTopic = (tid) => {
        const next = new Set(selectedTopics);
        if (next.has(tid)) next.delete(tid);
        else next.add(tid);
        setSelectedTopics(next);
    };

    const visibleTopics = useMemo(() => {
        if (selectedSubjects.size === 0) {
            return Object.values(allTopics).flat();
        }
        return Object.entries(allTopics)
            .filter(([sid]) => selectedSubjects.has(sid))
            .flatMap(([, ts]) => ts);
    }, [allTopics, selectedSubjects]);

    const totalAvailable = useMemo(() => {
        let pool = visibleTopics;
        if (selectedTopics.size > 0) pool = pool.filter((t) => selectedTopics.has(t.id));
        return pool.reduce((a, t) => a + (t.question_count || 0), 0);
    }, [visibleTopics, selectedTopics]);

    const handleStart = async () => {
        setStarting(true);
        try {
            const payload = {
                mode,
                subject_ids: Array.from(selectedSubjects),
                topic_ids: Array.from(selectedTopics),
                num_questions: numQuestions,
                time_limit_minutes: mode === "exam" ? timeLimit : null,
                question_type: questionType,
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
                    subject_ids: Array.from(selectedSubjects),
                    topic_ids: Array.from(selectedTopics),
                    time_limit_seconds: mode === "exam" ? timeLimit * 60 : null,
                    penalty_factor: penalty > 0 ? penalty : null,
                    question_type: questionType,
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

            {/* Asignaturas */}
            <div className="mb-6">
                <div className="flex items-center justify-between mb-3">
                    <span className="label-eyebrow">Asignaturas {selectedSubjects.size === 0 && "(todas)"}</span>
                    {selectedSubjects.size > 0 && (
                        <button
                            data-testid="clear-subjects"
                            onClick={() => setSelectedSubjects(new Set())}
                            className="text-xs font-medium hover:underline"
                            style={{ color: "var(--brand)" }}
                        >
                            Limpiar
                        </button>
                    )}
                </div>
                {subjects.length === 0 ? (
                    <div className="card-organic p-5 text-sm" style={{ color: "var(--text-muted)" }}>
                        No tienes asignaturas. Crea una desde el inicio.
                    </div>
                ) : (
                    <div className="flex flex-wrap gap-2">
                        {subjects.map((s) => {
                            const active = selectedSubjects.has(s.id);
                            return (
                                <button
                                    key={s.id}
                                    onClick={() => toggleSubject(s.id)}
                                    data-testid={`subject-toggle-${s.id}`}
                                    className="px-3 py-2 rounded-md border flex items-center gap-2 transition-all text-sm font-medium"
                                    style={{
                                        borderColor: active ? s.color : "var(--border)",
                                        background: active ? `${s.color}18` : "white",
                                    }}
                                >
                                    <span
                                        className="w-2.5 h-2.5 rounded-full"
                                        style={{ background: s.color }}
                                    />
                                    {s.name}
                                    <span
                                        className="text-xs font-mono px-1.5 py-0.5 rounded-sm"
                                        style={{ background: "var(--bg-secondary)" }}
                                    >
                                        {s.question_count}
                                    </span>
                                </button>
                            );
                        })}
                    </div>
                )}
            </div>

            {/* Temas */}
            {visibleTopics.length > 0 && (
                <div className="mb-6">
                    <div className="flex items-center justify-between mb-3">
                        <span className="label-eyebrow">
                            Temas {selectedTopics.size === 0 && "(todos)"}
                        </span>
                        {selectedTopics.size > 0 && (
                            <button
                                data-testid="clear-topics"
                                onClick={() => setSelectedTopics(new Set())}
                                className="text-xs font-medium hover:underline"
                                style={{ color: "var(--brand)" }}
                            >
                                Limpiar
                            </button>
                        )}
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {visibleTopics.map((t) => {
                            const active = selectedTopics.has(t.id);
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
                                        style={{
                                            background: "var(--bg-secondary)",
                                            color: "var(--text-secondary)",
                                        }}
                                    >
                                        {t.question_count}
                                    </span>
                                </button>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* Tipo de examen */}
            <div className="mb-6">
                <span className="label-eyebrow block mb-3">Tipo de pregunta</span>
                <div className="grid grid-cols-3 gap-2">
                    {QTYPES.map((t) => (
                        <button
                            key={t.id}
                            onClick={() => setQuestionType(t.id)}
                            data-testid={`qtype-${t.id}`}
                            className="px-3 py-2 rounded-md border text-sm font-medium transition-all"
                            style={{
                                borderColor: questionType === t.id ? "var(--brand)" : "var(--border)",
                                background: questionType === t.id ? "#fdf1ea" : "white",
                            }}
                        >
                            {t.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* Penalización */}
            <div className="mb-6">
                <span className="label-eyebrow block mb-3">Sistema de corrección</span>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
                    {PENALTIES.map((p) => (
                        <button
                            key={p.id}
                            onClick={() => setPenalty(p.id)}
                            data-testid={`penalty-${p.id}`}
                            className="px-3 py-2 rounded-md border text-sm font-medium transition-all"
                            style={{
                                borderColor: penalty === p.id ? "var(--brand)" : "var(--border)",
                                background: penalty === p.id ? "#fdf1ea" : "white",
                            }}
                        >
                            {p.label}
                        </button>
                    ))}
                </div>
                {penalty > 0 && (
                    <div
                        className="mt-2 text-xs flex items-start gap-2 p-2 rounded-md"
                        style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
                    >
                        <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" style={{ color: "var(--brand)" }} />
                        Las preguntas en blanco no penalizan. Solo restan las falladas.
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

            {mode === "exam" && (
                <div className="mb-8">
                    <span className="label-eyebrow block mb-2">
                        Tiempo: <span className="font-mono">{timeLimit} min</span>
                    </span>
                    <input
                        type="range"
                        min="2"
                        max="120"
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
                {starting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                Empezar sesión
            </button>
        </div>
    );
}
