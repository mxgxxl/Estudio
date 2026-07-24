"""
Migración idempotente: inicializa el contador de CORRECCIONES en los usuarios
existentes (`ai_corrections_used = 0`).

Contexto: la cuota de IA pasa a tener DOS contadores independientes que comparten
el mismo periodo (`ai_period_start`, ciclo unificado):
- `ai_generations_used`  → crear material (ya existía).
- `ai_corrections_used`  → evaluar respuestas de desarrollo (NUEVO).

Como comparten periodo, no hace falta un `period_start` propio de correcciones:
basta con que el nuevo contador exista a 0. El backend ya trata el campo ausente
como 0 y reinicia ambos al expirar el periodo, pero dejamos los datos coherentes.

ADITIVA y SEGURA:
- Pone `ai_corrections_used = 0` SOLO en los usuarios que aún no tienen el campo.
- Si algún usuario (muy antiguo) no tuviera `ai_period_start`, lo inicializa a
  ahora para que el ciclo unificado tenga una fecha de referencia.
- No toca `ai_generations_used`, `plan` ni nada de suscripción.
- IDEMPOTENTE: re-ejecutar actualiza 0 usuarios.
- MODO DRY RUN: con DRY_RUN=1 (o --dry-run) NO escribe; solo cuenta.

Uso (dry run):
    cd backend
    DRY_RUN=1 .venv/bin/python scripts/migrate_corrections_counter.py

Uso (real):
    cd backend
    .venv/bin/python scripts/migrate_corrections_counter.py

Variables de entorno usadas: MONGO_URL, DB_NAME (de .env) y DRY_RUN.
"""
import os
import sys
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


async def main() -> int:
    dry_run = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "True") or "--dry-run" in sys.argv[1:]

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL y DB_NAME deben estar configurados (revisa backend/.env).")
        return 2

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    print(f"Base de datos: {db_name}")
    if dry_run:
        print("(DRY RUN: no se escribirá nada en Mongo)")
    print("-" * 60)

    try:
        missing_counter = {"ai_corrections_used": {"$exists": False}}
        missing_period = {"ai_period_start": {"$exists": False}}

        n_counter = await db.users.count_documents(missing_counter)
        n_period = await db.users.count_documents(missing_period)

        if not dry_run:
            await db.users.update_many(missing_counter, {"$set": {"ai_corrections_used": 0}})
            if n_period:
                await db.users.update_many(
                    missing_period, {"$set": {"ai_period_start": datetime.now(timezone.utc).isoformat()}}
                )

        print(f"  Usuarios {'a inicializar' if dry_run else 'inicializados'} (ai_corrections_used=0): {n_counter}")
        if n_period:
            print(f"  Usuarios sin ai_period_start {'a fijar' if dry_run else 'fijados'} a ahora: {n_period}")
        print("-" * 60)
        if dry_run:
            print("MODO DRY RUN: no se ha escrito nada")
        else:
            print("Migración completada. Idempotente: re-ejecutarla actualiza 0 usuarios.")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
