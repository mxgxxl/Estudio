import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import {
    Clock, Sparkles, Flame, Brain, Star, ArrowLeft,
    Play, Loader2, AlertCircle, Sliders, Layers, Info, FileText, X, Plus,
} from "lucide-react";
import { toast } from "sonner";
import { listSubjects, listSubjectTopics, quizStart, quizAvailable, getTopicPdfs } from "@/lib/api";
import PdfPicker from "@/components/PdfPicker";

// Dos ejes independientes: COMPORTAMIENTO (cómo se juega) × SELECCIÓN (qué entra).
const BEHAVIOR_OPTS = [
    { id: "practice", label: "Práctica", icon: Sparkles, desc: "Feedback al instante, sin tiempo",
      info: "Ves si aciertas nada más responder, con la explicación. Sin cronómetro. Para aprender sin presión." },
    { id: "exam", label: "Examen", icon: Clock, desc: "Con cronómetro y nota al final",
      info: "Simulacro: cronómetro, sin feedback hasta enviar, nota /10 con penalización. Puedes dejar preguntas en blanco." },
];
const SELECTION_OPTS = [
    { id: "all", label: "Todas", icon: Layers, desc: "Todo el temario elegido",
      info: "Todas las preguntas de las asignaturas y temas seleccionados." },
    { id: "errors", label: "Errores", icon: Flame, desc: "Las que has fallado antes",
      info: "Solo preguntas con más fallos que aciertos en tu historial." },
    { id: "srs", label: "Repaso", icon: Brain, desc: "Las que toca repasar hoy",
      info: "Repetición espaciada: preguntas cuya fecha de repaso ya venció. Solo el modo Repaso actualiza esos intervalos." },
    { id: "favorites", label: "Favoritas", icon: Star, desc: "Las marcadas con estrella",
      info: "Solo las preguntas que marcaste como favoritas." },
];
// Mensaje de vacío por selección (para el gating sin "botón muerto").
const SELECTION_EMPTY = {
    errors: "No tienes preguntas falladas en esta selección.",
    srs: "No tienes preguntas por repasar hoy en esta selección.",
    favorites: "No tienes preguntas favoritas en esta selección.",
};
// Fallback de marcadores/enlaces viejos con ?mode=  → ejes.
const MODE_TO_AXES = {
    exam: { behavior: "exam", selection: "all" },
    practice: { behavior: "practice", selection: "all" },
    errors: { behavior: "practice", selection: "errors" },
    srs: { behavior: "practice", selection: "srs" },
    favorites: { behavior: "practice", selection: "favorites" },
};

// Tarjeta de opción de un eje, con detalle inline colapsable (patrón de la app;
// sin tooltip/popover nuevos).
function OptionCard({ opt, active, onSelect, testid }) {
    const [open, setOpen] = useState(false);
    const Icon = opt.icon;
    return (
        <div className="rounded-md border transition-all"
            style={{ borderColor: active ? "var(--brand)" : "var(--border)", background: active ? "#fdf1ea" : "white" }}>
            <div className="flex items-start">
                <button onClick={onSelect} data-testid={testid} className="flex-1 p-3 text-left">
                    <Icon className="w-5 h-5 mb-1.5" style={{ color: active ? "var(--brand)" : "var(--text-secondary)" }} />
                    <div className="font-display font-bold text-sm">{opt.label}</div>
                    <div className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>{opt.desc}</div>
                </button>
                <button onClick={() => setOpen((o) => !o)} title="Más info" data-testid={`${testid}-info`}
                    className="p-2 shrink-0 hover:opacity-70" style={{ color: "var(--text-muted)" }}>
                    <Info className="w-3.5 h-3.5" />
                </button>
            </div>
            {open && (
                <div className="text-xs px-3 pb-3" style={{ color: "var(--text-secondary)" }}>{opt.info}</div>
            )}
        </div>
    );
}

// Tarjeta seleccionable reutilizable (asignaturas y temas): dot de color opcional
// + nombre + contador. Estado activo con el coral de la app (`--brand`), igual que
// los temas; hover sutil en el borde. El borde va por clase (no inline) para que
// el :hover funcione. La selección multi la sigue gestionando el padre.
function SelectableCard({ name, count, color, active, onClick, testid }) {
    return (
        <button
            type="button"
            onClick={onClick}
            data-testid={testid}
            className={`p-3 rounded-md border flex items-center justify-between gap-2 transition-all text-left cursor-pointer ${
                active
                    ? "border-[color:var(--brand)] bg-[#fdf1ea]"
                    : "border-[color:var(--border)] bg-white hover:border-[color:var(--brand)]"
            }`}
        >
            <span className="flex items-center gap-2 min-w-0">
                {color && (
                    <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: color }} />
                )}
                <span className="font-medium text-sm truncate">{name}</span>
            </span>
            <span className="text-xs font-mono px-1.5 py-0.5 rounded-sm shrink-0"
                style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}>
                {count}
            </span>
        </button>
    );
}

