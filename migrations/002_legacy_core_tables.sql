CREATE TABLE IF NOT EXISTS sim_vendors (
    id BIGSERIAL PRIMARY KEY,
    vendor_name TEXT NOT NULL UNIQUE,
    apn TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sim_cards (
    id BIGSERIAL PRIMARY KEY,
    vendor_id BIGINT NOT NULL REFERENCES sim_vendors(id),
    iccid TEXT NOT NULL,
    sim_id TEXT,
    assigned_gateway_id BIGINT,
    assigned_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (vendor_id, iccid)
);

CREATE INDEX IF NOT EXISTS idx_sim_cards_vendor_id ON sim_cards(vendor_id);
CREATE INDEX IF NOT EXISTS idx_sim_cards_assigned_gateway_id ON sim_cards(assigned_gateway_id);

CREATE TABLE IF NOT EXISTS gateway_inventory (
    id BIGSERIAL PRIMARY KEY,
    vpn_ip TEXT NOT NULL UNIQUE,
    private_key TEXT,
    eui TEXT,
    wifi_ssid TEXT,
    serial_number TEXT,
    gateway_name TEXT,
    status_overall TEXT NOT NULL DEFAULT 'FREE',
    sim_card_id BIGINT REFERENCES sim_cards(id),
    wifi_ip TEXT,
    apn TEXT,
    cellular_status TEXT,
    lte_connected BOOLEAN,
    cellular_ip TEXT,
    vpn_key_present BOOLEAN,
    gateway_vendor TEXT,
    gateway_model TEXT,
    lora_gateway_eui TEXT,
    lora_gateway_id TEXT,
    lora_active_server TEXT,
    lora_status TEXT,
    lora_pending BOOLEAN,
    conf_gateway_done BOOLEAN NOT NULL DEFAULT false,
    assigned_at TIMESTAMPTZ,
    last_gateway_sync_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_gateway_inventory_status_overall ON gateway_inventory(status_overall);
CREATE INDEX IF NOT EXISTS idx_gateway_inventory_eui ON gateway_inventory(eui);
CREATE INDEX IF NOT EXISTS idx_gateway_inventory_serial_number ON gateway_inventory(serial_number);
CREATE INDEX IF NOT EXISTS idx_gateway_inventory_sim_card_id ON gateway_inventory(sim_card_id);
