import { useEffect, useState, useRef, useCallback } from "react";
import { useNavigate, Link } from "react-router-dom";
import {
    Heart, Star, Zap, Trophy, RotateCcw, Home, Check, X,
    ChevronRight, Loader2, ArrowLeft, Sparkles
} from "lucide-react";
import { toast } from "sonner";
import { listSubjects, listSubjectTopics, api } from "@/lib/api";

const BONUS_STREAK = 5;
const BONUS_POINTS = 5;
const MAX_LIVES = 3;

function HeartDisplay({ lives }) {
    return (
        <div className="flex gap-1">
            {Array.from({ length: MAX_LIVES }).map((_, i) => (
                <Heart
                    key={i}
                    className="w-5 h-5"
                    fill={i < lives ? "var(--error)" : "none"}
                    style={{ color: i < lives ? "var(--error)" : "var(--border)" }}
                />
            ))}
        </div>
    );
}

function ScoreDisplay({ score, streak }) {
    return (
        <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5">
                <Trophy className="w-4 h-4" style={{ color: "var(--warning)" }} />
                <span className="font-display font-bold text-lg font-mono">{score}</span>
            </div>
            {streak >= 3 && (
                <div className="flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold"
                    style={{ background: "#fdf1ea", color: "var(--brand)" }}>
                    <Zap className="w-3 h-3" />
                    {streak} seguidas
                </div>
            )}
        </div>
    );
}