// Ghost card "+ Nueva …": última tarjeta del grid, borde punteado sin fondo,
// para el futuro stepper de creación. onClick aún sin cablear (TODO).
function GhostCard({ label, onClick, testid }) {
    return (
        <button
            type="button"
            onClick={onClick}
            data-testid={testid}
            className="p-3 rounded-md border border-dashed flex items-center justify-center gap-1.5 transition-all cursor-pointer border-[color:var(--border)] bg-transparent hover:border-[color:var(--brand)] hover:bg-[color:var(--bg-secondary)]"
            style={{ color: "var(--text-secondary)" }}
        >
            <Plus className="w-4 h-4 shrink-0" />
            <span className="text-sm font-medium">{label}</span>
        </button>
    );
}

const QTYPES = [
    { id: "any", label: "Cualquier tipo" },
    { id: "mcq", label: "Opción múltiple" },
    { id: "tf", label: "Verdadero/Falso" },
    { id: "dev", label: "Desarrollo (IA evalúa)" },
];

// Preguntas disponibles en un tema para el tipo elegido. "any" = todas; en otro
// caso usa el desglose counts_by_type que ahora devuelve el backend (con
// fallback a 0 si un tema aún no lo trae).
const availOf = (t, questionType) =>
    questionType === "any"
        ? (t.question_count || 0)
        : ((t.counts_by_type || {})[questionType] || 0);

const PENALTIES = [
    { id: 0, label: "Sin penalización" },
    { id: 1, label: "1 mal = −1 bien" },
    { id: 2, label: "2 mal = −1 bien" },
    { id: 3, label: "3 mal = −1 bien" },
    { id: 4, label: "4 mal = −1 bien" },
];

