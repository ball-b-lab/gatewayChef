#!/usr/bin/env python3
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db.connection import get_db_connection


def apply_migrations():
    migrations_dir = PROJECT_ROOT / "migrations"

    files = sorted(
        [path for path in migrations_dir.glob("*.sql") if path.is_file()],
        key=lambda path: path.name,
    )

    if not files:
        print("Keine Migrationen gefunden.")
        return

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            conn.commit()

        for file_path in files:
            version = file_path.name
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = %s",
                    (version,),
                )
                already_applied = cur.fetchone() is not None

            if already_applied:
                print(f"SKIP {version}")
                continue

            sql = file_path.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations(version) VALUES (%s)",
                    (version,),
                )
            conn.commit()
            print(f"APPLY {version}")

        print("Migrationen abgeschlossen.")
    finally:
        conn.close()


if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    apply_migrations()
