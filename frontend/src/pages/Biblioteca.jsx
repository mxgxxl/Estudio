import { NavLink, Outlet } from "react-router-dom";

// Página paraguas "Biblioteca": agrupa el material del usuario (PDFs, preguntas,
// resúmenes) en pestañas. Cada pestaña es una ruta hija que pinta en el <Outlet/>.
// Separa "material que acumulas" (aquí) de "actividad" (Estudiar).
const TABS = [
    { to: "/biblioteca/pdfs", label: "PDFs", testid: "biblio-tab-pdfs" },
    { to: "/biblioteca/preguntas", label: "Preguntas", testid: "biblio-tab-preguntas" },
    { to: "/biblioteca/resumenes", label: "Resúmenes", testid: "biblio-tab-resumenes" },
];

export default function Biblioteca() {
    return (
        <div className="max-w-4xl mx-auto px-5 md:px-8 py-8 md:py-12">
            <span className="label-eyebrow">Tu material</span>
            <h1 className="font-display text-3xl md:text-4xl font-bold mt-1 mb-5">Biblioteca</h1>

            <div className="flex gap-1 mb-6 border-b" style={{ borderColor: "var(--border)" }}>
                {TABS.map((t) => (
                    <NavLink
                        key={t.to}
                        to={t.to}
                        data-testid={t.testid}
                        className={({ isActive }) =>
                            `px-4 py-2.5 text-sm font-medium -mb-px border-b-2 transition-colors ${
                                isActive
                                    ? "border-[color:var(--brand)] text-[color:var(--text-primary)]"
                                    : "border-transparent text-[color:var(--text-secondary)] hover:text-[color:var(--text-primary)]"
                            }`
                        }
                    >
                        {t.label}
                    </NavLink>
                ))}
            </div>

            <Outlet />
        </div>
    );
}
