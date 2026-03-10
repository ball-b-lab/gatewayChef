#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db.connection import get_db_connection


def parse_args():
    parser = argparse.ArgumentParser(
        description="Import a generated gateway_inventory SQL file into PostgreSQL from the host machine."
    )
    parser.add_argument(
        "--sql-file",
        required=True,
        help="Path to generated gateway_inventory.sql",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate that the SQL file exists and DB connection works, but do not execute SQL.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    sql_path = Path(args.sql_file).resolve()
    if not sql_path.is_file():
        raise SystemExit(f"ERROR: SQL file not found: {sql_path}")

    sql = sql_path.read_text(encoding="utf-8").strip()
    if not sql:
        raise SystemExit(f"ERROR: SQL file is empty: {sql_path}")

    conn = get_db_connection()
    try:
        if args.dry_run:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database(), current_user")
                db_name, db_user = cur.fetchone()
            print(f"Dry run OK. Connected to database '{db_name}' as '{db_user}'.")
            print(f"SQL file: {sql_path}")
            return

        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        print(f"Import successful: {sql_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
