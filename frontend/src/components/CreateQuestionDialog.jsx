import { useEffect, useMemo, useState } from "react";
import { X, Loader2, Check, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { createQuestion, listSubjects, listTopics, getTopicPdfs } from "@/lib/api";

// Alta MANUAL de una pregunta (sin IA, sin cuota). Reutiliza POST /questions.
// Dos puntos de entrada:
//  - Banco: destino editable (asignatura → tema → PDF), precargado desde filtros.
//  - TopicDetail: modo "tema fijo" (fixedTopic) — el tema se muestra pero no se
//    edita; el PDF de origen sí es elegible entre los del tema.
// Props: { open, onClose, onCreated, defaultSubjectId, defaultTopicId,
//          defaultPdfId, fixedTopic }
const TYPES = [
    { id: "mcq", label: "Opción múltiple" },
    { id: "tf", label: "Verdadero/Falso" },
    { id: "dev", label: "Desarrollo" },
];
const MIN_OPTS = 2;
const MAX_OPTS = 5;

export default function CreateQuestionDialog({
    open,
    onClose,
    onCreated,
    defaultSubjectId = null,
    defaultTopicId = null,
    defaultPdfId = null,
    fixedTopic = false,
}) {
    // Catálogos de destino.
    const [subjects, setSubjects] = useState([]);
    const [topics, setTopics] = useState([]);
    const [topicPdfs, setTopicPdfs] = useState([]);

    // Destino.
    const [subjectId, setSubjectId] = useState("");
    const [topicId, setTopicId] = useState("");
    const [pdfId, setPdfId] = useState("");

    // Contenido.
    const [type, setType] = useState("mcq");
    const [text, setText] = useState("");
    const [options, setOptions] = useState(["", "", "", ""]);
    const [correctIndex, setCorrectIndex] = useState(0);
    const [tfCorrect, setTfCorrect] = useState(0); // 0 = Verdadero, 1 = Falso
    const [modelAnswer, setModelAnswer] = useState("");
    const [explanation, setExplanation] = useState("");

    const [saving, setSaving] = useState(false);

    // Reset del CONTENIDO (conserva destino + tipo). Usado tras "crear otra".
    const resetContent = () => {
        setText("");
        setOptions(["", "", "", ""]);
        setCorrectIndex(0);
        setTfCorrect(0);
        setModelAnswer("");
        setExplanation("");
    };

    // Al abrir: carga catálogos y fija el destino desde los defaults.
    useEffect(() => {
        if (!open) return;
        setType("mcq");
        resetContent();
        setSubjectId(defaultSubjectId || "");
        setTopicId(defaultTopicId || "");
        setPdfId(defaultPdfId || "");
        Promise.all([listSubjects(), listTopics()])
            .then(([s, t]) => { setSubjects(s); setTopics(t); })
            .catch(() => toast.error("No se pudieron cargar asignaturas y temas"));
    }, [open, defaultSubjectId, defaultTopicId, defaultPdfId]);

    // Temas de la asignatura elegida (o todos si no hay asignatura).
    const topicsForSubject = useMemo(
        () => (subjectId ? topics.filter((t) => t.subject_id === subjectId) : topics),
        [topics, subjectId]
    );

    // Si solo llegó el tema (sin asignatura), deriva la asignatura del tema.
    useEffect(() => {
        if (!open || subjectId || !topicId || topics.length === 0) return;
        const t = topics.find((x) => x.id === topicId);
        if (t?.subject_id) setSubjectId(t.subject_id);
    }, [open, subjectId, topicId, topics]);

    // Al cambiar de asignatura, si el tema ya no pertenece, límpialo (salvo tema fijo).
    useEffect(() => {
        if (fixedTopic) return;
        if (topicId && subjectId && !topicsForSubject.some((t) => t.id === topicId)) {
            setTopicId("");
        }
    }, [subjectId, topicId, topicsForSubject, fixedTopic]);

    // Carga los PDFs del tema elegido (para el selector de PDF de origen).
    useEffect(() => {
        if (!open || !topicId) { setTopicPdfs([]); return; }
        let alive = true;
        getTopicPdfs(topicId)
            .then((pdfs) => {
                if (!alive) return;
                setTopicPdfs(pdfs);
                // Descartar el PDF elegido si no pertenece al tema cargado.
                setPdfId((cur) => (cur && pdfs.some((p) => p.id === cur) ? cur : ""));
            })
            .catch(() => { if (alive) setTopicPdfs([]); });
        return () => { alive = false; };
    }, [open, topicId]);

    const topicName = useMemo(
        () => topics.find((t) => t.id === topicId)?.name || "",
        [topics, topicId]
    );

    if (!open) return null;

    const isMcq = type === "mcq";
    const isTf = type === "tf";
    const isDev = type === "dev";

    const setOption = (i, val) => setOptions((prev) => prev.map((o, k) => (k === i ? val : o)));
    const addOption = () => setOptions((prev) => (prev.length >= MAX_OPTS ? prev : [...prev, ""]));
    const removeOption = (i) =>
        setOptions((prev) => {
            if (prev.length <= MIN_OPTS) return prev;
            const next = prev.filter((_, k) => k !== i);
            // Reajusta el índice de la correcta para no quedar fuera de rango.
            setCorrectIndex((ci) => (i === ci ? 0 : i < ci ? ci - 1 : ci));
            return next;
        });

    // Devuelve el payload validado, o null (con toast) si algo falla.
    const buildPayload = () => {
        const q = text.trim();
        if (!q) { toast.error("El enunciado no puede estar vacío"); return null; }
        if (!topicId) { toast.error("Elige un tema de destino"); return null; }

        const base = {
            topic_id: topicId,
            question_type: type,
            question_text: q,
            explanation: explanation.trim() || undefined,
            pdf_source_id: pdfId || undefined,
        };

        if (isDev) {
            const model = modelAnswer.trim();
            if (!model) { toast.error("La respuesta modelo es obligatoria en desarrollo"); return null; }
            return { ...base, dev_answer: model };
        }
        if (isTf) {
            return { ...base, correct_answer: tfCorrect };
        }
        // mcq
        const opts = options.map((o) => o.trim());
        if (opts.length < MIN_OPTS || opts.length > MAX_OPTS) {
            toast.error(`Una pregunta de opción múltiple necesita entre ${MIN_OPTS} y ${MAX_OPTS} opciones`);
            return null;
        }
        if (opts.some((o) => !o)) { toast.error("Las opciones no pueden estar vacías"); return null; }
        const lower = opts.map((o) => o.toLowerCase());
        if (new Set(lower).size !== lower.length) { toast.error("Hay opciones duplicadas"); return null; }
        if (!(correctIndex >= 0 && correctIndex < opts.length)) {
            toast.error("Marca cuál es la opción correcta"); return null;
        }
        return { ...base, options: opts, correct_answer: correctIndex, num_options: opts.length };
    };

    const submit = async (keepOpen) => {
        const payload = buildPayload();
        if (!payload) return;
        setSaving(true);
        try {
            const created = await createQuestion(payload);
            toast.success("Pregunta creada");
            onCreated?.(created);
            if (keepOpen) {
                resetContent(); // conserva tipo + destino (asignatura/tema/PDF)
            } else {
                onClose();
            }
        } catch (err) {
            toast.error(err?.response?.data?.detail || "No se pudo crear la pregunta");
            // No cerramos: el usuario corrige y reintenta.
        } finally {
            setSaving(false);
        }
    };

    const selectCls = "w-full border rounded-md px-3 py-2 text-sm bg-white";
    const selectStyle = { borderColor: "var(--border)" };

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4 overflow-y-auto"
            style={{ background: "rgba(35,33,31,0.45)" }}
            data-testid="create-question-dialog"
        >
            <div className="card-organic w-full max-w-lg fade-up my-8" style={{ background: "white" }}>
                <div className="flex items-center justify-between p-5 border-b" style={{ borderColor: "var(--border)" }}>
                    <div>
                        <h3 className="font-display text-xl font-bold">Crear pregunta</h3>
                        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                            A mano, sin IA. No consume tu cuota de generación.
                        </p>
                    </div>
                    <button onClick={onClose} disabled={saving} data-testid="create-question-close" className="p-1.5 rounded-md hover:bg-[color:var(--bg-secondary)]">
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <form onSubmit={(e) => { e.preventDefault(); submit(false); }} className="p-5 space-y-4">
                    {/* Tipo */}
                    <div>
                        <label className="label-eyebrow block mb-1.5">Tipo</label>
                        <div className="flex gap-2">
                            {TYPES.map((t) => (
                                <button
                                    key={t.id}
                                    type="button"
                                    onClick={() => setType(t.id)}
                                    disabled={saving}
                                    data-testid={`create-question-type-${t.id}`}
                                    className="flex-1 px-3 py-2 rounded-md text-sm font-medium border"
                                    style={{
                                        borderColor: type === t.id ? "var(--brand)" : "var(--border)",
                                        background: type === t.id ? "#fdf1ea" : "white",
                                        color: type === t.id ? "var(--brand)" : "var(--text-secondary)",
                                    }}
                                >
                                    {t.label}
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Destino */}
                    {fixedTopic ? (
                        <div>
                            <label className="label-eyebrow block mb-1.5">Tema</label>
                            <div className="text-sm px-3 py-2 rounded-md border" style={{ borderColor: "var(--border)", background: "var(--bg-secondary)" }} data-testid="create-question-fixed-topic">
                                {topicName || "Tema actual"}
                            </div>
                        </div>
                    ) : (
                        <div className="grid grid-cols-2 gap-2">
                            <div>
                                <label className="label-eyebrow block mb-1.5">Asignatura</label>
                                <select value={subjectId} onChange={(e) => setSubjectId(e.target.value)} disabled={saving} className={selectCls} style={selectStyle} data-testid="create-question-subject">
                                    <option value="">Todas</option>
                                    {subjects.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                                </select>
                            </div>
                            <div>
                                <label className="label-eyebrow block mb-1.5">Tema</label>
                                <select value={topicId} onChange={(e) => setTopicId(e.target.value)} disabled={saving} className={selectCls} style={selectStyle} data-testid="create-question-topic">
                                    <option value="">Elige un tema…</option>
                                    {topicsForSubject.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                                </select>
                            </div>
                        </div>
                    )}

                    {/* PDF de origen (opcional) */}
                    {topicPdfs.length > 0 && (
                        <div>
                            <label className="label-eyebrow block mb-1.5">
                                PDF de origen <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>(opcional)</span>
                            </label>
                            <select value={pdfId} onChange={(e) => setPdfId(e.target.value)} disabled={saving} className={selectCls} style={selectStyle} data-testid="create-question-pdf">
                                <option value="">Sin PDF de origen</option>
                                {topicPdfs.map((p) => <option key={p.id} value={p.id}>{p.filename}</option>)}
                            </select>
                        </div>
                    )}

                    {/* Enunciado */}
                    <div>
                        <label className="label-eyebrow block mb-1.5">Enunciado</label>
                        <textarea
                            value={text}
                            onChange={(e) => setText(e.target.value)}
                            disabled={saving}
                            rows={3}
                            data-testid="create-question-text"
                            className="w-full border rounded-md px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1"
                            style={{ borderColor: "var(--border)" }}
                        />
                    </div>

                    {/* MCQ: opciones */}
                    {isMcq && (
                        <div>
                            <label className="label-eyebrow block mb-1.5">Opciones (marca la correcta)</label>
                            <div className="space-y-2">
                                {options.map((opt, i) => (
                                    <div key={i} className="flex items-center gap-2">
                                        <button
                                            type="button"
                                            onClick={() => setCorrectIndex(i)}
                                            disabled={saving}
                                            data-testid={`create-question-correct-${i}`}
                                            title="Marcar como correcta"
                                            className="w-6 h-6 rounded-full flex items-center justify-center shrink-0 border"
                                            style={{
                                                borderColor: correctIndex === i ? "var(--brand)" : "var(--border)",
                                                background: correctIndex === i ? "var(--brand)" : "white",
                                            }}
                                        >
                                            {correctIndex === i && <Check className="w-3.5 h-3.5 text-white" />}
                                        </button>
                                        <input
                                            type="text"
                                            value={opt}
                                            onChange={(e) => setOption(i, e.target.value)}
                                            disabled={saving}
                                            placeholder={`Opción ${String.fromCharCode(65 + i)}`}
                                            data-testid={`create-question-option-${i}`}
                                            className="flex-1 border rounded-md px-3 py-2 text-sm"
                                            style={{ borderColor: "var(--border)" }}
                                        />
                                        <button
                                            type="button"
                                            onClick={() => removeOption(i)}
                                            disabled={saving || options.length <= MIN_OPTS}
                                            data-testid={`create-question-remove-option-${i}`}
                                            className="p-1.5 rounded hover:bg-[color:var(--bg-secondary)] disabled:opacity-30 shrink-0"
                                            aria-label="Quitar opción"
                                        >
                                            <Trash2 className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
                                        </button>
                                    </div>
                                ))}
                            </div>
                            {options.length < MAX_OPTS && (
                                <button
                                    type="button"
                                    onClick={addOption}
                                    disabled={saving}
                                    data-testid="create-question-add-option"
                                    className="mt-2 text-sm flex items-center gap-1 px-2 py-1 rounded hover:bg-[color:var(--bg-secondary)]"
                                    style={{ color: "var(--brand)" }}
                                >
                                    <Plus className="w-4 h-4" /> Añadir opción
                                </button>
                            )}
                        </div>
                    )}

                    {/* TF: correcta */}
                    {isTf && (
                        <div>
                            <label className="label-eyebrow block mb-1.5">Respuesta correcta</label>
                            <div className="flex gap-2">
                                {["Verdadero", "Falso"].map((lbl, i) => (
                                    <button
                                        key={lbl}
                                        type="button"
                                        onClick={() => setTfCorrect(i)}
                                        disabled={saving}
                                        data-testid={`create-question-tf-${i}`}
                                        className="flex-1 px-3 py-2 rounded-md text-sm font-medium border"
                                        style={{
                                            borderColor: tfCorrect === i ? "var(--brand)" : "var(--border)",
                                            background: tfCorrect === i ? "#fdf1ea" : "white",
                                            color: tfCorrect === i ? "var(--brand)" : "var(--text-secondary)",
                                        }}
                                    >
                                        {lbl}
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* DEV: respuesta modelo */}
                    {isDev && (
                        <div>
                            <label className="label-eyebrow block mb-1.5">Respuesta modelo</label>
                            <textarea
                                value={modelAnswer}
                                onChange={(e) => setModelAnswer(e.target.value)}
                                disabled={saving}
                                rows={4}
                                data-testid="create-question-model-answer"
                                className="w-full border rounded-md px-3 py-2 text-sm resize-none"
                                style={{ borderColor: "var(--border)" }}
                            />
                        </div>
                    )}

                    {/* Explicación */}
                    <div>
                        <label className="label-eyebrow block mb-1.5">
                            Explicación <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>(opcional)</span>
                        </label>
                        <textarea
                            value={explanation}
                            onChange={(e) => setExplanation(e.target.value)}
                            disabled={saving}
                            rows={2}
                            data-testid="create-question-explanation"
                            className="w-full border rounded-md px-3 py-2 text-sm resize-none"
                            style={{ borderColor: "var(--border)" }}
                        />
                    </div>

                    <div className="flex flex-col sm:flex-row gap-2 pt-2">
                        <button type="button" onClick={onClose} disabled={saving} className="px-4 py-2.5 rounded-md border font-medium text-sm hover:bg-[color:var(--bg-secondary)]" style={{ borderColor: "var(--border)" }}>
                            Cancelar
                        </button>
                        <button
                            type="button"
                            onClick={() => submit(true)}
                            disabled={saving}
                            data-testid="create-question-save-another"
                            className="flex-1 px-4 py-2.5 rounded-md border font-medium text-sm hover:bg-[color:var(--bg-secondary)] disabled:opacity-60"
                            style={{ borderColor: "var(--border)" }}
                        >
                            Guardar y crear otra
                        </button>
                        <button type="submit" disabled={saving} data-testid="create-question-save" className="btn-primary flex-1 flex items-center justify-center gap-2 text-sm">
                            {saving ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</> : "Guardar"}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
