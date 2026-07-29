"""
VERIFICACIÓN PREVIA (solo-lectura) para la retirada de `pdfs.topic_id`.

Puerta bloqueante antes de dejar de escribir el campo, hacer `$unset` y soltar los
índices. Este script NO escribe, NO borra, NO crea índices: solo LEE y CUENTA.

Reporta, para la BASE indicada por DB_NAME:

1. ¿Está aplicada la migración pdf_links? (observable, no de memoria):
   - nº total de documentos en `pdf_links`.
   - nº de PDFs con `topic_id` no vacío.
   Si hay PDFs con topic_id pero pdf_links está vacía/casi, migrate_pdf_links.py
   probablemente no se corrió.

2. COMPROBACIÓN CRÍTICA: PDFs con `topic_id` no vacío PERO sin ninguna `pdf_link`
   que cubra el par (user_id, pdf_id, topic_id). Son los que un `$unset` dejaría
   huérfanos. DEBE ser 0. Si es > 0, los lista (id, topic_id, user_id, filename).

3. Bonus de contexto: foto de cuántos docs tocaría el `$unset` (presencia del
   campo: no vacío / null explícito / campo ausente / cadena vacía).

Uso (anteponiendo DB_NAME, como el resto de scripts):
    cd backend
    DB_NAME=studia_staging .venv/bin/python scripts/verify_topic_id_retirement.py
    DB_NAME=studia_dev     .venv/bin/python scripts/verify_topic_id_retirement.py

Variables de entorno usadas: MONGO_URL, DB_NAME (de .env; DB_NAME antepuesto gana).
"""
import os
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Carga backend/.env (el script vive en backend/scripts/).
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

# "topic_id no vacío" = existe y no es None ni cadena vacía (mismo criterio que
# migrate_pdf_links.py, que salta con `if not topic_id`).
NON_EMPTY = {"topic_id": {"$exists": True, "$nin": [None, ""]}}


async def main() -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL y DB_NAME deben estar configurados (revisa backend/.env).")
        return 2

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    try:
        print("=" * 64)
        print(f"VERIFICACIÓN retirada pdfs.topic_id — Base: {db_name}")
        print("(solo-lectura: no se escribe, no se borra, no se crean índices)")
        print("=" * 64)

        # --- 1. ¿Migración pdf_links aplicada? -------------------------------
        total_pdfs = await db.pdfs.count_documents({})
        total_links = await db.pdf_links.count_documents({})
        pdfs_with_topic = await db.pdfs.count_documents(NON_EMPTY)

        print("\n[1] ¿Migración pdf_links aplicada? (observable)")
        print(f"    Documentos en pdf_links (total):        {total_links}")
        print(f"    PDFs con topic_id no vacío:             {pdfs_with_topic}")
        if pdfs_with_topic > 0 and total_links == 0:
            print("    ⚠️  Hay PDFs con topic_id pero pdf_links VACÍA:")
            print("        migrate_pdf_links.py probablemente NO se ejecutó.")

        # --- 2. COMPROBACIÓN CRÍTICA ----------------------------------------
        # PDFs con topic_id no vacío sin pdf_link que cubra (user_id, pdf_id, topic_id).
        uncovered = []
        cursor = db.pdfs.find(
            NON_EMPTY, {"_id": 0, "id": 1, "user_id": 1, "topic_id": 1, "filename": 1}
        )
        async for pdf in cursor:
            covered = await db.pdf_links.find_one(
                {
                    "user_id": pdf.get("user_id"),
                    "pdf_id": pdf.get("id"),
                    "topic_id": pdf.get("topic_id"),
                },
                {"_id": 0, "id": 1},
            )
            if not covered:
                uncovered.append(pdf)

        print("\n[2] COMPROBACIÓN CRÍTICA (debe ser 0)")
        print(f"    PDFs con topic_id SIN pdf_link que lo respalde: {len(uncovered)}")
        if uncovered:
            print("    ⚠️  Estos PDFs quedarían huérfanos con un $unset. NO abrir la puerta:")
            for p in uncovered:
                print(
                    f"      - id={p.get('id')}  topic_id={p.get('topic_id')}  "
                    f"user_id={p.get('user_id')}  filename={p.get('filename')!r}"
                )
        else:
            print("    ✓ Todos los topic_id están cubiertos por pdf_links.")

        # --- 3. Bonus: foto del $unset --------------------------------------
        n_non_empty = pdfs_with_topic
        n_null = await db.pdfs.count_documents({"topic_id": {"$type": "null"}})
        n_missing = await db.pdfs.count_documents({"topic_id": {"$exists": False}})
        n_empty_str = await db.pdfs.count_documents({"topic_id": ""})
        n_field_present = await db.pdfs.count_documents({"topic_id": {"$exists": True}})

        print("\n[3] Bonus: foto de la colección pdfs")
        print(f"    PDFs totales:                           {total_pdfs}")
        print(f"    · topic_id no vacío (biblioteca ligada):{n_non_empty}")
        print(f"    · topic_id = null explícito:            {n_null}")
        print(f"    · topic_id ausente (sin el campo):      {n_missing}")
        print(f"    · topic_id = '' (cadena vacía):         {n_empty_str}")
        print(f"    → docs con el campo presente ($unset tocaría): {n_field_present}")
        print("=" * 64)

        return 0 if not uncovered else 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
