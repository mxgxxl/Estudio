import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { Check, X, RotateCcw, Home, Sparkles } from "lucide-react";

export default function QuizResults() {
    const navigate = useNavigate();
    const [data, setData] = useState(null);

    useEffect(() => {
        const raw = sessionStorage.getItem("quiz_result");
        if (!raw) {
            navigate("/");
            return;
        }
        setData(JSON.parse(raw));
    }, [navigate]);

    if (!data) return null;

    const { correct, total, score_10, questions, answers } = data;
    const pct = total ? Math.round((correct / total) * 100) : 0;
    const passed = score_10 >= 5;

    return (
        <div className="max-w-3xl mx-auto px-5 md:px-8 py-8 md:py-12">
            <span className="label-eyebrow">Resultado</span>
            <h1 className="font-display text-3xl md:text-4xl font-bold mt-1 mb-6">
                {passed ? "¡Bien hecho!" : "Sigue así, repasa los fallos"}
            </h1>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-10">
                <div className="card-organic p-5 fade-up" data-testid="result-score">
                    <span className="label-eyebrow">Nota</span>
                    <div
                        className="font-display text-5xl font-bold mt-1"
                        style={{ color: passed ? "var(--sage)" : "var(--error)" }}
                    >
                        {score_10}
                        <span className="text-2xl" style={{ color: "var(--text-muted)" }}>
                            /10
                        </span>
                    </div>
                </div>
                <div className="card-organic p-5 fade-up">
                    <span className="label-eyebrow">Aciertos</span>
                    <div className="font-display text-4xl font-bold mt-1">
                        {correct}
                        <span className="text-2xl" style={{ color: "var(--text-muted)" }}>
                            /{total}
                        </span>
                    </div>
                </div>
                <div className="card-organic p-5 fade-up">
                    <span className="label-eyebrow">Precisión</span>
                    <div className="font-display text-4xl font-bold mt-1">{pct}%</div>
                    <div className="progress-track mt-2">
                        <div className="progress-fill" style={{ width: `${pct}%` }} />
                    </div>
                </div>
            </div>

            <div className="flex flex-wrap gap-3 mb-10">
                <Link to="/" className="btn-primary inline-flex items-center gap-2" data-testid="back-home-btn">
                    <Home className="w-4 h-4" /> Inicio
                </Link>
                <Link
                    to="/quiz/setup?mode=errors"
                    data-testid="review-errors-btn"
                    className="px-5 py-2.5 rounded-md border font-medium text-sm flex items-center gap-2 hover:bg-[color:var(--bg-secondary)]"
                    style={{ borderColor: "var(--border)" }}
                >
                    <RotateCcw className="w-4 h-4" /> Repasar errores
                </Link>
                <Link
                    to="/quiz/setup"
                    className="px-5 py-2.5 rounded-md border font-medium text-sm flex items-center gap-2 hover:bg-[color:var(--bg-secondary)]"
                    style={{ borderColor: "var(--border)" }}
                >
                    <Sparkles className="w-4 h-4" /> Nueva sesión
                </Link>
            </div>

            <span className="label-eyebrow block mb-3">Revisión</span>
            <div className="space-y-3">
                {questions.map((q, i) => {
                    const sel = answers[i];
                    const ok = sel === q.correct_index;
                    return (
                        <div key={q.id} className="card-organic p-4 md:p-5 fade-up" data-testid={`review-q-${i}`}>
                            <div className="flex items-start gap-3">
                                <span
                                    className="w-7 h-7 rounded-md flex items-center justify-center shrink-0"
                                    style={{ background: ok ? "#eef2ec" : "#fbeeee" }}
                                >
                                    {ok ? (
                                        <Check className="w-4 h-4" style={{ color: "var(--sage)" }} />
                                    ) : (
                                        <X className="w-4 h-4" style={{ color: "var(--error)" }} />
                                    )}
                                </span>
                                <div className="flex-1">
                                    <div className="text-xs mb-1" style={{ color: "var(--text-muted)" }}>
                                        {q.topic_name} · Pregunta {i + 1}
                                    </div>
                                    <div className="font-display font-bold text-base md:text-lg leading-snug mb-2">
                                        {q.question}
                                    </div>
                                    <ul className="space-y-1 text-sm">
                                        {q.options.map((opt, oi) => {
                                            const isCorrect = oi === q.correct_index;
                                            const isSelected = oi === sel;
                                            return (
                                                <li
                                                    key={oi}
                                                    className="flex items-start gap-2 px-2 py-1 rounded"
                                                    style={{
                                                        background: isCorrect
                                                            ? "#eef2ec"
                                                            : isSelected
                                                              ? "#fbeeee"
                                                              : "transparent",
                                                        color: isCorrect
                                                            ? "var(--sage)"
                                                            : isSelected
                                                              ? "var(--error)"
                                                              : "var(--text-secondary)",
                                                    }}
                                                >
                                                    <span className="kbd" style={{ background: "white" }}>
                                                        {String.fromCharCode(65 + oi)}
                                                    </span>
                                                    <span className="flex-1">{opt}</span>
                                                </li>
                                            );
                                        })}
                                    </ul>
                                    {q.explanation && (
                                        <div
                                            className="mt-2 text-xs italic"
                                            style={{ color: "var(--text-muted)" }}
                                        >
                                            {q.explanation}
                                        </div>
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
