import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { LayoutDashboard, BarChart3, BookOpen, LogOut, User, Library, ListChecks } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import UsageBadge from "@/components/UsageBadge";
import PremiumDialog from "@/components/PremiumDialog";

const navItems = [
    { to: "/", label: "Inicio", icon: LayoutDashboard, exact: true, testid: "nav-home" },
    { to: "/quiz/setup", label: "Estudiar", icon: BookOpen, testid: "nav-quiz" },
    { to: "/preguntas", label: "Preguntas", icon: ListChecks, testid: "nav-questions" },
    { to: "/biblioteca", label: "Biblioteca", icon: Library, testid: "nav-library" },
    { to: "/stats", label: "Estadísticas", icon: BarChart3, testid: "nav-stats" },
    { to: "/cuenta", label: "Cuenta", icon: User, testid: "nav-account" },
];

export default function Layout() {
    const location = useLocation();
    const navigate = useNavigate();
    const { logout, refreshUsage } = useAuth();
    const isQuizRun = location.pathname.startsWith("/quiz/run");

    // Modal "hazte Premium" cuando una acción de IA devuelve 402.
    const [quotaDialog, setQuotaDialog] = useState({ open: false, detail: "" });
    useEffect(() => {
        const onQuota = (e) => {
            setQuotaDialog({ open: true, detail: e?.detail || "" });
            // El backend no consumió: aun así refrescamos para reflejar el estado.
            refreshUsage();
        };
        window.addEventListener("studia:quota-exceeded", onQuota);
        return () => window.removeEventListener("studia:quota-exceeded", onQuota);
    }, [refreshUsage]);

    const handleLogout = () => {
        logout();
        navigate("/login");
    };

    return (
        <div className="min-h-screen flex flex-col" style={{ background: "var(--bg-primary)" }}>
            {!isQuizRun && (
                <header
                    className="border-b sticky top-0 z-40 backdrop-blur"
                    style={{ borderColor: "var(--border)", background: "rgba(253,251,247,0.85)" }}
                >
                    <div className="max-w-6xl mx-auto px-5 md:px-8 py-4 flex items-center justify-between">
                        <NavLink to="/" className="flex items-center gap-2 group" data-testid="brand-link">
                            <div
                                className="w-9 h-9 rounded-md flex items-center justify-center"
                                style={{ background: "var(--brand)" }}
                            >
                                <span className="text-white font-display font-bold text-lg">S</span>
                            </div>
                            <div className="flex flex-col leading-tight">
                                <span className="font-display font-bold text-lg tracking-tight">Studia</span>
                                <span className="label-eyebrow" style={{ fontSize: "0.55rem" }}>
                                    Estudio inteligente
                                </span>
                            </div>
                        </NavLink>
                        <nav className="flex items-center gap-1 md:gap-2">
                            <UsageBadge />
                            {navItems.map((item) => {
                                const Icon = item.icon;
                                return (
                                    <NavLink
                                        key={item.to}
                                        to={item.to}
                                        end={item.exact}
                                        data-testid={item.testid}
                                        className={({ isActive }) =>
                                            `flex items-center gap-2 px-3 md:px-4 py-2 rounded-md text-sm font-medium transition-all ${
                                                isActive
                                                    ? "bg-[color:var(--bg-secondary)] text-[color:var(--text-primary)]"
                                                    : "text-[color:var(--text-secondary)] hover:bg-[color:var(--bg-secondary)]"
                                            }`
                                        }
                                    >
                                        <Icon className="w-4 h-4" />
                                        <span className="hidden sm:inline">{item.label}</span>
                                    </NavLink>
                                );
                            })}
                            <button
                                type="button"
                                onClick={handleLogout}
                                data-testid="nav-logout"
                                className="flex items-center gap-2 px-3 md:px-4 py-2 rounded-md text-sm font-medium transition-all text-[color:var(--text-secondary)] hover:bg-[color:var(--bg-secondary)]"
                            >
                                <LogOut className="w-4 h-4" />
                                <span className="hidden sm:inline">Salir</span>
                            </button>
                        </nav>
                    </div>
                </header>
            )}
            <main className="flex-1">
                <Outlet />
            </main>
            {!isQuizRun && (
                <footer
                    className="border-t mt-12 py-6 text-center text-xs"
                    style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
                >
                    Studia · Estudia cualquier asignatura con preguntas generadas desde tus apuntes
                </footer>
            )}
            <PremiumDialog
                open={quotaDialog.open}
                detail={quotaDialog.detail}
                onClose={() => setQuotaDialog({ open: false, detail: "" })}
            />
        </div>
    );
}
