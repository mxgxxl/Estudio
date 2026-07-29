"""
Migración de retirada de `pdfs.topic_id` (datos + índices).

Se ejecuta DESPUÉS de desplegar el código que ya no escribe ni lee el campo (la
atadura PDF<->tema vive solo en `pdf_links`). Puerta de seguridad previa: correr
antes `verify_topic_id_retirement.py` y confirmar que el conteo crítico es 0
(ningún PDF con topic_id sin pdf_link que lo respalde).

Hace, para la BASE indicada por DB_NAME:
  (a) $unset de `topic_id` en `pdfs` (update_many {topic_id: {$exists: true}}).
  (b) drop de los índices `pdfs.topic_id_1` y `pdfs.user_id_1_topic_id_1`,
      TOLERANTE a que ya no existan (como el drop_index de survival_records en
      server.py). No peta si el índice ya no está.

- IDEMPOTENTE: re-ejecutarla hace 0 unsets y 0 drops (no hay error).
- DRY RUN por defecto: sin DRY_RUN=0 explícito NO escribe nada; solo REPORTA
  cuántos docs tocaría y qué índices soltaría.

Uso (dry run — no escribe nada, valor por defecto):
    cd backend
    DB_NAME=studia_staging .venv/bin/python scripts/migrate_drop_pdf_topic_id.py

Uso (real — hay que pedirlo explícitamente):
    cd backend
    DB_NAME=studia_staging DRY_RUN=0 .venv/bin/python scripts/migrate_drop_pdf_topic_id.py

Variables de entorno: MONGO_URL, DB_NAME (de .env; DB_NAME antepuesto gana), DRY_RUN.
"""
import os
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Carga backend/.env (el script vive en backend/scripts/).
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

# Índices sobre pdfs.topic_id que hay que soltar (nombres autogenerados por Mongo).
INDEXES_TO_DROP = ["topic_id_1", "user_id_1_topic_id_1"]


async def main() -> int:
    # DRY RUN por defecto: solo se escribe si DRY_RUN es explícitamente "0"/"false".
    dry_run = os.environ.get("DRY_RUN", "1").strip().lower() not in ("0", "false", "no")

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL y DB_NAME deben estar configurados (revisa backend/.env).")
        return 2

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    try:
        print("=" * 64)
        print(f"RETIRADA pdfs.topic_id (datos + índices) — Base: {db_name}")
        print("(DRY RUN: no se escribe nada)" if dry_run else "(MODO REAL: se escribirá)")
        print("=" * 64)

        # --- (a) $unset del campo -------------------------------------------
        to_unset = await db.pdfs.count_documents({"topic_id": {"$exists": True}})
        print(f"\n[a] $unset topic_id en pdfs")
        print(f"    Docs con el campo topic_id presente: {to_unset}")
        if dry_run:
            print(f"    → se hará $unset en {to_unset} docs (no ejecutado).")
        else:
            res = await db.pdfs.update_many(
                {"topic_id": {"$exists": True}}, {"$unset": {"topic_id": ""}}
            )
            print(f"    → modified_count: {res.modified_count}")

        # --- (b) drop de índices (tolerante) --------------------------------
        existing = set((await db.pdfs.index_information()).keys())
        print(f"\n[b] drop de índices pdfs.topic_id")
        for name in INDEXES_TO_DROP:
            present = name in existing
            if dry_run:
                print(f"    {name}: {'presente → se soltaría' if present else 'ausente → nada que soltar'}")
            else:
                try:
                    await db.pdfs.drop_index(name)
                    print(f"    {name}: soltado")
                except Exception as e:
                    # Tolerante: si ya no existe (u otra causa benigna), no peta.
                    print(f"    {name}: no soltado ({type(e).__name__}: {e}) — se ignora")

        print("=" * 64)
        if dry_run:
            print("MODO DRY RUN: no se ha escrito nada. Para ejecutar: DRY_RUN=0")
        else:
            print("Retirada completada. Idempotente: re-ejecutarla no cambia nada.")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
