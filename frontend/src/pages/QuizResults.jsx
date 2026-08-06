import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { Check, X, RotateCcw, Home, Sparkles, MinusCircle, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { quizStart } from "@/lib/api";
import EditQuestionDialog from "@/components/EditQuestionDialog";
import AttemptReview from "@/components/AttemptReview";

export default function QuizResults() {
    const navigate = useNavigate();
    const [data, setData] = useState(null);
    const [reviewing, setReviewing] = useState(false);
    const [editingModel, setEditingModel] = useState(null); // pregunta cuya respuesta modelo se edita

    // Al guardar la respuesta modelo desde resultados: se persiste en el backend
    // (para próximos exámenes) y refrescamos la vista actual + el sessionStorage,
    // pero la NOTA de este examen no cambia (no hay recorrección).
    const onModelSaved = (updated) => {
        setData((d) => {
            if (!d) return d;
            const questions = d.questions.map((q) => (q.id === updated.id ? { ...q, ...updated } : q));
            const next = { ...d, questions };
            try { sessionStorage.setItem("quiz_result", JSON.stringify(next)); } catch { /* noop */ }
            return next;
        });
        setEditingModel(null);
    };

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
        devResults = {},
        blanks_count_as_wrong = false,
        blanks_penalized,
    } = data;
    // Autoritativo del backend; fallback al flag del cliente durante el despliegue.
    const blanksPenalized = blanks_penalized ?? blanks_count_as_wrong;

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
                behavior: "practice",
                selection: "all",
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
                behavior: "practice",
                selection: "all",
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

    // Desglose por pregunta en el MISMO shape que el snapshot del backend
    // (Attempt.items), para reutilizar AttemptReview. Los extras del post-quiz
    // (model_answer, feedback, key_points_missing) viajan como campos opcionales.
    const reviewItems = questions.map((q, i) => {
        const base = {
            question_id: q.id,
            question_type: q.question_type,
            question: q.question,
            topic_name: q.topic_name,
            options: q.options || [],
            selected: answers[i] ?? -1,
            correct_index: q.correct_index,
            explanation: q.explanation || "",
        };
        if (q.question_type !== "dev") return base;
        return {
            ...base,
            dev_score: devScores[q.id] ?? 0,
            feedback: devResults[q.id]?.feedback || "",
            key_points_missing: devResults[q.id]?.key_points_missing || [],
            model_answer: q.model_answer || "",
        };
    });

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
                            Bruto: {parseFloat(Number(raw_score).toFixed(2))} sobre {total}
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
                            <MinusCircle className="w-4 h-4 mx-auto" style={{ color: blanksPenalized && unanswered > 0 ? "var(--error)" : "var(--text-muted)" }} />
                            <div className="font-display text-2xl font-bold mt-1">{unanswered}</div>
                            <div className="text-xs" style={{ color: "var(--text-muted)" }}>Blanco</div>
                            {blanksPenalized && unanswered > 0 && (
                                <div className="text-[10px] font-medium" style={{ color: "var(--error)" }}>penalizan</div>
                            )}
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

            {/* Revisión pregunta a pregunta (componente reutilizable; las tarjetas de
                nota/acciones de arriba son propias de esta pantalla → showTiles=false). */}
            <AttemptReview
                items={reviewItems}
                showTiles={false}
                blanksPenalized={blanksPenalized}
                onEditModel={(item) => setEditingModel(questions.find((q) => q.id === item.question_id))}
            />

            <EditQuestionDialog
                question={editingModel}
                onClose={() => setEditingModel(null)}
                onSaved={onModelSaved}
                notice="Los cambios se aplicarán en próximos exámenes; tu nota actual no cambia."
            />
        </div>
    );
}
