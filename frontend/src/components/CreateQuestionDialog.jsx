import { useEffect, useMemo, useState } from "react";
import { X, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { createQuestion, listSubjects, listTopics, getTopicPdfs } from "@/lib/api";
import QuestionFields, { MIN_OPTS, MAX_OPTS } from "@/components/QuestionFields";

// Alta MANUAL de una pregunta (sin IA, sin cuota). Reutiliza POST /questions.
// Dos puntos de entrada:
//  - Banco: destino editable (asignatura → tema → PDF), precargado desde filtros.
//  - TopicDetail: modo "tema fijo" (fixedTopic) — el tema se muestra pero no se
//    edita; el PDF de origen sí es elegible entre los del tema.
// Props: { open, onClose, onCreated, defaultSubjectId, defaultTopicId,
//          defaultPdfId, fixedTopic }

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
    // Índice de la correcta, compartido por mcq y tf (en tf: 0=Verdadero, 1=Falso).
    const [correctIndex, setCorrectIndex] = useState(0);
    const [modelAnswer, setModelAnswer] = useState("");
    const [explanation, setExplanation] = useState("");

    const [saving, setSaving] = useState(false);

    // Reset del CONTENIDO (conserva destino + tipo). Usado tras "crear otra".
    const resetContent = () => {
        setText("");
        setOptions(["", "", "", ""]);
        setCorrectIndex(0);
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

    // mcq y tf comparten `correctIndex`. En V/F solo 0 y 1 son válidos, así que
    // al cambiar de tipo se recorta (si venías de una mcq con la correcta en la
    // 3ª opción, quedaría fuera de rango).
    const changeType = (next) => {
        setType(next);
        if (next === "tf" && correctIndex > 1) setCorrectIndex(0);
    };

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
            return { ...base, correct_answer: correctIndex };
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

                    <QuestionFields
                        questionType={type}
                        onQuestionTypeChange={changeType}
                        options={options}
                        onOptionsChange={setOptions}
                        correctIndex={correctIndex}
                        onCorrectIndexChange={setCorrectIndex}
                        modelAnswer={modelAnswer}
                        onModelAnswerChange={setModelAnswer}
                        explanation={explanation}
                        onExplanationChange={setExplanation}
                        disabled={saving}
                        testIdPrefix="create-question"
                    />

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