// Setup screen
function SurvivalSetup({ onStart }) {
    const [subjects, setSubjects] = useState([]);
    const [allTopics, setAllTopics] = useState({});
    const [scope, setScope] = useState(null); // { type: "topic"|"subject", id, name }
    const [questionType, setQuestionType] = useState("any");
    const [loading, setLoading] = useState(true);
    const [starting, setStarting] = useState(false);
    const [expandedSubject, setExpandedSubject] = useState(null);

    useEffect(() => {
        listSubjects()
            .then(subs => {
                setSubjects(subs);
                return Promise.all(subs.map(s => listSubjectTopics(s.id).then(ts => ({ id: s.id, topics: ts }))));
            })
            .then(arr => {
                const map = {};
                arr.forEach(x => (map[x.id] = x.topics));
                setAllTopics(map);
            })
            .catch(() => toast.error("Error cargando datos"))
            .finally(() => setLoading(false));
    }, []);

    const handleStart = async () => {
        if (!scope) return toast.error("Selecciona un tema o asignatura");
        setStarting(true);
        try {
            // Load all questions for the scope
            let questions = [];
            if (scope.type === "subject") {
                const topics = allTopics[scope.id] || [];
                const results = await Promise.all(
                    topics.map(t => api.get(`/topics/${t.id}/questions`).then(r => r.data))
                );
                questions = results.flat();
            } else {
                questions = await api.get(`/topics/${scope.id}/questions`).then(r => r.data);
            }

            // Filter by question type
            const filtered = questions.filter(q => {
                if (questionType === "any") return q.question_type !== "dev";
                return q.question_type === questionType;
            });

            if (filtered.length === 0) {
                toast.error("No hay preguntas disponibles para esta selección");
                return;
            }

            // Shuffle
            const shuffled = [...filtered].sort(() => Math.random() - 0.5);
            onStart({ scope, questionType, questions: shuffled });
        } catch {
            toast.error("Error al cargar preguntas");
        } finally {
            setStarting(false);
        }
    };

    if (loading) return (
        <div className="flex items-center justify-center py-20" style={{ color: "var(--text-muted)" }}>
            <Loader2 className="w-5 h-5 animate-spin mr-2" /> Cargando…
        </div>
    );

    return (
        <div className="max-w-2xl mx-auto px-5 md:px-8 py-8">
            <Link to="/" className="inline-flex items-center gap-1 text-sm font-medium mb-6 hover:underline" style={{ color: "var(--text-secondary)" }}>
                <ArrowLeft className="w-4 h-4" /> Volver
            </Link>
            <span className="label-eyebrow">Modo supervivencia</span>
            <h1 className="font-display text-3xl font-bold mt-1 mb-2">¿Cuánto aguantas?</h1>
            <p className="text-sm mb-8" style={{ color: "var(--text-secondary)" }}>
                Responde preguntas sin límite · +1 por acierto · +{BONUS_POINTS} cada {BONUS_STREAK} seguidas · {MAX_LIVES} fallos y fin
            </p>

            {/* Scope selector */}
            <div className="mb-6">
                <span className="label-eyebrow block mb-3">Selecciona un tema o asignatura completa</span>
                <div className="space-y-2">
                    {subjects.map(s => {
                        const topics = allTopics[s.id] || [];
                        const isSubjectSelected = scope?.type === "subject" && scope.id === s.id;
                        const expanded = expandedSubject === s.id;
                        return (
                            <div key={s.id} className="rounded-md border overflow-hidden" style={{ borderColor: isSubjectSelected ? s.color : "var(--border)" }}>
                                {/* Subject row */}
                                <div className="flex items-center gap-2">
                                    <button
                                        onClick={() => setScope({ type: "subject", id: s.id, name: s.name })}
                                        className="flex-1 flex items-center gap-3 p-3 text-left transition-colors hover:bg-[color:var(--bg-secondary)]"
                                        style={{ background: isSubjectSelected ? `${s.color}12` : "white" }}
                                    >
                                        <span className="w-3 h-3 rounded-full shrink-0" style={{ background: s.color }} />
                                        <span className="font-medium text-sm">{s.name}</span>
                                        <span className="text-xs font-mono px-1.5 py-0.5 rounded-sm ml-auto" style={{ background: "var(--bg-secondary)", color: "var(--text-muted)" }}>
                                            {s.question_count} preg.
                                        </span>
                                        {isSubjectSelected && <Check className="w-4 h-4 shrink-0" style={{ color: s.color }} />}
                                    </button>
                                    {topics.length > 0 && (
                                        <button
                                            onClick={() => setExpandedSubject(expanded ? null : s.id)}
                                            className="px-3 py-3 text-xs hover:bg-[color:var(--bg-secondary)] border-l"
                                            style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
                                        >
                                            {expanded ? "▲" : "▼"} temas
                                        </button>
                                    )}
                                </div>
                                {/* Topics */}
                                {expanded && topics.map(t => {
                                    const isTopicSelected = scope?.type === "topic" && scope.id === t.id;
                                    return (
                                        <button
                                            key={t.id}
                                            onClick={() => setScope({ type: "topic", id: t.id, name: t.name })}
                                            className="w-full flex items-center gap-3 px-4 py-2.5 text-left border-t transition-colors hover:bg-[color:var(--bg-secondary)]"
                                            style={{
                                                borderColor: "var(--border)",
                                                background: isTopicSelected ? "#fdf1ea" : "var(--bg-secondary)",
                                            }}
                                        >
                                            <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: s.color }} />
                                            <span className="text-sm">{t.name}</span>
                                            <span className="text-xs font-mono ml-auto" style={{ color: "var(--text-muted)" }}>{t.question_count}</span>
                                            {isTopicSelected && <Check className="w-3.5 h-3.5 shrink-0" style={{ color: "var(--brand)" }} />}
                                        </button>
                                    );
                                })}
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* Question type */}
            <div className="mb-8">
                <span className="label-eyebrow block mb-3">Tipo de pregunta</span>
                <div className="grid grid-cols-3 gap-2">
                    {[{ id: "any", label: "Ambos" }, { id: "mcq", label: "Test" }, { id: "tf", label: "V/F" }].map(t => (
                        <button key={t.id} onClick={() => setQuestionType(t.id)}
                            className="px-3 py-2 rounded-md border text-sm font-medium transition-all"
                            style={{ borderColor: questionType === t.id ? "var(--brand)" : "var(--border)", background: questionType === t.id ? "#fdf1ea" : "white" }}>
                            {t.label}
                        </button>
                    ))}
                </div>
            </div>

            <button onClick={handleStart} disabled={!scope || starting}
                className="btn-primary w-full flex items-center justify-center gap-2">
                {starting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
                Empezar supervivencia
            </button>
        </div>
    );
}

// Game over screen
function GameOver({ score, questionsAnswered, livesLost, scope, questionType, bestScore, isNewRecord, onRestart }) {
    return (
        <div className="max-w-lg mx-auto px-5 py-12 text-center fade-up">
            <div className="text-5xl mb-4">{isNewRecord ? "🏆" : livesLost === MAX_LIVES ? "💀" : "🎉"}</div>
            <h1 className="font-display text-3xl font-bold mb-1">
                {isNewRecord ? "¡Nuevo récord!" : livesLost === MAX_LIVES ? "Eliminado" : "¡Completado!"}
            </h1>
            <p className="text-sm mb-8" style={{ color: "var(--text-secondary)" }}>{scope.name}</p>

            <div className="card-organic p-6 mb-6">
                <div className="font-display text-6xl font-bold mb-1" style={{ color: "var(--warning)" }}>{score}</div>
                <div className="text-sm mb-4" style={{ color: "var(--text-muted)" }}>puntos</div>
                <div className="grid grid-cols-2 gap-4 text-center">
                    <div>
                        <div className="font-display text-2xl font-bold">{questionsAnswered}</div>
                        <div className="text-xs" style={{ color: "var(--text-muted)" }}>respondidas</div>
                    </div>
                    <div>
                        <div className="font-display text-2xl font-bold" style={{ color: "var(--error)" }}>{livesLost}</div>
                        <div className="text-xs" style={{ color: "var(--text-muted)" }}>fallos</div>
                    </div>
                </div>
                {!isNewRecord && bestScore > 0 && (
                    <div className="mt-4 text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                        Récord: {bestScore} pts
                    </div>
                )}
            </div>

            <div className="flex gap-3 justify-center">
                <button onClick={onRestart} className="btn-primary flex items-center gap-2">
                    <RotateCcw className="w-4 h-4" /> Intentar de nuevo
                </button>
                <Link to="/" className="px-5 py-2.5 rounded-md border font-medium text-sm flex items-center gap-2"
                    style={{ borderColor: "var(--border)" }}>
                    <Home className="w-4 h-4" /> Inicio
                </Link>
            </div>
        </div>
    );
}

// Main game
function SurvivalGame({ gameData, onGameOver }) {
    const [idx, setIdx] = useState(0);
    const [lives, setLives] = useState(MAX_LIVES);
    const [score, setScore] = useState(0);
    const [streak, setStreak] = useState(0);
    const [answered, setAnswered] = useState(false);
    const [selected, setSelected] = useState(null);
    const [bonusAnim, setBonusAnim] = useState(false);
    const [shakeAnim, setShakeAnim] = useState(false);

    const { questions, scope } = gameData;
    const q = questions[idx];
    const isTF = q?.question_type === "tf";

    // Shuffle options for mcq
    const [shuffledQ, setShuffledQ] = useState(null);
    useEffect(() => {
        if (!q) return;
        if (q.question_type === "mcq") {
            const order = [...q.options.map((_, i) => i)].sort(() => Math.random() - 0.5);
            setShuffledQ({
                options: order.map(i => q.options[i]),
                correct_index: order.indexOf(q.correct_index),
            });
        } else {
            setShuffledQ({ options: q.options, correct_index: q.correct_index });
        }
        setAnswered(false);
        setSelected(null);
    }, [idx, q]);

    const handleSelect = (optIdx) => {
        if (answered) return;
        setSelected(optIdx);
        setAnswered(true);

        const correct = optIdx === shuffledQ.correct_index;

        if (correct) {
            const newStreak = streak + 1;
            setStreak(newStreak);
            let pts = 1;
            if (newStreak % BONUS_STREAK === 0) {
                pts += BONUS_POINTS;
                setBonusAnim(true);
                setTimeout(() => setBonusAnim(false), 1500);
            }
            setScore(s => s + pts);
        } else {
            setStreak(0);
            setShakeAnim(true);
            setTimeout(() => setShakeAnim(false), 600);
            const newLives = lives - 1;
            setLives(newLives);
            if (newLives === 0) {
                setTimeout(() => onGameOver(score + (correct ? 1 : 0), idx + 1, MAX_LIVES - newLives), 1200);
                return;
            }
        }
    };

    const handleNext = () => {
        if (idx + 1 >= questions.length) {
            // Completed all questions!
            onGameOver(score, questions.length, MAX_LIVES - lives);
        } else {
            setIdx(i => i + 1);
        }
    };

    if (!q || !shuffledQ) return null;

    return (
        <div className="min-h-screen flex flex-col" style={{ background: "var(--bg-primary)" }}>
            {/* Header */}
            <header className="border-b sticky top-0 z-30 backdrop-blur"
                style={{ borderColor: "var(--border)", background: "rgba(253,251,247,0.95)" }}>
                <div className="max-w-2xl mx-auto px-5 py-3 flex items-center justify-between">
                    <HeartDisplay lives={lives} />
                    <div className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                        {idx + 1} / {questions.length}
                    </div>
                    <ScoreDisplay score={score} streak={streak} />
                </div>
                <div className="progress-track" style={{ borderRadius: 0, height: 3 }}>
                    <div className="progress-fill" style={{ width: `${((idx + 1) / questions.length) * 100}%`, background: "var(--warning)" }} />
                </div>
            </header>

            <main className="flex-1 max-w-2xl mx-auto w-full px-5 py-8">
                {/* Bonus animation */}
                {bonusAnim && (
                    <div className="text-center mb-4 fade-up">
                        <span className="inline-flex items-center gap-1 px-4 py-2 rounded-full font-display font-bold text-lg"
                            style={{ background: "#fdf1ea", color: "var(--brand)" }}>
                            <Sparkles className="w-4 h-4" /> +{BONUS_POINTS} puntos extra · {BONUS_STREAK} seguidas!
                        </span>
                    </div>
                )}

                <div className={`fade-up ${shakeAnim ? "animate-shake" : ""}`} key={idx}>
                    <span className="label-eyebrow block mb-3">
                        {q.topic_name} · {isTF ? "V/F" : "Test"}
                    </span>
                    <h2 className="font-display text-xl md:text-2xl font-bold mb-6 leading-snug">{q.question}</h2>

                    <div className={`mb-6 ${isTF ? "grid grid-cols-2 gap-3" : "space-y-3"}`}>
                        {shuffledQ.options.map((opt, i) => {
                            const isSelected = selected === i;
                            const isCorrect = i === shuffledQ.correct_index;
                            let cls = "option-pill";
                            if (answered) {
                                if (isCorrect) cls += " correct";
                                else if (isSelected) cls += " wrong";
                            } else if (isSelected) {
                                cls += " selected";
                            }
                            return (
                                <button key={i} onClick={() => handleSelect(i)} disabled={answered}
                                    className={cls}>
                                    <div className="flex items-center gap-3">
                                        <span className="kbd" style={{ minWidth: "1.5rem", textAlign: "center", background: "white" }}>
                                            {isTF ? (i === 0 ? "V" : "F") : String.fromCharCode(65 + i)}
                                        </span>
                                        <span className="flex-1 text-sm md:text-base">{opt}</span>
                                        {answered && isCorrect && <Check className="w-4 h-4" style={{ color: "var(--sage)" }} />}
                                        {answered && isSelected && !isCorrect && <X className="w-4 h-4" style={{ color: "var(--error)" }} />}
                                    </div>
                                </button>
                            );
                        })}
                    </div>

                    {answered && q.explanation && (
                        <div className="rounded-md p-3 text-sm mb-4 fade-up"
                            style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}>
                            {q.explanation}
                        </div>
                    )}

                    {answered && lives > 0 && (
                        <button onClick={handleNext} className="btn-primary w-full flex items-center justify-center gap-2 fade-up">
                            {idx + 1 >= questions.length ? "Ver resultado" : "Siguiente"}
                            <ChevronRight className="w-4 h-4" />
                        </button>
                    )}
                </div>
            </main>
        </div>
    );
}

export default function SurvivalMode() {
    const [phase, setPhase] = useState("setup"); // setup | game | gameover
    const [gameData, setGameData] = useState(null);
    const [gameResult, setGameResult] = useState(null);
    const [bestScore, setBestScore] = useState(0);
    const [isNewRecord, setIsNewRecord] = useState(false);

    const handleStart = (data) => {
        setGameData(data);
        setPhase("game");
    };

    const handleGameOver = async (score, questionsAnswered, livesLost) => {
        const { scope, questionType } = gameData;
        setGameResult({ score, questionsAnswered, livesLost });

        try {
            const res = await api.post("/survival/records", {
                scope_type: scope.type,
                scope_id: scope.id,
                scope_name: scope.name,
                score,
                questions_answered: questionsAnswered,
                lives_lost: livesLost,
                question_type: questionType,
            });
            setBestScore(res.data.best_score);
            setIsNewRecord(res.data.new_record);
        } catch {
            // Ignore save errors
        }
        setPhase("gameover");
    };

    const handleRestart = () => {
        setPhase("setup");
        setGameData(null);
        setGameResult(null);
        setIsNewRecord(false);
    };

    if (phase === "setup") return <SurvivalSetup onStart={handleStart} />;
    if (phase === "game") return <SurvivalGame gameData={gameData} onGameOver={handleGameOver} />;
    if (phase === "gameover") return (
        <GameOver
            score={gameResult.score}
            questionsAnswered={gameResult.questionsAnswered}
            livesLost={gameResult.livesLost}
            scope={gameData.scope}
            questionType={gameData.questionType}
            bestScore={bestScore}
            isNewRecord={isNewRecord}
            onRestart={handleRestart}
        />
    );
}
