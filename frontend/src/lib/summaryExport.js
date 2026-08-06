// Exportación de resúmenes de IA (100% cliente, sin cuota ni backend).
// El `content` de un resumen es el JSON de Gemini:
//   { overview, key_concepts:[{concept,explanation}], sections:[{title,points:[]}], remember:[] }
// Estas utilidades lo pasan a Markdown (.md descargable) o a un HTML imprimible
// (Guardar como PDF vía el diálogo del navegador). Todo es defensivo: el content
// puede llegar como objeto (normal), como string JSON (fallback) o incompleto.

const MAX_NAME = 80;

// Caracteres inválidos en nombres de fichero (Windows/*nix) + control (U+0000–U+001F).
// Los espacios NO entran aquí (se colapsan aparte). eslint: control chars a propósito.
// eslint-disable-next-line no-control-regex
const INVALID_FS_CHARS = /[\u0000-\u001f\\/:*?"<>|]/g;

// Limpia el nombre del PDF para usarlo como nombre de fichero (SIN extensión).
export function sanitizeFilename(name, fallback = "resumen") {
    if (name == null || String(name).trim() === "") return fallback;
    let base = String(name);
    // Quitar la última extensión (.pdf, .md, …) si la hay.
    base = base.replace(/\.[^./\\]+$/, "");
    // Reemplazar caracteres inválidos por "_" (los espacios se conservan).
    base = base.replace(INVALID_FS_CHARS, "_");
    // Colapsar espacios múltiples.
    base = base.replace(/\s+/g, " ").trim();
    // Recortar espacios/puntos al final.
    base = base.replace(/[\s.]+$/, "");
    // Limitar longitud.
    if (base.length > MAX_NAME) base = base.slice(0, MAX_NAME).trim();
    return base || fallback;
}

// Normaliza el content: acepta objeto o string (JSON). Devuelve { obj, raw } donde
// `obj` es el objeto si se pudo, o null; `raw` es el string original si vino como
// string y no pudo parsearse (para volcarlo tal cual como fallback).
function normalizeContent(content) {
    if (content && typeof content === "object") return { obj: content, raw: null };
    if (typeof content === "string") {
        try {
            const parsed = JSON.parse(content);
            if (parsed && typeof parsed === "object") return { obj: parsed, raw: null };
        } catch {
            /* no era JSON: se usa como cuerpo crudo */
        }
        return { obj: null, raw: content };
    }
    return { obj: null, raw: null };
}

// Normaliza saltos de línea y colapsa 3+ líneas en blanco a 2.
function collapse(md) {
    return md.replace(/\r\n/g, "\n").replace(/\n{3,}/g, "\n\n");
}

// Escapa texto para insertarlo en HTML.
function esc(s) {
    return String(s == null ? "" : s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

// content (objeto/string) → Markdown. `filename` da el título H1.
export function summaryToMarkdown(content, filename) {
    const title = sanitizeFilename(filename);
    const { obj, raw } = normalizeContent(content);

    if (!obj) {
        // Fallback: string crudo, o nada.
        const body = raw && raw.trim() ? raw.trim() : "_(Resumen no disponible)_";
        return collapse(`# ${title}\n\n${body}\n`);
    }

    const parts = [`# ${title}`];

    if (typeof obj.overview === "string" && obj.overview.trim()) {
        parts.push(obj.overview.trim());
    }

    const conceptLines = (Array.isArray(obj.key_concepts) ? obj.key_concepts : [])
        .filter((c) => c && (c.concept || c.explanation))
        .map((c) => {
            const name = (c.concept || "").trim();
            const exp = (c.explanation || "").trim();
            return exp ? `- **${name}**: ${exp}` : `- **${name}**`;
        });
    if (conceptLines.length) parts.push("## Conceptos clave", conceptLines.join("\n"));

    for (const s of Array.isArray(obj.sections) ? obj.sections : []) {
        if (!s) continue;
        const stitle = (s.title || "").trim();
        const points = (Array.isArray(s.points) ? s.points : [])
            .filter((p) => p != null && String(p).trim())
            .map((p) => `- ${String(p).trim()}`);
        if (!stitle && !points.length) continue;
        parts.push(`## ${stitle || "Sección"}`);
        if (points.length) parts.push(points.join("\n"));
    }

    const remember = (Array.isArray(obj.remember) ? obj.remember : [])
        .filter((r) => r != null && String(r).trim())
        .map((r) => `- ${String(r).trim()}`);
    if (remember.length) parts.push("## 💡 Recuerda", remember.join("\n"));

    return collapse(parts.join("\n\n") + "\n");
}

// content (objeto/string) → HTML del cuerpo (mismas secciones que el Markdown, con
// etiquetas reales). Cada bloque va en <section> para respetar break-inside.
export function summaryToHtml(content, filename) {
    const title = sanitizeFilename(filename);
    const { obj, raw } = normalizeContent(content);
    const out = [`<h1>${esc(title)}</h1>`];

    if (!obj) {
        const body = raw && raw.trim() ? esc(raw.trim()) : "<em>(Resumen no disponible)</em>";
        out.push(`<section><p>${body}</p></section>`);
        return out.join("\n");
    }

    if (typeof obj.overview === "string" && obj.overview.trim()) {
        out.push(`<section><p>${esc(obj.overview.trim())}</p></section>`);
    }

    const concepts = (Array.isArray(obj.key_concepts) ? obj.key_concepts : [])
        .filter((c) => c && (c.concept || c.explanation));
    if (concepts.length) {
        const lis = concepts
            .map((c) => {
                const name = esc((c.concept || "").trim());
                const exp = (c.explanation || "").trim();
                return exp ? `<li><strong>${name}</strong>: ${esc(exp)}</li>` : `<li><strong>${name}</strong></li>`;
            })
            .join("");
        out.push(`<section><h2>Conceptos clave</h2><ul>${lis}</ul></section>`);
    }

    for (const s of Array.isArray(obj.sections) ? obj.sections : []) {
        if (!s) continue;
        const stitle = (s.title || "").trim();
        const points = (Array.isArray(s.points) ? s.points : []).filter((p) => p != null && String(p).trim());
        if (!stitle && !points.length) continue;
        const lis = points.map((p) => `<li>${esc(String(p).trim())}</li>`).join("");
        out.push(`<section><h2>${esc(stitle || "Sección")}</h2>${lis ? `<ul>${lis}</ul>` : ""}</section>`);
    }

    const remember = (Array.isArray(obj.remember) ? obj.remember : []).filter((r) => r != null && String(r).trim());
    if (remember.length) {
        const lis = remember.map((r) => `<li>${esc(String(r).trim())}</li>`).join("");
        out.push(`<section><h2>💡 Recuerda</h2><ul>${lis}</ul></section>`);
    }

    return out.join("\n");
}

// Descarga el Markdown como fichero .md. Devuelve true si se disparó la descarga.
export function downloadMarkdown(md, filename) {
    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${sanitizeFilename(filename)}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    return true;
}

// Genera un PDF REAL (texto seleccionable/buscable) con jsPDF y lo abre en el visor
// nativo del navegador (ver + descargar). jsPDF se carga de forma DIFERIDA (import
// dinámico) para no engordar el bundle inicial. Lanza Error("popup-blocked") si el
// navegador bloquea la pestaña del visor. Async.
export async function exportSummaryAsPdf(content, filename) {
    const { jsPDF } = await import("jspdf");
    const title = sanitizeFilename(filename);
    const { obj, raw } = normalizeContent(content);

    // Unidad en puntos (pt) para trabajar con tamaños tipográficos directos.
    const doc = new jsPDF({ unit: "pt", format: "a4" });
    // helvetica (fuente estándar) cubre acentos y ñ vía Latin-1; se evitan emojis
    // (las fuentes estándar de jsPDF no los renderizan → "Recuerda" sin 💡).
    const margin = 48;
    const pageW = doc.internal.pageSize.getWidth();
    const pageH = doc.internal.pageSize.getHeight();
    const maxW = pageW - margin * 2;
    const BULLET_INDENT = 14;
    let y = margin;

    // Salto de página si la siguiente línea no cabe.
    const ensure = (h) => {
        if (y + h > pageH - margin) { doc.addPage(); y = margin; }
    };
    // Bloque de texto con wrap (doc.splitTextToSize). `indent` en pt; `gap` tras el bloque.
    const block = (text, { size = 11, style = "normal", indent = 0, gap = 6 } = {}) => {
        if (text == null || String(text).trim() === "") return;
        doc.setFont("helvetica", style);
        doc.setFontSize(size);
        doc.setTextColor(35, 33, 31);
        const lh = size * 1.35;
        for (const ln of doc.splitTextToSize(String(text).trim(), maxW - indent)) {
            ensure(lh);
            doc.text(ln, margin + indent, y);
            y += lh;
        }
        y += gap;
    };
    // Bullet con sangría colgante: el "•" solo en la primera línea, el texto envuelto.
    const bullet = (text, { size = 11, style = "normal", gap = 4 } = {}) => {
        if (text == null || String(text).trim() === "") return;
        doc.setFont("helvetica", style);
        doc.setFontSize(size);
        doc.setTextColor(35, 33, 31);
        const lh = size * 1.35;
        const lines = doc.splitTextToSize(String(text).trim(), maxW - BULLET_INDENT);
        lines.forEach((ln, i) => {
            ensure(lh);
            if (i === 0) doc.text("•", margin, y);
            doc.text(ln, margin + BULLET_INDENT, y);
            y += lh;
        });
        y += gap;
    };

    // Título (nombre del PDF sanitizado).
    block(title, { size: 19, style: "bold", gap: 12 });

    if (!obj) {
        block(raw && raw.trim() ? raw : "(Resumen no disponible)", { size: 11 });
    } else {
        if (typeof obj.overview === "string" && obj.overview.trim()) {
            block(obj.overview, { size: 11, gap: 12 });
        }

        const concepts = (Array.isArray(obj.key_concepts) ? obj.key_concepts : [])
            .filter((c) => c && (c.concept || c.explanation));
        if (concepts.length) {
            block("Conceptos clave", { size: 14, style: "bold", gap: 6 });
            for (const c of concepts) {
                bullet((c.concept || "").trim(), { size: 11, style: "bold", gap: 2 });
                const exp = (c.explanation || "").trim();
                if (exp) block(exp, { size: 11, indent: BULLET_INDENT, gap: 6 });
            }
        }

        for (const s of Array.isArray(obj.sections) ? obj.sections : []) {
            if (!s) continue;
            const stitle = (s.title || "").trim();
            const points = (Array.isArray(s.points) ? s.points : []).filter((p) => p != null && String(p).trim());
            if (!stitle && !points.length) continue;
            block(stitle || "Sección", { size: 14, style: "bold", gap: 6 });
            for (const p of points) bullet(String(p).trim(), { size: 11 });
            y += 4;
        }

        const remember = (Array.isArray(obj.remember) ? obj.remember : []).filter((r) => r != null && String(r).trim());
        if (remember.length) {
            block("Recuerda", { size: 14, style: "bold", gap: 6 });
            for (const r of remember) bullet(String(r).trim(), { size: 11 });
        }
    }

    doc.setProperties({ title });

    // Blob → visor nativo en pestaña nueva (SIN noopener: necesitamos el handle para
    // detectar el bloqueo real de popup). No revocamos el URL de inmediato (el visor
    // lo necesita para cargar); limpieza diferida generosa.
    const blob = doc.output("blob");
    const url = URL.createObjectURL(blob);
    const win = window.open(url, "_blank");
    if (!win) {
        URL.revokeObjectURL(url);
        throw new Error("popup-blocked");
    }
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    return true;
}
