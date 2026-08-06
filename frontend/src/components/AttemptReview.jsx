import { Check, X, MinusCircle, Pencil } from "lucide-react";
import { BEHAVIOR_LABELS, SELECTION_LABELS } from "@/lib/quizLabels";

// Desglose reutilizable de un intento. Alimentado por `items` con el shape del
// snapshot del backend (Attempt.items) o por un derivado equivalente construido en
// QuizResults desde sessionStorage. Campos por item:
//   { question_id, question_type, question, topic_name?, options, selected,
//     correct_index, is_correct?, explanation? }  y para dev, además:
//   { user_answer?, dev_score, feedback?, key_points_missing?, model_answer? }
// Extras (model_answer, explanation, key_points_missing, onEditModel) solo se
// pintan si vienen: un intento histórico sin ellos degrada de forma limpia.
export default function AttemptReview({
    items,
    score_10 = 0,
    correct_count = 0,
    wrong_count = 0,
    unanswered_count = 0,
    total = 0,
    duration_seconds = 0,
    behavior,
    selection,
    createdAt,
    showTiles = true,
    blanksPenalized = false,
    onEditModel,
}) {
    const hasItems = Array.isArray(items) && items.length > 0;
    const passed = score_10 >= 5;

    return (
        <div data-testid="attempt-review">
            {/* Chips de ejes + fecha/duración */}
            {(behavior || selection || createdAt) && (
                <div className="flex flex-wrap items-center gap-2 mb-3 text-xs" style={{ color: "var(--text-muted)" }}>
                    {behavior && (
                        <span className="px-2 py-0.5 rounded-md font-medium" style={{ background: "#fdf1ea", color: "var(--brand)" }}>
                            {BEHAVIOR_LABELS[behavior] || "Práctica"}
                        </span>
                    )}
                    {selection && (
                        <span className="px-2 py-0.5 rounded-md font-medium" style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}>
                            {SELECTION_LABELS[selection] || "Todas"}
                        </span>
                    )}
                    {createdAt && <span className="font-mono">{new Date(createdAt).toLocaleString("es-ES")}</span>}
                    {duration_seconds > 0 && <span className="font-mono">· {formatDuration(duration_seconds)}</span>}
                </div>
            )}

            {/* Tiles de nota + conteos */}
            {showTiles && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
                    <div className="card-organic p-5" data-testid="attempt-review-score">
                        <span className="label-eyebrow">Nota</span>
                        <div className="font-display text-5xl font-bold mt-1" style={{ color: passed ? "var(--sage)" : "var(--error)" }}>
                            {score_10}<span className="text-2xl" style={{ color: "var(--text-muted)" }}>/10</span>
                        </div>
                    </div>
                    <div className="card-organic p-5">
                        <span className="label-eyebrow">Resumen</span>
                        <div className="grid grid-cols-3 gap-2 mt-2 text-center">
                            <Tile icon={<Check className="w-4 h-4 mx-auto" style={{ color: "var(--sage)" }} />} value={correct_count} label="Aciertos" />
                            <Tile icon={<X className="w-4 h-4 mx-auto" style={{ color: "var(--error)" }} />} value={wrong_count} label="Fallos" />
                            <Tile icon={<MinusCircle className="w-4 h-4 mx-auto" style={{ color: "var(--text-muted)" }} />} value={unanswered_count} label="Blanco" />
                        </div>
                        {total > 0 && (
                            <div className="text-xs mt-3 font-mono text-right" style={{ color: "var(--text-muted)" }}>
                                {correct_count}/{total} correctas
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* Intento legacy sin snapshot: solo agregado */}
            {!hasItems ? (
                <div
                    className="card-organic p-4 text-sm"
                    style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
                    data-testid="attempt-review-legacy"
                >
                    Este es un intento antiguo. Solo se muestra el resumen agregado (sin desglose por pregunta).
                </div>
            ) : (
                <>
                    <span className="label-eyebrow block mb-3">Revisión pregunta a pregunta</span>
                    <div className="space-y-3">
                        {items.map((it, i) => (
                            <ReviewCard
                                key={it.question_id || i}
                                item={it}
                                index={i}
                                blanksPenalized={blanksPenalized}
                                onEditModel={onEditModel}
                            />
                        ))}
                    </div>
                </>
            )}
        </div>
    );
}

function Tile({ icon, value, label }) {
    return (
        <div>
            {icon}
            <div className="font-display text-2xl font-bold mt-1">{value}</div>
            <div className="text-xs" style={{ color: "var(--text-muted)" }}>{label}</div>
        </div>
    );
}

function ReviewCard({ item, index, blanksPenalized, onEditModel }) {
    const isDev = item.question_type === "dev";
    const sel = item.selected ?? -1;
    // Blanco en mcq/tf: "sin responder" salvo que los blancos penalicen (entonces error).
    const isUnanswered = !isDev && sel === -1 && !blanksPenalized;
    const ok = isDev
        ? (item.dev_score ?? 0) >= 5
        : (typeof item.is_correct === "boolean" ? item.is_correct : sel === item.correct_index) && !isUnanswered;

    return (
        <div className="card-organic p-4 md:p-5 fade-up" data-testid={`review-q-${index}`}>
            <div className="flex items-start gap-3">
                <span
                    className="w-7 h-7 rounded-md flex items-center justify-center shrink-0 mt-0.5"
                    style={{ background: isUnanswered ? "var(--bg-secondary)" : ok ? "#eef2ec" : "#fbeeee" }}
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
                        {item.topic_name ? `${item.topic_name} · ` : ""}Pregunta {index + 1} ·{" "}
                        {isDev ? "Desarrollo" : item.question_type === "tf" ? "V/F" : "Test"}
                        {!isDev && sel === -1 && blanksPenalized && (
                            <span style={{ color: "var(--error)" }}> · En blanco (penaliza)</span>
                        )}
                    </div>
                    <div className="font-display font-bold text-base md:text-lg leading-snug mb-3">{item.question}</div>

                    {isDev ? (
                        <DevBlock item={item} onEditModel={onEditModel} />
                    ) : (
                        <>
                            <ul className="space-y-1 text-sm">
                                {(item.options || []).map((opt, oi) => {
                                    const isCorrect = oi === item.correct_index;
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
                                                {item.question_type === "tf" ? (oi === 0 ? "V" : "F") : String.fromCharCode(65 + oi)}
                                            </span>
                                            <span className="flex-1">{opt}</span>
                                            {isCorrect && <Check className="w-3.5 h-3.5 shrink-0 mt-0.5" style={{ color: "var(--sage)" }} />}
                                        </li>
                                    );
                                })}
                            </ul>
                            {sel === -1 && !blanksPenalized && (
                                <div className="mt-2 text-xs" style={{ color: "var(--text-muted)" }}>Sin responder</div>
                            )}
                            {item.explanation && (
                                <div className="mt-2 text-xs italic" style={{ color: "var(--text-muted)" }}>{item.explanation}</div>
                            )}
                        </>
                    )}
                </div>
            </div>
        </div>
    );
}

