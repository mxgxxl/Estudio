// Exportación de un intento a Markdown (.md) y a PDF real (texto seleccionable),
// reutilizando la fontanería de summaryExport.js. 100% cliente, sin backend.
// Un intento legacy (sin `items`) se exporta con el aviso de degradación + agregado.
import { BEHAVIOR_LABELS, SELECTION_LABELS } from "@/lib/quizLabels";
import { downloadMarkdown, loadJsPdf, createPdfLayout, openPdfInViewer } from "@/lib/summaryExport";

function fmtDate(iso) {
    try { return new Date(iso).toLocaleString("es-ES"); } catch { return ""; }
}
function fmtDateShort(iso) {
    try { return new Date(iso).toLocaleDateString("es-ES"); } catch { return ""; }
}
function fmtDuration(sec) {
    const s = Math.max(0, Math.floor(sec || 0));
    const m = Math.floor(s / 60), r = s % 60;
    return m > 0 ? `${m}m ${r}s` : `${r}s`;
}
// Letra/etiqueta de opción: V/F para tf, A/B/C… para mcq.
function optLetter(qtype, i) {
    return qtype === "tf" ? (i === 0 ? "V" : "F") : String.fromCharCode(65 + i);
}
// Marcas de una opción (texto plano; helvetica del PDF no renderiza ✓/←).
function optMarks(item, oi) {
    const marks = [];
    if (oi === item.correct_index) marks.push("correcta");
    if (oi === (item.selected ?? -1)) marks.push("tu respuesta");
    return marks;
}
function defaultFilename(attempt) {
    return `Intento ${fmtDateShort(attempt?.created_at)}`;
}

// ---------------------------------------------------------------------------
// Markdown
// ---------------------------------------------------------------------------
export function attemptToMarkdown(attempt) {
    const a = attempt || {};
    const beh = BEHAVIOR_LABELS[a.behavior] || "Práctica";
    const sel = SELECTION_LABELS[a.selection] || "Todas";
    const lines = [`# Intento del ${fmtDate(a.created_at)}`, ""];
    lines.push(`**${beh} · ${sel}**${a.duration_seconds ? ` · Duración: ${fmtDuration(a.duration_seconds)}` : ""}`);
    lines.push(`**Nota:** ${a.score_10 ?? 0}/10 · Aciertos ${a.correct_count ?? 0} · Fallos ${a.wrong_count ?? 0} · En blanco ${a.unanswered_count ?? 0} · Total ${a.total ?? 0}`);
    lines.push("");

    const items = Array.isArray(a.items) ? a.items : [];
    if (!items.length) {
        lines.push("_Este es un intento antiguo. Solo se muestra el resumen agregado._");
        return lines.join("\n") + "\n";
    }

    items.forEach((it, idx) => {
        lines.push(`## ${idx + 1}. ${it.question || ""}`);
        if (it.question_type === "dev") {
            lines.push(`**Desarrollo — ${it.dev_score ?? 0}/10**`);
            const ua = (it.user_answer || "").trim();
            lines.push(`**Tu respuesta:** ${ua || "Sin responder"}`);
            if ((it.feedback || "").trim()) lines.push(`**Comentario:** ${it.feedback.trim()}`);
        } else {
            const sel = it.selected ?? -1;
            (it.options || []).forEach((opt, oi) => {
                const marks = optMarks(it, oi);
                lines.push(`- ${optLetter(it.question_type, oi)}. ${opt}${marks.length ? `  _(${marks.join(", ")})_` : ""}`);
            });
            if (sel === -1) lines.push("- _Sin responder_");
        }
        lines.push("");
    });

    return lines.join("\n").replace(/\n{3,}/g, "\n\n") + "\n";
}

// Descarga el intento como .md. `filename` opcional (por defecto "Intento {fecha}").
export function downloadAttemptMarkdown(attempt, filename) {
    return downloadMarkdown(attemptToMarkdown(attempt), filename || defaultFilename(attempt));
}

// ---------------------------------------------------------------------------
// PDF real (texto seleccionable) abierto en el visor nativo
// ---------------------------------------------------------------------------
export async function exportAttemptAsPdf(attempt) {
    const a = attempt || {};
    const jsPDF = await loadJsPdf();
    const { doc, block, bullet, spacer } = createPdfLayout(jsPDF);
    const title = defaultFilename(a);
    const beh = BEHAVIOR_LABELS[a.behavior] || "Práctica";
    const sel = SELECTION_LABELS[a.selection] || "Todas";

    // Cabecera.
    block(`Intento del ${fmtDate(a.created_at)}`, { size: 19, style: "bold", gap: 6 });
    block(`${beh} · ${sel}${a.duration_seconds ? ` · Duración: ${fmtDuration(a.duration_seconds)}` : ""}`, { size: 10, gap: 2 });
    block(
        `Nota: ${a.score_10 ?? 0}/10   ·   Aciertos ${a.correct_count ?? 0} · Fallos ${a.wrong_count ?? 0} · En blanco ${a.unanswered_count ?? 0} · Total ${a.total ?? 0}`,
        { size: 11, style: "bold", gap: 12 },
    );

    const items = Array.isArray(a.items) ? a.items : [];
    if (!items.length) {
        block("Este es un intento antiguo. Solo se muestra el resumen agregado.", { size: 11 });
        return openPdfInViewer(doc, title);
    }

    items.forEach((it, idx) => {
        block(`${idx + 1}. ${it.question || ""}`, { size: 12, style: "bold", gap: 4 });
        if (it.question_type === "dev") {
            block(`Desarrollo — ${it.dev_score ?? 0}/10`, { size: 10, style: "bold", gap: 2 });
            const ua = (it.user_answer || "").trim();
            block(`Tu respuesta: ${ua || "Sin responder"}`, { size: 11, gap: 2 });
            if ((it.feedback || "").trim()) block(`Comentario: ${it.feedback.trim()}`, { size: 11, gap: 6 });
            else spacer(6);
        } else {
            const selIdx = it.selected ?? -1;
            (it.options || []).forEach((opt, oi) => {
                const marks = optMarks(it, oi);
                const label = `${optLetter(it.question_type, oi)}. ${opt}${marks.length ? `  (${marks.join(", ")})` : ""}`;
                bullet(label, { size: 11, style: oi === it.correct_index ? "bold" : "normal" });
            });
            if (selIdx === -1) bullet("Sin responder", { size: 10 });
            spacer(6);
        }
    });

    return openPdfInViewer(doc, title);
}
