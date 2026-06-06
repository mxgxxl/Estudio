import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { LayoutDashboard, BarChart3, BookOpen, LogOut } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const navItems = [
    { to: "/", label: "Inicio", icon: LayoutDashboard, exact: true, testid: "nav-home" },
    { to: "/quiz/setup", label: "Estudiar", icon: BookOpen, testid: "nav-quiz" },
    { to: "/stats", label: "Estadísticas", icon: BarChart3, testid: "nav-stats" },
];

export default function Layout() {
    const location = useLocation();
    const navigate = useNavigate();
    const { logout } = useAuth();
    const isQuizRun = location.pathname.startsWith("/quiz/run");

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
        </div>
    );
}
