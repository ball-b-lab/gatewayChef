#!/usr/bin/env python3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db.connection import get_db_connection


def apply_v2_migrations():
    migrations_dir = PROJECT_ROOT / "gatewaychef_v2" / "migrations"
    files = sorted(path for path in migrations_dir.glob("*.sql") if path.is_file())
    if not files:
        print("Keine v2 Migrationen gefunden.")
        return

    try:
        conn = get_db_connection()
    except Exception as exc:
        print(f"DB Verbindung fuer v2 Migration fehlgeschlagen: {exc}")
        raise SystemExit(1) from exc
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations_v2 (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        conn.commit()

        for file_path in files:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM schema_migrations_v2 WHERE version = %s", (file_path.name,))
                already_applied = cur.fetchone() is not None
            if already_applied:
                print(f"SKIP {file_path.name}")
                continue
            sql = file_path.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute("INSERT INTO schema_migrations_v2(version) VALUES (%s)", (file_path.name,))
            conn.commit()
            print(f"APPLY {file_path.name}")
        print("v2 Migrationen abgeschlossen.")
    finally:
        conn.close()


if __name__ == "__main__":
    apply_v2_migrations()
