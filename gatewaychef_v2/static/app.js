const state = {
    run: null,
    runtime: null,
    discovery: null,
    lastError: null,
};

const LAST_OPERATOR_KEY = "gatewaychef_v2_last_operator";

const timelineStates = [
    "DRAFT",
    "PRECHECK_PASSED",
    "CONFIG_PENDING",
    "CONFIG_APPLIED",
    "CLOUD_SYNCED",
    "VERIFIED",
    "DONE",
    "FAILED",
];

async function api(path, options = {}) {
    const response = await fetch(path, {
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
        ...options,
    });
    const payload = await response.json();
    if (!response.ok || payload.ok !== true) {
        const error = payload.error || { message: "Unbekannter Fehler" };
        const err = new Error(error.message || "Unbekannter Fehler");
        err.debug = {
            path,
            httpStatus: response.status,
            message: error.message || "Unbekannter Fehler",
            code: error.code || null,
            stage: error.stage || null,
            retryable: error.retryable ?? null,
            details: error.details || null,
        };
        throw err;
    }
    return payload.data;
}

function renderDebugError() {
    const box = document.getElementById("debugErrorBox");
    if (!box) return;
    if (!state.lastError) {
        box.className = "debug-box debug-empty";
        box.textContent = "Keine aktuellen API-Fehler.";
        return;
    }
    box.className = "debug-box debug-error";
    box.textContent = JSON.stringify(state.lastError, null, 2);
}

function formData() {
    return Object.fromEntries(new FormData(document.getElementById("runForm")).entries());
}

function setField(name, value, force = false) {
    const field = document.querySelector(`[name="${name}"]`);
    if (!field) return;
    if (!force && field.value) return;
    field.value = value || "";
}

async function copyText(value) {
    if (!value) return;
    try {
        await navigator.clipboard.writeText(String(value));
    } catch (_) {
        // ignore
    }
}

function openGatewayUrl(path) {
    window.open(`http://192.168.1.1${path}`, "_blank", "noopener,noreferrer");
}

function buildWifiQrValue(ssid) {
    if (!ssid) return "";
    return `WIFI:T:WPA;S:${ssid};P:rat4all!;;`;
}

function currentRunId() {
    return state.run?.run_id;
}

function renderRuntime() {
    if (!state.runtime) return;
    const summary = document.getElementById("runtimeSummary");
    const issues = document.getElementById("runtimeIssues");
    const missingCloud = state.runtime.missing_cloud_sync || [];
    const missingInventory = state.runtime.missing_inventory || [];
    const connectionGrid = document.getElementById("connectionGrid");
    summary.textContent = missingCloud.length || missingInventory.length
        ? "Konfiguration unvollstaendig"
        : "v2 Runtime bereit";
    issues.innerHTML = "";
    [...missingCloud, ...missingInventory].forEach((entry) => {
        const div = document.createElement("div");
        div.textContent = `${entry.group}: ${entry.missing.join(", ")}`;
        issues.appendChild(div);
    });

    const select = document.getElementById("simVendor");
    select.innerHTML = '<option value="">Bitte waehlen</option>';
    (state.runtime.sim_vendors || []).forEach((vendor) => {
        const option = document.createElement("option");
        option.value = vendor.id;
        option.textContent = `${vendor.name}${vendor.apn ? ` (${vendor.apn})` : ""}`;
        select.appendChild(option);
    });

    connectionGrid.innerHTML = "";
    (state.runtime.connections || []).forEach((connection) => {
        const item = document.createElement("div");
        item.className = "connection-item";
        const stateClass = connection.ok === true ? "state-ok" : connection.ok === false ? "state-fail" : "state-neutral";
        const label = connection.service || "service";
        item.innerHTML = `<div><strong>${label}</strong></div><div><span class="state ${stateClass}">${connection.ok === true ? "OK" : connection.ok === false ? "Fehler" : "Offen"}</span><small>${connection.message || "-"}</small></div>`;
        connectionGrid.appendChild(item);
    });
}

