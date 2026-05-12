import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, Star, Flag, Trash2, Plus, Check, Sparkles } from "lucide-react";
import { toast } from "sonner";
import {
    getTopicQuestions,
    listTopics,
    toggleFavorite as apiFav,
    toggleDifficult as apiDiff,
    deleteQuestion,
} from "@/lib/api";
import UploadDialog from "@/components/UploadDialog";

export default function TopicDetail() {
    const { id } = useParams();
    const [topic, setTopic] = useState(null);
    const [questions, setQuestions] = useState([]);
    const [uploadOpen, setUploadOpen] = useState(false);
    const [filter, setFilter] = useState("all"); // all, favorites, difficult, errors

    const load = async () => {
        const [qs, ts] = await Promise.all([getTopicQuestions(id), listTopics()]);
        setQuestions(qs);
        setTopic(ts.find((t) => t.id === id));
    };

    useEffect(() => {
        load();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [id]);

    const filtered = questions.filter((q) => {
        if (filter === "favorites") return q.favorite;
        if (filter === "difficult") return q.difficult;
        if (filter === "errors") return q.times_answered > q.times_correct;
        return true;
    });

    const toggleFav = async (qid) => {
        const { favorite } = await apiFav(qid);
        setQuestions((qs) => qs.map((q) => (q.id === qid ? { ...q, favorite } : q)));
    };
    const toggleDiff = async (qid) => {
        const { difficult } = await apiDiff(qid);
        setQuestions((qs) => qs.map((q) => (q.id === qid ? { ...q, difficult } : q)));
    };
    const removeQ = async (qid) => {
        if (!window.confirm("¿Eliminar esta pregunta?")) return;
        await deleteQuestion(qid);
        toast.success("Pregunta eliminada");
        setQuestions((qs) => qs.filter((q) => q.id !== qid));
    };

    if (!topic) {
        return (
            <div className="max-w-4xl mx-auto px-5 md:px-8 py-10" style={{ color: "var(--text-muted)" }}>
                Cargando…
            </div>
        );
    }

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
            <div className="flex flex-wrap items-start justify-between gap-3 mb-2">
                <div>
                    <span className="label-eyebrow">Tema</span>
                    <h1 className="font-display text-3xl md:text-4xl font-bold mt-1">{topic.name}</h1>
                    <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
                        {questions.length} preguntas · {topic.accuracy}% precisión
                    </p>
                </div>
                <div className="flex gap-2">
                    <Link
                        to={`/quiz/setup?mode=practice&topic=${topic.id}`}
                        data-testid="practice-here-btn"
                        className="px-4 py-2 rounded-md border font-medium text-sm hover:bg-[color:var(--bg-secondary)] flex items-center gap-2"
                        style={{ borderColor: "var(--border)" }}
                    >
                        <Sparkles className="w-4 h-4" /> Practicar
                    </Link>
                    <button
                        onClick={() => setUploadOpen(true)}
                        data-testid="add-more-btn"
                        className="btn-primary flex items-center gap-2 text-sm"
                    >
                        <Plus className="w-4 h-4" /> Más preguntas
                    </button>
                </div>
            </div>

            <div className="flex flex-wrap gap-2 my-6">
                {[
                    { id: "all", label: "Todas" },
                    { id: "favorites", label: "Favoritas" },
                    { id: "difficult", label: "Difíciles" },
                    { id: "errors", label: "Falladas" },
                ].map((f) => (
                    <button
                        key={f.id}
                        onClick={() => setFilter(f.id)}
                        data-testid={`filter-${f.id}`}
                        className="px-3 py-1.5 rounded-md text-xs font-medium border"
                        style={{
                            borderColor: filter === f.id ? "var(--brand)" : "var(--border)",
                            background: filter === f.id ? "#fdf1ea" : "white",
                            color: filter === f.id ? "var(--brand)" : "var(--text-secondary)",
                        }}
                    >
                        {f.label}
                    </button>
                ))}
            </div>

            <div className="space-y-3">
                {filtered.length === 0 ? (
                    <div className="card-organic p-6 text-center text-sm" style={{ color: "var(--text-muted)" }}>
                        No hay preguntas con este filtro.
                    </div>
                ) : (
                    filtered.map((q, i) => (
                        <div key={q.id} className="card-organic p-5 fade-up" data-testid={`question-${q.id}`}>
                            <div className="flex items-start justify-between gap-3 mb-2">
                                <div className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                                    #{i + 1}
                                </div>
                                <div className="flex gap-1">
                                    <button
                                        onClick={() => toggleFav(q.id)}
                                        className="p-1.5 rounded hover:bg-[color:var(--bg-secondary)]"
                                        data-testid={`fav-${q.id}`}
                                    >
                                        <Star
                                            className="w-4 h-4"
                                            fill={q.favorite ? "var(--warning)" : "none"}
                                            style={{ color: q.favorite ? "var(--warning)" : "var(--text-muted)" }}
                                        />
                                    </button>
                                    <button
                                        onClick={() => toggleDiff(q.id)}
                                        className="p-1.5 rounded hover:bg-[color:var(--bg-secondary)]"
                                        data-testid={`diff-${q.id}`}
                                    >
                                        <Flag
                                            className="w-4 h-4"
                                            fill={q.difficult ? "var(--error)" : "none"}
                                            style={{ color: q.difficult ? "var(--error)" : "var(--text-muted)" }}
                                        />
                                    </button>
                                    <button
                                        onClick={() => removeQ(q.id)}
                                        className="p-1.5 rounded hover:bg-[color:var(--bg-secondary)]"
                                        data-testid={`del-${q.id}`}
                                    >
                                        <Trash2 className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
                                    </button>
                                </div>
                            </div>
                            <div className="font-display font-bold text-base md:text-lg leading-snug mb-3">
                                {q.question}
                            </div>
                            <ul className="space-y-1 text-sm">
                                {q.options.map((opt, oi) => {
                                    const isCorrect = oi === q.correct_index;
                                    return (
                                        <li
                                            key={oi}
                                            className="flex items-start gap-2 px-2 py-1 rounded"
                                            style={{
                                                background: isCorrect ? "#eef2ec" : "transparent",
                                                color: isCorrect ? "var(--sage)" : "var(--text-secondary)",
                                            }}
                                        >
                                            <span className="kbd" style={{ background: "white" }}>
                                                {String.fromCharCode(65 + oi)}
                                            </span>
                                            <span className="flex-1">{opt}</span>
                                            {isCorrect && <Check className="w-4 h-4 mt-0.5" />}
                                        </li>
                                    );
                                })}
                            </ul>
                            {q.explanation && (
                                <p className="text-xs italic mt-2" style={{ color: "var(--text-muted)" }}>
                                    {q.explanation}
                                </p>
                            )}
                            {q.times_answered > 0 && (
                                <div
                                    className="mt-3 text-xs flex gap-3 font-mono"
                                    style={{ color: "var(--text-muted)" }}
                                >
                                    <span>Respondida {q.times_answered}×</span>
                                    <span>
                                        Acierto {Math.round((q.times_correct / q.times_answered) * 100)}%
                                    </span>
                                </div>
                            )}
                        </div>
                    ))
                )}
            </div>

            <UploadDialog
                open={uploadOpen}
                existingTopic={topic}
                onClose={() => setUploadOpen(false)}
                onCreated={load}
            />
        </div>
    );
}
