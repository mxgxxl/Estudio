import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
    Search, Star, Flag, Trash2, Check, Sparkles, Loader2, ChevronLeft,
    ChevronRight, ExternalLink, Pencil, ListChecks,
} from "lucide-react";
import { toast } from "sonner";
import {
    listQuestions, listQuestionIds, listSubjects, listTopics, listPdfs,
    toggleFavorite as apiFav, toggleDifficult as apiDiff, deleteQuestion, quizStart,
} from "@/lib/api";
import EditQuestionDialog from "@/components/EditQuestionDialog";

const STATUSES = [
    { id: "all", label: "Todas" },
    { id: "errors", label: "Falladas" },
    { id: "difficult", label: "Difíciles" },
    { id: "favorites", label: "Favoritas" },
    { id: "unpracticed", label: "Sin practicar" },
    { id: "mastered", label: "Dominadas" },
    { id: "due", label: "Toca repasar" },
];
const TYPES = [
    { id: "", label: "Todos los tipos" },
    { id: "mcq", label: "Opción múltiple" },
    { id: "tf", label: "Verdadero/Falso" },
    { id: "dev", label: "Desarrollo" },
];
const LIMIT = 30;

export default function QuestionBank() {
    const navigate = useNavigate();

    // Catálogos para desplegables y mapeo de nombres.
    const [subjects, setSubjects] = useState([]);
    const [topics, setTopics] = useState([]);
    const [pdfs, setPdfs] = useState([]);

    // Filtros.
    const [subjectId, setSubjectId] = useState("");
    const [topicId, setTopicId] = useState("");
    const [pdfId, setPdfId] = useState("");
    const [qType, setQType] = useState("");
    const [status, setStatus] = useState("all");
    const [sort, setSort] = useState("recent");
    const [search, setSearch] = useState("");
    const [debouncedSearch, setDebouncedSearch] = useState("");
    const [page, setPage] = useState(1);

    const [data, setData] = useState(null); // { items, total, page, limit }
    const [loading, setLoading] = useState(true);
    const [practicing, setPracticing] = useState(false);
    const [toDelete, setToDelete] = useState(null);
    const [deleting, setDeleting] = useState(false);
    const [editing, setEditing] = useState(null);

    useEffect(() => {
        Promise.all([listSubjects(), listTopics(), listPdfs()])
            .then(([s, t, p]) => { setSubjects(s); setTopics(t); setPdfs(p); })
            .catch(() => toast.error("No se pudieron cargar los filtros"));
    }, []);

    // Debounce del buscador.
    useEffect(() => {
        const id = setTimeout(() => setDebouncedSearch(search), 350);
        return () => clearTimeout(id);
    }, [search]);

    // Mapas de nombres.
    const subjectName = useMemo(() => Object.fromEntries(subjects.map((s) => [s.id, s.name])), [subjects]);
    const topicName = useMemo(() => Object.fromEntries(topics.map((t) => [t.id, t.name])), [topics]);
    const pdfName = useMemo(() => Object.fromEntries(pdfs.map((p) => [p.id, p.filename])), [pdfs]);
    const topicsForSubject = useMemo(
        () => (subjectId ? topics.filter((t) => t.subject_id === subjectId) : topics),
        [topics, subjectId]
    );

    // Filtros actuales (para list y para /ids).
    const filters = useMemo(() => ({
        subject_id: subjectId || undefined,
        topic_id: topicId || undefined,
        pdf_source_id: pdfId || undefined,
        question_type: qType || undefined,
        status,
        q: debouncedSearch || undefined,
    }), [subjectId, topicId, pdfId, qType, status, debouncedSearch]);

    // Al cambiar cualquier filtro, vuelve a la página 1.
    useEffect(() => { setPage(1); }, [filters]);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const res = await listQuestions({ ...filters, sort, page, limit: LIMIT });
            setData(res);
        } catch {
            toast.error("Error al cargar las preguntas");
        } finally {
            setLoading(false);
        }
    }, [filters, sort, page]);

    useEffect(() => { load(); }, [load]);

    // Si al cambiar de asignatura el tema elegido ya no pertenece, lo limpiamos.
    useEffect(() => {
        if (topicId && subjectId && !topicsForSubject.some((t) => t.id === topicId)) {
            setTopicId("");
        }
    }, [subjectId, topicId, topicsForSubject]);

    const patchItem = (qid, fields) =>
        setData((d) => d && { ...d, items: d.items.map((q) => (q.id === qid ? { ...q, ...fields } : q)) });

    const toggleFav = async (qid) => {
        const { favorite } = await apiFav(qid);
        patchItem(qid, { favorite });
    };
    const toggleDiff = async (qid) => {
        const { difficult } = await apiDiff(qid);
        patchItem(qid, { difficult });
    };

    const confirmDelete = async () => {
        if (!toDelete) return;
        setDeleting(true);
        try {
            await deleteQuestion(toDelete.id);
            toast.success("Pregunta eliminada");
            setToDelete(null);
            load();
        } catch (err) {
            toast.error(err?.response?.data?.detail || "No se pudo eliminar");
        } finally {
            setDeleting(false);
        }
    };

    const practiceSelection = async () => {
        setPracticing(true);
        try {
            const { ids, total, capped } = await listQuestionIds(filters);
            if (!ids.length) {
                toast.error("No hay preguntas para practicar con estos filtros");
                return;
            }
            if (capped) {
                toast(`Practicando ${ids.length} de ${total} preguntas`, {
                    description: "Es el máximo por sesión. Afina los filtros para incluir el resto.",
                });
            }
            const res = await quizStart({
                mode: "practice",
                question_ids: ids,
                num_questions: ids.length,
                question_type: qType || "any",
            });
            const questions = res.questions || [];
            if (!questions.length) {
                toast.error("No hay preguntas disponibles");
                return;
            }
            sessionStorage.setItem("current_quiz", JSON.stringify({
                questions,
                mode: "practice",
                subject_ids: [],
                topic_ids: [],
                time_limit_seconds: null,
                penalty_factor: null,
                question_type: qType || "any",
                started_at: Date.now(),
            }));
            navigate("/quiz/run");
        } catch (err) {
            toast.error(err?.response?.data?.detail || "No se pudo iniciar la práctica");
        } finally {
            setPracticing(false);
        }
    };

    const total = data?.total ?? 0;
    const items = data?.items ?? [];
    const totalPages = Math.max(1, Math.ceil(total / LIMIT));

    const selectCls = "px-3 py-2 rounded-md border text-sm bg-white";
    const selectStyle = { borderColor: "var(--border)" };

    return (
        <div className="max-w-4xl mx-auto px-5 md:px-8 py-8 md:py-12">
            <div className="flex items-start justify-between gap-4 mb-2">
                <div>
                    <span className="label-eyebrow">Tu material</span>
                    <h1 className="font-display text-3xl md:text-4xl font-bold mt-1">Banco de preguntas</h1>
                </div>
                <button
                    onClick={practiceSelection}
                    disabled={practicing || total === 0}
                    data-testid="practice-selection-btn"
                    className="btn-primary flex items-center gap-2 text-sm shrink-0 disabled:opacity-50"
                >
                    {practicing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                    Practicar selección
                </button>
            </div>
            <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>
                Todas tus preguntas generadas, en un solo sitio. Filtra, busca y practica lo que quieras.
            </p>

            {/* Buscador */}
            <div className="relative mb-3">
                <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: "var(--text-muted)" }} />
                <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Buscar en el enunciado…"
                    data-testid="qbank-search"
                    className="w-full pl-9 pr-3 py-2 rounded-md border text-sm"
                    style={{ borderColor: "var(--border)" }}
                />
            </div>

            {/* Filtros */}
            <div className="flex flex-wrap gap-2 mb-3">
                <select value={subjectId} onChange={(e) => setSubjectId(e.target.value)} className={selectCls} style={selectStyle} data-testid="qbank-subject">
                    <option value="">Todas las asignaturas</option>
                    {subjects.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
                <select value={topicId} onChange={(e) => setTopicId(e.target.value)} className={selectCls} style={selectStyle} data-testid="qbank-topic">
                    <option value="">Todos los temas</option>
                    {topicsForSubject.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
                <select value={pdfId} onChange={(e) => setPdfId(e.target.value)} className={selectCls} style={selectStyle} data-testid="qbank-pdf">
                    <option value="">Todos los PDFs</option>
                    <option value="none">Sin PDF de origen</option>
                    {pdfs.map((p) => <option key={p.id} value={p.id}>{p.filename}</option>)}
                </select>
                <select value={qType} onChange={(e) => setQType(e.target.value)} className={selectCls} style={selectStyle} data-testid="qbank-type">
                    {TYPES.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
                </select>
                <select value={sort} onChange={(e) => setSort(e.target.value)} className={selectCls} style={selectStyle} data-testid="qbank-sort">
                    <option value="recent">Más recientes</option>
                    <option value="most_failed">Más practicadas</option>
                </select>
            </div>

            {/* Estados (chips) */}
            <div className="flex flex-wrap gap-2 mb-5">
                {STATUSES.map((s) => (
                    <button
                        key={s.id}
                        onClick={() => setStatus(s.id)}
                        data-testid={`qbank-status-${s.id}`}
                        className="px-3 py-1.5 rounded-md text-xs font-medium border"
                        style={{
                            borderColor: status === s.id ? "var(--brand)" : "var(--border)",
                            background: status === s.id ? "#fdf1ea" : "white",
                            color: status === s.id ? "var(--brand)" : "var(--text-secondary)",
                        }}
                    >
                        {s.label}
                    </button>
                ))}
            </div>

            {/* Contador */}
            <div className="flex items-center justify-between mb-3 text-sm" style={{ color: "var(--text-muted)" }}>
                <span data-testid="qbank-count">
                    {loading ? "Cargando…" : `${total} ${total === 1 ? "pregunta" : "preguntas"}`}
                </span>
                {totalPages > 1 && <span>Página {page} de {totalPages}</span>}
            </div>

            {/* Lista */}
            {!loading && items.length === 0 ? (
                <div className="card-organic p-10 text-center" data-testid="qbank-empty">
                    <ListChecks className="w-10 h-10 mx-auto mb-3" style={{ color: "var(--brand)" }} />
                    <h3 className="font-display text-xl font-bold">No hay preguntas con estos filtros</h3>
                    <p className="mt-1 text-sm" style={{ color: "var(--text-muted)" }}>
                        Prueba a quitar filtros o genera preguntas desde un tema.
                    </p>
                </div>
            ) : (
                <div className="space-y-3">
                    {items.map((q) => (
                        <QuestionCard
                            key={q.id}
                            q={q}
                            subjectName={subjectName[q.subject_id]}
                            topicName={topicName[q.topic_id] || q.topic_name}
                            pdfLabel={q.pdf_source_id ? pdfName[q.pdf_source_id] : null}
                            onFav={() => toggleFav(q.id)}
                            onDiff={() => toggleDiff(q.id)}
                            onDelete={() => setToDelete(q)}
                            onEdit={() => setEditing(q)}
                            onGoTopic={() => navigate(`/temas/${q.topic_id}`)}
                        />
                    ))}
                </div>
            )}

            {/* Paginación */}
            {totalPages > 1 && (
                <div className="flex items-center justify-center gap-3 mt-6">
                    <button
                        onClick={() => setPage((p) => Math.max(1, p - 1))}
                        disabled={page <= 1}
                        data-testid="qbank-prev"
                        className="px-3 py-2 rounded-md border text-sm flex items-center gap-1 disabled:opacity-40 hover:bg-[color:var(--bg-secondary)]"
                        style={{ borderColor: "var(--border)" }}
                    >
                        <ChevronLeft className="w-4 h-4" /> Anterior
                    </button>
                    <span className="text-sm font-mono" style={{ color: "var(--text-muted)" }}>{page} / {totalPages}</span>
                    <button
                        onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                        disabled={page >= totalPages}
                        data-testid="qbank-next"
                        className="px-3 py-2 rounded-md border text-sm flex items-center gap-1 disabled:opacity-40 hover:bg-[color:var(--bg-secondary)]"
                        style={{ borderColor: "var(--border)" }}
                    >
                        Siguiente <ChevronRight className="w-4 h-4" />
                    </button>
                </div>
            )}

            {/* Confirmación de borrado */}
            {toDelete && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: "rgba(35,33,31,0.45)" }} data-testid="qbank-delete-dialog">
                    <div className="card-organic w-full max-w-md fade-up" style={{ background: "white" }}>
                        <div className="p-5 border-b" style={{ borderColor: "var(--border)" }}>
                            <h3 className="font-display text-xl font-bold">Eliminar pregunta</h3>
                        </div>
                        <div className="p-5 space-y-4">
                            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>{toDelete.question}</p>
                            <div className="flex flex-col gap-2">
                                <button
                                    onClick={confirmDelete}
                                    disabled={deleting}
                                    data-testid="qbank-delete-confirm"
                                    className="w-full px-4 py-2.5 rounded-md font-semibold text-sm text-white flex items-center justify-center gap-2 disabled:opacity-60"
                                    style={{ background: "var(--error, #B84A4A)" }}
                                >
                                    {deleting && <Loader2 className="w-4 h-4 animate-spin" />}
                                    Eliminar definitivamente
                                </button>
                                <button
                                    onClick={() => setToDelete(null)}
                                    disabled={deleting}
                                    className="w-full px-4 py-2.5 rounded-md font-medium text-sm hover:bg-[color:var(--bg-secondary)]"
                                    style={{ color: "var(--text-secondary)" }}
                                >
                                    Cancelar
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            <EditQuestionDialog
                question={editing}
                onClose={() => setEditing(null)}
                onSaved={(updated) => { patchItem(updated.id, updated); setEditing(null); }}
            />
        </div>
    );
}

