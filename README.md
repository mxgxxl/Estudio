# Studia

App de estudio que genera preguntas, flashcards y resúmenes a partir de PDFs usando IA
(Google Gemini). En proceso de convertirse en un SaaS de oposiciones freemium con
autenticación, multiusuario, **límites de uso de IA** y **pagos con Paddle**.

- Backend: FastAPI + MongoDB (`backend/server.py`).
- Frontend: React + Tailwind (`frontend/`).
- Ver `CLAUDE.md` para la guía completa del proyecto.

## Arranque local

```bash
# Backend
cd backend
cp .env.example .env          # y rellena los valores
uvicorn server:app --reload   # http://127.0.0.1:8000

# Frontend (otra terminal)
cd frontend
yarn install
yarn start                    # http://localhost:3000
```

---

## Pagos con Paddle (Billing v4 · Sandbox)

El plan **premium** se deriva siempre del estado de la suscripción. El flujo es:

1. Frontend abre el **Paddle Overlay Checkout** (Paddle aloja el formulario; nunca
   tocamos datos de tarjeta).
2. Paddle envía **webhooks** a `POST /api/webhooks/paddle`.
3. El backend **verifica la firma**, actualiza `users.plan`/`subscription_status` y
   responde 200.

### 1) Variables de entorno a rellenar

**Backend** (`backend/.env`):

| Variable | Dónde se obtiene en el panel de Paddle (Sandbox) |
|----------|--------------------------------------------------|
| `PADDLE_ENV=sandbox` | Fijo en sandbox. |
| `PADDLE_API_KEY` | **Developer Tools → Authentication → API keys**. Empieza por `pdl_sdbx_apikey_...`. |
| `PADDLE_WEBHOOK_SECRET` | **Developer Tools → Notifications →** (tu destino) **→ Secret key**. Empieza por `pdl_ntfset_...`. |
| `PADDLE_PREMIUM_PRICE_ID` | **Catalog → Products →** (tu producto Premium) **→ Prices**. Empieza por `pri_...`. |

**Frontend** (`frontend/.env`):

| Variable | Dónde se obtiene |
|----------|------------------|
| `REACT_APP_PADDLE_CLIENT_TOKEN` | **Developer Tools → Authentication → Client-side tokens**. (token público de cliente). |
| `REACT_APP_PADDLE_ENV=sandbox` | Fijo en sandbox. |
| `REACT_APP_PADDLE_PREMIUM_PRICE_ID` | El mismo `pri_...` que `PADDLE_PREMIUM_PRICE_ID`. |

> Tras editar `frontend/.env` hay que **reiniciar** `yarn start` (CRA solo lee las
> env al arrancar).

### 2) Exponer el backend para que Paddle llegue al webhook

Paddle necesita una **URL pública** para entregar los webhooks; tu `localhost` no le
sirve. Levanta un túnel hacia tu backend (puerto 8000). Elige UNA opción:

**Opción A — ngrok**
```bash
# Instálalo tú si no lo tienes: https://ngrok.com/download
ngrok http 8000
# Copia la URL https que muestra, p. ej. https://abcd-1234.ngrok-free.app
```

**Opción B — cloudflared**
```bash
# Instálalo tú: https://developers.cloudflare.com/cloudflare-tunnel/
cloudflared tunnel --url http://localhost:8000
# Copia la URL https que muestra, p. ej. https://algo.trycloudflare.com
```

Luego, en el panel de Paddle: **Developer Tools → Notifications → New destination**
(o edita el existente):
- **URL**: `https://TU-URL-PUBLICA/api/webhooks/paddle`
- **Type**: Webhook · **Version**: Billing (v4, la actual).
- Eventos a suscribir: `subscription.created`, `subscription.activated`,
  `subscription.updated`, `subscription.canceled`, `subscription.past_due`,
  `transaction.completed`.
- Guarda y copia el **Secret key** del destino → ese es `PADDLE_WEBHOOK_SECRET`.

> Cada vez que reinicies el túnel la URL cambia (en planes gratuitos): actualiza la
> URL del destino en Paddle.

### 3) Simular un webhook con curl (sin túnel)

Para probar el endpoint sin Paddle, firma el cuerpo con tu `PADDLE_WEBHOOK_SECRET`
y mándalo a tu backend local. Este script genera la cabecera `Paddle-Signature`
correcta y hace el POST:

```bash
# Ejecútalo desde la raíz del repo. Cambia EMAIL por el de un usuario registrado.
python3 - <<'PY'
import hmac, hashlib, json, time, urllib.request

SECRET = "PEGAR_AQUI"            # = PADDLE_WEBHOOK_SECRET de tu .env
URL    = "http://127.0.0.1:8000/api/webhooks/paddle"
EMAIL  = "tu-usuario@example.com"

payload = {
    "event_id": "evt_demo_001",
    "event_type": "subscription.activated",
    "occurred_at": "2026-01-01T00:00:00Z",
    "data": {
        "id": "sub_demo_001",
        "status": "active",
        "customer_id": "ctm_demo_001",
        "customer_email": EMAIL,
        "current_billing_period": {"starts_at": "2026-01-01T00:00:00Z",
                                    "ends_at": "2099-01-01T00:00:00Z"},
    },
}
body = json.dumps(payload).encode()
ts = str(int(time.time()))
h1 = hmac.new(SECRET.encode(), f"{ts}:".encode() + body, hashlib.sha256).hexdigest()

req = urllib.request.Request(URL, data=body, method="POST", headers={
    "Content-Type": "application/json",
    "Paddle-Signature": f"ts={ts};h1={h1}",
})
print(urllib.request.urlopen(req).read().decode())
PY
```

- Respuesta `{"ok": true}` → suscripción aplicada. Comprueba con
  `GET /api/billing/status` (con el token del usuario) que `plan` es `premium`.
- Para probar la **baja**: repite con `"event_type": "subscription.canceled"`,
  `"status": "canceled"` y un `event_id` nuevo → `plan` vuelve a `free`.
- Firma mal el cuerpo (cambia un carácter de `h1`) → responde **401**.

### 4) Simular una compra real en Sandbox (con túnel activo)

1. Con el túnel arriba y el webhook configurado, inicia sesión en el frontend.
2. Pulsa **"Hazte Premium"** (en el modal de límite o en el panel de cuenta) → se
   abre el Overlay de Paddle.
3. Usa la **tarjeta de prueba de Paddle Sandbox**:
   - Número: `4242 4242 4242 4242`
   - Fecha: cualquier fecha futura · CVC: cualquier 3 dígitos · Nombre/CP: cualquiera.
4. Completa el pago. Paddle dispara `subscription.activated` al webhook y, tras el
   callback `checkout.completed`, el frontend refresca el estado: verás el plan
   **Premium** y el contador de cuota actualizado.

> Documentación de tarjetas de test de Paddle:
> https://developer.paddle.com/concepts/payment-methods/credit-debit-card

### 5) Al desplegar en Railway

⚠️ **Recuerda añadir todas las variables `PADDLE_*` al servicio del backend en
Railway** (`PADDLE_ENV`, `PADDLE_API_KEY`, `PADDLE_WEBHOOK_SECRET`,
`PADDLE_PREMIUM_PRICE_ID`) y las `REACT_APP_PADDLE_*` al frontend. Además, cambia la
URL del destino del webhook en Paddle a la URL pública de Railway
(`https://TU-APP.up.railway.app/api/webhooks/paddle`).
