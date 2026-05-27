import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
    ArrowLeft,
    Star,
    Flag,
    Trash2,
    Plus,
    Check,
    Sparkles,
    FileText,
    Layers,
} from "lucide-react";
import { toast } from "sonner";
import {
    getTopic,
    getTopicQuestions,
    getTopicPdfs,
    toggleFavorite as apiFav,
    toggleDifficult as apiDiff,
    deleteQuestion,
    deletePdf,
} from "@/lib/api";
import GenerateDialog from "@/components/GenerateDialog";
import AddPdfDialog from "@/components/AddPdfDialog";

export default function TopicDetail() {
    const { id } = useParams();
    const [topic, setTopic] = useState(null);
    const [questions, setQuestions] = useState([]);
    const [pdfs, setPdfs] = useState([]);
    const [filter, setFilter] = useState("all");
    const [genOpen, setGenOpen] = useState(false);
    const [genDefault, setGenDefault] = useState(null);
    const [addOpen, setAddOpen] = useState(false);

    const load = async () => {
        try {
            const [t, qs, ps] = await Promise.all([
                getTopic(id),
                getTopicQuestions(id),
                getTopicPdfs(id),
            ]);
            setTopic(t);
            setQuestions(qs);
            setPdfs(ps);
        } catch {
            toast.error("Error al cargar el tema");
        }
    };

    useEffect(() => {
        load();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [id]);

    const filtered = questions.filter((q) => {
        if (filter === "favorites") return q.favorite;
        if (filter === "difficult") return q.difficult;
        if (filter === "errors") return q.times_answered > q.times_correct;
        if (filter === "mcq") return q.question_type === "mcq";
        if (filter === "tf") return q.question_type === "tf";
        if (filter === "dev") return q.question_type === "dev";
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

    const removePdf = async (pid) => {
        if (!window.confirm("¿Eliminar este PDF? Las preguntas generadas se conservan.")) return;
        await deletePdf(pid);
        toast.success("PDF eliminado");
        setPdfs((ps) => ps.filter((p) => p.id !== pid));
    };

    if (!topic) {
        return (
            <div className="max-w-4xl mx-auto px-5 md:px-8 py-10" style={{ color: "var(--text-muted)" }}>
                Cargando…
            </div>
        );
    }

    const subjectColor = topic.subject?.color || "var(--brand)";

    return (
        <div className="max-w-4xl mx-auto px-5 md:px-8 py-8 md:py-12">
            <Link
                to={topic.subject_id ? `/asignaturas/${topic.subject_id}` : "/"}
                data-testid="back-subject"
                className="inline-flex items-center gap-1 text-sm font-medium mb-4 hover:underline"
                style={{ color: "var(--text-secondary)" }}
            >
                <ArrowLeft className="w-4 h-4" /> Volver{" "}
                {topic.subject?.name && `a ${topic.subject.name}`}
            </Link>

            <div className="flex flex-wrap items-start justify-between gap-3 mb-6">
                <div>
                    <span className="label-eyebrow">{topic.subject?.name || "Tema"}</span>
                    <h1 className="font-display text-3xl md:text-4xl font-bold mt-1">{topic.name}</h1>
                    <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
                        {questions.length} preguntas · {topic.accuracy}% precisión · {pdfs.length} PDFs
                    </p>
                </div>
                <div className="flex gap-2">
                    <Link
                        to={`/temas/${topic.id}/flashcards`}
                        data-testid="flashcards-btn"
                        className="px-4 py-2 rounded-md border font-medium text-sm hover:bg-[color:var(--bg-secondary)] flex items-center gap-2"
                        style={{ borderColor: "var(--border)" }}
                    >
                        <Layers className="w-4 h-4" /> Flashcards
                    </Link>
                    <Link
                        to={`/quiz/setup?topic=${topic.id}&mode=practice`}
                        data-testid="practice-here-btn"
                        className="px-4 py-2 rounded-md border font-medium text-sm hover:bg-[color:var(--bg-secondary)] flex items-center gap-2"
                        style={{ borderColor: "var(--border)" }}
                    >
                        <Sparkles className="w-4 h-4" /> Practicar
                    </Link>
                </div>
            </div>

            {/* PDFs section */}
            <section className="mb-8">
                <div className="flex items-center justify-between mb-3">
                    <span className="label-eyebrow">Fuentes PDF</span>
                    <div className="flex gap-2">
                        <button
                            onClick={() => setAddOpen(true)}
                            data-testid="add-pdf-btn"
                            className="px-3 py-1.5 rounded-md border text-xs font-medium flex items-center gap-1 hover:bg-[color:var(--bg-secondary)]"
                            style={{ borderColor: "var(--border)" }}
                        >
                            <Plus className="w-3.5 h-3.5" /> Añadir PDF
                        </button>
                        <button
                            onClick={() => {
                                setGenDefault(null);
                                setGenOpen(true);
                            }}
                            disabled={pdfs.length === 0}
                            data-testid="generate-questions-btn"
                            className="btn-primary text-xs flex items-center gap-1"
                            style={{ padding: "0.4rem 0.8rem" }}
                        >
                            <Sparkles className="w-3.5 h-3.5" /> Generar preguntas
                        </button>
                    </div>
                </div>
                {pdfs.length === 0 ? (
                    <div className="card-organic p-5 text-sm" style={{ color: "var(--text-muted)" }}>
                        Aún no hay PDFs en este tema. Pulsa "Añadir PDF" para subir el primero.
                    </div>
                ) : (
                    <div className="space-y-2">
                        {pdfs.map((p) => (
                            <div
                                key={p.id}
                                className="card-organic p-4 flex items-center justify-between gap-3 fade-up"
                                data-testid={`pdf-${p.id}`}
                            >
                                <div className="flex items-center gap-3 min-w-0 flex-1">
                                    <div
                                        className="w-9 h-9 rounded-md flex items-center justify-center shrink-0"
                                        style={{ background: "var(--bg-secondary)" }}
                                    >
                                        <FileText className="w-4 h-4" style={{ color: subjectColor }} />
                                    </div>
                                    <div className="min-w-0">
                                        <div className="text-sm font-medium truncate">{p.filename}</div>
                                        <div
                                            className="text-xs font-mono"
                                            style={{ color: "var(--text-muted)" }}
                                        >
                                            {p.question_count} preguntas generadas ·{" "}
                                            {Math.round(p.char_count / 1000)}k caracteres
                                        </div>
                                    </div>
                                </div>
                                <div className="flex gap-1">
                                    <button
                                        onClick={() => {
                                            setGenDefault([p.id]);
                                            setGenOpen(true);
                                        }}
                                        data-testid={`gen-from-${p.id}`}
                                        className="px-2.5 py-1.5 rounded-md text-xs font-medium hover:bg-[color:var(--bg-secondary)]"
                                        style={{ color: subjectColor }}
                                    >
                                        Generar de este
                                    </button>
                                    <button
                                        onClick={() => removePdf(p.id)}
                                        data-testid={`del-pdf-${p.id}`}
                                        className="p-1.5 rounded hover:bg-[color:var(--bg-secondary)]"
                                    >
                                        <Trash2 className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </section>

            <div className="flex items-end justify-between mb-3">
                <span className="label-eyebrow">Preguntas</span>
            </div>
            <div className="flex flex-wrap gap-2 mb-6">
                {[
                    { id: "all", label: "Todas" },
                    { id: "mcq", label: "Opción múltiple" },
                    { id: "tf", label: "V/F" },
                    { id: "dev", label: "Desarrollo" },
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
                                <div className="flex items-center gap-2">
                                    <span className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                                        #{i + 1}
                                    </span>
                                    <span
                                        className="text-[10px] uppercase tracking-widest px-1.5 py-0.5 rounded-sm font-bold"
                                        style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
                                    >
                                        {q.question_type === "tf" ? "V/F" : `${q.num_options} opc`}
                                    </span>
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
                                                {q.question_type === "tf"
                                                    ? oi === 0
                                                        ? "V"
                                                        : "F"
                                                    : String.fromCharCode(65 + oi)}
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
                                    <span>Acierto {Math.round((q.times_correct / q.times_answered) * 100)}%</span>
                                </div>
                            )}
                        </div>
                    ))
                )}
            </div>

            <GenerateDialog
                open={genOpen}
                topic={topic}
                pdfs={pdfs}
                defaultSelected={genDefault}
                onClose={() => setGenOpen(false)}
                onDone={load}
            />
            <AddPdfDialog
                open={addOpen}
                topicId={topic.id}
                onClose={() => setAddOpen(false)}
                onUploaded={load}
            />
        </div>
    );
}
