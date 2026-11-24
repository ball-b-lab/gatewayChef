-- Gateway-Meldungen (services/gw_reports.py legt die Tabelle auch selbst an)
CREATE TABLE IF NOT EXISTS gw_reports (
    id BIGSERIAL PRIMARY KEY,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    eui TEXT,
    vpn_ip TEXT,
    kind TEXT NOT NULL,
    boot BOOLEAN NOT NULL DEFAULT false,
    uptime_s BIGINT,
    data JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gw_reports_ip_time ON gw_reports(vpn_ip, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_gw_reports_eui_time ON gw_reports(eui, received_at DESC);
