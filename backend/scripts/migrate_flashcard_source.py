"""
Migración idempotente: rellena `flashcards.pdf_source_id` en los temas que
tienen UN ÚNICO PDF, donde la atribución es inequívoca.

Contexto: las flashcards ahora guardan `pdf_source_id` (de qué PDF salieron),
para poder regenerar por PDF sin borrar el resto ni perder el progreso SRS. Las
tarjetas anteriores a este campo no lo tienen (`None`). No podemos adivinar la
fuente en temas con varios PDFs, pero SÍ en los de un solo PDF: todas sus
tarjetas provienen de ese único PDF.

ADITIVA y SEGURA:
- Solo escribe `pdf_source_id` en tarjetas donde hoy es None/ausente y cuyo
  tema tiene exactamente 1 PDF asociado (vía pdf_links).
- No borra ni modifica nada más. Las tarjetas de temas multi-PDF quedan como
  legacy (None) y las gestiona el endpoint de generación (se conservan en
  regeneraciones por subconjunto; se barren al regenerar el tema completo).
- IDEMPOTENTE: al re-ejecutar, ya no quedan tarjetas None en temas de 1 PDF.
- MODO DRY RUN: con DRY_RUN=1 (o --dry-run) NO escribe; solo cuenta.

Uso (dry run):
    cd backend
    DRY_RUN=1 .venv/bin/python scripts/migrate_flashcard_source.py

Uso (real):
    cd backend
    .venv/bin/python scripts/migrate_flashcard_source.py

Variables de entorno usadas: MONGO_URL, DB_NAME (de .env) y DRY_RUN.
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

    updated = 0            # tarjetas actualizadas
    topics_touched = 0     # temas de 1 PDF con tarjetas legacy
    skipped_multi = 0      # temas con != 1 PDF (no se tocan)

    try:
        # Temas que tienen alguna flashcard sin pdf_source_id.
        topic_ids = await db.flashcards.distinct(
            "topic_id", {"$or": [{"pdf_source_id": None}, {"pdf_source_id": {"$exists": False}}]}
        )
        for topic_id in topic_ids:
            # PDFs asociados al tema (fuente de verdad: pdf_links).
            pdf_ids = await db.pdf_links.distinct("pdf_id", {"topic_id": topic_id})
            if len(pdf_ids) != 1:
                skipped_multi += 1
                continue
            pdf_id = pdf_ids[0]

            flt = {
                "topic_id": topic_id,
                "$or": [{"pdf_source_id": None}, {"pdf_source_id": {"$exists": False}}],
            }
            n = await db.flashcards.count_documents(flt)
            if n == 0:
                continue
            topics_touched += 1
            if dry_run:
                updated += n
                continue
            res = await db.flashcards.update_many(flt, {"$set": {"pdf_source_id": pdf_id}})
            updated += res.modified_count

        print(f"  Tarjetas {'a actualizar' if dry_run else 'actualizadas'}: {updated}")
        print(f"  Temas de 1 PDF migrados:                {topics_touched}")
        print(f"  Temas multi-PDF (dejados como legacy):  {skipped_multi}")
        print("-" * 60)
        if dry_run:
            print("MODO DRY RUN: no se ha escrito nada")
        else:
            print("Migración completada. Idempotente: re-ejecutarla actualiza 0 tarjetas.")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
