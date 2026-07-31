"""
Migración Fase 2: histórico de `attempts` del viejo `mode` a los ejes
(selection, behavior), y retirada del campo `mode`.

Dos pasos SEPARADOS, con una PUERTA entre ellos:
  (a) BACKFILL: para cada attempt con `mode` y SIN `selection`, derivar los ejes
      con el inverso EXACTO del mapeo de compat y $set-earlos.
  [puerta] contar attempts que quedarían sin `selection` (deben ser 0 para el unset).
  (b) $UNSET: quitar `mode` de TODOS los attempts.

- IDEMPOTENTE: backfill solo donde faltan ejes; $unset tolerante a que ya no esté.
  Re-ejecutar no rompe ni cambia nada.
- DRY RUN por defecto: sin DRY_RUN=0 explícito NO escribe; solo REPORTA cuántos
  tocaría cada paso y el conteo de la puerta.
- En modo real, ABORTA antes del $unset si la puerta no está en 0 (algún attempt
  con `mode` no mapeable, p. ej. un valor inesperado).

Uso (dry run — no escribe nada, por defecto):
    cd backend
    DB_NAME=studia_staging .venv/bin/python scripts/migrate_attempt_axes.py

Uso (real — explícito):
    cd backend
    DB_NAME=studia_staging DRY_RUN=0 .venv/bin/python scripts/migrate_attempt_axes.py

Variables: MONGO_URL, DB_NAME (de .env; DB_NAME antepuesto gana), DRY_RUN.
"""
import os
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

# Inverso EXACTO del mapeo de compat mode → (selection, behavior).
MODE_TO_AXES = {
    "exam": ("all", "exam"),
    "practice": ("all", "practice"),
    "errors": ("errors", "practice"),
    "srs": ("srs", "practice"),
    "favorites": ("favorites", "practice"),
}


async def main() -> int:
    dry_run = os.environ.get("DRY_RUN", "1").strip().lower() not in ("0", "false", "no")
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL y DB_NAME deben estar configurados (revisa backend/.env).")
        return 2

    db = AsyncIOMotorClient(mongo_url)[db_name]
    try:
        print("=" * 64)
        print(f"MIGRACIÓN attempts mode→ejes — Base: {db_name}")
        print("(DRY RUN: no se escribe nada)" if dry_run else "(MODO REAL: se escribirá)")
        print("=" * 64)

        total = await db.attempts.count_documents({})
        print(f"\nAttempts totales: {total}")

        # --- (a) BACKFILL ---------------------------------------------------
        print("\n[a] BACKFILL de ejes en attempts viejos (mode presente, sin selection)")
        backfilled = 0
        for mode, (selection, behavior) in MODE_TO_AXES.items():
            flt = {"mode": mode, "selection": {"$exists": False}}
            n = await db.attempts.count_documents(flt)
            if not n:
                continue
            backfilled += n
            if dry_run:
                print(f"    {mode:10s} → selection={selection}, behavior={behavior}: {n} (se haría)")
            else:
                res = await db.attempts.update_many(
                    flt, {"$set": {"selection": selection, "behavior": behavior}}
                )
                print(f"    {mode:10s} → selection={selection}, behavior={behavior}: {res.modified_count}")
        if backfilled == 0:
            print("    (nada que backfillear)")

        # --- [puerta] -------------------------------------------------------
        # Attempts que quedarían SIN selection tras el backfill: los que aún no la
        # tienen y cuyo `mode` no es mapeable (ausente o inesperado).
        stuck = await db.attempts.count_documents({
            "selection": {"$exists": False},
            "$or": [{"mode": {"$exists": False}}, {"mode": {"$nin": list(MODE_TO_AXES)}}],
        })
        # En dry-run el backfill no se aplicó: el residual real serían solo los `stuck`.
        remaining_no_axes = stuck if dry_run else await db.attempts.count_documents(
            {"selection": {"$exists": False}}
        )
        print(f"\n[puerta] attempts que quedarían/quedan SIN selection: {remaining_no_axes}")
        if remaining_no_axes:
            bad = await db.attempts.distinct("mode", {"selection": {"$exists": False}})
            print(f"    ⚠️ No mapeables (mode ausente/inesperado): {sorted(map(str, bad))}")
            if not dry_run:
                print("    ABORTADO: no se hace $unset con attempts sin ejes. Revisa esos docs.")
                return 1
        else:
            print("    ✓ todos los attempts tendrán ejes.")

        # --- (b) $UNSET mode ------------------------------------------------
        to_unset = await db.attempts.count_documents({"mode": {"$exists": True}})
        print(f"\n[b] $UNSET mode en attempts (campo presente): {to_unset}")
        if dry_run:
            print(f"    → se haría $unset en {to_unset} docs (no ejecutado).")
        else:
            res = await db.attempts.update_many(
                {"mode": {"$exists": True}}, {"$unset": {"mode": ""}}
            )
            print(f"    → modified_count: {res.modified_count}")

        print("=" * 64)
        if dry_run:
            print("MODO DRY RUN: no se ha escrito nada. Para ejecutar: DRY_RUN=0")
        else:
            print("Migración completada. Idempotente: re-ejecutarla no cambia nada.")
        return 0
    finally:
        db.client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
