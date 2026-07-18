// Integración con Paddle.js (Billing v4). Carga el script UNA sola vez,
// inicializa el entorno + token, y expone helpers para abrir el checkout.
import { billingCheckout } from "@/lib/api";

const PADDLE_JS = "https://cdn.paddle.com/paddle/v2/paddle.js";

let paddlePromise = null;

function loadScript() {
    return new Promise((resolve, reject) => {
        if (window.Paddle) return resolve(window.Paddle);
        const existing = document.querySelector(`script[src="${PADDLE_JS}"]`);
        if (existing) {
            existing.addEventListener("load", () => resolve(window.Paddle));
            existing.addEventListener("error", reject);
            return;
        }
        const s = document.createElement("script");
        s.src = PADDLE_JS;
        s.async = true;
        s.onload = () => resolve(window.Paddle);
        s.onerror = () => reject(new Error("No se pudo cargar Paddle.js"));
        document.head.appendChild(s);
    });
}

// Inicializa Paddle una sola vez (memoizado). El eventCallback global emite un
// evento de ventana cuando el checkout se completa, para refrescar la UI.
export function initPaddle() {
    if (paddlePromise) return paddlePromise;
    const token = process.env.REACT_APP_PADDLE_CLIENT_TOKEN;
    const env = process.env.REACT_APP_PADDLE_ENV || "sandbox";
    paddlePromise = loadScript().then((Paddle) => {
        if (!Paddle) throw new Error("Paddle.js no disponible");
        if (typeof Paddle.Environment?.set === "function") Paddle.Environment.set(env);
        Paddle.Initialize({
            token,
            eventCallback: (ev) => {
                const name = ev?.name || ev?.type;
                if (name === "checkout.completed") {
                    window.dispatchEvent(new CustomEvent("studia:checkout-completed", { detail: ev }));
                }
            },
        });
        return Paddle;
    });
    return paddlePromise;
}

// Abre el Paddle Overlay Checkout para el plan Premium.
// Inyecta customData.user_id para que el webhook empareje por ID propio (viaja
// firmado en el propio evento) sin depender de la resolución por email.
export async function openPremiumCheckout({ priceId, email, userId }) {
    const Paddle = await initPaddle();
    Paddle.Checkout.open({
        items: [{ priceId, quantity: 1 }],
        ...(email ? { customer: { email } } : {}),
        ...(userId ? { customData: { user_id: userId } } : {}),
        settings: { displayMode: "overlay", theme: "light", locale: "es" },
    });
}

// Flujo completo: pide datos al backend (valida plan/precio) y abre el overlay.
// Lanza el error de la API (p. ej. 409 si ya es premium) para que el caller lo trate.
export async function startPremiumCheckout(fallbackEmail) {
    const data = await billingCheckout();
    const priceId = process.env.REACT_APP_PADDLE_PREMIUM_PRICE_ID || data.price_id;
    await openPremiumCheckout({
        priceId,
        email: data.customer_email || fallbackEmail,
        userId: data.user_id,
    });
}
