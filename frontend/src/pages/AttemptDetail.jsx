import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Loader2 } from "lucide-react";
import { getAttempt } from "@/lib/api";
import AttemptReview from "@/components/AttemptReview";

// Detalle de un intento del historial (/stats/intentos/:id). Reutiliza
// AttemptReview. Los intentos legacy sin snapshot se muestran degradados
// (solo agregado) desde el propio AttemptReview.
export default function AttemptDetail() {
    const { id } = useParams();
    const navigate = useNavigate();
    const [attempt, setAttempt] = useState(null);
    const [loading, setLoading] = useState(true);
    const [notFound, setNotFound] = useState(false);

    useEffect(() => {
        let alive = true;
        setLoading(true);
        setNotFound(false);
        getAttempt(id)
            .then((a) => { if (alive) setAttempt(a); })
            .catch(() => { if (alive) setNotFound(true); })
            .finally(() => { if (alive) setLoading(false); });
        return () => { alive = false; };
    }, [id]);

    return (
        <div className="max-w-3xl mx-auto px-5 md:px-8 py-8 md:py-12">
            <button
                onClick={() => navigate(-1)}
                data-testid="attempt-back"
                className="flex items-center gap-1.5 text-sm mb-6 hover:underline"
                style={{ color: "var(--text-secondary)" }}
            >
                <ArrowLeft className="w-4 h-4" /> Volver al historial
            </button>

            <span className="label-eyebrow">Intento</span>
            <h1 className="font-display text-3xl md:text-4xl font-bold mt-1 mb-6">Detalle del intento</h1>

            {loading ? (
                <div className="card-organic p-6 flex items-center gap-2 text-sm" style={{ color: "var(--text-muted)" }}>
                    <Loader2 className="w-4 h-4 animate-spin" /> Cargando…
                </div>
            ) : notFound ? (
                <div className="card-organic p-8 text-center" data-testid="attempt-not-found">
                    <h3 className="font-display text-xl font-bold">Intento no encontrado</h3>
                    <p className="mt-1 text-sm" style={{ color: "var(--text-muted)" }}>
                        Puede que se haya borrado o que no sea tuyo.
                    </p>
                </div>
            ) : (
                <AttemptReview
                    items={attempt.items}
                    score_10={attempt.score_10}
                    correct_count={attempt.correct_count}
                    wrong_count={attempt.wrong_count}
                    unanswered_count={attempt.unanswered_count}
                    total={attempt.total}
                    duration_seconds={attempt.duration_seconds}
                    behavior={attempt.behavior}
                    selection={attempt.selection}
                    createdAt={attempt.created_at}
                />
            )}
        </div>
    );
}
