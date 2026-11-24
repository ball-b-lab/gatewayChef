-- Flottenstände (services/fleet_snapshots.py legt die Tabelle auch selbst an)
CREATE TABLE IF NOT EXISTS fleet_snapshots (
    id BIGSERIAL PRIMARY KEY,
    taken_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deep BOOLEAN NOT NULL DEFAULT false,
    summary JSONB NOT NULL,
    rows JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fleet_snapshots_taken_at ON fleet_snapshots(taken_at DESC);
