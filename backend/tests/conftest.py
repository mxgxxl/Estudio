"""
Configuración de pytest para los tests in-process del backend.

Parchea el driver de Mongo (`motor`) con un cliente en memoria
(`mongomock_motor`) ANTES de que se importe `server`, de modo que el smoke test
de multiusuario pueda arrancar la app con FastAPI TestClient sin necesitar un
MongoDB real ni claves de Gemini.

Solo afecta a los tests que importan `server` (el smoke in-process). Los tests
de integración que golpean un BASE_URL remoto no importan `server` y no se ven
alterados.
"""
import os

# Variables mínimas que `server` lee en import-time.
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "studia_test_multiuser")
os.environ.setdefault("JWT_SECRET", "test-secret-multiuser-isolation")
os.environ.setdefault("CORS_ORIGINS", "*")
# Sin clave de Gemini: el smoke test no llama al modelo real (se mockea).
os.environ.setdefault("GEMINI_API_KEY", "")

# Parchea motor con el cliente en memoria antes de importar server en los tests.
import motor.motor_asyncio  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

motor.motor_asyncio.AsyncIOMotorClient = AsyncMongoMockClient
