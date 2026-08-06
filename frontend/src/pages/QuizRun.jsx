import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
    Check, X, ChevronRight, Flag, Star, AlertCircle, Clock,
    MinusCircle, BookOpen, ChevronDown, ChevronUp, Pencil, Send, Loader2
} from "lucide-react";
import { toast } from "sonner";
import { quizSubmit, toggleFavorite as apiFav, toggleDifficult as apiDiff, api } from "@/lib/api";
import { SELECTION_LABELS } from "@/lib/quizLabels";

function formatTime(sec) {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

// Panel de temario desplegable
function TemarioPanel({ topicId, topicName }) {
    const [open, setOpen] = useState(false);
    const [text, setText] = useState(null);
    const [loading, setLoading] = useState(false);

    const load = useCallback(async () => {
        if (text !== null) { setOpen(o => !o); return; }
        setLoading(true);
        try {
            const res = await api.get(`/topics/${topicId}/text`);
            setText(res.data.text);
            setOpen(true);
        } catch {
            toast.error("No se pudo cargar el temario");
        } finally {
            setLoading(false);
        }
    }, [topicId, text]);

    return (
        <div className="mb-4 rounded-md border overflow-hidden" style={{ borderColor: "var(--border)" }}>
            <button
                onClick={load}
                className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium hover:bg-[color:var(--bg-secondary)] transition-colors"
                style={{ background: "var(--bg-secondary)" }}
            >
                <span className="flex items-center gap-2">
                    <BookOpen className="w-4 h-4" style={{ color: "var(--brand)" }} />
                    Ver temario: {topicName}
                </span>
                {loading ? (
                    <Loader2 className="w-4 h-4 animate-spin" style={{ color: "var(--text-muted)" }} />
                ) : open ? (
                    <ChevronUp className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
                ) : (
                    <ChevronDown className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
                )}
            </button>
            {open && text && (
                <div
                    className="px-4 py-3 text-sm leading-relaxed max-h-64 overflow-y-auto whitespace-pre-wrap"
                    style={{ color: "var(--text-secondary)", borderTop: "1px solid var(--border)" }}
                >
                    {text}
                </div>
            )}
        </div>
    );
}

// Componente para preguntas de desarrollo
// `value`/`onChange` los controla el padre (persisten al navegar, imprescindible
// en examen). En examen la respuesta NO se evalúa aquí: se corrige toda de una
// vez al finalizar. En práctica se mantiene la evaluación inline.
function DevQuestion({ question, isExam, value, onChange, onSubmit, revealed, devResult, devLoading }) {
    return (
        <div className="space-y-4">
            <textarea
                value={value}
                onChange={e => onChange(e.target.value)}
                disabled={revealed}
                placeholder="Escribe tu respuesta aquí..."
                className="w-full h-36 p-3 rounded-md border text-sm resize-none focus:outline-none focus:ring-1"
                style={{
                    borderColor: "var(--border)",
                    background: revealed ? "var(--bg-secondary)" : "white",
                    color: "var(--text-primary)",
                    focusRingColor: "var(--brand)"
                }}
            />
            {isExam ? (
                <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                    La IA corregirá tu respuesta al finalizar el examen.
                </p>
            ) : !revealed && (
                <button
                    onClick={() => onSubmit(value)}
                    disabled={!value.trim() || devLoading}
                    className="btn-primary flex items-center gap-2 text-sm"
                >
                    {devLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                    Evaluar respuesta
                </button>
            )}
            {!isExam && revealed && devResult && (
                <div className="space-y-3 fade-up">
                    <div
                        className="rounded-md p-4 border"
                        style={{
                            borderColor: devResult.score >= 5 ? "var(--sage)" : "var(--error)",
                            background: devResult.score >= 5 ? "#eef2ec" : "#fbeeee"
                        }}
                    >
                        <div className="flex items-center justify-between mb-2">
                            <span className="font-display font-bold text-sm">Tu puntuación</span>
                            <span className="font-display font-bold text-2xl" style={{
                                color: devResult.score >= 5 ? "var(--sage)" : "var(--error)"
                            }}>
                                {devResult.score}/10
                            </span>
                        </div>
                        <p className="text-sm" style={{ color: "var(--text-secondary)" }}>{devResult.feedback}</p>
                        {devResult.key_points_missing?.length > 0 && (
                            <div className="mt-2">
                                <p className="text-xs font-medium mb-1" style={{ color: "var(--text-muted)" }}>
                                    Puntos que faltaron:
                                </p>
                                <ul className="list-disc list-inside text-xs space-y-0.5" style={{ color: "var(--text-secondary)" }}>
                                    {devResult.key_points_missing.map((p, i) => <li key={i}>{p}</li>)}
                                </ul>
                            </div>
                        )}
                    </div>
                    <div className="rounded-md p-4 border" style={{ borderColor: "var(--border)", background: "var(--bg-secondary)" }}>
                        <p className="text-xs font-medium mb-1" style={{ color: "var(--text-muted)" }}>Respuesta modelo:</p>
                        <p className="text-sm" style={{ color: "var(--text-secondary)" }}>{question.model_answer}</p>
                    </div>
                </div>
            )}
        </div>
    );
}

// Modal de edición de pregunta
function EditModal({ question, onClose, onSaved }) {
    const [text, setText] = useState(question.question);
    const [options, setOptions] = useState([...question.options]);
    const [correctIdx, setCorrectIdx] = useState(question.correct_index);
    const [explanation, setExplanation] = useState(question.explanation || "");
    const [saving, setSaving] = useState(false);

    const save = async () => {
        setSaving(true);
        try {
            await api.patch(`/questions/${question.id}`, {
                question: text,
                options,
                correct_index: correctIdx,
                explanation,
            });
            toast.success("Pregunta actualizada");
            onSaved({ ...question, question: text, options, correct_index: correctIdx, explanation });
            onClose();
        } catch {
            toast.error("Error al guardar");
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.4)" }}>
            <div className="w-full max-w-lg rounded-xl p-6 shadow-xl" style={{ background: "white" }}>
                <h3 className="font-display font-bold text-lg mb-4">Editar pregunta</h3>
                <div className="space-y-3">
                    <div>
                        <label className="text-xs font-medium block mb-1" style={{ color: "var(--text-muted)" }}>Pregunta</label>
                        <textarea
                            value={text}
                            onChange={e => setText(e.target.value)}
                            className="w-full h-20 p-2 rounded border text-sm resize-none"
                            style={{ borderColor: "var(--border)" }}
                        />
                    </div>
                    {options.map((opt, i) => (
                        <div key={i} className="flex items-center gap-2">
                            <button
                                onClick={() => setCorrectIdx(i)}
                                className="w-6 h-6 rounded-full border-2 flex-shrink-0 flex items-center justify-center"
                                style={{
                                    borderColor: correctIdx === i ? "var(--sage)" : "var(--border)",
                                    background: correctIdx === i ? "var(--sage)" : "white"
                                }}
                            >
                                {correctIdx === i && <Check className="w-3 h-3 text-white" />}
                            </button>
                            <input
                                value={opt}
                                onChange={e => { const o = [...options]; o[i] = e.target.value; setOptions(o); }}
                                className="flex-1 p-2 rounded border text-sm"
                                style={{ borderColor: "var(--border)" }}
                            />
                        </div>
                    ))}
                    <div>
                        <label className="text-xs font-medium block mb-1" style={{ color: "var(--text-muted)" }}>Explicación</label>
                        <textarea
                            value={explanation}
                            onChange={e => setExplanation(e.target.value)}
                            className="w-full h-16 p-2 rounded border text-sm resize-none"
                            style={{ borderColor: "var(--border)" }}
                        />
                    </div>
                </div>
                <div className="flex justify-end gap-2 mt-4">
                    <button onClick={onClose} className="px-4 py-2 text-sm border rounded-md" style={{ borderColor: "var(--border)" }}>
                        Cancelar
                    </button>
                    <button onClick={save} disabled={saving} className="btn-primary text-sm flex items-center gap-1">
                        {saving && <Loader2 className="w-3 h-3 animate-spin" />} Guardar
                    </button>
                </div>
            </div>
        </div>
    );
}

export default function QuizRun() {
    const navigate = useNavigate();
    const [quiz, setQuiz] = useState(null);
    const [idx, setIdx] = useState(0);
    const [answers, setAnswers] = useState([]);
    const [devScores, setDevScores] = useState({}); // { questionId: score }
    const [devResultsMap, setDevResultsMap] = useState({}); // { questionId: {score, feedback, key_points_missing} } para resultados
    const [devAnswers, setDevAnswers] = useState({}); // { questionId: texto } (persiste al navegar; examen)
    const [revealed, setRevealed] = useState(false);
    const [devResult, setDevResult] = useState(null);
    const [devLoading, setDevLoading] = useState(false);
    const [submitting, setSubmitting] = useState(false); // corrigiendo/enviando el examen
    const [elapsed, setElapsed] = useState(0);
    const [showTemario, setShowTemario] = useState(false);
    const [editOpen, setEditOpen] = useState(false);
    const startedRef = useRef(Date.now());
    const submittedRef = useRef(false);

    useEffect(() => {
        const raw = sessionStorage.getItem("current_quiz");
        if (!raw) { navigate("/quiz/setup"); return; }
        const q = JSON.parse(raw);
        setQuiz(q);
        setAnswers(new Array(q.questions.length).fill(-1));
        startedRef.current = q.started_at || Date.now();
    }, [navigate]);

    useEffect(() => {
        const t = setInterval(() => {
            setElapsed(Math.floor((Date.now() - startedRef.current) / 1000));
        }, 1000);
        return () => clearInterval(t);
    }, []);

    // Ejes del estudio. Fallback al `mode` viejo por si una sesión quedó en
    // sessionStorage con el esquema anterior (ventana de despliegue de Fase 3).
    const behavior = quiz?.behavior || (quiz?.mode === "exam" ? "exam" : "practice");
    const selection = quiz?.selection
        || (["errors", "srs", "favorites"].includes(quiz?.mode) ? quiz.mode : "all");
    const isExam = behavior === "exam";
    const isPractice = !isExam;
    const timeLeft = useMemo(() => {
        if (!quiz?.time_limit_seconds) return null;
        return Math.max(0, quiz.time_limit_seconds - elapsed);
    }, [quiz, elapsed]);

    const handleSubmit = async () => {
        if (submittedRef.current) return;
        submittedRef.current = true;
        setSubmitting(true);
        try {
            // En EXAMEN la corrección de desarrollo se difiere a aquí: se evalúan
            // TODAS de una vez (1 unidad de cuota para el lote). Las que están en
            // blanco no se evalúan (0, sin gastar cuota). En práctica ya vienen
            // evaluadas inline en devScores.
            let scores = devScores;
            let devResults = { ...devResultsMap }; // práctica: feedback inline ya acumulado
            const devQs = quiz.questions.filter((qq) => qq.question_type === "dev");
            if (isExam && devQs.length > 0) {
                try {
                    const items = devQs.map((qq) => ({
                        question_id: qq.id,
                        user_answer: devAnswers[qq.id] || "",
                    }));
                    const { data } = await api.post("/quiz/eval-dev-batch", { answers: items });
                    scores = { ...devScores };
                    (data.results || []).forEach((r) => {
                        scores[r.question_id] = r.score;
                        devResults[r.question_id] = r;
                    });
                    setDevScores(scores);
                } catch (err) {
                    // No bloqueamos el examen por un fallo de corrección: se guarda
                    // con las de desarrollo sin nota (0) y avisamos.
                    const msg = err?.response?.status === 402
                        ? "Sin cuota para corregir las de desarrollo: el examen se guarda sin su nota."
                        : "No se pudieron corregir las de desarrollo: se guardan sin nota.";
                    toast.error(msg);
                }
            }

            const payload = {
                selection,
                behavior,
                subject_ids: quiz.subject_ids || [],
                topic_ids: quiz.topic_ids || [],
                answers: quiz.questions.map((qq, i) => ({
                    question_id: qq.id,
                    selected: answers[i] ?? -1,
                    correct_index: qq.correct_index,
                    question_type: qq.question_type,
                    dev_score: scores[qq.id] ?? 0,
                })),
                duration_seconds: Math.floor((Date.now() - startedRef.current) / 1000),
                time_limit_seconds: quiz.time_limit_seconds || null,
                penalty_factor: quiz.penalty_factor || null,
                blanks_count_as_wrong: !!quiz.blanks_count_as_wrong,
                question_type: quiz.question_type || null,
                // Snapshot por pregunta (orden mostrado/barajado de la sesión) para
                // reconstruir el intento después. Mismo orden que `answers`. El backend
                // recalcula is_correct; aquí solo mandamos lo mostrado + respuesta dev.
                snapshot: quiz.questions.map((qq, i) => {
                    const item = {
                        question_id: qq.id,
                        question_type: qq.question_type,
                        question: qq.question,
                        options: qq.options || [],
                        selected: answers[i] ?? -1,
                        correct_index: qq.correct_index,
                    };
                    if (qq.question_type === "dev") {
                        item.user_answer = devAnswers[qq.id] || "";
                        item.dev_score = scores[qq.id] ?? 0;
                        item.feedback = devResults[qq.id]?.feedback || "";
                    }
                    return item;
                }),
            };
            const res = await quizSubmit(payload);
            sessionStorage.setItem("quiz_result", JSON.stringify({
                ...res,
                questions: quiz.questions,
                answers,
                devScores: scores,
                devResults,  // feedback por pregunta (lo consumirá la pantalla de resultados en D)
                selection,
                behavior,
                blanks_count_as_wrong: !!quiz.blanks_count_as_wrong,
            }));
            navigate("/quiz/results");
        } catch {
            toast.error("Error al enviar el examen");
            submittedRef.current = false;
            setSubmitting(false);
        }
    };

    useEffect(() => {
        if (isExam && timeLeft === 0 && !submittedRef.current) handleSubmit();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [timeLeft, isExam]);

    if (!quiz) return null;
    const q = quiz.questions[idx];
    const selected = answers[idx];
    const isDevQ = q.question_type === "dev";
    const isTF = q.question_type === "tf";

    const onSelect = (optIdx) => {
        if (isExam) {
            const next = [...answers]; next[idx] = optIdx; setAnswers(next);
        } else {
            if (revealed) return;
            const next = [...answers]; next[idx] = optIdx; setAnswers(next);
            setRevealed(true);
        }
    };

    const onDevAnswer = async (userAnswer) => {
        if (!userAnswer.trim()) return;
        setDevLoading(true);
        try {
            const res = await api.post("/quiz/eval-dev", {
                question_id: q.id,
                user_answer: userAnswer,
            });
            setDevResult(res.data);
            setDevScores(prev => ({ ...prev, [q.id]: res.data.score }));
            setDevResultsMap(prev => ({ ...prev, [q.id]: res.data })); // para el feedback en resultados
            const next = [...answers]; next[idx] = 0; setAnswers(next); // mark as answered
            setRevealed(true);
        } catch {
            toast.error("Error al evaluar la respuesta");
        } finally {
            setDevLoading(false);
        }
    };

    const onClearAnswer = () => {
        if (!isExam) return;
        const next = [...answers]; next[idx] = -1; setAnswers(next);
    };

    const onNext = () => {
        if (idx + 1 >= quiz.questions.length) {
            handleSubmit();
        } else {
            setIdx(idx + 1);
            setRevealed(isExam ? false : answers[idx + 1] !== -1);
            setDevResult(null);
            setShowTemario(false);
        }
    };

    const onPrev = () => {
        if (idx > 0) {
            setIdx(idx - 1);
            setRevealed(isExam ? false : answers[idx - 1] !== -1);
            setDevResult(null);
            setShowTemario(false);
        }
    };

    const toggleFav = async () => {
        try {
            const { favorite } = await apiFav(q.id);
            quiz.questions[idx] = { ...q, favorite };
            setQuiz({ ...quiz });
        } catch { toast.error("Error"); }
    };

    const toggleDiff = async () => {
        try {
            const { difficult } = await apiDiff(q.id);
            quiz.questions[idx] = { ...q, difficult };
            setQuiz({ ...quiz });
        } catch { toast.error("Error"); }
    };

    const onQuestionEdited = (updated) => {
        quiz.questions[idx] = updated;
        setQuiz({ ...quiz });
    };

    const answeredCount = answers.filter((a) => a !== -1).length;
    const blankCount = quiz.questions.length - answeredCount;
    // En examen se navega libre (dev incluido: se corrige al final). En práctica
    // hay que revelar/responder para avanzar.
    const canGoNext = isExam ? true : revealed;

    // Envío desde el botón "Finalizar": en examen, si quedan preguntas en blanco,
    // confirmar antes. El auto-envío por tiempo agotado NO pasa por aquí (envía
    // sin preguntar). Práctica no llega aquí (feedback inmediato, sin envío).
    const confirmAndSubmit = () => {
        if (
            isExam && blankCount > 0 &&
            !window.confirm(
                `Te quedan ${blankCount} pregunta${blankCount === 1 ? "" : "s"} sin responder` +
                (quiz.blanks_count_as_wrong ? ", y penalizan como un fallo" : "") +
                ". ¿Enviar de todas formas?"
            )
        ) {
            return;
        }
        handleSubmit();
    };

    return (
        <div className="min-h-screen flex flex-col" style={{ background: "var(--bg-primary)" }}>
            {/* Header */}
            <header
                className="border-b sticky top-0 z-30 backdrop-blur"
                style={{ borderColor: "var(--border)", background: "rgba(253,251,247,0.92)" }}
            >
                <div className="max-w-3xl mx-auto px-5 py-3 flex items-center justify-between gap-3">
                    <button
                        onClick={() => { if (window.confirm("¿Salir? Perderás el progreso.")) navigate("/"); }}
                        data-testid="exit-quiz-btn"
                        className="text-sm font-medium hover:underline"
                        style={{ color: "var(--text-secondary)" }}
                    >
                        Salir
                    </button>
                    <div className="flex items-center gap-3 text-sm flex-wrap justify-end">
                        <span className="font-mono" data-testid="quiz-progress">
                            {idx + 1} / {quiz.questions.length}
                        </span>
                        {quiz.penalty_factor && (
                            <span className="font-mono text-xs px-2 py-1 rounded-md" style={{ background: "#fdf1ea", color: "var(--brand)" }}>
                                −1/{quiz.penalty_factor}
                            </span>
                        )}
                        {isExam && timeLeft !== null && (
                            <span
                                className="flex items-center gap-1 font-mono px-2 py-1 rounded-md"
                                style={{
                                    background: timeLeft < 60 ? "#fbeeee" : "var(--bg-secondary)",
                                    color: timeLeft < 60 ? "var(--error)" : "var(--text-primary)",
                                }}
                                data-testid="quiz-timer"
                            >
                                <Clock className="w-3.5 h-3.5" />
                                {formatTime(timeLeft)}
                            </span>
                        )}
                        {!isExam && (
                            <span className="font-mono text-xs px-2 py-1 rounded-md" style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}>
                                {SELECTION_LABELS[selection] || "Todas"}
                            </span>
                        )}
                    </div>
                </div>
                <div className="progress-track" style={{ borderRadius: 0, height: 3 }}>
                    <div className="progress-fill" style={{ width: `${((idx + 1) / quiz.questions.length) * 100}%` }} />
                </div>
            </header>

            <main className="flex-1 max-w-3xl mx-auto w-full px-5 py-8">
                <div className="fade-up" key={idx}>
                    {/* Temario panel (solo en modo práctica) */}
                    {isPractice && (
                        <TemarioPanel topicId={q.topic_id} topicName={q.topic_name} />
                    )}

                    {/* Cabecera pregunta */}
                    <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2 min-w-0">
                            <span className="label-eyebrow truncate">
                                {q.topic_name} · {isDevQ ? "Desarrollo" : isTF ? "Verdadero/Falso" : "Opción múltiple"}
                            </span>
                            {isExam && answers[idx] === -1 && (
                                <span
                                    data-testid="blank-indicator"
                                    className="shrink-0 flex items-center gap-1 text-[0.65rem] font-medium px-1.5 py-0.5 rounded"
                                    style={{ background: "var(--bg-secondary)", color: "var(--text-muted)" }}
                                >
                                    <MinusCircle className="w-3 h-3" /> Sin responder
                                </span>
                            )}
                        </div>
                        <div className="flex gap-1">
                            <button
                                onClick={() => setEditOpen(true)}
                                className="p-1.5 rounded hover:bg-[color:var(--bg-secondary)]"
                                title="Editar pregunta"
                            >
                                <Pencil className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
                            </button>
                            <button onClick={toggleFav} data-testid="toggle-fav-btn" className="p-1.5 rounded hover:bg-[color:var(--bg-secondary)]" title="Favorita">
                                <Star className="w-4 h-4" fill={q.favorite ? "var(--warning)" : "none"} style={{ color: q.favorite ? "var(--warning)" : "var(--text-muted)" }} />
                            </button>
                            <button onClick={toggleDiff} data-testid="toggle-diff-btn" className="p-1.5 rounded hover:bg-[color:var(--bg-secondary)]" title="Difícil">
                                <Flag className="w-4 h-4" fill={q.difficult ? "var(--error)" : "none"} style={{ color: q.difficult ? "var(--error)" : "var(--text-muted)" }} />
                            </button>
                        </div>
                    </div>

                    <h2 className="font-display text-xl md:text-2xl font-bold mb-6 leading-snug">{q.question}</h2>

                    {/* Pregunta de desarrollo */}
                    {isDevQ ? (
                        <DevQuestion
                            question={q}
                            isExam={isExam}
                            value={devAnswers[q.id] || ""}
                            onChange={(text) => {
                                setDevAnswers((prev) => ({ ...prev, [q.id]: text }));
                                if (isExam) {
                                    const next = [...answers];
                                    next[idx] = text.trim() ? 0 : -1; // marca respondida/en blanco
                                    setAnswers(next);
                                }
                            }}
                            onSubmit={onDevAnswer}
                            revealed={revealed}
                            devResult={devResult}
                            devLoading={devLoading}
                        />
                    ) : (
                        <>
                            <div className={`mb-6 ${isTF ? "grid grid-cols-2 gap-3" : "space-y-3"}`}>
                                {q.options.map((opt, i) => {
                                    const isSelected = selected === i;
                                    const isCorrect = i === q.correct_index;
                                    let cls = "option-pill";
                                    if (revealed) {
                                        if (isCorrect) cls += " correct";
                                        else if (isSelected) cls += " wrong";
                                    } else if (isSelected) {
                                        cls += " selected";
                                    }
                                    return (
                                        <button key={i} onClick={() => onSelect(i)} disabled={revealed && !isExam} data-testid={`option-${i}`} className={cls}>
                                            <div className="flex items-center gap-3">
                                                <span className="kbd" style={{ minWidth: "1.5rem", textAlign: "center", background: "white" }}>
                                                    {isTF ? (i === 0 ? "V" : "F") : String.fromCharCode(65 + i)}
                                                </span>
                                                <span className="flex-1 text-sm md:text-base">{opt}</span>
                                                {revealed && isCorrect && <Check className="w-4 h-4" style={{ color: "var(--sage)" }} />}
                                                {revealed && isSelected && !isCorrect && <X className="w-4 h-4" style={{ color: "var(--error)" }} />}
                                            </div>
                                        </button>
                                    );
                                })}
                            </div>
                            {isExam && (
                                <button onClick={onClearAnswer} data-testid="clear-answer-btn" className="text-xs flex items-center gap-1 mb-4 hover:underline" style={{ color: "var(--text-muted)" }}>
                                    <MinusCircle className="w-3 h-3" /> Dejar en blanco{quiz.blanks_count_as_wrong ? " (penaliza)" : quiz.penalty_factor ? " (no penaliza)" : ""}
                                </button>
                            )}
                            {revealed && q.explanation && (
                                <div className="rounded-md p-4 border flex gap-3 fade-up mb-6" style={{ borderColor: "var(--border)", background: "var(--bg-secondary)" }} data-testid="explanation-box">
                                    <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" style={{ color: "var(--brand)" }} />
                                    <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
                                        <strong className="font-display" style={{ color: "var(--text-primary)" }}>Explicación:</strong>{" "}{q.explanation}
                                    </div>
                                </div>
                            )}
                        </>
                    )}

                    {/* Navegación */}
                    <div className="flex items-center justify-between gap-3 mt-6">
                        <button onClick={onPrev} disabled={idx === 0} data-testid="prev-btn" className="px-4 py-2 rounded-md border font-medium text-sm disabled:opacity-40" style={{ borderColor: "var(--border)" }}>
                            Anterior
                        </button>
                        <span className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                            {answeredCount} respondidas{isExam && blankCount > 0 ? ` · ${blankCount} en blanco` : ""}
                        </span>
                        {isExam ? (
                            idx + 1 === quiz.questions.length ? (
                                <button onClick={confirmAndSubmit} disabled={submitting} data-testid="submit-exam-btn" className="btn-primary flex items-center gap-2 text-sm disabled:opacity-60">
                                    {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
                                    {submitting ? "Corrigiendo…" : "Finalizar"}
                                </button>
                            ) : (
                                <button onClick={onNext} data-testid="next-btn" className="btn-primary flex items-center gap-2 text-sm">
                                    Siguiente <ChevronRight className="w-4 h-4" />
                                </button>
                            )
                        ) : (
                            <button onClick={onNext} disabled={!canGoNext} data-testid="next-btn" className="btn-primary flex items-center gap-2 text-sm">
                                {idx + 1 === quiz.questions.length ? "Ver resultado" : "Siguiente"}
                                <ChevronRight className="w-4 h-4" />
                            </button>
                        )}
                    </div>
                </div>
            </main>

            {/* Modal edición */}
            {editOpen && !isDevQ && (
                <EditModal question={q} onClose={() => setEditOpen(false)} onSaved={onQuestionEdited} />
            )}

            {/* Overlay mientras se corrige/envía (la corrección de desarrollo en
                examen puede tardar unos segundos). También cubre el auto-envío por
                tiempo agotado. */}
            {submitting && isExam && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: "rgba(35,33,31,0.55)" }} data-testid="submitting-overlay">
                    <div className="card-organic px-6 py-5 flex items-center gap-3" style={{ background: "white" }}>
                        <Loader2 className="w-5 h-5 animate-spin" style={{ color: "var(--brand)" }} />
                        <span className="text-sm font-medium">Corrigiendo tu examen…</span>
                    </div>
                </div>
            )}
        </div>
    );
}
