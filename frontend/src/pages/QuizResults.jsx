import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { Check, X, RotateCcw, Home, Sparkles, MinusCircle, BookOpen, ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { quizStart } from "@/lib/api";

function DevReviewCard({ question, devScore }) {
    const [showModel, setShowModel] = useState(false);
    const score = devScore ?? 0;
    const passed = score >= 5;

    return (
        <div className="space-y-2">
            <div
                className="flex items-center justify-between px-3 py-2 rounded-md"
                style={{ background: passed ? "#eef2ec" : "#fbeeee" }}
            >
                <span className="text-sm font-medium" style={{ color: passed ? "var(--sage)" : "var(--error)" }}>
                    Puntuación obtenida
                </span>
                <span className="font-display font-bold text-xl" style={{ color: passed ? "var(--sage)" : "var(--error)" }}>
                    {score}/10
                </span>
            </div>
            <button
                onClick={() => setShowModel(o => !o)}
                className="flex items-center gap-1 text-xs font-medium hover:underline"
                style={{ color: "var(--brand)" }}
            >
                <BookOpen className="w-3 h-3" />
                {showModel ? "Ocultar" : "Ver"} respuesta modelo
                {showModel ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            </button>
            {showModel && question.model_answer && (
                <div
                    className="rounded-md p-3 text-sm leading-relaxed"
                    style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
                >
                    {question.model_answer}
                </div>
            )}
            {question.explanation && (
                <div className="text-xs italic" style={{ color: "var(--text-muted)" }}>
                    Puntos clave: {question.explanation}
                </div>
            )}
        </div>
    );
}

export default function QuizResults() {
    const navigate = useNavigate();
    const [data, setData] = useState(null);
    const [reviewing, setReviewing] = useState(false);

    useEffect(() => {
        const raw = sessionStorage.getItem("quiz_result");
        if (!raw) { navigate("/"); return; }
        setData(JSON.parse(raw));
    }, [navigate]);

    if (!data) return null;

    const {
        correct,
        wrong = 0,
        unanswered = 0,
        total,
        score_10,
        raw_score,
        penalty_factor,
        questions,
        answers,
        devScores = {},
    } = data;

    const pct = total ? Math.round((correct / total) * 100) : 0;
    const passed = score_10 >= 5;

    // Preguntas NO acertadas en ESTE examen: fallos + en blanco (sel === -1) +
    // desarrollo con nota < 5. Es la base del botón "Repasar errores".
    const failedIds = questions
        .filter((q, i) =>
            q.question_type === "dev"
                ? (devScores[q.id] ?? 0) < 5
                : answers[i] !== q.correct_index
        )
        .map((q) => q.id);

    // Lanza un quiz de práctica solo con las preguntas falladas ahora, reusando
    // quiz/start + question_ids (mismo patrón que "Practicar selección" del banco).
    const reviewErrors = async () => {
        if (!failedIds.length) return;
        setReviewing(true);
        try {
            const res = await quizStart({
                mode: "practice",
                question_ids: failedIds,
                num_questions: failedIds.length,
            });
            const qs = res.questions || [];
            if (!qs.length) {
                toast.error("No se pudieron cargar las preguntas para repasar");
                return;
            }
            sessionStorage.setItem("current_quiz", JSON.stringify({
                questions: qs,
                mode: "practice",
                subject_ids: [],
                topic_ids: [],
                time_limit_seconds: null,
                penalty_factor: null,
                question_type: "any",
                started_at: Date.now(),
            }));
            navigate("/quiz/run");
        } catch (err) {
            toast.error(err?.response?.data?.detail || "No se pudo iniciar el repaso");
        } finally {
            setReviewing(false);
        }
    };

    // Separate questions by type for the summary
    const devQuestions = questions.filter(q => q.question_type === "dev");
    const hasDevQuestions = devQuestions.length > 0;

    return (
        <div className="max-w-3xl mx-auto px-5 md:px-8 py-8 md:py-12">
            <span className="label-eyebrow">Resultado</span>
            <h1 className="font-display text-3xl md:text-4xl font-bold mt-1 mb-6">
                {passed ? "¡Bien hecho!" : "Sigue así, repasa los fallos"}
            </h1>

            {/* Score cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
                <div className="card-organic p-5 fade-up" data-testid="result-score">
                    <span className="label-eyebrow">
                        Nota {penalty_factor ? `(penalización ${penalty_factor}→−1)` : "(sin penalización)"}
                    </span>
                    <div
                        className="font-display text-5xl font-bold mt-1"
                        style={{ color: passed ? "var(--sage)" : "var(--error)" }}
                    >
                        {score_10}
                        <span className="text-2xl" style={{ color: "var(--text-muted)" }}>/10</span>
                    </div>
                    {penalty_factor && (
                        <div className="text-xs mt-1 font-mono" style={{ color: "var(--text-muted)" }}>
                            Bruto: {raw_score} sobre {total}
                        </div>
                    )}
                </div>
                <div className="card-organic p-5 fade-up">
                    <span className="label-eyebrow">Resumen</span>
                    <div className="grid grid-cols-3 gap-2 mt-2 text-center">
                        <div>
                            <Check className="w-4 h-4 mx-auto" style={{ color: "var(--sage)" }} />
                            <div className="font-display text-2xl font-bold mt-1">{correct}</div>
                            <div className="text-xs" style={{ color: "var(--text-muted)" }}>Aciertos</div>
                        </div>
                        <div>
                            <X className="w-4 h-4 mx-auto" style={{ color: "var(--error)" }} />
                            <div className="font-display text-2xl font-bold mt-1">{wrong}</div>
                            <div className="text-xs" style={{ color: "var(--text-muted)" }}>Fallos</div>
                        </div>
                        <div>
                            <MinusCircle className="w-4 h-4 mx-auto" style={{ color: "var(--text-muted)" }} />
                            <div className="font-display text-2xl font-bold mt-1">{unanswered}</div>
                            <div className="text-xs" style={{ color: "var(--text-muted)" }}>Blanco</div>
                        </div>
                    </div>
                    <div className="progress-track mt-3">
                        <div className="progress-fill" style={{ width: `${pct}%`, background: "var(--sage)" }} />
                    </div>
                    <div className="text-xs mt-1 font-mono text-right" style={{ color: "var(--text-muted)" }}>
                        {pct}% aciertos
                    </div>
                </div>
            </div>

            {/* Dev questions summary if any */}
            {hasDevQuestions && (
                <div className="card-organic p-5 fade-up mb-6">
                    <span className="label-eyebrow block mb-2">Preguntas de desarrollo</span>
                    <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
                        Respondiste {devQuestions.length} pregunta{devQuestions.length > 1 ? "s" : ""} de desarrollo.
                        Puntuación media:{" "}
                        <strong>
                            {(devQuestions.reduce((acc, q) => acc + (devScores[q.id] ?? 0), 0) / devQuestions.length).toFixed(1)}/10
                        </strong>
                    </div>
                </div>
            )}

            {/* Actions */}
            <div className="flex flex-wrap gap-3 mb-10">
                <Link to="/" className="btn-primary inline-flex items-center gap-2" data-testid="back-home-btn">
                    <Home className="w-4 h-4" /> Inicio
                </Link>
                {/* Solo si hay algo que repasar: un botón gris "deshabilitado"
                    invitaría a preguntarse por qué no funciona; ocultarlo comunica
                    mejor que el examen fue perfecto. */}
                {failedIds.length > 0 && (
                    <button
                        type="button"
                        onClick={reviewErrors}
                        disabled={reviewing}
                        data-testid="review-errors-btn"
                        className="px-5 py-2.5 rounded-md border font-medium text-sm flex items-center gap-2 hover:bg-[color:var(--bg-secondary)] disabled:opacity-60"
                        style={{ borderColor: "var(--border)" }}
                    >
                        {reviewing ? <Loader2 className="w-4 h-4 animate-spin" /> : <RotateCcw className="w-4 h-4" />}
                        Repasar errores ({failedIds.length})
                    </button>
                )}
                <Link
                    to="/quiz/setup"
                    className="px-5 py-2.5 rounded-md border font-medium text-sm flex items-center gap-2 hover:bg-[color:var(--bg-secondary)]"
                    style={{ borderColor: "var(--border)" }}
                >
                    <Sparkles className="w-4 h-4" /> Nueva sesión
                </Link>
            </div>

            {/* Review per question */}
            <span className="label-eyebrow block mb-3">Revisión pregunta a pregunta</span>
            <div className="space-y-3">
                {questions.map((q, i) => {
                    const sel = answers[i];
                    const isDevQ = q.question_type === "dev";
                    const devScore = devScores[q.id];
                    const isUnanswered = !isDevQ && sel === -1;
                    const ok = isDevQ
                        ? (devScore ?? 0) >= 5
                        : sel === q.correct_index && !isUnanswered;

                    return (
                        <div key={q.id} className="card-organic p-4 md:p-5 fade-up" data-testid={`review-q-${i}`}>
                            <div className="flex items-start gap-3">
                                <span
                                    className="w-7 h-7 rounded-md flex items-center justify-center shrink-0 mt-0.5"
                                    style={{
                                        background: isUnanswered
                                            ? "var(--bg-secondary)"
                                            : ok ? "#eef2ec" : "#fbeeee",
                                    }}
                                >
                                    {isUnanswered ? (
                                        <MinusCircle className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
                                    ) : ok ? (
                                        <Check className="w-4 h-4" style={{ color: "var(--sage)" }} />
                                    ) : (
                                        <X className="w-4 h-4" style={{ color: "var(--error)" }} />
                                    )}
                                </span>
                                <div className="flex-1">
                                    <div className="text-xs mb-1" style={{ color: "var(--text-muted)" }}>
                                        {q.topic_name} · Pregunta {i + 1} ·{" "}
                                        {isDevQ ? "Desarrollo" : q.question_type === "tf" ? "V/F" : "Test"}
                                    </div>
                                    <div className="font-display font-bold text-base md:text-lg leading-snug mb-3">
                                        {q.question}
                                    </div>

                                    {/* Development question review */}
                                    {isDevQ ? (
                                        <DevReviewCard question={q} devScore={devScore} />
                                    ) : (
                                        <>
                                            <ul className="space-y-1 text-sm">
                                                {q.options.map((opt, oi) => {
                                                    const isCorrect = oi === q.correct_index;
                                                    const isSelected = oi === sel;
                                                    return (
                                                        <li
                                                            key={oi}
                                                            className="flex items-start gap-2 px-2 py-1 rounded"
                                                            style={{
                                                                background: isCorrect ? "#eef2ec" : isSelected ? "#fbeeee" : "transparent",
                                                                color: isCorrect ? "var(--sage)" : isSelected ? "var(--error)" : "var(--text-secondary)",
                                                            }}
                                                        >
                                                            <span className="kbd" style={{ background: "white" }}>
                                                                {q.question_type === "tf"
                                                                    ? oi === 0 ? "V" : "F"
                                                                    : String.fromCharCode(65 + oi)}
                                                            </span>
                                                            <span className="flex-1">{opt}</span>
                                                            {isCorrect && <Check className="w-3.5 h-3.5 shrink-0 mt-0.5" style={{ color: "var(--sage)" }} />}
                                                        </li>
                                                    );
                                                })}
                                            </ul>
                                            {q.explanation && (
                                                <div className="mt-2 text-xs italic" style={{ color: "var(--text-muted)" }}>
                                                    {q.explanation}
                                                </div>
                                            )}
                                        </>
                                    )}
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