function DevBlock({ item, onEditModel }) {
    const score = item.dev_score ?? 0;
    const passed = score >= 5;
    const missing = item.key_points_missing || [];

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between px-3 py-2 rounded-md" style={{ background: passed ? "#eef2ec" : "#fbeeee" }}>
                <span className="text-sm font-medium" style={{ color: passed ? "var(--sage)" : "var(--error)" }}>Puntuación obtenida</span>
                <span className="font-display font-bold text-xl" style={{ color: passed ? "var(--sage)" : "var(--error)" }}>{score}/10</span>
            </div>
            {item.user_answer && (
                <div>
                    <p className="text-xs font-medium mb-1" style={{ color: "var(--text-muted)" }}>Tu respuesta:</p>
                    <div className="rounded-md p-3 text-sm leading-relaxed" style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}>
                        {item.user_answer}
                    </div>
                </div>
            )}
            {item.feedback && <p className="text-sm" style={{ color: "var(--text-secondary)" }}>{item.feedback}</p>}
            {missing.length > 0 && (
                <div>
                    <p className="text-xs font-medium mb-1" style={{ color: "var(--text-muted)" }}>Puntos que faltaron:</p>
                    <ul className="list-disc list-inside text-xs space-y-0.5" style={{ color: "var(--text-secondary)" }}>
                        {missing.map((p, i) => <li key={i}>{p}</li>)}
                    </ul>
                </div>
            )}
            {/* Respuesta modelo SIEMPRE visible (alineada con la práctica inline de
                QuizRun); solo se pinta si viene (en el histórico no está → nada). */}
            {item.model_answer && (
                <div>
                    <p className="text-xs font-medium mb-1" style={{ color: "var(--text-muted)" }}>Respuesta modelo:</p>
                    <div className="rounded-md p-3 text-sm leading-relaxed" style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}>
                        {item.model_answer}
                    </div>
                </div>
            )}
            {onEditModel && (
                <button
                    onClick={() => onEditModel(item)}
                    data-testid={`edit-model-${item.question_id}`}
                    className="flex items-center gap-1 text-xs font-medium hover:underline"
                    style={{ color: "var(--text-secondary)" }}
                >
                    <Pencil className="w-3 h-3" /> Editar respuesta modelo
                </button>
            )}
            {item.explanation && (
                <div className="text-xs italic" style={{ color: "var(--text-muted)" }}>Puntos clave: {item.explanation}</div>
            )}
        </div>
    );
}

function formatDuration(seconds) {
    const s = Math.max(0, Math.floor(seconds));
    const m = Math.floor(s / 60);
    const rem = s % 60;
    return m > 0 ? `${m}m ${rem}s` : `${rem}s`;
}
