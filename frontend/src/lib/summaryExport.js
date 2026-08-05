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

// Abre una ventana aislada con el resumen maquetado y lanza el diálogo de impresión
// (el usuario elige "Guardar como PDF"). Lanza Error("popup-blocked") si está bloqueada.
export function printSummaryAsPdf(content, filename) {
    // SIN "noopener": ese flag hace que window.open devuelva null SIEMPRE (spec
    // HTML) y perderíamos el handle para escribir/imprimir. Necesitamos el handle;
    // el guard de abajo queda para bloqueos REALES de popup.
    const win = window.open("", "_blank");
    if (!win) throw new Error("popup-blocked");

    const title = sanitizeFilename(filename);
    const body = summaryToHtml(content, filename);
    // El disparo de print() va INYECTADO en el HTML (window.onload interno): es la
    // vía fiable para documentos escritos con document.write, sin depender de
    // onload/readyState desde fuera. La ventana queda abierta para "Guardar como PDF".
    const html = `<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8" />
<title>${esc(title)}</title>
<style>
  body { font-family: system-ui, -apple-system, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; font-size: 12pt; color: #23211f; }
  h1 { font-size: 20pt; margin-bottom: 1rem; }
  h2 { font-size: 15pt; margin-top: 1.5rem; margin-bottom: 0.5rem; }
  ul { padding-left: 1.5rem; }
  li { margin-bottom: 0.25rem; }
  strong { font-weight: 600; }
  section { break-inside: avoid; }
  @media print { body { margin: 0; } }
</style>
</head>
<body>
${body}
<script>window.onload = function () { window.focus(); window.print(); };</script>
</body>
</html>`;
    win.document.write(html);
    win.document.close();
    return true;
}