function renderDiscovery() {
    const badge = document.getElementById("gatewayClassBadge");
    const summary = document.getElementById("gatewaySummary");
    const warnings = document.getElementById("gatewayWarnings");
    const grid = document.getElementById("currentGrid");
    const discrepancyGrid = document.getElementById("discrepancyGrid");
    const actionTitle = document.getElementById("actionTitle");
    const actionNote = document.getElementById("actionNote");
    const gate = document.getElementById("discoveryGate");
    const correctionToggleRow = document.getElementById("correctionToggleRow");
    const showCorrections = document.getElementById("showCorrections");
    const actionContent = document.getElementById("actionContent");

    if (!state.discovery) {
        badge.textContent = "Discovery fehlt";
        badge.className = "state state-fail";
        summary.textContent = "Gateway konnte nicht gelesen werden.";
        return;
    }

    const classification = state.discovery.classification || {};
    const suggested = state.discovery.suggested_form || {};
    const loraHealth = state.discovery.lora_health || {};
    const db = state.discovery.db_record || {};
    const isGolden = classification.is_golden;
    const isConfigured = classification.is_configured;
    const hasDiscrepancies = (state.discovery.discrepancies || []).some((entry) => !entry.ok);

    badge.textContent = isGolden ? "Golden / unvollstaendig" : isConfigured ? "Bereits konfiguriert" : "Gateway erkannt";
    badge.className = `state ${isGolden ? "state-warn" : "state-ok"}`;

    summary.innerHTML = `
        <strong>Aktueller Gateway-Zustand wurde automatisch gelesen.</strong>
        <p>SSID: <strong>${suggested.current_ssid || "-"}</strong></p>
        <p>VPN IP: <strong>${suggested.current_vpn_ip || "-"}</strong></p>
        <p>EUI: <strong>${suggested.current_eui || "-"}</strong></p>
        <p>LoRa Health: <strong>${loraHealth.status || "-"}</strong>, LNS verbunden: <strong>${String(!!loraHealth.lns_connected)}</strong></p>
    `;

    warnings.innerHTML = "";
    const warningTexts = [];
    if (isGolden) {
        warningTexts.push("SSID ist `bbdbmon_golden`: Gateway gilt als noch nicht fertig konfiguriert.");
        warningTexts.push(`Naechste freie VPN-IP laut Inventar: ${suggested.next_free_vpn_ip || "-"}.`);
    }
    if (isGolden && classification.ssid_change_must_be_last) {
        warningTexts.push("SSID-Wechsel ist der letzte Schritt. Erst VPN, LoRa und Cloud-Sync sauber setzen.");
    }
    if (isConfigured) {
        warningTexts.push("Gateway wirkt bereits konfiguriert. Fokus liegt auf Pruefung der Abweichungen und gezielter Korrektur.");
    }
    warningTexts.forEach((text) => {
        const item = document.createElement("div");
        item.className = "warning-item";
        item.textContent = text;
        warnings.appendChild(item);
    });

    grid.innerHTML = "";
    const current = {
        CURRENT_SSID: suggested.current_ssid,
        CURRENT_VPN: suggested.current_vpn_ip,
        CURRENT_EUI: suggested.current_eui,
        DB_NAME: db.gateway_name,
        DB_SERIAL: db.serial_number,
        DB_SIM_ICCID: db.sim_iccid,
    };
    Object.entries(current).forEach(([label, value]) => {
        const item = document.createElement("div");
        item.className = "target-item";
        item.innerHTML = `<span class="target-label">${label}</span><span class="target-value">${value || "-"}</span>`;
        grid.appendChild(item);
    });

    discrepancyGrid.innerHTML = "";
    (state.discovery.discrepancies || []).forEach((entry) => {
        const item = document.createElement("div");
        item.className = `check-item ${entry.ok ? "pass" : "block"}`;
        item.innerHTML = `<strong>${entry.label}</strong><small>${entry.detail || ""}</small>`;
        discrepancyGrid.appendChild(item);
    });

    if (!hasDiscrepancies) {
        gate.textContent = "KONFIG OK";
        gate.className = "release release-pass";
    } else {
        gate.textContent = "FEHLT";
        gate.className = "release release-block";
    }

    correctionToggleRow.style.display = hasDiscrepancies ? "inline-flex" : "none";
    if (!hasDiscrepancies) {
        showCorrections.checked = false;
    }
    actionContent.style.display = hasDiscrepancies && !showCorrections.checked ? "none" : "";

    if (isConfigured) {
        actionTitle.textContent = "2. Abweichungen korrigieren";
        actionNote.textContent = "Dieser Gateway scheint bereits konfiguriert zu sein. Nutze die Schritte nur fuer fehlende oder fehlerhafte Punkte.";
    } else if (isGolden) {
        actionTitle.textContent = "2. Neu konfigurieren";
        actionNote.textContent = "Dieser Gateway ist noch nicht fertig. Reserviere neue Zielwerte und setze die finale SSID ganz am Ende.";
    } else {
        actionTitle.textContent = "2. Pruefen und korrigieren";
        actionNote.textContent = "Pruefe zuerst den Ist-Zustand. Nur Abweichungen muessen korrigiert werden.";
    }
}