function QuestionCard({ q, subjectName, topicName, pdfLabel, onFav, onDiff, onDelete, onEdit, onGoTopic }) {
    const answered = q.times_answered || 0;
    const acc = answered ? Math.round((q.times_correct / answered) * 100) : null;
    return (
        <div className="card-organic p-5 fade-up" data-testid={`qbank-question-${q.id}`}>
            <div className="flex items-start justify-between gap-3 mb-2">
                <div className="flex items-center gap-2 flex-wrap min-w-0">
                    <span className="text-[10px] uppercase tracking-widest px-1.5 py-0.5 rounded-sm font-bold" style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}>
                        {q.question_type === "tf" ? "V/F" : q.question_type === "dev" ? "Desarrollo" : `${q.num_options} opc`}
                    </span>
                    <span className="text-xs truncate" style={{ color: "var(--text-muted)" }}>
                        {[subjectName, topicName].filter(Boolean).join(" · ")}
                        {pdfLabel ? ` · ${pdfLabel}` : ""}
                    </span>
                </div>
                <div className="flex gap-1 shrink-0">
                    <button onClick={onFav} className="p-1.5 rounded hover:bg-[color:var(--bg-secondary)]" data-testid={`qbank-fav-${q.id}`} title="Favorita">
                        <Star className="w-4 h-4" fill={q.favorite ? "var(--warning)" : "none"} style={{ color: q.favorite ? "var(--warning)" : "var(--text-muted)" }} />
                    </button>
                    <button onClick={onDiff} className="p-1.5 rounded hover:bg-[color:var(--bg-secondary)]" data-testid={`qbank-diff-${q.id}`} title="Difícil">
                        <Flag className="w-4 h-4" fill={q.difficult ? "var(--error)" : "none"} style={{ color: q.difficult ? "var(--error)" : "var(--text-muted)" }} />
                    </button>
                    <button onClick={onEdit} className="p-1.5 rounded hover:bg-[color:var(--bg-secondary)]" data-testid={`qbank-edit-${q.id}`} title="Editar">
                        <Pencil className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
                    </button>
                    <button onClick={onGoTopic} className="p-1.5 rounded hover:bg-[color:var(--bg-secondary)]" data-testid={`qbank-goto-${q.id}`} title="Ir al tema">
                        <ExternalLink className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
                    </button>
                    <button onClick={onDelete} className="p-1.5 rounded hover:bg-[color:var(--bg-secondary)]" data-testid={`qbank-del-${q.id}`} title="Eliminar">
                        <Trash2 className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
                    </button>
                </div>
            </div>
            <div className="font-display font-bold text-base md:text-lg leading-snug mb-3">{q.question}</div>
            {q.question_type !== "dev" && (
                <ul className="space-y-1 text-sm">
                    {q.options.map((opt, oi) => {
                        const isCorrect = oi === q.correct_index;
                        return (
                            <li key={oi} className="flex items-start gap-2 px-2 py-1 rounded" style={{ background: isCorrect ? "#eef2ec" : "transparent", color: isCorrect ? "var(--sage)" : "var(--text-secondary)" }}>
                                <span className="kbd" style={{ background: "white" }}>
                                    {q.question_type === "tf" ? (oi === 0 ? "V" : "F") : String.fromCharCode(65 + oi)}
                                </span>
                                <span className="flex-1">{opt}</span>
                                {isCorrect && <Check className="w-4 h-4 mt-0.5" />}
                            </li>
                        );
                    })}
                </ul>
            )}
            {q.explanation && (
                <p className="text-xs italic mt-2" style={{ color: "var(--text-muted)" }}>{q.explanation}</p>
            )}
            {answered > 0 && (
                <div className="mt-3 text-xs flex gap-3 font-mono" style={{ color: "var(--text-muted)" }}>
                    <span>Respondida {answered}×</span>
                    <span>Acierto {acc}%</span>
                </div>
            )}
        </div>
    );
}
