"""
Migración idempotente: asigna los documentos "huérfanos" (sin `user_id`) a un
único usuario propietario.

Contexto: antes del refactor multiusuario, las colecciones de contenido no tenían
`user_id` y todos los datos eran compartidos. Este script rellena `user_id` en
todos los documentos que aún no lo tengan, asignándolos al usuario indicado por
la variable de entorno LEGACY_OWNER_EMAIL.

Características:
- IDEMPOTENTE: solo toca documentos sin `user_id` (ausente, None o ""). Ejecutarlo
  varias veces no duplica ni reasigna nada.
- Imprime cuántos documentos actualiza por colección.
- NO crea usuarios: el email debe existir ya en la colección `users` (regístralo
  por la app antes de migrar).

Uso:
    cd backend
    LEGACY_OWNER_EMAIL=tu-email@ejemplo.com .venv/bin/python scripts/migrate_assign_owner.py

Variables de entorno usadas: MONGO_URL, DB_NAME (de .env) y LEGACY_OWNER_EMAIL.
"""
import os
import sys
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Carga backend/.env (el script vive en backend/scripts/).
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

# Colecciones de CONTENIDO del usuario. `users` NO se toca (es el catálogo).
COLLECTIONS = [
    "subjects",
    "topics",
    "pdfs",
    "questions",
    "attempts",
    "flashcards",
    "survival_records",
]

# Filtro de "huérfano": sin user_id (ausente, None o cadena vacía).
ORPHAN_FILTER = {
    "$or": [
        {"user_id": {"$exists": False}},
        {"user_id": None},
        {"user_id": ""},
    ]
}


async def main() -> int:
    owner_email = os.environ.get("LEGACY_OWNER_EMAIL", "").strip().lower()
    if not owner_email:
        print("ERROR: define LEGACY_OWNER_EMAIL con el email del usuario propietario.")
        return 2

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL y DB_NAME deben estar configurados (revisa backend/.env).")
        return 2

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    try:
        user = await db.users.find_one({"email": owner_email}, {"_id": 0, "id": 1, "email": 1})
        if not user:
            print(f"ERROR: no existe ningún usuario con email '{owner_email}' en la colección users.")
            print("Regístralo primero desde la app y vuelve a ejecutar el script.")
            return 1

        owner_id = user["id"]
        print(f"Propietario destino: {owner_email} (id={owner_id})")
        print("-" * 60)

        total = 0
        for coll_name in COLLECTIONS:
            coll = db[coll_name]
            orphans = await coll.count_documents(ORPHAN_FILTER)
            if orphans == 0:
                print(f"  {coll_name:18s}: 0 huérfanos (nada que hacer)")
                continue
            res = await coll.update_many(ORPHAN_FILTER, {"$set": {"user_id": owner_id}})
            print(f"  {coll_name:18s}: {res.modified_count} documentos actualizados")
            total += res.modified_count

        print("-" * 60)
        print(f"TOTAL actualizados: {total}")
        print("Migración completada. Es idempotente: re-ejecutarla actualizará 0 documentos.")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