// Panel de distribución de preguntas por tema
function TopicDistribution({ topics, topicQuestions, setTopicQuestions, totalQuestions, questionType }) {
    const total = Object.values(topicQuestions).reduce((a, b) => a + b, 0);
    const diff = totalQuestions - total;

    const setEqual = () => {
        const base = Math.floor(totalQuestions / topics.length);
        const remainder = totalQuestions % topics.length;
        const next = {};
        topics.forEach((t, i) => { next[t.id] = base + (i < remainder ? 1 : 0); });
        setTopicQuestions(next);
    };

    const setByWeight = () => {
        const totalQ = topics.reduce((a, t) => a + availOf(t, questionType), 0);
        if (!totalQ) return setEqual();
        let assigned = 0;
        const next = {};
        topics.forEach((t, i) => {
            if (i === topics.length - 1) {
                next[t.id] = Math.max(1, totalQuestions - assigned);
            } else {
                const n = Math.max(1, Math.round((availOf(t, questionType) / totalQ) * totalQuestions));
                next[t.id] = n;
                assigned += n;
            }
        });
        setTopicQuestions(next);
    };

    return (
        <div className="rounded-md border overflow-hidden" style={{ borderColor: "var(--border)" }}>
            <div className="px-4 py-3 flex items-center justify-between" style={{ background: "var(--bg-secondary)" }}>
                <div className="flex items-center gap-2">
                    <Sliders className="w-4 h-4" style={{ color: "var(--brand)" }} />
                    <span className="text-sm font-medium">Distribución por tema</span>
                </div>
                <div className="flex gap-2">
                    <button onClick={setEqual} className="text-xs px-2 py-1 rounded border hover:bg-white transition-colors" style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}>
                        Repartir igual
                    </button>
                    <button onClick={setByWeight} className="text-xs px-2 py-1 rounded border hover:bg-white transition-colors" style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}>
                        Por peso
                    </button>
                </div>
            </div>
            <div className="divide-y" style={{ borderColor: "var(--border)" }}>
                {topics.map((t) => {
                    const val = topicQuestions[t.id] ?? 0;
                    const pct = totalQuestions > 0 ? Math.round((val / totalQuestions) * 100) : 0;
                    const available = availOf(t, questionType);
                    return (
                        <div key={t.id} className="px-4 py-3">
                            <div className="flex items-center justify-between mb-2">
                                <span className="text-sm font-medium truncate mr-3">{t.name}</span>
                                <div className="flex items-center gap-2 shrink-0">
                                    <span className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                                        {pct}%
                                    </span>
                                    <div className="flex items-center gap-1">
                                        <button
                                            onClick={() => setTopicQuestions(p => ({ ...p, [t.id]: Math.max(0, (p[t.id] ?? 0) - 1) }))}
                                            className="w-6 h-6 rounded border flex items-center justify-center text-sm font-bold hover:bg-[color:var(--bg-secondary)]"
                                            style={{ borderColor: "var(--border)" }}
                                        >−</button>
                                        <input
                                            type="number"
                                            min={0}
                                            max={available}
                                            value={val}
                                            onChange={e => {
                                                const n = Math.max(0, Math.min(available, parseInt(e.target.value) || 0));
                                                setTopicQuestions(p => ({ ...p, [t.id]: n }));
                                            }}
                                            className="w-12 text-center border rounded text-sm py-0.5 font-mono"
                                            style={{ borderColor: "var(--border)" }}
                                        />
                                        <button
                                            onClick={() => setTopicQuestions(p => ({ ...p, [t.id]: Math.min(available, (p[t.id] ?? 0) + 1) }))}
                                            className="w-6 h-6 rounded border flex items-center justify-center text-sm font-bold hover:bg-[color:var(--bg-secondary)]"
                                            style={{ borderColor: "var(--border)" }}
                                        >+</button>
                                    </div>
                                    <span className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                                        /{available}
                                    </span>
                                </div>
                            </div>
                            <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "var(--bg-secondary)" }}>
                                <div
                                    className="h-full rounded-full transition-all"
                                    style={{
                                        width: `${available > 0 ? Math.min(100, (val / available) * 100) : 0}%`,
                                        background: "var(--brand)"
                                    }}
                                />
                            </div>
                        </div>
                    );
                })}
            </div>
            <div
                className="px-4 py-2.5 flex items-center justify-between text-sm border-t"
                style={{
                    borderColor: "var(--border)",
                    background: diff !== 0 ? "#fdf1ea" : "var(--bg-secondary)"
                }}
            >
                <span style={{ color: "var(--text-secondary)" }}>Total asignado</span>
                <span
                    className="font-mono font-bold"
                    style={{ color: diff !== 0 ? "var(--brand)" : "var(--text-primary)" }}
                >
                    {total} / {totalQuestions}
                    {diff > 0 && <span className="text-xs ml-1">(faltan {diff})</span>}
                    {diff < 0 && <span className="text-xs ml-1">(sobran {Math.abs(diff)})</span>}
                </span>
            </div>
        </div>
    );
}

