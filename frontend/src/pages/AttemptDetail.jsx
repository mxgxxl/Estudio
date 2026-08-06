import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Loader2, Download, FileText, FileDown } from "lucide-react";
import { toast } from "sonner";
import { getAttempt } from "@/lib/api";
import {
    DropdownMenu,
    DropdownMenuTrigger,
    DropdownMenuContent,
    DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import AttemptReview from "@/components/AttemptReview";
import { downloadAttemptMarkdown, exportAttemptAsPdf } from "@/lib/attemptExport";

// Detalle de un intento del historial (/stats/intentos/:id). Reutiliza
// AttemptReview. Los intentos legacy sin snapshot se muestran degradados
// (solo agregado) desde el propio AttemptReview.
export default function AttemptDetail() {
    const { id } = useParams();
    const navigate = useNavigate();
    const [attempt, setAttempt] = useState(null);
    const [loading, setLoading] = useState(true);
    const [notFound, setNotFound] = useState(false);
    const [exportingPdf, setExportingPdf] = useState(false);

    const onDownloadMd = () => {
        downloadAttemptMarkdown(attempt);
        toast.success("Intento descargado");
    };
    const onExportPdf = async () => {
        if (exportingPdf) return;
        setExportingPdf(true);
        try {
            await exportAttemptAsPdf(attempt);
        } catch {
            toast.error("Permite las ventanas emergentes para ver el PDF");
        } finally {
            setExportingPdf(false);
        }
    };

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
            <div className="flex items-center justify-between gap-3 mb-6">
                <button
                    onClick={() => navigate(-1)}
                    data-testid="attempt-back"
                    className="flex items-center gap-1.5 text-sm hover:underline"
                    style={{ color: "var(--text-secondary)" }}
                >
                    <ArrowLeft className="w-4 h-4" /> Volver al historial
                </button>
                {attempt && !loading && !notFound && (
                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            <button
                                data-testid="attempt-export"
                                className="px-3 py-1.5 rounded-md border text-sm font-medium flex items-center gap-1.5 hover:bg-[color:var(--bg-secondary)]"
                                style={{ borderColor: "var(--border)" }}
                            >
                                <Download className="w-4 h-4" /> Exportar
                            </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={onDownloadMd} data-testid="attempt-export-md" className="gap-2 cursor-pointer">
                                <FileText className="w-4 h-4" /> Descargar Markdown (.md)
                            </DropdownMenuItem>
                            <DropdownMenuItem
                                onSelect={(e) => { e.preventDefault(); onExportPdf(); }}
                                disabled={exportingPdf}
                                data-testid="attempt-export-pdf"
                                className="gap-2 cursor-pointer"
                            >
                                {exportingPdf ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileDown className="w-4 h-4" />}
                                Exportar a PDF
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                )}
            </div>

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
