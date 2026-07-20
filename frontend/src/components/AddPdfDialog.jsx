import { useEffect, useState } from "react";
import { Upload, X, FileText, Loader2, Library, Check } from "lucide-react";
import { toast } from "sonner";
import { addPdfToTopic, listPdfs, linkPdfToTopic } from "@/lib/api";

export default function AddPdfDialog({ open, onClose, onUploaded, topicId, currentPdfIds = [] }) {
    const [mode, setMode] = useState("upload"); // "upload" | "library"
    const [file, setFile] = useState(null);
    const [loading, setLoading] = useState(false);

    // Biblioteca
    const [library, setLibrary] = useState(null);
    const [libLoading, setLibLoading] = useState(false);
    const [query, setQuery] = useState("");
    const [selected, setSelected] = useState(() => new Set());

    const alreadyHere = new Set(currentPdfIds);

    // Carga la biblioteca al cambiar a esa pestaña.
    useEffect(() => {
        if (!open || mode !== "library" || library) return;
        setLibLoading(true);
        listPdfs()
            .then((pdfs) => setLibrary(pdfs))
            .catch(() => toast.error("No se pudo cargar tu biblioteca de PDFs"))
            .finally(() => setLibLoading(false));
    }, [open, mode, library]);

    // Reset al cerrar.
    useEffect(() => {
        if (!open) {
            setMode("upload");
            setFile(null);
            setQuery("");
            setSelected(new Set());
            setLibrary(null);
        }
    }, [open]);

    if (!open) return null;

    const onSubmitUpload = async (e) => {
        e.preventDefault();
        if (!file) return toast.error("Selecciona un PDF");
        const fd = new FormData();
        fd.append("file", file);
        setLoading(true);
        try {
            const pdf = await addPdfToTopic(topicId, fd);
            toast.success(`PDF "${pdf.filename}" añadido`);
            onUploaded?.();
            onClose();
        } catch (err) {
            toast.error(err?.response?.data?.detail || "Error al subir PDF");
        } finally {
            setLoading(false);
        }
    };

    const toggleSelect = (id) => {
        setSelected((prev) => {
            const next = new Set(prev);
            next.has(id) ? next.delete(id) : next.add(id);
            return next;
        });
    };

    const onSubmitLibrary = async () => {
        const ids = [...selected];
        if (ids.length === 0) return toast.error("Selecciona al menos un PDF");
        setLoading(true);
        try {
            for (const id of ids) {
                await linkPdfToTopic(topicId, id);
            }
            toast.success(ids.length === 1 ? "PDF añadido al tema" : `${ids.length} PDFs añadidos al tema`);
            onUploaded?.();
            onClose();
        } catch (err) {
            toast.error(err?.response?.data?.detail || "No se pudo añadir el PDF");
        } finally {
            setLoading(false);
        }
    };

    const filtered = (library || []).filter((p) =>
        p.filename.toLowerCase().includes(query.trim().toLowerCase())
    );

    const TabButton = ({ id, icon: Icon, label }) => (
        <button
            type="button"
            onClick={() => setMode(id)}
            data-testid={`add-pdf-tab-${id}`}
            className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-md text-sm font-medium transition-colors"
            style={{
                background: mode === id ? "var(--brand)" : "var(--bg-secondary)",
                color: mode === id ? "#fff" : "var(--text-secondary)",
            }}
        >
            <Icon className="w-4 h-4" /> {label}
        </button>
    );

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: "rgba(35,33,31,0.45)" }}
            data-testid="add-pdf-dialog"
        >
            <div className="card-organic w-full max-w-md fade-up" style={{ background: "white" }}>
                <div className="flex items-center justify-between p-5 border-b" style={{ borderColor: "var(--border)" }}>
                    <div>
                        <h3 className="font-display text-xl font-bold">Añadir PDF</h3>
                        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                            Súbelo nuevo o reutiliza uno de tu biblioteca.
                        </p>
                    </div>
                    <button
                        onClick={onClose}
                        disabled={loading}
                        data-testid="add-pdf-close"
                        className="p-1.5 rounded-md hover:bg-[color:var(--bg-secondary)]"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <div className="p-5 space-y-4">
                    <div className="flex gap-2">
                        <TabButton id="upload" icon={Upload} label="Subir nuevo" />
                        <TabButton id="library" icon={Library} label="De mi biblioteca" />
                    </div>

                    {mode === "upload" ? (
                        <form onSubmit={onSubmitUpload} className="space-y-4">
                            <label
                                className="border-2 border-dashed rounded-md p-5 flex flex-col items-center justify-center gap-2 cursor-pointer transition-colors hover:border-[color:var(--brand)]"
                                style={{ borderColor: file ? "var(--brand)" : "var(--border)" }}
                                data-testid="add-pdf-dropzone"
                            >
                                <input
                                    type="file"
                                    accept="application/pdf"
                                    className="hidden"
                                    disabled={loading}
                                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                                    data-testid="add-pdf-input"
                                />
                                {file ? (
                                    <>
                                        <FileText className="w-7 h-7" style={{ color: "var(--brand)" }} />
                                        <span className="text-sm font-medium">{file.name}</span>
                                        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                                            {(file.size / 1024).toFixed(0)} KB
                                        </span>
                                    </>
                                ) : (
                                    <>
                                        <Upload className="w-7 h-7" style={{ color: "var(--text-muted)" }} />
                                        <span className="text-sm font-medium">Selecciona un PDF</span>
                                    </>
                                )}
                            </label>
                            <div className="flex gap-3 pt-2">
                                <button
                                    type="button"
                                    onClick={onClose}
                                    disabled={loading}
                                    className="flex-1 px-4 py-2.5 rounded-md border font-medium text-sm hover:bg-[color:var(--bg-secondary)]"
                                    style={{ borderColor: "var(--border)" }}
                                >
                                    Cancelar
                                </button>
                                <button
                                    type="submit"
                                    disabled={loading || !file}
                                    data-testid="add-pdf-submit"
                                    className="btn-primary flex-1 flex items-center justify-center gap-2 text-sm"
                                >
                                    {loading ? (
                                        <>
                                            <Loader2 className="w-4 h-4 animate-spin" /> Subiendo…
                                        </>
                                    ) : (
                                        "Subir PDF"
                                    )}
                                </button>
                            </div>
                        </form>
                    ) : (
                        <div className="space-y-3">
                            <input
                                type="text"
                                value={query}
                                onChange={(e) => setQuery(e.target.value)}
                                placeholder="Buscar por nombre…"
                                data-testid="add-pdf-library-search"
                                className="w-full px-3 py-2 rounded-md border text-sm"
                                style={{ borderColor: "var(--border)" }}
                            />
                            <div className="max-h-64 overflow-y-auto space-y-1.5" data-testid="add-pdf-library-list">
                                {libLoading ? (
                                    <div className="flex items-center gap-2 text-sm py-6 justify-center" style={{ color: "var(--text-muted)" }}>
                                        <Loader2 className="w-4 h-4 animate-spin" /> Cargando…
                                    </div>
                                ) : filtered.length === 0 ? (
                                    <div className="text-sm py-6 text-center" style={{ color: "var(--text-muted)" }}>
                                        {library && library.length === 0
                                            ? "Tu biblioteca está vacía. Sube tu primer PDF."
                                            : "Ningún PDF coincide con la búsqueda."}
                                    </div>
                                ) : (
                                    filtered.map((p) => {
                                        const here = alreadyHere.has(p.id);
                                        const isSel = selected.has(p.id);
                                        return (
                                            <button
                                                key={p.id}
                                                type="button"
                                                disabled={here}
                                                onClick={() => toggleSelect(p.id)}
                                                data-testid={`add-pdf-lib-${p.id}`}
                                                className="w-full flex items-center gap-3 p-2.5 rounded-md border text-left transition-colors disabled:opacity-50"
                                                style={{
                                                    borderColor: isSel ? "var(--brand)" : "var(--border)",
                                                    background: isSel ? "#fdf1ea" : "white",
                                                }}
                                            >
                                                <div
                                                    className="w-5 h-5 rounded flex items-center justify-center shrink-0"
                                                    style={{
                                                        background: isSel ? "var(--brand)" : "var(--bg-secondary)",
                                                        color: "#fff",
                                                    }}
                                                >
                                                    {isSel && <Check className="w-3.5 h-3.5" />}
                                                </div>
                                                <div className="min-w-0 flex-1">
                                                    <div className="text-sm font-medium truncate">{p.filename}</div>
                                                    <div className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                                                        {here
                                                            ? "ya en este tema"
                                                            : `en ${p.link_count} ${p.link_count === 1 ? "tema" : "temas"} · ${Math.round(p.char_count / 1000)}k car.`}
                                                    </div>
                                                </div>
                                            </button>
                                        );
                                    })
                                )}
                            </div>
                            <div className="flex gap-3 pt-1">
                                <button
                                    type="button"
                                    onClick={onClose}
                                    disabled={loading}
                                    className="flex-1 px-4 py-2.5 rounded-md border font-medium text-sm hover:bg-[color:var(--bg-secondary)]"
                                    style={{ borderColor: "var(--border)" }}
                                >
                                    Cancelar
                                </button>
                                <button
                                    type="button"
                                    onClick={onSubmitLibrary}
                                    disabled={loading || selected.size === 0}
                                    data-testid="add-pdf-library-submit"
                                    className="btn-primary flex-1 flex items-center justify-center gap-2 text-sm"
                                >
                                    {loading ? (
                                        <>
                                            <Loader2 className="w-4 h-4 animate-spin" /> Añadiendo…
                                        </>
                                    ) : (
                                        `Añadir${selected.size > 0 ? ` (${selected.size})` : ""}`
                                    )}
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