function prefillFormFromDiscovery() {
    if (!state.discovery) return;
    const suggested = state.discovery.suggested_form || {};
    setField("serial_number", suggested.serial_number);
    setField("gateway_name", suggested.gateway_name);
    setField("sim_vendor_id", suggested.sim_vendor_id);
    setField("sim_iccid", suggested.sim_iccid);
    setField("operation_mode", suggested.operation_mode, true);
    const lastOperator = window.localStorage.getItem(LAST_OPERATOR_KEY);
    if (lastOperator) {
        setField("operator_name", lastOperator);
    }
}

function renderQuickActions() {
    const box = document.getElementById("gatewayQuickActions");
    box.innerHTML = "";
    const targetVpn = state.run?.context?.vpn_ip || state.discovery?.suggested_form?.next_free_vpn_ip || "";
    const targetSsid = state.run?.context?.wifi_ssid || state.discovery?.db_record?.wifi_ssid || "";
    const targetEui = state.run?.context?.discovered_eui || state.discovery?.suggested_form?.current_eui || "";
    const targetApn = state.run?.context?.apn || state.discovery?.db_record?.apn || "";
    const actions = [
        { label: "Gateway ID / EUI", value: targetEui, path: "/#packetforward/general" },
        { label: "VPN IP", value: targetVpn ? `${targetVpn}/32` : "", path: "/#network/vpn/wireguard" },
        { label: "WiFi SSID", value: targetSsid, path: "/#network/interfaces/wlan" },
        { label: "APN", value: targetApn, path: "/#network/interfaces/cellular" },
    ];
    actions.forEach((entry) => {
        const row = document.createElement("div");
        row.className = "check-item";
        row.innerHTML = `<div class="quick-action-row"><div><strong>${entry.label}</strong><small>${entry.value || "-"}</small></div></div>`;
        const controls = row.querySelector(".quick-action-row");
        const copyBtn = document.createElement("button");
        copyBtn.type = "button";
        copyBtn.textContent = "Copy";
        copyBtn.disabled = !entry.value;
        copyBtn.addEventListener("click", () => copyText(entry.value));
        const openBtn = document.createElement("button");
        openBtn.type = "button";
        openBtn.textContent = "Open";
        openBtn.addEventListener("click", () => openGatewayUrl(entry.path));
        controls.appendChild(copyBtn);
        controls.appendChild(openBtn);
        box.appendChild(row);
    });
}

function renderGatewayQr() {
    const card = document.getElementById("gatewayQrCard");
    const ssid = state.run?.context?.wifi_ssid || state.discovery?.db_record?.wifi_ssid || state.discovery?.suggested_form?.current_ssid || "";
    const vpnIp = state.run?.context?.vpn_ip || state.discovery?.suggested_form?.current_vpn_ip || "";
    const suffix = ssid.startsWith("bbdbmon_") ? ssid.replace("bbdbmon_", "") : "";
    const qrValue = buildWifiQrValue(ssid);
    const qrUrl = qrValue ? `https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encodeURIComponent(qrValue)}` : "";
    card.innerHTML = `
        <strong>Verbinden mit Gateway</strong>
        <p>SSID: <strong>${ssid || "-"}</strong></p>
        <p>Passwort: <strong>rat4all!</strong></p>
        <p>VPN Nummer: <strong>${suffix || (vpnIp ? vpnIp.split(".").slice(-2).join(".") : "-")}</strong></p>
        ${qrUrl ? `<img src="${qrUrl}" alt="Gateway QR" style="width:180px;height:180px;border-radius:12px;border:1px solid #dbe4ee;">` : ""}
        <p>Internetzugang nicht fuer private oder datenhungrige Anwendungen wie Musik und Video!</p>
    `;
    if (qrValue) {
        const copyBtn = document.createElement("button");
        copyBtn.type = "button";
        copyBtn.textContent = "QR-Inhalt kopieren";
        copyBtn.addEventListener("click", () => copyText(qrValue));
        card.appendChild(copyBtn);
    }
}

