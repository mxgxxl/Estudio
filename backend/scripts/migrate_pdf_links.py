"""
Migración idempotente: crea la colección intermedia `pdf_links` a partir del
`topic_id` embebido en cada documento de `pdfs`.

Contexto: hasta ahora un PDF estaba atado a un único tema mediante `pdfs.topic_id`.
Para soportar la relación muchos-a-muchos (un PDF en varios temas/asignaturas) la
relación pasa a vivir en la colección `pdf_links` (una fila por asociación).

Esta migración es ADITIVA y SEGURA:
- Por cada `pdfs` con `topic_id` no vacío, crea una fila en `pdf_links`
  {user_id, pdf_id, topic_id, subject_id} si no existe ya.
- NO toca `pdfs.text` ni borra `pdfs.topic_id` (se conserva como red de seguridad
  para poder hacer rollback al backend anterior). Se eliminará en una fase futura.
- IDEMPOTENTE: la clave única (user_id, pdf_id, topic_id) de pdf_links hace que
  re-ejecutar el script cree 0 vínculos nuevos.
- Cuenta y reporta: vínculos creados, ya existentes, y PDFs sin topic válido.
- MODO DRY RUN: con DRY_RUN=1 (o --dry-run) NO escribe nada; solo cuenta.

Uso (dry run — no escribe nada):
    cd backend
    DRY_RUN=1 .venv/bin/python scripts/migrate_pdf_links.py

Uso (real):
    cd backend
    .venv/bin/python scripts/migrate_pdf_links.py

Variables de entorno usadas: MONGO_URL, DB_NAME (de .env) y DRY_RUN.
"""
import os
import sys
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

# Carga backend/.env (el script vive en backend/scripts/).
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


async def _ensure_unique_index(db) -> None:
    """Garantiza el índice único que da idempotencia (por si el backend nuevo aún
    no ha arrancado y creado los índices)."""
    await db.pdf_links.create_index(
        [("user_id", ASCENDING), ("pdf_id", ASCENDING), ("topic_id", ASCENDING)],
        unique=True,
    )


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
    else:
        await _ensure_unique_index(db)
    print("-" * 60)

    created = 0
    already = 0
    skipped_no_topic = 0
    skipped_no_user = 0

    try:
        cursor = db.pdfs.find({}, {"_id": 0, "id": 1, "user_id": 1, "topic_id": 1})
        async for pdf in cursor:
            pdf_id = pdf.get("id")
            user_id = pdf.get("user_id")
            topic_id = pdf.get("topic_id")

            if not topic_id:
                skipped_no_topic += 1
                continue
            if not user_id:
                # Sin propietario no podemos aislar por usuario: ejecutar antes la
                # migración de multiusuario (migrate_assign_owner.py).
                skipped_no_user += 1
                continue

            # subject_id desnormalizado desde el topic (si existe).
            topic = await db.topics.find_one(
                {"id": topic_id, "user_id": user_id}, {"_id": 0, "subject_id": 1}
            )
            subject_id = topic.get("subject_id") if topic else None

            existing = await db.pdf_links.find_one(
                {"user_id": user_id, "pdf_id": pdf_id, "topic_id": topic_id}, {"_id": 0, "id": 1}
            )
            if existing:
                already += 1
                continue

            if dry_run:
                created += 1  # se crearía
                continue

            link = {
                "id": str(uuid4()),
                "user_id": user_id,
                "pdf_id": pdf_id,
                "topic_id": topic_id,
                "subject_id": subject_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                await db.pdf_links.insert_one(link)
                created += 1
            except DuplicateKeyError:
                # Otra ejecución concurrente ya lo creó: idempotente.
                already += 1

        print(f"  Vínculos {'a crear' if dry_run else 'creados'}: {created}")
        print(f"  Vínculos ya existentes (sin cambios):   {already}")
        print(f"  PDFs sin topic_id (ignorados):          {skipped_no_topic}")
        if skipped_no_user:
            print(f"  PDFs sin user_id (ejecuta migrate_assign_owner primero): {skipped_no_user}")
        print("-" * 60)
        if dry_run:
            print("MODO DRY RUN: no se ha escrito nada")
        else:
            print("Migración completada. Es idempotente: re-ejecutarla creará 0 vínculos nuevos.")
            print("No se ha tocado pdfs.text ni pdfs.topic_id (rollback seguro).")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
