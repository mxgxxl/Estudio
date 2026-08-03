import { createContext, useCallback, useContext } from "react";
import { toast } from "sonner";

// Seguimiento de generaciones de IA que quedan EN CURSO cuando el usuario cierra
// el modal que las lanzó (p. ej. CreateSubjectStepper). La promesa sigue viva:
// aquí solo le colgamos un feedback (toast) y un evento global para que las
// pantallas montadas (p. ej. QuizSetup) refresquen sus datos al completar.
const PendingGenerationContext = createContext(null);

export function PendingGenerationProvider({ children }) {
    // `metadata` = { topicName, subjectName, subjectId }.
    const trackGeneration = useCallback((promise, metadata = {}) => {
        const label = metadata.topicName || "tu tema";
        promise
            .then((res) => {
                toast.success(`Las preguntas de ${label} están listas`);
                // Aviso genérico para que las vistas montadas recarguen sus datos.
                window.dispatchEvent(
                    new CustomEvent("studia:generation-complete", { detail: { ...metadata, res } })
                );
            })
            .catch(() => {
                toast.error(
                    `No se pudieron generar las preguntas de ${label}. Inténtalo desde el tema.`
                );
            });
        return promise;
    }, []);

    return (
        <PendingGenerationContext.Provider value={{ trackGeneration }}>
            {children}
        </PendingGenerationContext.Provider>
    );
}

export function usePendingGeneration() {
    const ctx = useContext(PendingGenerationContext);
    if (!ctx) {
        throw new Error("usePendingGeneration debe usarse dentro de PendingGenerationProvider");
    }
    return ctx;
}
