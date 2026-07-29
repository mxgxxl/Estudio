import { useEffect, useMemo, useState } from "react";
import { BookOpenCheck, Search, ChevronDown, ChevronUp } from "lucide-react";
import { toast } from "sonner";
import { listSummaries, listSubjects, generatePdfSummary } from "@/lib/api";
import SummaryPanel from "@/components/SummaryPanel";

// Pestaña "Resúmenes" de Biblioteca: lista global de los resúmenes de IA del
// usuario (uno por PDF, compartido entre temas). Orientada a leer/repasar: cada
// fila se despliega y reutiliza SummaryPanel. Filtros mínimos: asignatura +
// buscador por nombre de PDF. Regenerar reusa POST /pdfs/{id}/summary.
export default function LibrarySummaries() {
    const [rows, setRows] = useState(null);
    const [subjects, setSubjects] = useState([]);
    const [subjectId, setSubjectId] = useState("");
    const [query, setQuery] = useState("");
    const [openId, setOpenId] = useState(null); // pdf_id de la fila abierta
    const [regenId, setRegenId] = useState(null);

    useEffect(() => {
        Promise.all([listSummaries(), listSubjects()])
            .then(([ss, subs]) => {
                setRows(ss);
                setSubjects(subs);
            })
            .catch(() => {
                toast.error("No se pudieron cargar los resúmenes");
                setRows([]);
            });
    }, []);

    // Filtro por asignatura = membership (coincide si CUALQUIERA de sus
    // asignaturas encaja, porque un PDF compartido pertenece a varias).
    const filtered = useMemo(() => {
        if (!rows) return [];
        const q = query.trim().toLowerCase();
        return rows.filter((r) => {
            const bySubject = !subjectId || (r.subjects || []).some((s) => s.id === subjectId);
            const byName = !q || (r.pdf_filename || "").toLowerCase().includes(q);
            return bySubject && byName;
        });
    }, [rows, subjectId, query]);

    const regenerate = async (pdfId) => {
        setRegenId(pdfId);
        try {
            const updated = await generatePdfSummary(pdfId);
            setRows((rs) =>
                rs.map((r) =>
                    r.pdf_id === pdfId
                        ? { ...r, content: updated.content, updated_at: updated.updated_at }
                        : r
                )
            );
            toast.success("Resumen regenerado");
        } catch (err) {
            toast.error(err?.response?.data?.detail || "Error al regenerar el resumen");
        } finally {
            setRegenId(null);
        }
    };

    if (rows === null) {
        return <div style={{ color: "var(--text-muted)" }}>Cargando…</div>;
    }

    const selectCls = "px-3 py-2 rounded-md border text-sm";
    const selectStyle = { borderColor: "var(--border)" };

    return (
        <div>
            <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>
                Los resúmenes que has generado de tus PDFs. Ábrelos para repasar o regenéralos.
            </p>

            <div className="flex flex-wrap gap-2 mb-5">
                <div className="relative flex-1 min-w-[200px]">
                    <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: "var(--text-muted)" }} />
                    <input
                        type="text"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Buscar por nombre de PDF…"
                        data-testid="summaries-search"
                        className="w-full pl-9 pr-3 py-2 rounded-md border text-sm"
                        style={{ borderColor: "var(--border)" }}
                    />
                </div>
                <select
                    value={subjectId}
                    onChange={(e) => setSubjectId(e.target.value)}
                    className={selectCls}
                    style={selectStyle}
                    data-testid="summaries-subject"
                >
                    <option value="">Todas las asignaturas</option>
                    {subjects.map((s) => (
                        <option key={s.id} value={s.id}>{s.name}</option>
                    ))}
                </select>
            </div>

            {filtered.length === 0 ? (
                <div className="card-organic p-10 text-center" data-testid="summaries-empty">
                    <BookOpenCheck className="w-10 h-10 mx-auto mb-3" style={{ color: "var(--brand)" }} />
                    <h3 className="font-display text-xl font-bold">
                        {rows.length === 0 ? "Aún no tienes resúmenes" : "No hay resúmenes con estos filtros"}
                    </h3>
                    <p className="mt-1 text-sm" style={{ color: "var(--text-muted)" }}>
                        {rows.length === 0
                            ? "Genera un resumen desde un PDF (en su tema) y aparecerá aquí."
                            : "Prueba a quitar filtros."}
                    </p>
                </div>
            ) : (
                <div className="space-y-2">
                    {filtered.map((r) => {
                        const isOpen = openId === r.pdf_id;
                        return (
                            <div key={r.id}>
                                <button
                                    onClick={() => setOpenId((o) => (o === r.pdf_id ? null : r.pdf_id))}
                                    data-testid={`summary-row-${r.pdf_id}`}
                                    className="card-organic p-4 w-full flex items-center justify-between gap-3 text-left hover:bg-[color:var(--bg-secondary)]"
                                >
                                    <div className="flex items-center gap-3 min-w-0 flex-1">
                                        <div
                                            className="w-9 h-9 rounded-md flex items-center justify-center shrink-0"
                                            style={{ background: "var(--bg-secondary)", color: "var(--brand)" }}
                                        >
                                            <BookOpenCheck className="w-4 h-4" />
                                        </div>
                                        <div className="min-w-0">
                                            <div className="text-sm font-medium truncate">
                                                {r.pdf_filename || "PDF sin nombre"}
                                            </div>
                                            {(r.subjects?.length > 0 || r.topics?.length > 0) && (
                                                <div className="flex flex-wrap gap-1 mt-1">
                                                    {r.subjects?.map((s) => (
                                                        <span
                                                            key={s.id}
                                                            className="px-1.5 py-0.5 rounded text-[0.65rem] font-medium"
                                                            style={{ background: "#fdf1ea", color: "var(--brand)" }}
                                                        >
                                                            {s.name}
                                                        </span>
                                                    ))}
                                                    {r.topics?.map((t) => (
                                                        <span
                                                            key={t.id}
                                                            className="px-1.5 py-0.5 rounded text-[0.65rem] font-medium"
                                                            style={{ background: "var(--bg-secondary)", color: "var(--text-muted)" }}
                                                        >
                                                            {t.name}
                                                        </span>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                    {isOpen ? (
                                        <ChevronUp className="w-4 h-4 shrink-0" style={{ color: "var(--text-muted)" }} />
                                    ) : (
                                        <ChevronDown className="w-4 h-4 shrink-0" style={{ color: "var(--text-muted)" }} />
                                    )}
                                </button>
                                {isOpen && (
                                    <div className="mt-2">
                                        <SummaryPanel
                                            summary={r.content}
                                            onRegenerate={() => regenerate(r.pdf_id)}
                                            regenerating={regenId === r.pdf_id}
                                            onClose={() => setOpenId(null)}
                                        />
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
