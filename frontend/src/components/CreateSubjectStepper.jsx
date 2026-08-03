import { useEffect, useRef, useState } from "react";
import {
    X, Loader2, Check, Upload, FileText, Library, Sparkles, ArrowLeft,
} from "lucide-react";
import {
    createSubject, createTopic, addPdfToTopic, linkPdfToTopic,
    unlinkPdfFromTopic, listPdfs, getTopicPdfs, generateFromTopicPdfs,
} from "@/lib/api";
import { usePendingGeneration } from "@/context/PendingGenerationContext";

const errMsg = (err, fallback) => {
    const d = err?.response?.data?.detail;
    return typeof d === "string" ? d : err?.message || fallback;
};

const QTYPES = [
    { id: "mcq", label: "Opción múltiple" },
    { id: "tf", label: "Verdadero/Falso" },
    { id: "dev", label: "Desarrollo" },
];

// Modal de 4 pasos que crea, de una sentada, asignatura → primer tema → adjuntar
// PDFs → generar preguntas. Cada entidad se persiste en cuanto se avanza su paso
// (idempotente: volver "Atrás" no la borra ni la renombra). Si la generación
// sigue en curso al cerrar, se delega en PendingGenerationContext (toast diferido).
export default function CreateSubjectStepper({ open, onClose, onComplete }) {
    const { trackGeneration } = usePendingGeneration();

    const [step, setStep] = useState(1);
    const [busy, setBusy] = useState(false);        // creando asignatura/tema
    const [stepError, setStepError] = useState(null);

    const [subjectName, setSubjectName] = useState("");
    const [subjectId, setSubjectId] = useState(null);
    const [topicName, setTopicName] = useState("");
    const [topicId, setTopicId] = useState(null);

    // Paso 3 — PDFs adjuntos al tema (se adjuntan de inmediato).
    const [attachedPdfs, setAttachedPdfs] = useState([]);
    const [pdfMode, setPdfMode] = useState("upload"); // "upload" | "library"
    const [uploading, setUploading] = useState(false);
    const [library, setLibrary] = useState(null);
    const [libLoading, setLibLoading] = useState(false);
    const [query, setQuery] = useState("");

    // Paso 4 — opciones de generación.
    const [numQuestions, setNumQuestions] = useState(10);
    const [questionType, setQuestionType] = useState("mcq");
    const [numOptions, setNumOptions] = useState(3);

    // Generación.
    const [genStatus, setGenStatus] = useState("idle"); // idle | generating | done | error
    const [genResult, setGenResult] = useState(null);
    const [genError, setGenError] = useState(null);
    const genPromiseRef = useRef(null);

    // Carga la biblioteca al abrir esa pestaña (una vez).
    useEffect(() => {
        if (!open || step !== 3 || pdfMode !== "library" || library) return;
        setLibLoading(true);
        listPdfs()
            .then((pdfs) => setLibrary(pdfs))
            .catch((err) => setStepError(errMsg(err, "No se pudo cargar tu biblioteca")))
            .finally(() => setLibLoading(false));
    }, [open, step, pdfMode, library]);

    if (!open) return null;

    const resetAndClose = () => {
        setStep(1);
        setBusy(false);
        setStepError(null);
        setSubjectName("");
        setSubjectId(null);
        setTopicName("");
        setTopicId(null);
        setAttachedPdfs([]);
        setPdfMode("upload");
        setUploading(false);
        setLibrary(null);
        setQuery("");
        setNumQuestions(10);
        setQuestionType("mcq");
        setNumOptions(3);
        setGenStatus("idle");
        setGenResult(null);
        setGenError(null);
        genPromiseRef.current = null;
        onClose?.();
    };

    // Cierre: si hay una generación en curso, confirmar y delegar la promesa al
    // context (se completa igual, con toast). En cualquier otro estado, cierre
    // limpio: lo ya creado (asignatura/tema) queda como carcasa en el Dashboard.
    const requestClose = () => {
        if (genStatus === "generating") {
            const ok = window.confirm(
                "La generación está en curso. Las preguntas se crearán igualmente. ¿Cerrar?"
            );
            if (!ok) return;
            const p = genPromiseRef.current;
            genPromiseRef.current = null; // el stepper deja de gestionar la promesa
            if (p) trackGeneration(p, { topicName, subjectName, subjectId });
        }
        resetAndClose();
    };

    // Paso 1 → 2: crea la asignatura (solo la primera vez).
    const submitSubject = async () => {
        const name = subjectName.trim();
        if (!name) return;
        setBusy(true);
        setStepError(null);
        try {
            if (!subjectId) {
                const s = await createSubject({ name });
                setSubjectId(s.id);
            }
            setStep(2);
        } catch (err) {
            setStepError(errMsg(err, "No se pudo crear la asignatura"));
        } finally {
            setBusy(false);
        }
    };

    // Paso 2 → 3: crea el primer tema (solo la primera vez).
    const submitTopic = async () => {
        const name = topicName.trim();
        if (!name || !subjectId) return;
        setBusy(true);
        setStepError(null);
        try {
            if (!topicId) {
                const t = await createTopic(subjectId, { name });
                setTopicId(t.id);
            }
            setStep(3);
        } catch (err) {
            setStepError(errMsg(err, "No se pudo crear el tema"));
        } finally {
            setBusy(false);
        }
    };

    const refreshAttached = async () => {
        const pdfs = await getTopicPdfs(topicId);
        setAttachedPdfs(pdfs);
    };

    const handleFiles = async (fileList) => {
        const picked = Array.from(fileList || []).filter((f) =>
            f.name.toLowerCase().endsWith(".pdf")
        );
        if (!picked.length) return;
        setUploading(true);
        setStepError(null);
        try {
            for (const f of picked) {
                const fd = new FormData();
                fd.append("file", f);
                await addPdfToTopic(topicId, fd);
            }
            await refreshAttached();
        } catch (err) {
            setStepError(errMsg(err, "No se pudo subir el PDF"));
        } finally {
            setUploading(false);
        }
    };

    const linkFromLibrary = async (pdfId) => {
        setUploading(true);
        setStepError(null);
        try {
            await linkPdfToTopic(topicId, pdfId);
            await refreshAttached();
        } catch (err) {
            setStepError(errMsg(err, "No se pudo añadir el PDF"));
        } finally {
            setUploading(false);
        }
    };

    const removeAttached = async (pdfId) => {
        setUploading(true);
        setStepError(null);
        try {
            await unlinkPdfFromTopic(topicId, pdfId);
            await refreshAttached();
        } catch (err) {
            setStepError(errMsg(err, "No se pudo quitar el PDF"));
        } finally {
            setUploading(false);
        }
    };

    // Paso 4: lanza la generación. La promesa se guarda en ref para poder
    // delegarla al context si el usuario cierra a mitad.
    const startGeneration = () => {
        setGenStatus("generating");
        setGenError(null);
        const p = generateFromTopicPdfs(topicId, {
            pdf_ids: attachedPdfs.map((pdf) => pdf.id),
            num_questions: numQuestions,
            question_type: questionType,
            num_options: numOptions,
        });
        genPromiseRef.current = p;
        p.then((res) => {
            if (genPromiseRef.current !== p) return; // se cerró: lo gestiona el context
            setGenResult(res);
            setGenStatus("done");
        }).catch((err) => {
            if (genPromiseRef.current !== p) return;
            setGenError(errMsg(err, "No se pudieron generar las preguntas"));
            setGenStatus("error");
        });
    };

    const finishAndStudy = () => {
        const payload = { subjectId, topicId };
        resetAndClose();
        onComplete?.(payload);
    };

    const attachedIds = new Set(attachedPdfs.map((p) => p.id));
    const filteredLibrary = (library || []).filter((p) =>
        p.filename.toLowerCase().includes(query.trim().toLowerCase())
    );
    const activeStep = genStatus === "idle" ? step : 4;

    const TabButton = ({ id, icon: Icon, label }) => (
        <button
            type="button"
            onClick={() => setPdfMode(id)}
            className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-md text-sm font-medium transition-colors"
            style={{
                background: pdfMode === id ? "var(--brand)" : "var(--bg-secondary)",
                color: pdfMode === id ? "#fff" : "var(--text-secondary)",
            }}
        >
            <Icon className="w-4 h-4" /> {label}
        </button>
    );

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4 overflow-y-auto"
            style={{ background: "rgba(35,33,31,0.45)" }}
            data-testid="create-subject-stepper"
        >
            <div className="card-organic w-full max-w-lg fade-up my-8" style={{ background: "white" }}>
                {/* Cabecera: título + progreso + cerrar */}
                <div className="flex items-center justify-between p-5 border-b" style={{ borderColor: "var(--border)" }}>
                    <div>
                        <h3 className="font-display text-xl font-bold">Nueva asignatura</h3>
                        <div className="flex items-center gap-1.5 mt-2" data-testid="stepper-progress">
                            {[1, 2, 3, 4].map((n) => (
                                <span
                                    key={n}
                                    className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-mono font-bold transition-colors"
                                    style={{
                                        background: n === activeStep ? "var(--brand)" : "var(--bg-secondary)",
                                        color: n === activeStep ? "#fff" : "var(--text-muted)",
                                    }}
                                >
                                    {n}
                                </span>
                            ))}
                        </div>
                    </div>
                    <button
                        onClick={requestClose}
                        data-testid="stepper-close"
                        className="p-1.5 rounded-md hover:bg-[color:var(--bg-secondary)]"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <div className="p-5 space-y-4">
                    {stepError && genStatus === "idle" && (
                        <div className="text-sm p-2.5 rounded-md" style={{ background: "#fdecea", color: "#b84a4a" }} data-testid="stepper-error">
                            {stepError}
                        </div>
                    )}

                    {/* Estado: generando */}
                    {genStatus === "generating" && (
                        <div className="py-8 flex flex-col items-center text-center gap-3" data-testid="stepper-generating">
                            <Loader2 className="w-10 h-10 animate-spin" style={{ color: "var(--brand)" }} />
                            <p className="font-medium">Generando preguntas, suele tardar ~1 min.</p>
                            <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                                Si prefieres, puedes cerrar esta ventana. Te avisaremos cuando estén listas.
                            </p>
                        </div>
                    )}

                    {/* Estado: completado */}
                    {genStatus === "done" && (
                        <div className="py-8 flex flex-col items-center text-center gap-3" data-testid="stepper-done">
                            <div className="w-14 h-14 rounded-full flex items-center justify-center" style={{ background: "#e8f0e6" }}>
                                <Check className="w-8 h-8" style={{ color: "#5c8a7a" }} />
                            </div>
                            <p className="font-display text-lg font-bold">
                                ¡Listo! Se han generado {genResult?.questions_created ?? 0} preguntas
                            </p>
                            <button
                                type="button"
                                onClick={finishAndStudy}
                                data-testid="stepper-study"
                                className="btn-primary flex items-center justify-center gap-2 text-sm px-6"
                            >
                                <Sparkles className="w-4 h-4" /> Estudiar
                            </button>
                        </div>
                    )}

                    {/* Paso 1 — nombre de asignatura */}
                    {genStatus === "idle" && step === 1 && (
                        <div>
                            <label className="label-eyebrow block mb-1.5">¿Cómo se llama la asignatura?</label>
                            <input
                                type="text"
                                value={subjectName}
                                onChange={(e) => setSubjectName(e.target.value)}
                                onKeyDown={(e) => { if (e.key === "Enter" && subjectName.trim() && !busy) submitSubject(); }}
                                placeholder="Ej. Derecho Constitucional"
                                autoFocus
                                disabled={busy || !!subjectId}
                                data-testid="stepper-subject-name"
                                className="w-full border rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[color:var(--brand)]/20 focus:border-[color:var(--brand)] disabled:opacity-60"
                                style={{ borderColor: "var(--border)" }}
                            />
                            {subjectId && (
                                <p className="text-xs mt-1.5 flex items-center gap-1" style={{ color: "var(--text-muted)" }}>
                                    <Check className="w-3.5 h-3.5" style={{ color: "#5c8a7a" }} /> Asignatura ya creada.
                                </p>
                            )}
                        </div>
                    )}

                    {/* Paso 2 — nombre del primer tema */}
                    {genStatus === "idle" && step === 2 && (
                        <div>
                            <label className="label-eyebrow block mb-1.5">
                                Primer tema de {subjectName.trim() || "la asignatura"}
                            </label>
                            <input
                                type="text"
                                value={topicName}
                                onChange={(e) => setTopicName(e.target.value)}
                                onKeyDown={(e) => { if (e.key === "Enter" && topicName.trim() && !busy) submitTopic(); }}
                                placeholder="Ej. Tema 1 — Introducción"
                                autoFocus
                                disabled={busy || !!topicId}
                                data-testid="stepper-topic-name"
                                className="w-full border rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[color:var(--brand)]/20 focus:border-[color:var(--brand)] disabled:opacity-60"
                                style={{ borderColor: "var(--border)" }}
                            />
                            {topicId && (
                                <p className="text-xs mt-1.5 flex items-center gap-1" style={{ color: "var(--text-muted)" }}>
                                    <Check className="w-3.5 h-3.5" style={{ color: "#5c8a7a" }} /> Tema ya creado.
                                </p>
                            )}
                        </div>
                    )}

                    {/* Paso 3 — adjuntar PDFs */}
                    {genStatus === "idle" && step === 3 && (
                        <div className="space-y-3">
                            <label className="label-eyebrow block">Añade PDFs al tema</label>
                            <div className="flex gap-2">
                                <TabButton id="upload" icon={Upload} label="Subir nuevos" />
                                <TabButton id="library" icon={Library} label="De mi biblioteca" />
                            </div>

                            {pdfMode === "upload" ? (
                                <label
                                    className="border-2 border-dashed rounded-md p-5 flex flex-col items-center justify-center gap-2 cursor-pointer transition-colors hover:border-[color:var(--brand)]"
                                    style={{ borderColor: "var(--border)" }}
                                    data-testid="stepper-dropzone"
                                >
                                    <input
                                        type="file"
                                        accept="application/pdf"
                                        multiple
                                        className="hidden"
                                        disabled={uploading}
                                        onChange={(e) => { handleFiles(e.target.files); e.target.value = ""; }}
                                    />
                                    <Upload className="w-7 h-7" style={{ color: "var(--text-muted)" }} />
                                    <span className="text-sm font-medium">Haz clic para seleccionar uno o varios PDFs</span>
                                    <span className="text-xs" style={{ color: "var(--text-muted)" }}>Solo se acepta .pdf</span>
                                </label>
                            ) : (
                                <div className="space-y-2">
                                    <input
                                        type="text"
                                        value={query}
                                        onChange={(e) => setQuery(e.target.value)}
                                        placeholder="Buscar por nombre…"
                                        className="w-full px-3 py-2 rounded-md border text-sm"
                                        style={{ borderColor: "var(--border)" }}
                                    />
                                    <div className="max-h-48 overflow-y-auto space-y-1.5">
                                        {libLoading ? (
                                            <div className="flex items-center gap-2 text-sm py-6 justify-center" style={{ color: "var(--text-muted)" }}>
                                                <Loader2 className="w-4 h-4 animate-spin" /> Cargando…
                                            </div>
                                        ) : filteredLibrary.length === 0 ? (
                                            <div className="text-sm py-6 text-center" style={{ color: "var(--text-muted)" }}>
                                                {library && library.length === 0
                                                    ? "Tu biblioteca está vacía. Sube PDFs desde la pestaña anterior."
                                                    : "Ningún PDF coincide con la búsqueda."}
                                            </div>
                                        ) : (
                                            filteredLibrary.map((p) => {
                                                const isAttached = attachedIds.has(p.id);
                                                return (
                                                    <button
                                                        key={p.id}
                                                        type="button"
                                                        onClick={() => !isAttached && linkFromLibrary(p.id)}
                                                        disabled={uploading || isAttached}
                                                        className="w-full flex items-center gap-3 p-2.5 rounded-md border text-left transition-colors disabled:opacity-60"
                                                        style={{ borderColor: isAttached ? "var(--brand)" : "var(--border)", background: isAttached ? "#fdf1ea" : "white" }}
                                                    >
                                                        <div className="w-5 h-5 rounded flex items-center justify-center shrink-0" style={{ background: isAttached ? "var(--brand)" : "var(--bg-secondary)", color: "#fff" }}>
                                                            {isAttached && <Check className="w-3.5 h-3.5" />}
                                                        </div>
                                                        <div className="min-w-0 flex-1">
                                                            <div className="text-sm font-medium truncate">{p.filename}</div>
                                                            <div className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                                                                {Math.round(p.char_count / 1000)}k car.
                                                            </div>
                                                        </div>
                                                    </button>
                                                );
                                            })
                                        )}
                                    </div>
                                </div>
                            )}

                            {/* PDFs adjuntos */}
                            <div>
                                <div className="flex items-center justify-between mb-1.5">
                                    <span className="label-eyebrow">Adjuntos ({attachedPdfs.length})</span>
                                    {uploading && <Loader2 className="w-4 h-4 animate-spin" style={{ color: "var(--brand)" }} />}
                                </div>
                                {attachedPdfs.length === 0 ? (
                                    <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                                        Aún no has añadido ningún PDF. Necesitas al menos uno para generar preguntas.
                                    </p>
                                ) : (
                                    <ul className="space-y-1.5" data-testid="stepper-attached-list">
                                        {attachedPdfs.map((p) => (
                                            <li key={p.id} className="flex items-center gap-2 p-2 rounded-md border text-sm" style={{ borderColor: "var(--border)" }}>
                                                <FileText className="w-4 h-4 shrink-0" style={{ color: "var(--brand)" }} />
                                                <span className="truncate flex-1">{p.filename}</span>
                                                <button
                                                    type="button"
                                                    onClick={() => removeAttached(p.id)}
                                                    disabled={uploading}
                                                    className="p-1 rounded hover:bg-[color:var(--bg-secondary)] shrink-0 disabled:opacity-50"
                                                    aria-label="Quitar PDF"
                                                >
                                                    <X className="w-3.5 h-3.5" style={{ color: "var(--text-muted)" }} />
                                                </button>
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </div>
                        </div>
                    )}

                    {/* Paso 4 — opciones de generación (también en estado error, para reintentar) */}
                    {(genStatus === "idle" || genStatus === "error") && step === 4 && (
                        <div className="space-y-4">
                            <div>
                                <label className="label-eyebrow block mb-1.5">Tipo</label>
                                <div className="grid grid-cols-3 gap-2">
                                    {QTYPES.map((t) => (
                                        <button
                                            key={t.id}
                                            type="button"
                                            onClick={() => setQuestionType(t.id)}
                                            className="px-3 py-2 rounded-md border text-sm font-medium transition-all"
                                            style={{ borderColor: questionType === t.id ? "var(--brand)" : "var(--border)", background: questionType === t.id ? "#fdf1ea" : "white" }}
                                        >
                                            {t.label}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            {questionType === "mcq" && (
                                <div>
                                    <label className="label-eyebrow block mb-1.5">
                                        Nº de opciones: <span className="font-mono">{numOptions}</span>
                                    </label>
                                    <input type="range" min="2" max="5" value={numOptions}
                                        onChange={(e) => setNumOptions(parseInt(e.target.value))}
                                        className="w-full accent-[color:var(--brand)]" />
                                </div>
                            )}

                            <div>
                                <label className="label-eyebrow block mb-1.5">
                                    Nº de preguntas: <span className="font-mono">{numQuestions}</span>
                                </label>
                                <input type="range" min="3" max="40" value={numQuestions}
                                    onChange={(e) => setNumQuestions(parseInt(e.target.value))}
                                    className="w-full accent-[color:var(--brand)]" />
                            </div>

                            {genStatus === "error" && (
                                <div className="text-sm p-2.5 rounded-md" style={{ background: "#fdecea", color: "#b84a4a" }} data-testid="stepper-gen-error">
                                    {genError}
                                </div>
                            )}
                        </div>
                    )}

                    {/* Pie de navegación (oculto en generating/done) */}
                    {(genStatus === "idle" || genStatus === "error") && (
                        <div className="flex gap-3 pt-2">
                            {step > 1 && (
                                <button
                                    type="button"
                                    onClick={() => { setStepError(null); setStep((s) => s - 1); }}
                                    disabled={busy}
                                    data-testid="stepper-back"
                                    className="px-4 py-2.5 rounded-md border font-medium text-sm hover:bg-[color:var(--bg-secondary)] flex items-center gap-1.5"
                                    style={{ borderColor: "var(--border)" }}
                                >
                                    <ArrowLeft className="w-4 h-4" /> Atrás
                                </button>
                            )}
                            {step === 1 && (
                                <button type="button" onClick={submitSubject} disabled={busy || !subjectName.trim()} data-testid="stepper-next"
                                    className="btn-primary flex-1 flex items-center justify-center gap-2 text-sm">
                                    {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : null} Siguiente
                                </button>
                            )}
                            {step === 2 && (
                                <button type="button" onClick={submitTopic} disabled={busy || !topicName.trim()} data-testid="stepper-next"
                                    className="btn-primary flex-1 flex items-center justify-center gap-2 text-sm">
                                    {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : null} Siguiente
                                </button>
                            )}
                            {step === 3 && (
                                <button type="button" onClick={() => setStep(4)} disabled={uploading || attachedPdfs.length === 0} data-testid="stepper-next"
                                    className="btn-primary flex-1 flex items-center justify-center gap-2 text-sm">
                                    Siguiente
                                </button>
                            )}
                            {step === 4 && (
                                <button type="button" onClick={startGeneration} data-testid="stepper-generate"
                                    className="btn-primary flex-1 flex items-center justify-center gap-2 text-sm">
                                    <Sparkles className="w-4 h-4" /> {genStatus === "error" ? "Reintentar" : "Generar preguntas"}
                                </button>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
