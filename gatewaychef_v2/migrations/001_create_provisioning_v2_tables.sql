CREATE TABLE IF NOT EXISTS provisioning_v2_runs (
    run_id UUID PRIMARY KEY,
    state TEXT NOT NULL,
    operator_name TEXT NOT NULL,
    gateway_name TEXT NOT NULL,
    serial_number TEXT NOT NULL,
    sim_vendor_id TEXT NOT NULL,
    sim_iccid TEXT NOT NULL,
    client_id TEXT,
    client_name TEXT,
    lns TEXT,
    manufacturer TEXT,
    gateway_type TEXT,
    requested_by TEXT,
    context_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_error_code TEXT,
    last_error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_provisioning_v2_runs_state ON provisioning_v2_runs(state);
CREATE INDEX IF NOT EXISTS idx_provisioning_v2_runs_gateway_name ON provisioning_v2_runs(gateway_name);
CREATE INDEX IF NOT EXISTS idx_provisioning_v2_runs_serial_number ON provisioning_v2_runs(serial_number);

CREATE TABLE IF NOT EXISTS provisioning_v2_events (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES provisioning_v2_runs(run_id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_provisioning_v2_events_run_id ON provisioning_v2_events(run_id);
CREATE INDEX IF NOT EXISTS idx_provisioning_v2_events_stage ON provisioning_v2_events(stage);
