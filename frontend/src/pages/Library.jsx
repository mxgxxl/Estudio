import { useCallback, useEffect, useRef, useState } from "react";
import { Library as LibraryIcon, Upload, FileText, Trash2, Loader2, Search } from "lucide-react";
import { toast } from "sonner";
import { listPdfs, uploadPdf, deletePdf, listTopics } from "@/lib/api";

export default function Library() {
    const [pdfs, setPdfs] = useState(null);
    const [topicsById, setTopicsById] = useState({});
    const [query, setQuery] = useState("");
    const [uploading, setUploading] = useState(false);
    const [pdfToDelete, setPdfToDelete] = useState(null);
    const [deleting, setDeleting] = useState(false);
    const fileRef = useRef(null);

    const load = useCallback(async () => {
        try {
            const [ps, ts] = await Promise.all([listPdfs(), listTopics()]);
            setPdfs(ps);
            setTopicsById(Object.fromEntries(ts.map((t) => [t.id, t.name])));
        } catch {
            toast.error("No se pudo cargar la biblioteca");
            setPdfs([]);
        }
    }, []);

    useEffect(() => {
        load();
    }, [load]);

    const onPickFile = async (e) => {
        const file = e.target.files?.[0];
        e.target.value = ""; // permite re-subir el mismo fichero
        if (!file) return;
        if (!file.name.toLowerCase().endsWith(".pdf")) {
            return toast.error("Solo se aceptan ficheros PDF");
        }
        const fd = new FormData();
        fd.append("file", file);
        setUploading(true);
        try {
            const pdf = await uploadPdf(fd);
            toast.success(`PDF "${pdf.filename}" subido a tu biblioteca`);
            await load();
        } catch (err) {
            toast.error(err?.response?.data?.detail || "Error al subir el PDF");
        } finally {
            setUploading(false);
        }
    };

    const confirmDelete = async () => {
        const p = pdfToDelete;
        if (!p) return;
        setDeleting(true);
        try {
            await deletePdf(p.id);
            toast.success("PDF eliminado");
            setPdfs((ps) => ps.filter((x) => x.id !== p.id));
            setPdfToDelete(null);
        } catch (err) {
            toast.error(err?.response?.data?.detail || "No se pudo eliminar el PDF");
        } finally {
            setDeleting(false);
        }
    };

    const topicNames = (p) =>
        (p.topic_ids || [])
            .map((tid) => topicsById[tid])
            .filter(Boolean);

    const UploadButton = ({ big = false }) => (
        <>
            <input
                ref={fileRef}
                type="file"
                accept="application/pdf"
                className="hidden"
                onChange={onPickFile}
                data-testid="library-upload-input"
            />
            <button
                type="button"
                onClick={() => fileRef.current?.click()}
                disabled={uploading}
                data-testid="library-upload-btn"
                className={`btn-primary flex items-center justify-center gap-2 ${big ? "text-sm px-5 py-2.5" : "text-xs"}`}
                style={big ? {} : { padding: "0.4rem 0.8rem" }}
            >
                {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                {uploading ? "Subiendo…" : "Subir PDF"}
            </button>
        </>
    );

    if (pdfs === null) {
        return (
            <div style={{ color: "var(--text-muted)" }}>
                Cargando…
            </div>
        );
    }

    const filtered = pdfs.filter((p) =>
        p.filename.toLowerCase().includes(query.trim().toLowerCase())
    );

    return (
        <div>
            <div className="flex items-start justify-between gap-4 mb-6">
                <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                    Aquí se guardan todos tus PDFs. Súbelos una vez y úsalos en los temas que quieras.
                </p>
                {pdfs.length > 0 && <UploadButton />}
            </div>

            {pdfs.length === 0 ? (
                // Estado vacío: explica para qué sirve la pantalla, no una página en blanco.
                <div
                    className="card-organic p-8 md:p-12 flex flex-col items-center text-center gap-4"
                    data-testid="library-empty"
                >
                    <div
                        className="w-14 h-14 rounded-full flex items-center justify-center"
                        style={{ background: "var(--bg-secondary)", color: "var(--brand)" }}
                    >
                        <LibraryIcon className="w-7 h-7" />
                    </div>
                    <h2 className="font-display text-xl font-bold">Tu biblioteca está vacía</h2>
                    <p className="text-sm max-w-md" style={{ color: "var(--text-secondary)" }}>
                        Aquí se guardan todos tus PDFs: súbelos una vez y reutilízalos en los temas
                        que quieras, sin volver a subirlos. Un PDF puede estar en varios temas a la vez.
                    </p>
                    <div className="mt-2">
                        <UploadButton big />
                    </div>
                </div>
            ) : (
                <>
                    <div className="relative mb-4">
                        <Search
                            className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2"
                            style={{ color: "var(--text-muted)" }}
                        />
                        <input
                            type="text"
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            placeholder="Buscar por nombre…"
                            data-testid="library-search"
                            className="w-full pl-9 pr-3 py-2 rounded-md border text-sm"
                            style={{ borderColor: "var(--border)" }}
                        />
                    </div>

                    {filtered.length === 0 ? (
                        <div className="card-organic p-5 text-sm" style={{ color: "var(--text-muted)" }}>
                            Ningún PDF coincide con la búsqueda.
                        </div>
                    ) : (
                        <div className="space-y-2">
                            {filtered.map((p) => {
                                const names = topicNames(p);
                                return (
                                    <div
                                        key={p.id}
                                        className="card-organic p-4 flex items-center justify-between gap-3 fade-up"
                                        data-testid={`library-pdf-${p.id}`}
                                    >
                                        <div className="flex items-center gap-3 min-w-0 flex-1">
                                            <div
                                                className="w-9 h-9 rounded-md flex items-center justify-center shrink-0"
                                                style={{ background: "var(--bg-secondary)" }}
                                            >
                                                <FileText className="w-4 h-4" style={{ color: "var(--brand)" }} />
                                            </div>
                                            <div className="min-w-0">
                                                <div className="text-sm font-medium truncate">{p.filename}</div>
                                                <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                                                    {p.link_count === 0 ? (
                                                        <span>sin usar · {Math.round(p.char_count / 1000)}k car.</span>
                                                    ) : names.length > 0 ? (
                                                        <span className="truncate">
                                                            en {p.link_count} {p.link_count === 1 ? "tema" : "temas"}: {names.join(", ")}
                                                        </span>
                                                    ) : (
                                                        <span>en {p.link_count} {p.link_count === 1 ? "tema" : "temas"}</span>
                                                    )}
                                                    {p.question_count > 0 && (
                                                        <span> · {p.question_count} preguntas</span>
                                                    )}
                                                </div>
                                            </div>
                                        </div>
                                        <button
                                            type="button"
                                            onClick={() => setPdfToDelete(p)}
                                            data-testid={`library-del-${p.id}`}
                                            title="Eliminar PDF"
                                            className="p-1.5 rounded hover:bg-[color:var(--bg-secondary)] shrink-0"
                                        >
                                            <Trash2 className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
                                        </button>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </>
            )}

            {pdfToDelete && (
                <div
                    className="fixed inset-0 z-50 flex items-center justify-center p-4"
                    style={{ background: "rgba(35,33,31,0.45)" }}
                    data-testid="library-delete-dialog"
                >
                    <div className="card-organic w-full max-w-md fade-up" style={{ background: "white" }}>
                        <div className="p-5 border-b" style={{ borderColor: "var(--border)" }}>
                            <h3 className="font-display text-xl font-bold">Eliminar PDF</h3>
                            <p className="text-sm mt-1 truncate" style={{ color: "var(--text-muted)" }}>
                                {pdfToDelete.filename}
                            </p>
                        </div>
                        <div className="p-5 space-y-4">
                            {pdfToDelete.link_count > 0 ? (
                                <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                                    Este PDF está en <strong>{pdfToDelete.link_count} {pdfToDelete.link_count === 1 ? "tema" : "temas"}</strong>.
                                    Se eliminará de <strong>todos</strong> ellos y no se podrá deshacer.
                                    {" "}<strong>Las preguntas ya generadas se conservan.</strong>
                                </p>
                            ) : (
                                <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                                    Este PDF no está en ningún tema. Se eliminará de tu biblioteca.
                                </p>
                            )}
                            <div className="flex flex-col gap-2 pt-1">
                                <button
                                    type="button"
                                    onClick={confirmDelete}
                                    disabled={deleting}
                                    data-testid="library-delete-confirm"
                                    className="w-full px-4 py-2.5 rounded-md font-semibold text-sm text-white flex items-center justify-center gap-2 disabled:opacity-60"
                                    style={{ background: "var(--error, #B84A4A)" }}
                                >
                                    {deleting && <Loader2 className="w-4 h-4 animate-spin" />}
                                    Eliminar definitivamente
                                </button>
                                <button
                                    type="button"
                                    onClick={() => setPdfToDelete(null)}
                                    disabled={deleting}
                                    className="w-full px-4 py-2.5 rounded-md font-medium text-sm hover:bg-[color:var(--bg-secondary)]"
                                    style={{ color: "var(--text-secondary)" }}
                                >
                                    Cancelar
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
