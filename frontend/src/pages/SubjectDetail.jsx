import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
    ArrowLeft,
    Plus,
    Trash2,
    BookOpen,
    Target,
    BarChart3,
    Sparkles,
    Clock,
    FileText,
} from "lucide-react";
import { toast } from "sonner";
import { getSubject, listSubjectTopics, deleteTopic } from "@/lib/api";
import CreateTopicDialog from "@/components/CreateTopicDialog";

export default function SubjectDetail() {
    const { id } = useParams();
    const [subject, setSubject] = useState(null);
    const [topics, setTopics] = useState([]);
    const [uploadOpen, setUploadOpen] = useState(false);
    const [loading, setLoading] = useState(true);

    const load = async () => {
        setLoading(true);
        try {
            const [s, t] = await Promise.all([getSubject(id), listSubjectTopics(id)]);
            setSubject(s);
            setTopics(t);
        } catch {
            toast.error("Error al cargar la asignatura");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        load();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [id]);

    const handleDelete = async (e, tid, name) => {
        e.preventDefault();
        e.stopPropagation();
        if (!window.confirm(`¿Eliminar el tema "${name}"?`)) return;
        try {
            await deleteTopic(tid);
            toast.success("Tema eliminado");
            load();
        } catch {
            toast.error("Error al eliminar");
        }
    };

    if (loading || !subject) {
        return (
            <div className="max-w-5xl mx-auto px-5 md:px-8 py-10" style={{ color: "var(--text-muted)" }}>
                Cargando…
            </div>
        );
    }

    return (
        <div className="max-w-5xl mx-auto px-5 md:px-8 py-8 md:py-12">
            <Link
                to="/"
                data-testid="back-home"
                className="inline-flex items-center gap-1 text-sm font-medium mb-4 hover:underline"
                style={{ color: "var(--text-secondary)" }}
            >
                <ArrowLeft className="w-4 h-4" /> Volver
            </Link>

            <div className="flex flex-wrap items-start justify-between gap-3 mb-8 fade-up">
                <div className="flex items-center gap-3">
                    <span
                        className="w-4 h-12 rounded-sm"
                        style={{ background: subject.color || "var(--brand)" }}
                    />
                    <div>
                        <span className="label-eyebrow">Asignatura</span>
                        <h1 className="font-display text-3xl md:text-4xl font-bold mt-1">{subject.name}</h1>
                        <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
                            {subject.topic_count} temas · {subject.question_count} preguntas
                        </p>
                    </div>
                </div>
                <div className="flex gap-2">
                    <Link
                        to={`/quiz/setup?subject=${subject.id}&behavior=practice&selection=all`}
                        data-testid="practice-subject-btn"
                        className="px-4 py-2 rounded-md border font-medium text-sm hover:bg-[color:var(--bg-secondary)] flex items-center gap-2"
                        style={{ borderColor: "var(--border)" }}
                    >
                        <Sparkles className="w-4 h-4" /> Practicar todo
                    </Link>
                    <Link
                        to={`/quiz/setup?subject=${subject.id}&behavior=exam&selection=all`}
                        data-testid="exam-subject-btn"
                        className="btn-primary flex items-center gap-2 text-sm"
                    >
                        <Clock className="w-4 h-4" /> Examen
                    </Link>
                </div>
            </div>

            <div className="flex items-end justify-between mb-4">
                <div>
                    <span className="label-eyebrow">Temas</span>
                    <h2 className="font-display text-xl md:text-2xl font-bold mt-1">Tus temas</h2>
                </div>
                <button
                    onClick={() => setUploadOpen(true)}
                    data-testid="add-topic-btn"
                    className="btn-primary flex items-center gap-2 text-sm"
                >
                    <Plus className="w-4 h-4" /> Nuevo tema
                </button>
            </div>

            {topics.length === 0 ? (
                <div className="card-organic p-10 text-center fade-up">
                    <BookOpen className="w-10 h-10 mx-auto mb-3" style={{ color: subject.color || "var(--brand)" }} />
                    <h3 className="font-display text-xl font-bold">No hay temas en esta asignatura</h3>
                    <p className="mt-1 text-sm" style={{ color: "var(--text-muted)" }}>
                        Crea tu primer tema. Podrás añadir PDFs y generar preguntas cuando quieras.
                    </p>
                    <button
                        onClick={() => setUploadOpen(true)}
                        data-testid="empty-add-topic-btn"
                        className="btn-primary mt-5 inline-flex items-center gap-2"
                    >
                        <Plus className="w-4 h-4" /> Nuevo tema
                    </button>
                </div>
            ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    {topics.map((t) => (
                        <Link
                            key={t.id}
                            to={`/temas/${t.id}`}
                            data-testid={`topic-card-${t.id}`}
                            className="card-organic p-5 flex flex-col gap-3 fade-up hover:-translate-y-0.5 transition-transform"
                        >
                            <div className="flex items-start justify-between">
                                <div className="font-display font-bold text-lg">{t.name}</div>
                                <button
                                    onClick={(e) => handleDelete(e, t.id, t.name)}
                                    data-testid={`delete-topic-${t.id}`}
                                    className="p-1.5 rounded hover:bg-[color:var(--bg-secondary)]"
                                    title="Eliminar tema"
                                >
                                    <Trash2 className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
                                </button>
                            </div>
                            <div
                                className="flex items-center gap-4 text-sm flex-wrap"
                                style={{ color: "var(--text-secondary)" }}
                            >
                                <span className="flex items-center gap-1">
                                    <Target className="w-3.5 h-3.5" /> {t.question_count} preguntas
                                </span>
                                <span className="flex items-center gap-1">
                                    <FileText className="w-3.5 h-3.5" /> {t.pdf_count || 0} PDFs
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
                                        background: subject.color || "var(--brand)",
                                    }}
                                />
                            </div>
                        </Link>
                    ))}
                </div>
            )}

            <CreateTopicDialog
                open={uploadOpen}
                onClose={() => setUploadOpen(false)}
                onCreated={load}
                subjectId={subject.id}
            />
        </div>
    );
}
