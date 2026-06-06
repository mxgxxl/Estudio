import { createContext, useContext, useEffect, useState } from "react";
import {
    getToken,
    setToken,
    clearToken,
    getMe,
    login as apiLogin,
    register as apiRegister,
} from "@/lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);

    // Al arrancar la app, si hay token guardado, recuperamos el usuario.
    useEffect(() => {
        const token = getToken();
        if (!token) {
            setLoading(false);
            return;
        }
        getMe()
            .then(setUser)
            .catch(() => {
                clearToken();
                setUser(null);
            })
            .finally(() => setLoading(false));
    }, []);

    const login = async (email, password) => {
        const { access_token } = await apiLogin(email, password);
        setToken(access_token);
        const me = await getMe();
        setUser(me);
        return me;
    };

    const register = async (email, password) => {
        await apiRegister(email, password);
        return login(email, password);
    };

    const logout = () => {
        clearToken();
        setUser(null);
    };

    return (
        <AuthContext.Provider
            value={{ user, loading, isAuthenticated: !!user, login, register, logout }}
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