function renderRun() {
    const trace = document.getElementById("traceId");
    const badge = document.getElementById("stateBadge");
    const timeline = document.getElementById("timeline");
    const targetGrid = document.getElementById("targetGrid");
    const checks = document.getElementById("readinessChecks");
    const release = document.getElementById("releaseGate");
    const events = document.getElementById("events");

    trace.textContent = state.run?.run_id || "-";
    badge.textContent = state.run?.state || "Kein Lauf";
    badge.className = `state ${state.run?.state === "FAILED" ? "state-fail" : state.run?.state === "DONE" || state.run?.state === "VERIFIED" ? "state-ok" : "state-neutral"}`;

    timeline.innerHTML = "";
    timelineStates.forEach((item) => {
        const box = document.createElement("div");
        box.className = "timeline-item";
        box.innerHTML = `<strong>${item}</strong><small>${state.run?.state === item ? "Aktueller Zustand" : "Noch nicht erreicht"}</small>`;
        if (state.run?.state === item) {
            box.style.borderColor = "#87b2de";
        }
        timeline.appendChild(box);
    });

    targetGrid.innerHTML = "";
    const targets = {
        TARGET_VPN_IP: state.run?.context?.vpn_ip,
        TARGET_WIFI_SSID: state.run?.context?.wifi_ssid,
        TARGET_APN: state.run?.context?.apn,
        EUI: state.run?.context?.discovered_eui,
        GATEWAY_NAME: state.run?.gateway_name,
        SERIAL: state.run?.serial_number,
    };
    Object.entries(targets).forEach(([label, value]) => {
        const item = document.createElement("div");
        item.className = "target-item";
        item.innerHTML = `<span class="target-label">${label}</span><span class="target-value">${value || "-"}</span>`;
        targetGrid.appendChild(item);
    });

    const report = state.run?.report || {};
    checks.innerHTML = "";
    (report.checks || []).forEach((check) => {
        const item = document.createElement("div");
        item.className = `check-item ${check.ok ? "pass" : "block"}`;
        item.innerHTML = `<strong>${check.label}</strong><small>${check.result}</small>`;
        checks.appendChild(item);
    });
    release.textContent = report.release_gate || "BLOCK";
    release.className = `release ${report.release_gate === "PASS" ? "release-pass" : "release-block"}`;

    events.innerHTML = "";
    (state.run?.events || []).forEach((event) => {
        const item = document.createElement("div");
        item.className = "event-item";
        item.innerHTML = `<span class="event-stage">${event.stage} / ${event.event_type}</span><strong>${event.message}</strong><small>${event.created_at || ""}</small>`;
        if (event.payload && Object.keys(event.payload).length) {
            const pre = document.createElement("pre");
            pre.textContent = JSON.stringify(event.payload, null, 2);
            item.appendChild(pre);
        }
        events.appendChild(item);
    });
    renderQuickActions();
    renderGatewayQr();
}

async function reloadRun() {
    if (!currentRunId()) return;
    state.run = await api(`/gatewaychef-v2/api/runs/${currentRunId()}`);
    renderRun();
}

async function createRun() {
    const payload = formData();
    if (state.discovery?.suggested_form?.current_eui) {
        payload.discovered_eui = state.discovery.suggested_form.current_eui;
    }
    if (state.discovery?.suggested_form?.current_vpn_ip) {
        payload.current_vpn_ip = state.discovery.suggested_form.current_vpn_ip;
        payload.current_ssid = state.discovery.suggested_form.current_ssid;
    }
    state.run = await api("/gatewaychef-v2/api/runs", {
        method: "POST",
        body: JSON.stringify(payload),
    });
    if (payload.operator_name) {
        window.localStorage.setItem(LAST_OPERATOR_KEY, payload.operator_name);
    }
    renderRun();
}

