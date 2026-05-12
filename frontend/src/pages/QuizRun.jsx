import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, X, ChevronRight, Flag, Star, AlertCircle, Clock } from "lucide-react";
import { toast } from "sonner";
import { quizSubmit, toggleFavorite as apiFav, toggleDifficult as apiDiff } from "@/lib/api";

const MODE_LABELS = {
    practice: "Práctica",
    exam: "Examen",
    errors: "Errores",
    srs: "Repaso espaciado",
    favorites: "Favoritas",
};

function formatTime(sec) {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export default function QuizRun() {
    const navigate = useNavigate();
    const [quiz, setQuiz] = useState(null);
    const [idx, setIdx] = useState(0);
    const [answers, setAnswers] = useState([]); // per question selected index
    const [revealed, setRevealed] = useState(false); // practice mode
    const [elapsed, setElapsed] = useState(0);
    const startedRef = useRef(Date.now());
    const submittedRef = useRef(false);

    useEffect(() => {
        const raw = sessionStorage.getItem("current_quiz");
        if (!raw) {
            navigate("/quiz/setup");
            return;
        }
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

    const isExam = quiz?.mode === "exam";
    const timeLeft = useMemo(() => {
        if (!quiz?.time_limit_seconds) return null;
        return Math.max(0, quiz.time_limit_seconds - elapsed);
    }, [quiz, elapsed]);

    useEffect(() => {
        if (isExam && timeLeft === 0 && !submittedRef.current) {
            handleSubmit();
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [timeLeft, isExam]);

    if (!quiz) return null;
    const q = quiz.questions[idx];
    const selected = answers[idx];

    const onSelect = (optIdx) => {
        if (isExam) {
            const next = [...answers];
            next[idx] = optIdx;
            setAnswers(next);
        } else {
            if (revealed) return;
            const next = [...answers];
            next[idx] = optIdx;
            setAnswers(next);
            setRevealed(true);
        }
    };

    const onNext = () => {
        if (idx + 1 >= quiz.questions.length) {
            handleSubmit();
        } else {
            setIdx(idx + 1);
            setRevealed(false);
        }
    };

    const onPrev = () => {
        if (idx > 0) {
            setIdx(idx - 1);
            setRevealed(isExam ? false : answers[idx - 1] !== -1);
        }
    };

    const handleSubmit = async () => {
        if (submittedRef.current) return;
        submittedRef.current = true;
        try {
            const payload = {
                mode: quiz.mode,
                topic_ids: quiz.topic_ids || [],
                answers: quiz.questions.map((qq, i) => ({
                    question_id: qq.id,
                    selected: answers[i] ?? -1,
                    correct_index: qq.correct_index,
                })),
                duration_seconds: Math.floor((Date.now() - startedRef.current) / 1000),
                time_limit_seconds: quiz.time_limit_seconds || null,
            };
            const res = await quizSubmit(payload);
            sessionStorage.setItem(
                "quiz_result",
                JSON.stringify({
                    ...res,
                    questions: quiz.questions,
                    answers,
                    mode: quiz.mode,
                }),
            );
            navigate("/quiz/results");
        } catch (e) {
            toast.error("Error al enviar el examen");
            submittedRef.current = false;
        }
    };

    const toggleFav = async () => {
        try {
            const { favorite } = await apiFav(q.id);
            quiz.questions[idx] = { ...q, favorite };
            setQuiz({ ...quiz });
        } catch {
            toast.error("Error");
        }
    };
    const toggleDiff = async () => {
        try {
            const { difficult } = await apiDiff(q.id);
            quiz.questions[idx] = { ...q, difficult };
            setQuiz({ ...quiz });
        } catch {
            toast.error("Error");
        }
    };

    const answeredCount = answers.filter((a) => a !== -1).length;

    return (
        <div className="min-h-screen flex flex-col" style={{ background: "var(--bg-primary)" }}>
            <header
                className="border-b sticky top-0 z-30 backdrop-blur"
                style={{ borderColor: "var(--border)", background: "rgba(253,251,247,0.92)" }}
            >
                <div className="max-w-3xl mx-auto px-5 py-3 flex items-center justify-between gap-3">
                    <button
                        onClick={() => {
                            if (window.confirm("¿Salir? Perderás el progreso.")) navigate("/");
                        }}
                        data-testid="exit-quiz-btn"
                        className="text-sm font-medium hover:underline"
                        style={{ color: "var(--text-secondary)" }}
                    >
                        Salir
                    </button>
                    <div className="flex items-center gap-3 text-sm">
                        <span className="font-mono" data-testid="quiz-progress">
                            {idx + 1} / {quiz.questions.length}
                        </span>
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
                            <span
                                className="font-mono text-xs px-2 py-1 rounded-md"
                                style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
                            >
                                {MODE_LABELS[quiz.mode]}
                            </span>
                        )}
                    </div>
                </div>
                <div className="progress-track" style={{ borderRadius: 0, height: 3 }}>
                    <div
                        className="progress-fill"
                        style={{ width: `${((idx + 1) / quiz.questions.length) * 100}%` }}
                    />
                </div>
            </header>

            <main className="flex-1 max-w-3xl mx-auto w-full px-5 py-8">
                <div className="fade-up" key={idx}>
                    <div className="flex items-center justify-between mb-3">
                        <span className="label-eyebrow">{q.topic_name}</span>
                        <div className="flex gap-1">
                            <button
                                onClick={toggleFav}
                                data-testid="toggle-fav-btn"
                                className="p-1.5 rounded hover:bg-[color:var(--bg-secondary)]"
                                title="Favorita"
                            >
                                <Star
                                    className="w-4 h-4"
                                    fill={q.favorite ? "var(--warning)" : "none"}
                                    style={{ color: q.favorite ? "var(--warning)" : "var(--text-muted)" }}
                                />
                            </button>
                            <button
                                onClick={toggleDiff}
                                data-testid="toggle-diff-btn"
                                className="p-1.5 rounded hover:bg-[color:var(--bg-secondary)]"
                                title="Difícil"
                            >
                                <Flag
                                    className="w-4 h-4"
                                    fill={q.difficult ? "var(--error)" : "none"}
                                    style={{ color: q.difficult ? "var(--error)" : "var(--text-muted)" }}
                                />
                            </button>
                        </div>
                    </div>
                    <h2 className="font-display text-xl md:text-2xl font-bold mb-6 leading-snug">
                        {q.question}
                    </h2>

                    <div className="space-y-3 mb-6">
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
                                <button
                                    key={i}
                                    onClick={() => onSelect(i)}
                                    disabled={revealed && !isExam}
                                    data-testid={`option-${i}`}
                                    className={cls}
                                >
                                    <div className="flex items-center gap-3">
                                        <span
                                            className="kbd"
                                            style={{
                                                minWidth: "1.5rem",
                                                textAlign: "center",
                                                background: "white",
                                            }}
                                        >
                                            {String.fromCharCode(65 + i)}
                                        </span>
                                        <span className="flex-1 text-sm md:text-base">{opt}</span>
                                        {revealed && isCorrect && (
                                            <Check className="w-4 h-4" style={{ color: "var(--sage)" }} />
                                        )}
                                        {revealed && isSelected && !isCorrect && (
                                            <X className="w-4 h-4" style={{ color: "var(--error)" }} />
                                        )}
                                    </div>
                                </button>
                            );
                        })}
                    </div>

                    {revealed && q.explanation && (
                        <div
                            className="rounded-md p-4 border flex gap-3 fade-up mb-6"
                            style={{ borderColor: "var(--border)", background: "var(--bg-secondary)" }}
                            data-testid="explanation-box"
                        >
                            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" style={{ color: "var(--brand)" }} />
                            <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
                                <strong className="font-display" style={{ color: "var(--text-primary)" }}>
                                    Explicación:
                                </strong>{" "}
                                {q.explanation}
                            </div>
                        </div>
                    )}

                    <div className="flex items-center justify-between gap-3">
                        <button
                            onClick={onPrev}
                            disabled={idx === 0}
                            data-testid="prev-btn"
                            className="px-4 py-2 rounded-md border font-medium text-sm disabled:opacity-40"
                            style={{ borderColor: "var(--border)" }}
                        >
                            Anterior
                        </button>
                        <span className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                            {answeredCount} respondidas
                        </span>
                        {isExam ? (
                            idx + 1 === quiz.questions.length ? (
                                <button
                                    onClick={handleSubmit}
                                    data-testid="submit-exam-btn"
                                    className="btn-primary flex items-center gap-2 text-sm"
                                >
                                    Finalizar examen
                                </button>
                            ) : (
                                <button
                                    onClick={onNext}
                                    data-testid="next-btn"
                                    className="btn-primary flex items-center gap-2 text-sm"
                                >
                                    Siguiente <ChevronRight className="w-4 h-4" />
                                </button>
                            )
                        ) : (
                            <button
                                onClick={onNext}
                                disabled={!revealed}
                                data-testid="next-btn"
                                className="btn-primary flex items-center gap-2 text-sm"
                            >
                                {idx + 1 === quiz.questions.length ? "Ver resultado" : "Siguiente"}
                                <ChevronRight className="w-4 h-4" />
                            </button>
                        )}
                    </div>
                </div>
            </main>
        </div>
    );
}
