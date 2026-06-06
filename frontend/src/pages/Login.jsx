import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useAuth } from "@/context/AuthContext";

export default function Login() {
    const { login } = useAuth();
    const navigate = useNavigate();
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [submitting, setSubmitting] = useState(false);

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (submitting) return;
        setSubmitting(true);
        try {
            await login(email, password);
            toast.success("Sesión iniciada");
            navigate("/");
        } catch (err) {
            const detail = err?.response?.data?.detail;
            toast.error(typeof detail === "string" ? detail : "No se pudo iniciar sesión");
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <div
            className="min-h-screen flex items-center justify-center px-5"
            style={{ background: "var(--bg-primary)" }}
        >
            <Card className="w-full max-w-md">
                <CardHeader>
                    <CardTitle className="font-display text-2xl">Iniciar sesión</CardTitle>
                    <CardDescription>Accede a tu cuenta de Studia</CardDescription>
                </CardHeader>
                <CardContent>
                    <form onSubmit={handleSubmit} className="flex flex-col gap-4" data-testid="login-form">
                        <div className="flex flex-col gap-2">
                            <Label htmlFor="email">Email</Label>
                            <Input
                                id="email"
                                type="email"
                                required
                                autoComplete="email"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                data-testid="login-email"
                            />
                        </div>
                        <div className="flex flex-col gap-2">
                            <Label htmlFor="password">Contraseña</Label>
                            <Input
                                id="password"
                                type="password"
                                required
                                autoComplete="current-password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                data-testid="login-password"
                            />
                        </div>
                        <Button type="submit" disabled={submitting} data-testid="login-submit">
                            {submitting ? "Entrando…" : "Entrar"}
                        </Button>
                        <p className="text-sm text-center" style={{ color: "var(--text-secondary)" }}>
                            ¿No tienes cuenta?{" "}
                            <Link to="/register" className="font-medium underline">
                                Regístrate
                            </Link>
                        </p>
                    </form>
                </CardContent>
            </Card>
        </div>
    );
}
