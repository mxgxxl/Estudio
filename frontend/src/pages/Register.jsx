import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useAuth } from "@/context/AuthContext";

export default function Register() {
    const { register } = useAuth();
    const navigate = useNavigate();
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [submitting, setSubmitting] = useState(false);

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (submitting) return;
        if (password.length < 6) {
            toast.error("La contraseña debe tener al menos 6 caracteres");
            return;
        }
        setSubmitting(true);
        try {
            await register(email, password);
            toast.success("Cuenta creada");
            navigate("/");
        } catch (err) {
            const detail = err?.response?.data?.detail;
            toast.error(typeof detail === "string" ? detail : "No se pudo crear la cuenta");
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
                    <CardTitle className="font-display text-2xl">Crear cuenta</CardTitle>
                    <CardDescription>Empieza a estudiar con Studia</CardDescription>
                </CardHeader>
                <CardContent>
                    <form onSubmit={handleSubmit} className="flex flex-col gap-4" data-testid="register-form">
                        <div className="flex flex-col gap-2">
                            <Label htmlFor="email">Email</Label>
                            <Input
                                id="email"
                                type="email"
                                required
                                autoComplete="email"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                data-testid="register-email"
                            />
                        </div>
                        <div className="flex flex-col gap-2">
                            <Label htmlFor="password">Contraseña</Label>
                            <Input
                                id="password"
                                type="password"
                                required
                                minLength={6}
                                autoComplete="new-password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                data-testid="register-password"
                            />
                            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                                Mínimo 6 caracteres
                            </span>
                        </div>
                        <Button type="submit" disabled={submitting} data-testid="register-submit">
                            {submitting ? "Creando…" : "Crear cuenta"}
                        </Button>
                        <p className="text-sm text-center" style={{ color: "var(--text-secondary)" }}>
                            ¿Ya tienes cuenta?{" "}
                            <Link to="/login" className="font-medium underline">
                                Inicia sesión
                            </Link>
                        </p>
                    </form>
                </CardContent>
            </Card>
        </div>
    );
}