export default function QuizSetup() {
    const navigate = useNavigate();
    const [params] = useSearchParams();
    const initialSubject = params.get("subject");
    const initialTopic = params.get("topic");
    // Ejes desde la URL; con fallback al ?mode= viejo (marcadores/enlaces antiguos).
    const legacyAxes = MODE_TO_AXES[params.get("mode")] || {};
    const initialBehavior = params.get("behavior") || legacyAxes.behavior || "practice";
    const initialSelection = params.get("selection") || legacyAxes.selection || "all";

    const [subjects, setSubjects] = useState([]);
    const [allTopics, setAllTopics] = useState({});
    const [selectedSubjects, setSelectedSubjects] = useState(new Set(initialSubject ? [initialSubject] : []));
    const [selectedTopics, setSelectedTopics] = useState(new Set(initialTopic ? [initialTopic] : []));
    const [behavior, setBehavior] = useState(initialBehavior);
    const [selection, setSelection] = useState(initialSelection);
    const [questionType, setQuestionType] = useState("any");
    const [numQuestions, setNumQuestions] = useState(15);
    const [timeLimit, setTimeLimit] = useState(15);
    const [penalty, setPenalty] = useState(0);
    // Examen: los blancos también restan (como un fallo). Subordinado a la
    // penalización y solo en Examen; se reinicia si deja de aplicar.
    const [blanksCountAsWrong, setBlanksCountAsWrong] = useState(false);
    const [starting, setStarting] = useState(false);
    const [useDistribution, setUseDistribution] = useState(false);
    const [topicQuestions, setTopicQuestions] = useState({}); // { topicId: numQuestions }
    // Disponibilidad de la SELECCIÓN activa (solo cuando ≠ "all"): del backend.
    const [selectionCount, setSelectionCount] = useState(null);
    const [countLoading, setCountLoading] = useState(false);
    // Filtro de PDFs (solo con scope de un único tema y >1 PDF). Estado LOCAL:
    // no viaja a URL/sessionStorage/marcadores. Todos preseleccionados por defecto.
    const [topicPdfs, setTopicPdfs] = useState([]);
    const [selectedPdfIds, setSelectedPdfIds] = useState(new Set());
    const [pdfDialogOpen, setPdfDialogOpen] = useState(false);

    // El toggle de "blancos restan" solo aplica en Examen con penalización: si deja
    // de cumplirse, lo desmarcamos para no arrastrar un valor obsoleto.
    useEffect(() => {
        if (behavior !== "exam" || penalty === 0) setBlanksCountAsWrong(false);
    }, [behavior, penalty]);

    useEffect(() => {
        listSubjects()
            .then((subs) => {
                setSubjects(subs);
                return Promise.all(subs.map((s) => listSubjectTopics(s.id).then((ts) => ({ id: s.id, topics: ts }))));
            })
            .then((arr) => {
                const map = {};
                arr.forEach((x) => (map[x.id] = x.topics));
                setAllTopics(map);
            })
            .catch(() => toast.error("Error cargando datos"));
    }, []);

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

    const togglePdf = (id) => {
        setSelectedPdfIds((prev) => {
            const next = new Set(prev);
            next.has(id) ? next.delete(id) : next.add(id);
            return next;
        });
    };
    const toggleAllPdfs = () => {
        setSelectedPdfIds((prev) =>
            prev.size === topicPdfs.length ? new Set() : new Set(topicPdfs.map((p) => p.id))
        );
    };

    const visibleTopics = useMemo(() => {
        if (selectedSubjects.size === 0) return Object.values(allTopics).flat();
        return Object.entries(allTopics)
            .filter(([sid]) => selectedSubjects.has(sid))
            .flatMap(([, ts]) => ts);
    }, [allTopics, selectedSubjects]);

    const activeTopics = useMemo(() => {
        if (selectedTopics.size === 0) return visibleTopics;
        return visibleTopics.filter((t) => selectedTopics.has(t.id));
    }, [visibleTopics, selectedTopics]);

    // Disponibles para el TIPO elegido (selección "Todas"): del desglose local
    // counts_by_type (instantáneo). Alimenta también la distribución por tema.
    const totalAvailable = useMemo(
        () => activeTopics.reduce((a, t) => a + availOf(t, questionType), 0),
        [activeTopics, questionType]
    );

    // Scope de un único tema: única situación donde tiene sentido filtrar por PDFs
    // (el control cross-tema vive en el Banco → "Practicar selección").
    const singleTopicId = selectedTopics.size === 1 ? [...selectedTopics][0] : null;

    // Al entrar/salir de single-topic (o cambiar de tema), recarga los PDFs del
    // tema y reinicia la selección a "todos". Fuera de single-topic, limpia.
    useEffect(() => {
        if (!singleTopicId) { setTopicPdfs([]); setSelectedPdfIds(new Set()); return; }
        let cancelled = false;
        getTopicPdfs(singleTopicId)
            .then((pdfs) => {
                if (cancelled) return;
                setTopicPdfs(pdfs);
                setSelectedPdfIds(new Set(pdfs.map((p) => p.id)));
            })
            .catch(() => { if (!cancelled) { setTopicPdfs([]); setSelectedPdfIds(new Set()); } });
        return () => { cancelled = true; };
    }, [singleTopicId]);

    // El filtro de PDFs "actúa" (manda pdf_ids) solo con un subconjunto propio:
    // todos seleccionados = sin filtro (retro-compat, incluye huérfanos);
    // 0 seleccionados = selección vacía (se bloquea aparte, sin llamar al backend).
    const pdfFilterActive =
        !!singleTopicId && topicPdfs.length > 1 &&
        selectedPdfIds.size > 0 && selectedPdfIds.size < topicPdfs.length;
    const pdfEmptySelection =
        !!singleTopicId && topicPdfs.length > 1 && selectedPdfIds.size === 0;
    // "all" se cuenta localmente salvo que haya un subconjunto de PDFs activo (que
    // el conteo local por tema no conoce): entonces también hay que ir al backend.
    const needsBackendCount = selection !== "all" || pdfFilterActive;

    // Al cambiar la SELECCIÓN, el conteo anterior deja de valer → desconocido
    // (null) hasta el primer fetch. Un cambio de FILTRO dentro de la misma
    // selección NO lo resetea, así el botón no se traba en cada tweak.
    useEffect(() => {
        setSelectionCount(null);
    }, [selection]);

    // Para selecciones ≠ "all" (errores/repaso/favoritas) el conteo depende del
    // historial: se pide al backend (debounced) al cambiar selección/filtros/tipo.
    // El conteo previo se mantiene durante el refetch (no se pone a null aquí).
    useEffect(() => {
        if (!needsBackendCount || pdfEmptySelection) { setCountLoading(false); return; }
        let cancelled = false;
        setCountLoading(true);
        const id = setTimeout(() => {
            quizAvailable({
                selection,
                subject_ids: Array.from(selectedSubjects),
                topic_ids: Array.from(selectedTopics),
                question_type: questionType,
                pdf_ids: pdfFilterActive ? [...selectedPdfIds] : [],
            })
                .then((d) => { if (!cancelled) { setSelectionCount(d.count); setCountLoading(false); } })
                .catch(() => { if (!cancelled) { setSelectionCount(0); setCountLoading(false); } });
        }, 300);
        return () => { cancelled = true; clearTimeout(id); };
    }, [selection, selectedSubjects, selectedTopics, questionType, needsBackendCount, pdfEmptySelection, pdfFilterActive, selectedPdfIds]);

    // Disponibilidad efectiva: sin PDFs seleccionados = 0; con conteo de backend
    // (selección ≠ all o subconjunto de PDFs) = ese conteo (0 mientras es
    // desconocido); resto ("all" sin filtro de PDFs) = local por tipo (instantáneo).
    const effectiveAvailable = pdfEmptySelection
        ? 0
        : (needsBackendCount ? (selectionCount ?? 0) : totalAvailable);

    // Ajusta el nº pedido para no exceder lo que hay.
    useEffect(() => {
        if (effectiveAvailable > 0) {
            setNumQuestions((n) => Math.min(Math.max(1, n), effectiveAvailable));
        }
    }, [effectiveAvailable]);

    // Sync distribution when numQuestions or activeTopics change
    useEffect(() => {
        if (!useDistribution || activeTopics.length === 0) return;
        const base = Math.floor(numQuestions / activeTopics.length);
        const remainder = numQuestions % activeTopics.length;
        const next = {};
        activeTopics.forEach((t, i) => { next[t.id] = base + (i < remainder ? 1 : 0); });
        setTopicQuestions(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [useDistribution, numQuestions, activeTopics.length]);

    const handleStart = async () => {
        setStarting(true);
        try {
            let questions = [];

            if (useDistribution && activeTopics.length > 1) {
                // Fetch questions per topic according to distribution
                const results = await Promise.all(
                    activeTopics
                        .filter(t => (topicQuestions[t.id] ?? 0) > 0)
                        .map(t => quizStart({
                            selection,
                            behavior,
                            subject_ids: Array.from(selectedSubjects),
                            topic_ids: [t.id],
                            num_questions: topicQuestions[t.id],
                            time_limit_minutes: null,
                            question_type: questionType,
                        }))
                );
                // Interleave questions from all topics
                const pools = results.map(r => r.questions || []);
                const maxLen = Math.max(...pools.map(p => p.length));
                for (let i = 0; i < maxLen; i++) {
                    pools.forEach(pool => { if (pool[i]) questions.push(pool[i]); });
                }
            } else {
                const data = await quizStart({
                    selection,
                    behavior,
                    subject_ids: Array.from(selectedSubjects),
                    topic_ids: Array.from(selectedTopics),
                    num_questions: numQuestions,
                    time_limit_minutes: behavior === "exam" ? timeLimit : null,
                    question_type: questionType,
                    // Solo con un subconjunto propio de PDFs (todos = sin filtro).
                    ...(pdfFilterActive ? { pdf_ids: [...selectedPdfIds] } : {}),
                });
                questions = data.questions || [];
            }

            if (!questions.length) {
                toast.error("No hay preguntas disponibles");
                return;
            }

            sessionStorage.setItem("current_quiz", JSON.stringify({
                questions,
                selection,
                behavior,
                subject_ids: Array.from(selectedSubjects),
                topic_ids: Array.from(selectedTopics),
                time_limit_seconds: behavior === "exam" ? timeLimit * 60 : null,
                penalty_factor: penalty > 0 ? penalty : null,
                // Valor efectivo (solo Examen + penalización); downstream lo usa tal cual.
                blanks_count_as_wrong: behavior === "exam" && penalty > 0 && blanksCountAsWrong,
                question_type: questionType,
                started_at: Date.now(),
            }));
            navigate("/quiz/run");
        } catch (e) {
            toast.error(e?.response?.data?.detail || "No hay preguntas para esos filtros");
        } finally {
            setStarting(false);
        }
    };

    // La distribución por tema solo tiene sentido con "Todas" (las demás
    // selecciones toman lo que exista, sin reparto manual).
    const showDistributionToggle = selection === "all" && activeTopics.length > 1;
    const distributionTotal = Object.values(topicQuestions).reduce((a, b) => a + b, 0);
    // Solo "espera" (botón bloqueado sin poder empezar) en la PRIMERA comprobación
    // de una selección (conteo aún desconocido). En refetches por cambio de filtro,
    // el botón se rige por el último conteo conocido → no se traba.
    const checkingFirst = needsBackendCount && !pdfEmptySelection && countLoading && selectionCount === null;
    // Exige que la SELECCIÓN activa tenga preguntas (y, si hay distribución manual,
    // que se haya repartido al menos una).
    const canStart = effectiveAvailable > 0 && !checkingFirst
        && (useDistribution && showDistributionToggle ? distributionTotal > 0 : true);

    return (
        <div className="max-w-4xl mx-auto px-5 md:px-8 py-8 md:py-12">
            <Link to="/" data-testid="back-home" className="inline-flex items-center gap-1 text-sm font-medium mb-4 hover:underline" style={{ color: "var(--text-secondary)" }}>
                <ArrowLeft className="w-4 h-4" /> Volver
            </Link>
            <span className="label-eyebrow">Configurar sesión</span>
            <h1 className="font-display text-3xl md:text-4xl font-bold mt-1 mb-8">¿Qué quieres estudiar hoy?</h1>

            {/* Eje 1: cómo estudiar (comportamiento) */}
            <div className="mb-6">
                <span className="label-eyebrow block mb-3">¿Cómo quieres estudiar?</span>
                <div className="grid grid-cols-2 gap-2">
                    {BEHAVIOR_OPTS.map((o) => (
                        <OptionCard key={o.id} opt={o} active={behavior === o.id}
                            onSelect={() => setBehavior(o.id)} testid={`behavior-${o.id}`} />
                    ))}
                </div>
            </div>

            {/* Eje 2: qué preguntas entran (selección) */}
            <div className="mb-8">
                <span className="label-eyebrow block mb-3">¿Qué preguntas quieres?</span>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                    {SELECTION_OPTS.map((o) => (
                        <OptionCard key={o.id} opt={o} active={selection === o.id}
                            onSelect={() => setSelection(o.id)} testid={`selection-${o.id}`} />
                    ))}
                </div>
            </div>

            {/* Asignaturas */}
            <div className="mb-6">
                <div className="flex items-center justify-between mb-3">
                    <span className="label-eyebrow">
                        Asignaturas{" "}
                        {subjects.length > 0 &&
                            (selectedSubjects.size === 0 || selectedSubjects.size === subjects.length
                                ? "(todas)"
                                : `(${selectedSubjects.size} de ${subjects.length})`)}
                    </span>
                    {selectedSubjects.size > 0 && (
                        <button data-testid="clear-subjects" onClick={() => setSelectedSubjects(new Set())}
                            className="text-xs font-medium hover:underline" style={{ color: "var(--brand)" }}>
                            Limpiar
                        </button>
                    )}
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {subjects.map((s) => (
                        <SelectableCard
                            key={s.id}
                            name={s.name}
                            count={s.question_count}
                            color={s.color}
                            active={selectedSubjects.has(s.id)}
                            onClick={() => toggleSubject(s.id)}
                            testid={`subject-toggle-${s.id}`}
                        />
                    ))}
                    <GhostCard
                        label="Nueva asignatura"
                        testid="new-subject-ghost"
                        onClick={() => console.log("TODO: abrir stepper")}
                    />
                </div>
            </div>

            {/* Temas */}
            {visibleTopics.length > 0 && (
                <div className="mb-6">
                    <div className="flex items-center justify-between mb-3">
                        <span className="label-eyebrow">Temas {selectedTopics.size === 0 && "(todos)"}</span>
                        {selectedTopics.size > 0 && (
                            <button data-testid="clear-topics" onClick={() => setSelectedTopics(new Set())}
                                className="text-xs font-medium hover:underline" style={{ color: "var(--brand)" }}>
                                Limpiar
                            </button>
                        )}
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {visibleTopics.map((t) => (
                            <SelectableCard
                                key={t.id}
                                name={t.name}
                                count={t.question_count}
                                active={selectedTopics.has(t.id)}
                                onClick={() => toggleTopic(t.id)}
                                testid={`topic-toggle-${t.id}`}
                            />
                        ))}
                        <GhostCard
                            label="Nuevo tema"
                            testid="new-topic-ghost"
                            onClick={() => console.log("TODO: abrir stepper")}
                        />
                    </div>
                </div>
            )}

            {/* De qué PDFs (solo scope de un único tema con >1 PDF) */}
            {singleTopicId && topicPdfs.length > 1 && (
                <div className="mb-6">
                    <span className="label-eyebrow block mb-3">¿De qué PDFs?</span>
                    <div className="rounded-md border p-3 flex items-center justify-between gap-3"
                        style={{ borderColor: "var(--border)", background: "white" }}>
                        <div className="flex items-center gap-2 min-w-0">
                            <FileText className="w-4 h-4 shrink-0" style={{ color: "var(--text-muted)" }} />
                            <span className="text-sm truncate" data-testid="pdf-filter-summary">
                                {selectedPdfIds.size === topicPdfs.length
                                    ? `Todos los PDFs (${topicPdfs.length})`
                                    : selectedPdfIds.size === 0
                                        ? `Ningún PDF (de ${topicPdfs.length})`
                                        : `${selectedPdfIds.size} de ${topicPdfs.length} PDFs`}
                            </span>
                        </div>
                        <button
                            type="button"
                            onClick={() => setPdfDialogOpen(true)}
                            data-testid="pick-pdfs-btn"
                            className="text-xs font-medium px-3 py-1.5 rounded-md border shrink-0 hover:bg-[color:var(--bg-secondary)]"
                            style={{ borderColor: "var(--brand)", color: "var(--brand)" }}
                        >
                            Elegir PDFs
                        </button>
                    </div>
                </div>
            )}

            {/* Tipo de pregunta */}
            <div className="mb-6">
                <span className="label-eyebrow block mb-3">Tipo de pregunta</span>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                    {QTYPES.map((t) => (
                        <button key={t.id} onClick={() => setQuestionType(t.id)} data-testid={`qtype-${t.id}`}
                            className="px-3 py-2 rounded-md border text-sm font-medium transition-all"
                            style={{ borderColor: questionType === t.id ? "var(--brand)" : "var(--border)", background: questionType === t.id ? "#fdf1ea" : "white" }}
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
                        <button key={p.id} onClick={() => setPenalty(p.id)} data-testid={`penalty-${p.id}`}
                            className="px-3 py-2 rounded-md border text-sm font-medium transition-all"
                            style={{ borderColor: penalty === p.id ? "var(--brand)" : "var(--border)", background: penalty === p.id ? "#fdf1ea" : "white" }}
                        >
                            {p.label}
                        </button>
                    ))}
                </div>
                {penalty > 0 && behavior === "exam" && (
                    <label
                        data-testid="blanks-count-as-wrong"
                        className="mt-2 flex items-center gap-2 text-sm p-2 rounded-md cursor-pointer"
                        style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
                    >
                        <input
                            type="checkbox"
                            checked={blanksCountAsWrong}
                            onChange={(e) => setBlanksCountAsWrong(e.target.checked)}
                            className="accent-[color:var(--brand)]"
                        />
                        Las preguntas en blanco también restan (cuentan como un fallo)
                    </label>
                )}
                {penalty > 0 && (
                    <div className="mt-2 text-xs flex items-start gap-2 p-2 rounded-md"
                        style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}>
                        <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" style={{ color: "var(--brand)" }} />
                        {blanksCountAsWrong && behavior === "exam"
                            ? "Los blancos restan como un fallo (−1 cada N según el ratio); solo suman las acertadas."
                            : "Las preguntas en blanco no penalizan. Solo restan las falladas."}
                    </div>
                )}
            </div>

            {/* Nº preguntas + distribución */}
            <div className="mb-6">
                <div className="flex items-center justify-between mb-2">
                    <span className="label-eyebrow">
                        Nº de preguntas: <span className="font-mono">{numQuestions}</span>{" "}
                        <span className="font-mono" style={{ color: "var(--text-muted)" }}>
                            (disponibles: {checkingFirst ? "…" : effectiveAvailable}{questionType !== "any" ? ` de tipo ${QTYPES.find((x) => x.id === questionType)?.label}` : ""})
                        </span>
                    </span>
                    {showDistributionToggle && (
                        <button
                            onClick={() => setUseDistribution(d => !d)}
                            className="text-xs flex items-center gap-1 px-2.5 py-1.5 rounded-md border transition-all font-medium"
                            style={{
                                borderColor: useDistribution ? "var(--brand)" : "var(--border)",
                                background: useDistribution ? "#fdf1ea" : "white",
                                color: useDistribution ? "var(--brand)" : "var(--text-secondary)",
                            }}
                        >
                            <Sliders className="w-3 h-3" />
                            {useDistribution ? "Distribución activada" : "Distribuir por tema"}
                        </button>
                    )}
                </div>
                <input
                    type="range"
                    min="1"
                    max={Math.max(1, Math.min(effectiveAvailable, 100))}
                    value={numQuestions}
                    onChange={(e) => setNumQuestions(parseInt(e.target.value))}
                    disabled={effectiveAvailable === 0}
                    data-testid="num-questions-range"
                    className="w-full accent-[color:var(--brand)] mb-4 disabled:opacity-50"
                />
                {checkingFirst ? (
                    <div className="text-xs flex items-center gap-2 p-2 rounded-md mb-2"
                        style={{ background: "var(--bg-secondary)", color: "var(--text-muted)" }}
                        data-testid="checking-availability">
                        <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" /> Comprobando disponibilidad…
                    </div>
                ) : effectiveAvailable === 0 && (
                    <div
                        className="text-xs flex items-start gap-2 p-2 rounded-md mb-2"
                        style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
                        data-testid="no-questions-of-type"
                    >
                        <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" style={{ color: "var(--brand)" }} />
                        {pdfEmptySelection
                            ? "Selecciona al menos un PDF."
                            : selection !== "all"
                                ? `${SELECTION_EMPTY[selection]} Prueba otra selección o cambia el tipo/filtros.`
                                : `No hay preguntas${questionType !== "any" ? ` de tipo ${QTYPES.find((x) => x.id === questionType)?.label}` : ""} en la selección. Genera alguna desde el tema o cambia el tipo.`}
                    </div>
                )}

                {/* Panel de distribución */}
                {useDistribution && showDistributionToggle && (
                    <TopicDistribution
                        topics={activeTopics}
                        topicQuestions={topicQuestions}
                        setTopicQuestions={setTopicQuestions}
                        totalQuestions={numQuestions}
                        questionType={questionType}
                    />
                )}
            </div>

            {/* Tiempo (solo examen) */}
            {behavior === "exam" && (
                <div className="mb-8">
                    <span className="label-eyebrow block mb-2">
                        Tiempo: <span className="font-mono">{timeLimit} min</span>
                    </span>
                    <input
                        type="range" min="2" max="120" value={timeLimit}
                        onChange={(e) => setTimeLimit(parseInt(e.target.value))}
                        data-testid="time-limit-range"
                        className="w-full accent-[color:var(--brand)]"
                    />
                </div>
            )}

            <button
                onClick={handleStart}
                disabled={starting || !canStart}
                data-testid="start-quiz-btn"
                className="btn-primary w-full flex items-center justify-center gap-2"
            >
                {starting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                Empezar sesión
            </button>

            {/* Diálogo de selección de PDFs — PdfPicker controlado por el padre
                (selección en vivo y persistente mientras se configura la sesión).
                No reutiliza PdfSelectDialog (su reset-on-open no encaja aquí). */}
            {pdfDialogOpen && (
                <div
                    className="fixed inset-0 z-50 flex items-center justify-center p-4 overflow-y-auto"
                    style={{ background: "rgba(35,33,31,0.45)" }}
                    data-testid="quiz-pdf-dialog"
                >
                    <div className="card-organic w-full max-w-lg fade-up my-8" style={{ background: "white" }}>
                        <div className="flex items-center justify-between p-5 border-b" style={{ borderColor: "var(--border)" }}>
                            <div>
                                <h3 className="font-display text-xl font-bold">¿De qué PDFs?</h3>
                                <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                                    Elige de qué PDFs saldrán las preguntas de esta sesión.
                                </p>
                            </div>
                            <button
                                onClick={() => setPdfDialogOpen(false)}
                                data-testid="quiz-pdf-close"
                                className="p-1.5 rounded-md hover:bg-[color:var(--bg-secondary)]"
                            >
                                <X className="w-5 h-5" />
                            </button>
                        </div>
                        <div className="p-5 space-y-4">
                            <PdfPicker
                                pdfs={topicPdfs}
                                selected={selectedPdfIds}
                                onToggle={togglePdf}
                                onToggleAll={toggleAllPdfs}
                            />
                            <button
                                type="button"
                                onClick={() => setPdfDialogOpen(false)}
                                data-testid="quiz-pdf-done"
                                className="btn-primary w-full text-sm"
                            >
                                Hecho
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
