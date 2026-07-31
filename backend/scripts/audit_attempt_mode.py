"""
AUDITORÍA (solo-lectura) del campo `attempts.mode` para la Fase 2 (retirada).

Cuenta, para la BASE indicada por DB_NAME:
  - Attempts totales.
  - Con `mode` presente.
  - Con los ejes nuevos (selection Y behavior) — creados desde el deploy de Fase 1.
  - Solo con `mode`, sin ejes (los viejos, a MIGRAR).
  - Desglose de `mode` entre los viejos (para dimensionar el mapeo).

NO escribe nada.

Uso:
    cd backend
    DB_NAME=studia_staging .venv/bin/python scripts/audit_attempt_mode.py
    DB_NAME=studia_dev     .venv/bin/python scripts/audit_attempt_mode.py
"""
import os
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


async def main() -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL y DB_NAME deben estar configurados (revisa backend/.env).")
        return 2

    db = AsyncIOMotorClient(mongo_url)[db_name]
    try:
        print("=" * 60)
        print(f"AUDITORÍA attempts.mode — Base: {db_name} (solo-lectura)")
        print("=" * 60)

        total = await db.attempts.count_documents({})
        with_mode = await db.attempts.count_documents({"mode": {"$exists": True}})
        with_axes = await db.attempts.count_documents(
            {"selection": {"$exists": True}, "behavior": {"$exists": True}}
        )
        old_only = await db.attempts.count_documents(
            {"mode": {"$exists": True}, "selection": {"$exists": False}}
        )
        no_mode_no_axes = await db.attempts.count_documents(
            {"mode": {"$exists": False}, "selection": {"$exists": False}}
        )

        print(f"\n  Attempts totales:                         {total}")
        print(f"  · con `mode` presente:                    {with_mode}")
        print(f"  · con ejes nuevos (selection+behavior):   {with_axes}")
        print(f"  · SOLO mode, sin ejes (A MIGRAR):         {old_only}")
        print(f"  · sin mode y sin ejes (raro, revisar):    {no_mode_no_axes}")

        # Desglose de `mode` entre los viejos (sin ejes) para dimensionar el mapeo.
        print("\n  Desglose de `mode` en los viejos (a migrar):")
        any_old = False
        for m in ("exam", "practice", "errors", "srs", "favorites"):
            c = await db.attempts.count_documents(
                {"mode": m, "selection": {"$exists": False}}
            )
            if c:
                any_old = True
                print(f"      {m:10s}: {c}")
        if not any_old:
            print("      (ninguno)")

        # Valores de `mode` fuera de los 5 esperados (por si hay basura).
        distinct_modes = await db.attempts.distinct("mode")
        unexpected = [m for m in distinct_modes if m not in
                      ("exam", "practice", "errors", "srs", "favorites")]
        print(f"\n  Valores de `mode` distintos hallados: {sorted(map(str, distinct_modes))}")
        if unexpected:
            print(f"  ⚠️ Valores inesperados de mode: {unexpected}")
        print("=" * 60)
        return 0
    finally:
        db.client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
