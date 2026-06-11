import { createContext, useCallback, useContext, useEffect, useState } from "react";
import {
    getToken,
    setToken,
    clearToken,
    getMe,
    getUsage,
    login as apiLogin,
    register as apiRegister,
} from "@/lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
    const [user, setUser] = useState(null);
    const [usage, setUsage] = useState(null);
    const [loading, setLoading] = useState(true);

    // Refresca el contador de uso de IA del usuario.
    const refreshUsage = useCallback(() => {
        if (!getToken()) return Promise.resolve(null);
        return getUsage()
            .then((u) => {
                setUsage(u);
                return u;
            })
            .catch(() => null);
    }, []);

    // Refresca el documento del usuario (p. ej. el plan tras un pago).
    const refreshUser = useCallback(() => {
        if (!getToken()) return Promise.resolve(null);
        return getMe()
            .then((me) => {
                setUser(me);
                return me;
            })
            .catch(() => null);
    }, []);

    // Al arrancar la app, si hay token guardado, recuperamos el usuario y el uso.
    useEffect(() => {
        const token = getToken();
        if (!token) {
            setLoading(false);
            return;
        }
        getMe()
            .then((me) => {
                setUser(me);
                return refreshUsage();
            })
            .catch(() => {
                clearToken();
                setUser(null);
            })
            .finally(() => setLoading(false));
    }, [refreshUsage]);

    // Tras cualquier generación de IA correcta, refrescamos el contador.
    useEffect(() => {
        const onGenerated = () => refreshUsage();
        window.addEventListener("studia:ai-generated", onGenerated);
        return () => window.removeEventListener("studia:ai-generated", onGenerated);
    }, [refreshUsage]);

    // Tras completar un checkout de Paddle, el webhook actualiza el plan en el
    // backend; refrescamos usuario y contador (con un pequeño margen para que el
    // webhook llegue). El panel de cuenta también refresca su estado.
    useEffect(() => {
        const onCheckout = () => {
            const tick = () => {
                refreshUser();
                refreshUsage();
            };
            tick();
            setTimeout(tick, 2500);
        };
        window.addEventListener("studia:checkout-completed", onCheckout);
        return () => window.removeEventListener("studia:checkout-completed", onCheckout);
    }, [refreshUser, refreshUsage]);

    const login = async (email, password) => {
        const { access_token } = await apiLogin(email, password);
        setToken(access_token);
        const me = await getMe();
        setUser(me);
        await refreshUsage();
        return me;
    };

    const register = async (email, password) => {
        await apiRegister(email, password);
        return login(email, password);
    };

    const logout = () => {
        clearToken();
        setUser(null);
        setUsage(null);
    };

    return (
        <AuthContext.Provider
            value={{ user, usage, loading, isAuthenticated: !!user, login, register, logout, refreshUsage, refreshUser }}
        >
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const ctx = useContext(AuthContext);
    if (!ctx) throw new Error("useAuth debe usarse dentro de <AuthProvider>");
    return ctx;
}
