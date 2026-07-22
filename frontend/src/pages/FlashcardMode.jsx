import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import {
    ArrowLeft, RotateCcw, Check, X, Star, ChevronLeft,
    ChevronRight, Sparkles, Loader2, BookOpen
} from "lucide-react";
import { toast } from "sonner";
import { api, getTopic, getTopicPdfs, generateTopicFlashcards } from "@/lib/api";
import PdfSelectDialog from "@/components/PdfSelectDialog";

function FlipCard({ card, flipped, onFlip, onCorrect, onWrong, isLast, onFinish }) {
    return (
        <div className="flex flex-col items-center w-full max-w-xl mx-auto">
            {/* Card */}
            <div
                onClick={onFlip}
                className="w-full cursor-pointer select-none"
                style={{ perspective: "1000px" }}
            >
                <div
                    style={{
                        position: "relative",
                        transformStyle: "preserve-3d",
                        transition: "transform 0.45s cubic-bezier(0.4,0,0.2,1)",
                        transform: flipped ? "rotateY(180deg)" : "rotateY(0deg)",
                        minHeight: "280px",
                    }}
                >
                    {/* Front */}
                    <div
                        className="absolute inset-0 rounded-xl border p-8 flex flex-col items-center justify-center text-center"
                        style={{
                            backfaceVisibility: "hidden",
                            WebkitBackfaceVisibility: "hidden",
                            borderColor: "var(--border)",
                            background: "white",
                            boxShadow: "0 4px 24px rgba(35,33,31,0.08)",
                        }}
                    >
                        <span className="label-eyebrow mb-4">Término</span>
                        <h2 className="font-display text-2xl md:text-3xl font-bold leading-snug">
                            {card.term}
                        </h2>
                        <p className="text-xs mt-6" style={{ color: "var(--text-muted)" }}>
                            Toca para ver la definición
                        </p>
                    </div>

                    {/* Back */}
                    <div
                        className="absolute inset-0 rounded-xl border p-8 flex flex-col items-center justify-center text-center"
                        style={{
                            backfaceVisibility: "hidden",
                            WebkitBackfaceVisibility: "hidden",
                            transform: "rotateY(180deg)",
                            borderColor: "var(--brand)",
                            background: "#fdf1ea",
                            boxShadow: "0 4px 24px rgba(198,93,71,0.12)",
                        }}
                    >
                        <span className="label-eyebrow mb-4" style={{ color: "var(--brand)" }}>Definición</span>
                        <p className="text-base md:text-lg leading-relaxed" style={{ color: "var(--text-primary)" }}>
                            {card.definition}
                        </p>
                        {card.example && (
                            <div
                                className="mt-4 px-4 py-2 rounded-md text-sm italic"
                                style={{ background: "rgba(198,93,71,0.08)", color: "var(--text-secondary)" }}
                            >
                                Ej: {card.example}
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {/* Actions after flip */}
            {flipped && (
                <div className="flex gap-3 mt-6 w-full fade-up">
                    <button
                        onClick={onWrong}
                        className="flex-1 flex items-center justify-center gap-2 py-3 rounded-xl font-medium text-sm border-2 transition-all hover:-translate-y-0.5"
                        style={{ borderColor: "var(--error)", color: "var(--error)", background: "#fbeeee" }}
                    >
                        <X className="w-4 h-4" /> No lo sabía
                    </button>
                    <button
                        onClick={onCorrect}
                        className="flex-1 flex items-center justify-center gap-2 py-3 rounded-xl font-medium text-sm border-2 transition-all hover:-translate-y-0.5"
                        style={{ borderColor: "var(--sage)", color: "var(--sage)", background: "#eef2ec" }}
                    >
                        <Check className="w-4 h-4" /> Lo sabía
                    </button>
                </div>
            )}
        </div>
    );
}

export default function FlashcardMode() {
    const { id: topicId } = useParams();
    const navigate = useNavigate();
    const [topic, setTopic] = useState(null);
    const [cards, setCards] = useState([]);
    const [idx, setIdx] = useState(0);
    const [flipped, setFlipped] = useState(false);
    const [results, setResults] = useState([]); // { cardId, correct }
    const [finished, setFinished] = useState(false);
    const [generating, setGenerating] = useState(false);
    const [loading, setLoading] = useState(true);
    const [numCards, setNumCards] = useState(15);
    const [pdfs, setPdfs] = useState([]);
    const [pickOpen, setPickOpen] = useState(false); // selector de PDFs (temas con >1 PDF)

    const loadCards = useCallback(async () => {
        setLoading(true);
        try {
            const [t, res, ps] = await Promise.all([
                getTopic(topicId),
                api.get(`/topics/${topicId}/flashcards`),
                getTopicPdfs(topicId),
            ]);
            setTopic(t);
            setCards(res.data);
            setPdfs(ps);
        } catch {
            toast.error("Error al cargar flashcards");
        } finally {
            setLoading(false);
        }
    }, [topicId]);

    useEffect(() => { loadCards(); }, [loadCards]);

    // Genera con los PDFs indicados (null = todos). Reemplazo por PDF en el
    // backend: al regenerar un subconjunto se conservan las demás y su progreso.
    const runGenerate = async (pdfIds = null) => {
        setGenerating(true);
        try {
            const data = await generateTopicFlashcards(topicId, numCards, pdfIds);
            setCards(data.flashcards);
            setIdx(0);
            setFlipped(false);
            setResults([]);
            setFinished(false);
            setPickOpen(false);
            toast.success(`${data.flashcards_created} flashcards generadas`);
        } catch (e) {
            toast.error(e?.response?.data?.detail || "Error al generar flashcards");
        } finally {
            setGenerating(false);
        }
    };

    // Con >1 PDF abre el selector; con ≤1 PDF genera directo (un clic).
    const generate = () => {
        if (pdfs.length > 1) { setPickOpen(true); return; }
        runGenerate(null);
    };

    const handleCorrect = async () => {
        const card = cards[idx];
        setResults(r => [...r, { cardId: card.id, correct: true }]);
        try { await api.post(`/flashcards/${card.id}/review?correct=true`); } catch {}
        advance();
    };

    const handleWrong = async () => {
        const card = cards[idx];
        setResults(r => [...r, { cardId: card.id, correct: false }]);
        try { await api.post(`/flashcards/${card.id}/review?correct=false`); } catch {}
        advance();
    };

    const advance = () => {
        if (idx + 1 >= cards.length) {
            setFinished(true);
        } else {
            setIdx(i => i + 1);
            setFlipped(false);
        }
    };

    const restart = () => {
        setIdx(0);
        setFlipped(false);
        setResults([]);
        setFinished(false);
    };

    const toggleFav = async (cardId) => {
        try {
            const res = await api.post(`/flashcards/${cardId}/favorite`);
            setCards(cs => cs.map(c => c.id === cardId ? { ...c, favorite: res.data.favorite } : c));
        } catch { toast.error("Error"); }
    };

    if (loading) {
        return (
            <div className="max-w-2xl mx-auto px-5 py-16 flex items-center justify-center" style={{ color: "var(--text-muted)" }}>
                <Loader2 className="w-5 h-5 animate-spin mr-2" /> Cargando…
            </div>
        );
    }

    const correctCount = results.filter(r => r.correct).length;
    const wrongCount = results.filter(r => !r.correct).length;

    // ---- Finished screen ----
    if (finished) {
        const pct = results.length ? Math.round((correctCount / results.length) * 100) : 0;
        return (
            <div className="max-w-2xl mx-auto px-5 md:px-8 py-12 text-center fade-up">
                <span className="label-eyebrow">Sesión completada</span>
                <h1 className="font-display text-3xl font-bold mt-2 mb-6">
                    {pct >= 70 ? "¡Muy bien!" : "Sigue practicando"}
                </h1>
                <div className="card-organic p-6 mb-6">
                    <div className="font-display text-5xl font-bold mb-1" style={{ color: pct >= 70 ? "var(--sage)" : "var(--error)" }}>
                        {pct}%
                    </div>
                    <div className="text-sm" style={{ color: "var(--text-muted)" }}>de aciertos</div>
                    <div className="grid grid-cols-2 gap-4 mt-4 text-center">
                        <div>
                            <div className="font-display text-2xl font-bold" style={{ color: "var(--sage)" }}>{correctCount}</div>
                            <div className="text-xs" style={{ color: "var(--text-muted)" }}>Sabías</div>
                        </div>
                        <div>
                            <div className="font-display text-2xl font-bold" style={{ color: "var(--error)" }}>{wrongCount}</div>
                            <div className="text-xs" style={{ color: "var(--text-muted)" }}>No sabías</div>
                        </div>
                    </div>
                </div>
                <div className="flex flex-wrap gap-3 justify-center">
                    <button onClick={restart} className="btn-primary flex items-center gap-2">
                        <RotateCcw className="w-4 h-4" /> Repetir
                    </button>
                    <Link
                        to={`/temas/${topicId}`}
                        className="px-5 py-2.5 rounded-md border font-medium text-sm flex items-center gap-2"
                        style={{ borderColor: "var(--border)" }}
                    >
                        <ArrowLeft className="w-4 h-4" /> Volver al tema
                    </Link>
                </div>
            </div>
        );
    }

    // Selector de PDFs (solo se abre en temas con >1 PDF). Incluye el nº de
    // tarjetas para que la elección sea completa en un solo sitio.
    const pickDialog = (
        <PdfSelectDialog
            open={pickOpen}
            onClose={() => setPickOpen(false)}
            title="Generar flashcards"
            subtitle="Elige de qué PDFs generar las tarjetas"
            pdfs={pdfs}
            loading={generating}
            loadingText="Generando…"
            submitLabel="Generar flashcards"
            onSubmit={(ids) => runGenerate(ids)}
        >
            <div className="flex items-center gap-3">
                <label className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
                    Nº de tarjetas:
                </label>
                <input
                    type="number"
                    min={5} max={30}
                    value={numCards}
                    onChange={(e) => setNumCards(parseInt(e.target.value) || 15)}
                    disabled={generating}
                    className="w-16 p-1.5 border rounded text-center text-sm"
                    style={{ borderColor: "var(--border)" }}
                />
            </div>
        </PdfSelectDialog>
    );

    // ---- Empty state ----
    if (cards.length === 0) {
        return (
            <div className="max-w-2xl mx-auto px-5 md:px-8 py-12">
                {pickDialog}
                <Link to={`/temas/${topicId}`} className="inline-flex items-center gap-1 text-sm font-medium mb-6 hover:underline" style={{ color: "var(--text-secondary)" }}>
                    <ArrowLeft className="w-4 h-4" /> Volver
                </Link>
                <div className="text-center card-organic p-10 fade-up">
                    <BookOpen className="w-12 h-12 mx-auto mb-4" style={{ color: "var(--brand)" }} />
                    <h2 className="font-display text-2xl font-bold mb-2">Sin flashcards todavía</h2>
                    <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>
                        Genera flashcards automáticamente a partir de los PDFs del tema.
                    </p>
                    <div className="flex items-center justify-center gap-3 mb-4">
                        <label className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
                            Nº de tarjetas:
                        </label>
                        <input
                            type="number"
                            min={5} max={30}
                            value={numCards}
                            onChange={e => setNumCards(parseInt(e.target.value) || 15)}
                            className="w-16 p-1.5 border rounded text-center text-sm"
                            style={{ borderColor: "var(--border)" }}
                        />
                    </div>
                    <button onClick={generate} disabled={generating} className="btn-primary flex items-center gap-2 mx-auto">
                        {generating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                        {generating ? "Generando…" : "Generar flashcards con IA"}
                    </button>
                    {generating && (
                        <p className="text-xs mt-3" style={{ color: "var(--text-muted)" }}>
                            Esto puede tardar hasta ~1 min. No cierres esta ventana.
                        </p>
                    )}
                </div>
            </div>
        );
    }

    const card = cards[idx];
    const progress = ((idx + 1) / cards.length) * 100;

    // ---- Main card view ----
    return (
        <div className="max-w-2xl mx-auto px-5 md:px-8 py-8">
            {pickDialog}
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <Link to={`/temas/${topicId}`} className="inline-flex items-center gap-1 text-sm font-medium hover:underline" style={{ color: "var(--text-secondary)" }}>
                    <ArrowLeft className="w-4 h-4" /> {topic?.name}
                </Link>
                <div className="flex items-center gap-3">
                    <button
                        onClick={() => toggleFav(card.id)}
                        className="p-1.5 rounded hover:bg-[color:var(--bg-secondary)]"
                        title="Favorita"
                    >
                        <Star className="w-4 h-4" fill={card.favorite ? "var(--warning)" : "none"} style={{ color: card.favorite ? "var(--warning)" : "var(--text-muted)" }} />
                    </button>
                    <button
                        onClick={generate}
                        disabled={generating}
                        className="text-xs flex items-center gap-1 px-2.5 py-1.5 rounded-md border hover:bg-[color:var(--bg-secondary)]"
                        style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
                        title="Regenerar flashcards"
                    >
                        {generating ? <Loader2 className="w-3 h-3 animate-spin" /> : <RotateCcw className="w-3 h-3" />}
                        Regenerar
                    </button>
                </div>
            </div>

            {/* Progress */}
            <div className="flex items-center justify-between mb-2 text-xs" style={{ color: "var(--text-muted)" }}>
                <span>{idx + 1} / {cards.length}</span>
                <span className="font-mono">{correctCount} ✓ · {wrongCount} ✗</span>
            </div>
            <div className="progress-track mb-6" style={{ height: 4 }}>
                <div className="progress-fill" style={{ width: `${progress}%` }} />
            </div>

            {/* Flip card */}
            <FlipCard
                card={card}
                flipped={flipped}
                onFlip={() => setFlipped(f => !f)}
                onCorrect={handleCorrect}
                onWrong={handleWrong}
                isLast={idx + 1 === cards.length}
                onFinish={() => setFinished(true)}
            />

            {/* Nav arrows */}
            <div className="flex justify-center gap-4 mt-8">
                <button
                    onClick={() => { setIdx(i => Math.max(0, i - 1)); setFlipped(false); }}
                    disabled={idx === 0}
                    className="p-2 rounded-full border disabled:opacity-30"
                    style={{ borderColor: "var(--border)" }}
                >
                    <ChevronLeft className="w-5 h-5" style={{ color: "var(--text-secondary)" }} />
                </button>
                <button
                    onClick={() => { setIdx(i => Math.min(cards.length - 1, i + 1)); setFlipped(false); }}
                    disabled={idx === cards.length - 1}
                    className="p-2 rounded-full border disabled:opacity-30"
                    style={{ borderColor: "var(--border)" }}
                >
                    <ChevronRight className="w-5 h-5" style={{ color: "var(--text-secondary)" }} />
                </button>
            </div>
        </div>
    );
}
