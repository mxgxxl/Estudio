import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

export default function ProtectedRoute() {
    const { isAuthenticated, loading } = useAuth();

    if (loading) {
        return (
            <div
                className="min-h-screen flex items-center justify-center"
                style={{ background: "var(--bg-primary)", color: "var(--text-muted)" }}
            >
                Cargando…
            </div>
        );
    }

    if (!isAuthenticated) return <Navigate to="/login" replace />;

    return <Outlet />;
}