async function executeAction(action) {
    if (!currentRunId()) {
        alert("Zuerst einen Lauf anlegen.");
        return;
    }
    if (action === "finalize" && state.run?.state !== "VERIFIED") {
        alert("Finaler Abschluss ist erst nach erfolgreicher Verifikation erlaubt.");
        return;
    }
    const payload = {};
    if (action === "confirm-config") {
        const note = window.prompt("Was wurde jetzt exakt korrigiert oder bestaetigt?", "Gateway-Konfiguration geprueft und erforderliche Abweichungen korrigiert.");
        if (note === null) return;
        payload.confirm_apply = true;
        payload.note = note;
    }
    if (action === "secret-bundle") {
        const confirmed = window.confirm("VPN-Key nur lokal und nur einmalig anzeigen?");
        if (!confirmed) return;
        payload.confirm_secret_access = true;
    }
    if (action === "cloud-sync" || action === "verify") {
        const form = formData();
        payload.webservice_username = form.webservice_username;
        payload.webservice_password = form.webservice_password;
    }
    const endpoint = {
        precheck: "precheck",
        reserve: "reserve",
        "confirm-config": "confirm-config",
        "secret-bundle": "secret-bundle",
        "cloud-sync": "cloud-sync",
        verify: "verify",
        finalize: "finalize",
    }[action];
    const result = await api(`/gatewaychef-v2/api/runs/${currentRunId()}/${endpoint}`, {
        method: "POST",
        body: JSON.stringify(payload),
    });
    if (action === "secret-bundle") {
        window.alert(`VPN IP: ${result.vpn_ip}\nPrivate Key:\n${result.private_key}`);
        await reloadRun();
        return;
    }
    state.run = result;
    renderRun();
}

async function loadDiscovery() {
    try {
        state.discovery = await api("/gatewaychef-v2/api/discovery");
        state.lastError = null;
        renderDiscovery();
        prefillFormFromDiscovery();
        renderDebugError();
    } catch (error) {
        state.lastError = error.debug || { message: error.message };
        document.getElementById("gatewayClassBadge").textContent = "Discovery Fehler";
        document.getElementById("gatewayClassBadge").className = "state state-fail";
        document.getElementById("gatewaySummary").textContent = error.message;
        renderDebugError();
    }
}

async function refreshConnections() {
    try {
        const form = formData();
        const data = await api("/gatewaychef-v2/api/connections", {
            method: "POST",
            body: JSON.stringify({
                webservice_username: form.webservice_username,
                webservice_password: form.webservice_password,
            }),
        });
        state.runtime = { ...(state.runtime || {}), connections: data.connections || [] };
        renderRuntime();
    } catch (_) {
        // Keep the page usable even if the diagnostics refresh fails.
    }
}

async function init() {
    try {
        state.runtime = await api("/gatewaychef-v2/api/runtime");
        state.lastError = null;
        renderRuntime();
        renderDebugError();
    } catch (error) {
        state.lastError = error.debug || { message: error.message };
        document.getElementById("runtimeSummary").textContent = error.message;
        renderDebugError();
    }

    await loadDiscovery();
    await refreshConnections();
    renderQuickActions();
    renderGatewayQr();

    document.getElementById("createRunBtn").addEventListener("click", async () => {
        try {
            await createRun();
            state.lastError = null;
            renderDebugError();
        } catch (error) {
            state.lastError = error.debug || { message: error.message };
            renderDebugError();
            alert(error.message);
        }
    });

    document.querySelectorAll("[data-action]").forEach((button) => {
        button.addEventListener("click", async () => {
            try {
                await executeAction(button.dataset.action);
                state.lastError = null;
                renderDebugError();
            } catch (error) {
                state.lastError = error.debug || { message: error.message };
                await reloadRun();
                renderDebugError();
                alert(error.message);
            }
        });
    });

    ["webservice_username", "webservice_password"].forEach((name) => {
        const field = document.querySelector(`[name="${name}"]`);
        if (!field) return;
        field.addEventListener("change", refreshConnections);
        field.addEventListener("blur", refreshConnections);
    });

    const correctionToggle = document.getElementById("showCorrections");
    correctionToggle.addEventListener("change", () => {
        const content = document.getElementById("actionContent");
        const shouldShow = correctionToggle.checked;
        content.style.display = shouldShow || !(state.discovery?.discrepancies || []).some((entry) => !entry.ok) ? "" : "none";
    });

    renderDebugError();
}

window.addEventListener("DOMContentLoaded", init);
