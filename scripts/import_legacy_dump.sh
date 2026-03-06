#!/usr/bin/env bash
set -euo pipefail

# Required:
#   SOURCE_DATABASE_URL=postgresql://...
#   TARGET_DATABASE_URL=postgresql://...
# Optional:
#   LEGACY_SCHEMA=public
#   IMPORT_MODE=schema-and-data|data-only   (default: schema-and-data)
#   TABLES="gateway_inventory sim_cards sim_vendors"

SOURCE_DATABASE_URL="${SOURCE_DATABASE_URL:-}"
TARGET_DATABASE_URL="${TARGET_DATABASE_URL:-}"
LEGACY_SCHEMA="${LEGACY_SCHEMA:-public}"
IMPORT_MODE="${IMPORT_MODE:-schema-and-data}"
TABLES="${TABLES:-gateway_inventory sim_cards sim_vendors}"

if [[ -z "$SOURCE_DATABASE_URL" || -z "$TARGET_DATABASE_URL" ]]; then
  echo "ERROR: SOURCE_DATABASE_URL und TARGET_DATABASE_URL muessen gesetzt sein." >&2
  exit 1
fi

if ! command -v pg_dump >/dev/null 2>&1; then
  echo "ERROR: pg_dump nicht gefunden." >&2
  exit 1
fi

if ! command -v pg_restore >/dev/null 2>&1; then
  echo "ERROR: pg_restore nicht gefunden." >&2
  exit 1
fi

if [[ "$IMPORT_MODE" != "schema-and-data" && "$IMPORT_MODE" != "data-only" ]]; then
  echo "ERROR: IMPORT_MODE muss 'schema-and-data' oder 'data-only' sein." >&2
  exit 1
fi

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="$PROJECT_ROOT/backups"
mkdir -p "$BACKUP_DIR"
DUMP_FILE="$BACKUP_DIR/legacy_$(date +%Y%m%d_%H%M%S).dump"

echo "[1/4] Erzeuge Dump: $DUMP_FILE"

TABLE_ARGS=()
for table in $TABLES; do
  TABLE_ARGS+=("--table=${LEGACY_SCHEMA}.${table}")
done

DUMP_FLAGS=(--format=custom --no-owner --no-privileges)
RESTORE_FLAGS=(--no-owner --no-privileges --clean --if-exists)

if [[ "$IMPORT_MODE" == "data-only" ]]; then
  DUMP_FLAGS+=(--data-only)
  RESTORE_FLAGS+=(--data-only --disable-triggers)
fi

pg_dump "${DUMP_FLAGS[@]}" "${TABLE_ARGS[@]}" --dbname "$SOURCE_DATABASE_URL" --file "$DUMP_FILE"

echo "[2/4] Restore nach Ziel-DB"
pg_restore "${RESTORE_FLAGS[@]}" --dbname "$TARGET_DATABASE_URL" "$DUMP_FILE"

echo "[3/4] Fuehre App-Migrationen aus"
python3 "$PROJECT_ROOT/scripts/migrate.py"

echo "[4/4] Fertig"
echo "Import abgeschlossen. Dump-Datei: $DUMP_FILE"
