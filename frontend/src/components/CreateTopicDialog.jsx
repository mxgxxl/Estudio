import { useEffect, useState } from "react";
import { Upload, X, FileText, Loader2, Library, Check, Plus } from "lucide-react";
import { toast } from "sonner";
import { createTopic, addPdfToTopic, linkPdfToTopic, listPdfs } from "@/lib/api";

// Crea un tema vacío y, opcionalmente, le adjunta PDFs (nuevos o de la
// biblioteca) en el mismo paso. Nunca genera preguntas aquí: eso se hace
// después dentro del tema. La subida de PDFs no consume cuota de IA.
export default function CreateTopicDialog({ open, onClose, onCreated, subjectId }) {
    const [name, setName] = useState("");
    const [mode, setMode] = useState("upload"); // "upload" | "library"
    const [files, setFiles] = useState([]); // File[] nuevos a subir
    const [loading, setLoading] = useState(false);

    // Biblioteca
    const [library, setLibrary] = useState(null);
    const [libLoading, setLibLoading] = useState(false);
    const [query, setQuery] = useState("");
    const [selected, setSelected] = useState(() => new Set());

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
            setName("");
            setMode("upload");
            setFiles([]);
            setQuery("");
            setSelected(new Set());
            setLibrary(null);
        }
    }, [open]);

    if (!open) return null;

    const addFiles = (fileList) => {
        const picked = Array.from(fileList || []).filter((f) =>
            f.name.toLowerCase().endsWith(".pdf")
        );
        if (picked.length === 0) return;
        setFiles((prev) => {
            const seen = new Set(prev.map((f) => f.name + f.size));
            const next = [...prev];
            for (const f of picked) {
                if (!seen.has(f.name + f.size)) next.push(f);
            }
            return next;
        });
    };
    const removeFile = (idx) => setFiles((prev) => prev.filter((_, i) => i !== idx));

    const toggleSelect = (id) => {
        setSelected((prev) => {
            const next = new Set(prev);
            next.has(id) ? next.delete(id) : next.add(id);
            return next;
        });
    };

    const onSubmit = async (e) => {
        e.preventDefault();
        if (!name.trim()) return toast.error("Introduce un nombre para el tema");
        if (!subjectId) return toast.error("Falta la asignatura");

        setLoading(true);
        try {
            const topic = await createTopic(subjectId, { name: name.trim() });
            // Adjuntar PDFs opcionales. Si alguno falla, avisamos pero el tema ya existe.
            let attached = 0;
            for (const f of files) {
                const fd = new FormData();
                fd.append("file", f);
                await addPdfToTopic(topic.id, fd);
                attached++;
            }
            for (const pdfId of selected) {
                await linkPdfToTopic(topic.id, pdfId);
                attached++;
            }
            toast.success(
                attached > 0
                    ? `Tema "${topic.name}" creado con ${attached} PDF${attached === 1 ? "" : "s"}`
                    : `Tema "${topic.name}" creado`
            );
            onCreated?.(topic);
            onClose();
        } catch (err) {
            const msg = err?.response?.data?.detail || err.message || "Error al crear el tema";
            toast.error(typeof msg === "string" ? msg : "Error al crear el tema");
        } finally {
            setLoading(false);
        }
    };

    const filtered = (library || []).filter((p) =>
        p.filename.toLowerCase().includes(query.trim().toLowerCase())
    );
    const pdfCount = files.length + selected.size;

    const TabButton = ({ id, icon: Icon, label }) => (
        <button
            type="button"
            onClick={() => setMode(id)}
            data-testid={`create-topic-tab-${id}`}
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
            className="fixed inset-0 z-50 flex items-center justify-center p-4 overflow-y-auto"
            style={{ background: "rgba(35,33,31,0.45)" }}
            data-testid="create-topic-dialog"
        >
            <div className="card-organic w-full max-w-lg fade-up my-8" style={{ background: "white" }}>
                <div
                    className="flex items-center justify-between p-5 border-b"
                    style={{ borderColor: "var(--border)" }}
                >
                    <div>
                        <h3 className="font-display text-xl font-bold">Nuevo tema</h3>
                        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                            Crea el tema y, si quieres, añade PDFs. Las preguntas se generan luego.
                        </p>
                    </div>
                    <button
                        onClick={onClose}
                        disabled={loading}
                        data-testid="create-topic-close"
                        className="p-1.5 rounded-md hover:bg-[color:var(--bg-secondary)]"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <form onSubmit={onSubmit} className="p-5 space-y-4">
                    <div>
                        <label className="label-eyebrow block mb-1.5">Nombre del tema</label>
                        <input
                            type="text"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            placeholder="Ej. Tema 1 — Introducción"
                            disabled={loading}
                            autoFocus
                            data-testid="create-topic-name-input"
                            className="w-full border rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[color:var(--brand)]/20 focus:border-[color:var(--brand)]"
                            style={{ borderColor: "var(--border)" }}
                        />
                    </div>

                    <div>
                        <label className="label-eyebrow block mb-1.5">
                            PDFs{" "}
                            <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>(opcional)</span>
                        </label>
                        <div className="flex gap-2 mb-3">
                            <TabButton id="upload" icon={Upload} label="Subir nuevos" />
                            <TabButton id="library" icon={Library} label="De mi biblioteca" />
                        </div>

                        {mode === "upload" ? (
                            <div className="space-y-2">
                                <label
                                    className="border-2 border-dashed rounded-md p-5 flex flex-col items-center justify-center gap-2 cursor-pointer transition-colors hover:border-[color:var(--brand)]"
                                    style={{ borderColor: files.length ? "var(--brand)" : "var(--border)" }}
                                    data-testid="create-topic-dropzone"
                                >
                                    <input
                                        type="file"
                                        accept="application/pdf"
                                        multiple
                                        className="hidden"
                                        disabled={loading}
                                        onChange={(e) => {
                                            addFiles(e.target.files);
                                            e.target.value = "";
                                        }}
                                        data-testid="create-topic-file-input"
                                    />
                                    <Upload className="w-7 h-7" style={{ color: "var(--text-muted)" }} />
                                    <span className="text-sm font-medium">
                                        Haz clic para seleccionar uno o varios PDFs
                                    </span>
                                    <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                                        Solo se acepta .pdf
                                    </span>
                                </label>
                                {files.length > 0 && (
                                    <ul className="space-y-1.5" data-testid="create-topic-file-list">
                                        {files.map((f, i) => (
                                            <li
                                                key={f.name + f.size + i}
                                                className="flex items-center gap-2 p-2 rounded-md border text-sm"
                                                style={{ borderColor: "var(--border)" }}
                                            >
                                                <FileText className="w-4 h-4 shrink-0" style={{ color: "var(--brand)" }} />
                                                <span className="truncate flex-1">{f.name}</span>
                                                <span className="text-xs shrink-0" style={{ color: "var(--text-muted)" }}>
                                                    {(f.size / 1024).toFixed(0)} KB
                                                </span>
                                                <button
                                                    type="button"
                                                    onClick={() => removeFile(i)}
                                                    disabled={loading}
                                                    className="p-1 rounded hover:bg-[color:var(--bg-secondary)] shrink-0"
                                                    aria-label="Quitar archivo"
                                                >
                                                    <X className="w-3.5 h-3.5" style={{ color: "var(--text-muted)" }} />
                                                </button>
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </div>
                        ) : (
                            <div className="space-y-3">
                                <input
                                    type="text"
                                    value={query}
                                    onChange={(e) => setQuery(e.target.value)}
                                    placeholder="Buscar por nombre…"
                                    data-testid="create-topic-library-search"
                                    className="w-full px-3 py-2 rounded-md border text-sm"
                                    style={{ borderColor: "var(--border)" }}
                                />
                                <div className="max-h-56 overflow-y-auto space-y-1.5" data-testid="create-topic-library-list">
                                    {libLoading ? (
                                        <div className="flex items-center gap-2 text-sm py-6 justify-center" style={{ color: "var(--text-muted)" }}>
                                            <Loader2 className="w-4 h-4 animate-spin" /> Cargando…
                                        </div>
                                    ) : filtered.length === 0 ? (
                                        <div className="text-sm py-6 text-center" style={{ color: "var(--text-muted)" }}>
                                            {library && library.length === 0
                                                ? "Tu biblioteca está vacía. Sube PDFs desde la pestaña anterior."
                                                : "Ningún PDF coincide con la búsqueda."}
                                        </div>
                                    ) : (
                                        filtered.map((p) => {
                                            const isSel = selected.has(p.id);
                                            return (
                                                <button
                                                    key={p.id}
                                                    type="button"
                                                    onClick={() => toggleSelect(p.id)}
                                                    data-testid={`create-topic-lib-${p.id}`}
                                                    className="w-full flex items-center gap-3 p-2.5 rounded-md border text-left transition-colors"
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
                                                            en {p.link_count} {p.link_count === 1 ? "tema" : "temas"} · {Math.round(p.char_count / 1000)}k car.
                                                        </div>
                                                    </div>
                                                </button>
                                            );
                                        })
                                    )}
                                </div>
                            </div>
                        )}
                    </div>

                    <div className="flex gap-3 pt-2">
                        <button
                            type="button"
                            onClick={onClose}
                            disabled={loading}
                            data-testid="create-topic-cancel"
                            className="flex-1 px-4 py-2.5 rounded-md border font-medium text-sm hover:bg-[color:var(--bg-secondary)]"
                            style={{ borderColor: "var(--border)" }}
                        >
                            Cancelar
                        </button>
                        <button
                            type="submit"
                            disabled={loading || !name.trim()}
                            data-testid="create-topic-submit"
                            className="btn-primary flex-1 flex items-center justify-center gap-2 text-sm"
                        >
                            {loading ? (
                                <>
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                    Creando…
                                </>
                            ) : (
                                <>
                                    <Plus className="w-4 h-4" />
                                    {pdfCount > 0 ? `Crear tema (${pdfCount} PDF${pdfCount === 1 ? "" : "s"})` : "Crear tema"}
                                </>
                            )}
                        </button>
                    </div>
                    {loading && files.length > 0 && (
                        <p className="text-xs text-center" style={{ color: "var(--text-muted)" }}>
                            Subiendo y procesando los PDFs…
                        </p>
                    )}
                </form>
            </div>
        </div>
    );
}
