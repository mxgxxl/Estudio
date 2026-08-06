import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
    Search, Star, Flag, Trash2, Check, Sparkles, Loader2, ChevronLeft,
    ChevronRight, ExternalLink, Pencil, ListChecks, Plus, Shuffle, X,
} from "lucide-react";
import { toast } from "sonner";
import {
    listQuestions, listQuestionIds, listSubjects, listTopics, listPdfs,
    toggleFavorite as apiFav, toggleDifficult as apiDiff, deleteQuestion, quizStart,
} from "@/lib/api";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import EditQuestionDialog from "@/components/EditQuestionDialog";
import CreateQuestionDialog from "@/components/CreateQuestionDialog";
import CreateTopicStepper from "@/components/CreateTopicStepper";

// Valor centinela del <select> de temas: no es un filtro, abre el stepper.
const CREATE_TOPIC_VALUE = "__create__";

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
// Tope de preguntas por sesión de práctica (espejo de QUESTIONS_IDS_CAP del backend).
const SESSION_CAP = 500;

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
    const [createOpen, setCreateOpen] = useState(false);
    const [topicStepperOpen, setTopicStepperOpen] = useState(false);

    // Selección granular para practicar.
    const [selectedIds, setSelectedIds] = useState(() => new Set()); // marcadas por checkbox
    const [selectAllFiltered, setSelectAllFiltered] = useState(false); // "todas las que coinciden"
    const [randomMode, setRandomMode] = useState(null);   // null | "count" | "percent"
    const [randomValue, setRandomValue] = useState(10);

    // Catálogos de filtros (asignaturas/temas/PDFs). Reutilizado tras crear un
    // tema nuevo para que aparezca de inmediato como opción del desplegable.
    const loadCatalogs = useCallback(() => {
        return Promise.all([listSubjects(), listTopics(), listPdfs()])
            .then(([s, t, p]) => { setSubjects(s); setTopics(t); setPdfs(p); })
            .catch(() => toast.error("No se pudieron cargar los filtros"));
    }, []);

    useEffect(() => { loadCatalogs(); }, [loadCatalogs]);

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

    // Cambiar un FILTRO (o el orden) invalida la selección acumulada; paginar NO.
    useEffect(() => {
        setSelectedIds(new Set());
        setSelectAllFiltered(false);
    }, [filters, sort]);

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

    // Una generación diferida (usuario cerró el stepper a mitad) que completa
    // mientras seguimos aquí → refresca el listado para ver las preguntas nuevas.
    useEffect(() => {
        const onGen = () => load();
        window.addEventListener("studia:generation-complete", onGen);
        return () => window.removeEventListener("studia:generation-complete", onGen);
    }, [load]);

    // Al completar el stepper: enfoca los filtros en el tema recién creado (su
    // asignatura + el tema, el resto a "todos") y recarga catálogos y listado.
    const handleTopicCreated = async ({ subjectId: sid, topicId: tid }) => {
        await loadCatalogs(); // el nuevo tema debe existir como opción antes de fijarlo
        setSubjectId(sid || "");
        setTopicId(tid || "");
        setPdfId("");
        setQType("");
        setStatus("all");
    };

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

    // Arranca un quiz de práctica con un conjunto EXACTO de ids (reusado por los
    // tres modos: selección explícita, todas las filtradas y aleatorio).
    const launchQuiz = async (ids) => {
        const res = await quizStart({
            behavior: "practice",
            selection: "all",
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
            behavior: "practice",
            selection: "all",
            subject_ids: [],
            topic_ids: [],
            time_limit_seconds: null,
            penalty_factor: null,
            question_type: qType || "any",
            started_at: Date.now(),
        }));
        navigate("/quiz/run");
    };

    // Practicar según el modo activo:
    // - selectAllFiltered → /questions/ids con filtros (respeta CAP + aviso capped).
    // - selección explícita → esos ids exactos (sin llamar a /ids).
    // - nada marcado → comportamiento actual (todas las filtradas vía /ids).
    const practiceSelection = async () => {
        setPracticing(true);
        try {
            let ids;
            if (!selectAllFiltered && selectedIds.size > 0) {
                if (selectedIds.size > SESSION_CAP) {
                    toast.error(`Máximo ${SESSION_CAP} por sesión. Tienes ${selectedIds.size} seleccionadas.`);
                    return;
                }
                ids = [...selectedIds];
            } else {
                const res = await listQuestionIds(filters);
                ids = res.ids;
                if (res.capped) {
                    toast(`Practicando ${ids.length} de ${res.total} preguntas`, {
                        description: "Es el máximo por sesión. Afina los filtros para incluir el resto.",
                    });
                }
            }
            if (!ids.length) {
                toast.error("No hay preguntas para practicar con estos filtros");
                return;
            }
            await launchQuiz(ids);
        } catch (err) {
            toast.error(err?.response?.data?.detail || "No se pudo iniciar la práctica");
        } finally {
            setPracticing(false);
        }
    };

    // Practicar una muestra ALEATORIA (cantidad o %) sobre los filtros activos.
    const practiceRandom = async () => {
        if (!randomMode) return;
        const n = randomMode === "percent"
            ? Math.ceil((total * randomValue) / 100)
            : randomValue;
        const size = Math.max(1, Math.min(n, SESSION_CAP));
        setPracticing(true);
        try {
            const { ids } = await listQuestionIds({ ...filters, randomSample: size });
            if (!ids.length) {
                toast.error("No hay preguntas para practicar con estos filtros");
                return;
            }
            await launchQuiz(ids);
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

    // Selección: marcar/desmarcar una pregunta o toda la página.
    const toggleSelect = (id) => {
        setSelectAllFiltered(false);
        setSelectedIds((prev) => {
            const next = new Set(prev);
            next.has(id) ? next.delete(id) : next.add(id);
            return next;
        });
    };
    const pageIds = items.map((q) => q.id);
    const allPageSelected = pageIds.length > 0 && pageIds.every((id) => selectedIds.has(id));
    const somePageSelected = pageIds.some((id) => selectedIds.has(id));
    const headerCheck = allPageSelected ? true : somePageSelected ? "indeterminate" : false;
    const toggleSelectPage = () => {
        setSelectAllFiltered(false);
        setSelectedIds((prev) => {
            const next = new Set(prev);
            if (allPageSelected) pageIds.forEach((id) => next.delete(id));
            else pageIds.forEach((id) => next.add(id));
            return next;
        });
    };
    const clearSelection = () => {
        setSelectedIds(new Set());
        setSelectAllFiltered(false);
    };
    // Enlace "seleccionar todas las que coinciden": solo si la página entera está
    // marcada y hay más preguntas fuera de la página.
    const canSelectAllFiltered =
        !selectAllFiltered && allPageSelected && selectedIds.size === items.length && total > items.length;
    const hasSelection = selectAllFiltered || selectedIds.size > 0;

    return (
        <div>
            <div className="flex items-start justify-between gap-4 mb-6">
                <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                    Todas tus preguntas generadas, en un solo sitio. Filtra, busca y practica lo que quieras.
                </p>
                <div className="flex items-center gap-2 shrink-0">
                    <button
                        onClick={() => setCreateOpen(true)}
                        data-testid="create-question-btn"
                        className="px-4 py-2 rounded-md border font-medium text-sm flex items-center gap-2 hover:bg-[color:var(--bg-secondary)]"
                        style={{ borderColor: "var(--border)" }}
                    >
                        <Plus className="w-4 h-4" /> Crear pregunta
                    </button>
                    <button
                        onClick={practiceSelection}
                        disabled={practicing || total === 0}
                        data-testid="practice-selection-btn"
                        className="btn-primary flex items-center gap-2 text-sm disabled:opacity-50"
                    >
                        {practicing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                        Practicar selección
                    </button>
                </div>
            </div>

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
                <select
                    value={topicId}
                    onChange={(e) => {
                        // Centinela: abre el stepper y deja el filtro como estaba
                        // (el <select> controlado revierte solo al no tocar topicId).
                        if (e.target.value === CREATE_TOPIC_VALUE) { setTopicStepperOpen(true); return; }
                        setTopicId(e.target.value);
                    }}
                    className={selectCls}
                    style={selectStyle}
                    data-testid="qbank-topic"
                >
                    <option value="">Todos los temas</option>
                    {topicsForSubject.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                    <option value={CREATE_TOPIC_VALUE}>+ Nuevo tema</option>
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

            {/* Práctica aleatoria: N preguntas o X% sobre los filtros activos */}
            <div className="card-organic p-3 mb-4 flex flex-wrap items-center gap-2" data-testid="qbank-random-panel">
                <span className="text-xs font-medium flex items-center gap-1.5" style={{ color: "var(--text-secondary)" }}>
                    <Shuffle className="w-3.5 h-3.5" style={{ color: "var(--brand)" }} /> Práctica aleatoria
                </span>
                <div className="flex rounded-md border overflow-hidden" style={{ borderColor: "var(--border)" }}>
                    {[{ id: "count", label: "Cantidad" }, { id: "percent", label: "Porcentaje" }].map((m) => (
                        <button
                            key={m.id}
                            onClick={() => setRandomMode(m.id)}
                            data-testid={`qbank-random-mode-${m.id}`}
                            className="px-2.5 py-1 text-xs font-medium"
                            style={{
                                background: randomMode === m.id ? "var(--brand)" : "white",
                                color: randomMode === m.id ? "white" : "var(--text-secondary)",
                            }}
                        >
                            {m.label}
                        </button>
                    ))}
                </div>
                <Input
                    type="number"
                    min={1}
                    max={randomMode === "percent" ? 100 : SESSION_CAP}
                    value={randomValue}
                    onChange={(e) => setRandomValue(Math.max(1, parseInt(e.target.value || "1", 10)))}
                    disabled={!randomMode}
                    data-testid="qbank-random-value"
                    className="w-20 h-8 text-sm"
                />
                {randomMode === "percent" && <span className="text-xs" style={{ color: "var(--text-muted)" }}>%</span>}
                <span className="text-xs" style={{ color: "var(--text-muted)" }}>de {total} que coinciden</span>
                <button
                    onClick={practiceRandom}
                    disabled={!randomMode || practicing || total === 0}
                    data-testid="qbank-random-practice"
                    className="ml-auto btn-primary flex items-center gap-2 text-xs disabled:opacity-50"
                >
                    {practicing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Shuffle className="w-3.5 h-3.5" />}
                    {randomMode === "percent" ? `Practicar ${randomValue}% aleatorias` : `Practicar ${randomValue} aleatorias`}
                </button>
            </div>

            {/* Barra de acción de selección */}
            {hasSelection && (
                <div
                    className="card-organic p-3 mb-4 flex flex-wrap items-center gap-3"
                    style={{ borderColor: "var(--brand)", background: "#fdf1ea" }}
                    data-testid="qbank-selection-bar"
                >
                    <span className="text-sm font-medium" style={{ color: "var(--brand)" }} data-testid="qbank-selection-count">
                        {selectAllFiltered
                            ? `Todas las que coinciden (${total})`
                            : `${selectedIds.size} ${selectedIds.size === 1 ? "seleccionada" : "seleccionadas"}`}
                    </span>
                    {canSelectAllFiltered && (
                        <button
                            onClick={() => { setSelectAllFiltered(true); }}
                            data-testid="qbank-select-all-filtered"
                            className="text-xs hover:underline"
                            style={{ color: "var(--brand)" }}
                        >
                            Seleccionadas las {items.length} de esta página. Seleccionar las {total} que coinciden con el filtro.
                        </button>
                    )}
                    <div className="ml-auto flex items-center gap-2">
                        <button
                            onClick={practiceSelection}
                            disabled={practicing}
                            data-testid="qbank-practice-selected"
                            className="btn-primary flex items-center gap-2 text-xs disabled:opacity-50"
                        >
                            {practicing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
                            Practicar selección
                        </button>
                        <button
                            onClick={clearSelection}
                            data-testid="qbank-clear-selection"
                            className="text-xs flex items-center gap-1 px-2 py-1.5 rounded hover:bg-white"
                            style={{ color: "var(--text-secondary)" }}
                        >
                            <X className="w-3.5 h-3.5" /> Limpiar
                        </button>
                    </div>
                </div>
            )}

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
                <>
                    {/* Cabecera de lista: seleccionar toda la página (tri-estado) */}
                    <div className="flex items-center gap-2 mb-2 px-1">
                        <Checkbox
                            checked={headerCheck}
                            onCheckedChange={toggleSelectPage}
                            data-testid="qbank-select-page"
                            aria-label="Seleccionar todas las de esta página"
                        />
                        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                            {selectedIds.size > 0 ? `${selectedIds.size} seleccionadas` : "Seleccionar todas las de esta página"}
                        </span>
                    </div>
                    <div className="space-y-3">
                        {items.map((q) => (
                            <QuestionCard
                                key={q.id}
                                q={q}
                                selected={selectedIds.has(q.id)}
                                onToggleSelect={toggleSelect}
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
                </>
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

            {/* Alta manual: destino precargado desde los filtros activos. El PDF
                filtrado solo se preselecciona si es un id real (no el centinela "none"). */}
            <CreateQuestionDialog
                open={createOpen}
                onClose={() => setCreateOpen(false)}
                defaultSubjectId={subjectId || null}
                defaultTopicId={topicId || null}
                defaultPdfId={pdfId && pdfId !== "none" ? pdfId : null}
                onCreated={() => load()}
            />

            {/* Stepper "Nuevo tema" (última opción del desplegable de temas).
                preselectedSubjectId solo si hay una asignatura filtrada (no "Todas"). */}
            <CreateTopicStepper
                open={topicStepperOpen}
                onOpenChange={setTopicStepperOpen}
                subjects={subjects}
                preselectedSubjectId={subjectId || null}
                onComplete={handleTopicCreated}
            />
        </div>
    );
}

function QuestionCard({ q, selected, onToggleSelect, subjectName, topicName, pdfLabel, onFav, onDiff, onDelete, onEdit, onGoTopic }) {
    const answered = q.times_answered || 0;
    const acc = answered ? Math.round((q.times_correct / answered) * 100) : null;
    return (
        <div
            className="card-organic p-5 fade-up"
            data-testid={`qbank-question-${q.id}`}
            style={selected ? { borderColor: "var(--brand)", background: "#fff9f5" } : undefined}
        >
            <div className="flex items-start justify-between gap-3 mb-2">
                <div className="flex items-center gap-2 flex-wrap min-w-0">
                    <Checkbox
                        checked={selected}
                        onCheckedChange={() => onToggleSelect(q.id)}
                        data-testid={`qbank-select-${q.id}`}
                        aria-label="Seleccionar pregunta"
                    />
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
