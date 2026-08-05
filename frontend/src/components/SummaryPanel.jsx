import { BookOpenCheck, Loader2, RefreshCw, Download, FileText, Printer } from "lucide-react";
import { toast } from "sonner";
import {
    DropdownMenu,
    DropdownMenuTrigger,
    DropdownMenuContent,
    DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { summaryToMarkdown, downloadMarkdown, printSummaryAsPdf } from "@/lib/summaryExport";

// Render del resumen de IA (mismo aspecto que el panel histórico de TopicDetail).
// `summary` es el JSON estructurado de Gemini (overview/sections/remember).
// Cabecera con "Exportar" (Markdown/PDF, 100% cliente), "Regenerar" y "Cerrar".
export default function SummaryPanel({ summary, onRegenerate, regenerating = false, onClose, pdfFilename = "resumen" }) {
    if (!summary) return null;

    const onDownloadMd = () => {
        downloadMarkdown(summaryToMarkdown(summary, pdfFilename), pdfFilename);
        toast.success("Resumen descargado");
    };
    const onExportPdf = () => {
        try {
            printSummaryAsPdf(summary, pdfFilename);
        } catch {
            toast.error("Permite las ventanas emergentes para exportar a PDF");
        }
    };
    return (
        <div className="card-organic p-5 mb-2 fade-up" style={{ borderLeft: "3px solid var(--brand)" }} data-testid="summary-panel">
            <div className="flex items-center justify-between mb-3">
                <span className="label-eyebrow flex items-center gap-2">
                    <BookOpenCheck className="w-4 h-4" style={{ color: "var(--brand)" }} /> Resumen IA
                </span>
                <div className="flex items-center gap-3">
                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            <button
                                data-testid="summary-export"
                                className="text-xs hover:underline flex items-center gap-1"
                                style={{ color: "var(--brand)" }}
                            >
                                <Download className="w-3.5 h-3.5" /> Exportar
                            </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={onDownloadMd} data-testid="summary-export-md" className="gap-2 cursor-pointer">
                                <FileText className="w-4 h-4" /> Descargar Markdown (.md)
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={onExportPdf} data-testid="summary-export-pdf" className="gap-2 cursor-pointer">
                                <Printer className="w-4 h-4" /> Imprimir / Guardar PDF
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                    {onRegenerate && (
                        <button
                            onClick={onRegenerate}
                            disabled={regenerating}
                            data-testid="summary-regenerate"
                            className="text-xs hover:underline flex items-center gap-1 disabled:opacity-50"
                            style={{ color: "var(--brand)" }}
                        >
                            {regenerating ? (
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            ) : (
                                <RefreshCw className="w-3.5 h-3.5" />
                            )}
                            Regenerar
                        </button>
                    )}
                    {onClose && (
                        <button onClick={onClose} className="text-xs hover:underline" style={{ color: "var(--text-muted)" }}>
                            Cerrar
                        </button>
                    )}
                </div>
            </div>
            {summary.overview && (
                <p className="text-sm mb-4 leading-relaxed" style={{ color: "var(--text-secondary)" }}>{summary.overview}</p>
            )}
            {summary.sections?.map((s, i) => (
                <div key={i} className="mb-3">
                    <div className="font-display font-bold text-sm mb-1">{s.title}</div>
                    <ul className="space-y-1">
                        {s.points?.map((p, j) => (
                            <li key={j} className="text-sm flex gap-2" style={{ color: "var(--text-secondary)" }}>
                                <span style={{ color: "var(--brand)" }}>·</span>{p}
                            </li>
                        ))}
                    </ul>
                </div>
            ))}
            {summary.remember?.length > 0 && (
                <div className="mt-4 p-3 rounded-md" style={{ background: "var(--bg-secondary)" }}>
                    <div className="text-xs font-bold mb-2" style={{ color: "var(--brand)" }}>💡 RECUERDA</div>
                    <ul className="space-y-1">
                        {summary.remember.map((r, i) => (
                            <li key={i} className="text-xs flex gap-2" style={{ color: "var(--text-secondary)" }}>
                                <span>→</span>{r}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    );
}
