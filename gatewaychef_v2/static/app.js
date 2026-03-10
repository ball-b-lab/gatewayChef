const state = {
    run: null,
    runtime: null,
    discovery: null,
    lastError: null,
    lastSuggestedGatewayName: "",
};

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

function escapeHtml(value) {
    return String(value || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
}

function explainError(error) {
    const code = error?.code || "unknown_error";
    const details = error?.details || {};
    const messages = {
        missing_fields: {
            title: "Pflichtangaben fehlen",
            action: `Bitte diese Felder ausfuellen: ${(details.missing || []).join(", ") || "Pflichtfelder"}.`,
        },
        missing_webservice_credentials: {
            title: "Webservice-Login fehlt",
            action: "Webservice User und Passwort oben eintragen, dann den Schritt erneut ausfuehren.",
        },
        cleanup_confirmation_required: {
            title: "Neu konfigurieren ist noch nicht bestaetigt",
            action: "Nur den Button `Neu konfigurieren` verwenden und den Sicherheitshinweis bestaetigen.",
        },
        verification_failed: {
            title: "Readiness noch nicht erreicht",
            action: "Die roten Punkte in `Status & Naechste Schritte` abarbeiten und danach erneut verifizieren.",
        },
        invalid_state_transition: {
            title: "Schritt in diesem Zustand nicht erlaubt",
            action: "Die sichtbaren Schritte von links nach rechts ausfuehren. Uebersprungene Pflichtschritte zuerst erledigen.",
        },
        no_inventory_capacity: {
            title: "Keine freie VPN-Zuordnung verfuegbar",
            action: "Im Inventar eine freie VPN-IP bereitstellen oder alte Eintraege bereinigen.",
        },
        gateway_identity_missing: {
            title: "Gateway-ID fehlt",
            action: "Gateway-Verbindung pruefen und sicherstellen, dass die EUI im Gateway sichtbar ist.",
        },
        vpn_key_not_found: {
            title: "VPN-Key nicht gefunden",
            action: "Zuerst Zielwerte reservieren oder den bestehenden DB-Eintrag pruefen.",
        },
        run_not_found: {
            title: "Lauf nicht gefunden",
            action: "Seite neu laden und den Schritt erneut starten.",
        },
        discovery_failed: {
            title: "Gateway konnte nicht automatisch gelesen werden",
            action: "Erreichbarkeit von `192.168.1.1` und den Node-RED-Endpunkten pruefen.",
        },
        missing_env: {
            title: "Pflichtkonfiguration der Umgebung fehlt",
            action: "Fehlende ENV-Werte im Deploy hinterlegen, dann den Schritt erneut ausfuehren.",
        },
        request_failed: {
            title: "Externer Dienst nicht erreichbar",
            action: "Verbindung, URL und Login pruefen. Danach erneut versuchen.",
        },
        http_error: {
            title: "Externer Dienst hat einen Fehler geliefert",
            action: "Statuscode und Antwort unten pruefen. Meist ist es ein Login-, URL- oder Payload-Problem.",
        },
        invalid_json: {
            title: "Externer Dienst liefert ungueltige Antwort",
            action: "Response-Body im Debug-Teil pruefen. Das ist meist ein Service- oder Reverse-Proxy-Problem.",
        },
    };
    return messages[code] || {
        title: "Schritt fehlgeschlagen",
        action: error?.message || "Details im Debug-Teil pruefen.",
    };
}

function renderDebugError() {
    const box = document.getElementById("debugErrorBox");
    if (!box) return;
    if (!state.lastError) {
        box.className = "debug-box debug-empty";
        box.textContent = "Keine aktuellen API-Fehler.";
        return;
    }
    const explained = explainError(state.lastError);
    box.className = "debug-box debug-error";
    box.innerHTML = `
        <div class="debug-title">${escapeHtml(explained.title)}</div>
        <div class="debug-action">${escapeHtml(explained.action)}</div>
        <div class="debug-meta">Code: ${escapeHtml(state.lastError.code || "-")} / Stage: ${escapeHtml(state.lastError.stage || "-")} / HTTP: ${escapeHtml(state.lastError.httpStatus || "-")}</div>
        <pre>${escapeHtml(JSON.stringify(state.lastError, null, 2))}</pre>
    `;
}

function formData() {
    return Object.fromEntries(new FormData(document.getElementById("runForm")).entries());
}

function setField(name, value, force = false) {
    const field = document.querySelector(`[name="${name}"]`);
    if (!field) return;
    if (!force && field.value && name !== "client_name") return;
    field.value = value || "";
    if (name === "client_name") {
        const display = document.getElementById("clientNameDisplay");
        if (display) {
            display.value = value || "";
        }
    }
    if (name === "client_id") {
        const display = document.getElementById("clientIdDisplay");
        if (display) {
            display.textContent = `Interne Kunden-ID: ${value || "-"}`;
        }
    }
}

function deriveVpnSuffix(ip) {
    const value = String(ip || "").trim();
    if (!value) return "";
    const parts = value.split(".");
    if (parts.length < 2) return "";
    return parts.slice(-2).join(".");
}

function buildSuggestedGatewayName() {
    const suggested = state.discovery?.suggested_form || {};
    const db = state.discovery?.db_record || {};
    const vpnIp =
        state.run?.context?.vpn_ip ||
        suggested.current_vpn_ip ||
        db.vpn_ip ||
        suggested.next_free_vpn_ip ||
        "";
    const vpnSuffix = deriveVpnSuffix(vpnIp);
    const clientId = (formData().client_id || suggested.client_id || "").trim();
    const clientName = (formData().client_name || suggested.client_name || "").trim();
    const parts = [];
    if (vpnSuffix) parts.push(vpnSuffix);
    if (clientId && clientName) {
        parts.push(`${clientId} - ${clientName}`);
    } else {
        if (clientId) parts.push(clientId);
        if (clientName) parts.push(clientName);
    }
    return parts.join(" ").trim();
}

function renderSuggestedGatewayName() {
    const hint = document.getElementById("suggestedGatewayName");
    const applyBtn = document.getElementById("applySuggestedNameBtn");
    const gatewayNameField = document.querySelector('[name="gateway_name"]');
    if (!hint || !applyBtn || !gatewayNameField) return;
    const suggestion = buildSuggestedGatewayName();
    hint.textContent = `Vorschlag: ${suggestion || "-"}`;
    applyBtn.style.display = suggestion ? "" : "none";
    if (!gatewayNameField.value || gatewayNameField.value === state.lastSuggestedGatewayName) {
        gatewayNameField.value = suggestion;
    }
    state.lastSuggestedGatewayName = suggestion;
}

function renderClientSearchResults(items) {
    const container = document.getElementById("clientSearchResults");
    const status = document.getElementById("clientSearchStatus");
    if (!container || !status) return;
    container.innerHTML = "";
    if (!items.length) {
        status.textContent = "Keine Treffer.";
        return;
    }
    status.textContent = "Treffer auswaehlen.";
    items.forEach((item) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "search-result-btn";
        button.textContent = `${item.client_name} (${item.client_id})`;
        button.addEventListener("click", async () => {
            setField("client_id", item.client_id, true);
            setField("client_name", item.client_name, true);
            state.discovery = {
                ...(state.discovery || {}),
                suggested_form: {
                    ...((state.discovery || {}).suggested_form || {}),
                    client_id: item.client_id,
                    client_name: item.client_name,
                },
            };
            const queryField = document.getElementById("clientSearchQuery");
            if (queryField) {
                queryField.value = item.client_name || item.client_id;
            }
            container.innerHTML = "";
            status.textContent = "Kunde ausgewaehlt.";
            renderDiscovery();
            renderSuggestedGatewayName();
            await refreshConnections();
        });
        container.appendChild(button);
    });
}

async function searchClients(query) {
    const status = document.getElementById("clientSearchStatus");
    const container = document.getElementById("clientSearchResults");
    if (!status || !container) return;
    const term = String(query || "").trim();
    if (term.length < 3) {
        container.innerHTML = "";
        status.textContent = "Mindestens 3 Zeichen eingeben.";
        return;
    }
    try {
        status.textContent = "Suche...";
        const form = formData();
        const data = await api("/gatewaychef-v2/api/client-search", {
            method: "POST",
            body: JSON.stringify({
                query: term,
                webservice_username: form.webservice_username,
                webservice_password: form.webservice_password,
            }),
        });
        renderClientSearchResults(data.items || []);
    } catch (error) {
        state.lastError = error.debug || { message: error.message };
        renderDebugError();
        status.textContent = error.message;
    }
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

function setClientIdAttention(active) {
    const field = document.querySelector('[name="client_id"]');
    if (!field) return;
    const label = field.closest("label");
    field.classList.toggle("field-attention", Boolean(active));
    if (label) {
        label.classList.toggle("field-attention-wrap", Boolean(active));
    }
    if (active) {
        field.focus();
        field.select?.();
    }
}

function gatewayRelevantDiscrepancies(discrepancies) {
    const gatewayLabels = new Set([
        "Gateway ist Golden",
        "SSID wirkt unklar",
        "VPN stimmt mit DB ueberein",
        "SSID stimmt mit DB ueberein",
        "EUI stimmt mit DB ueberein",
        "VPN Health Check",
        "LoRa-Verbindung gesund",
        "DB-Zuordnung vorhanden",
    ]);
    return (discrepancies || []).filter((entry) => !entry.ok && gatewayLabels.has(entry.label));
}

function isWebserviceAuthFailure(message) {
    const text = String(message || "").toLowerCase();
    return text.includes("401") || text.includes("authentication failed") || text.includes("bad credentials");
}

function hasOpenItem(discrepancies, label) {
    return (discrepancies || []).some((entry) => entry.label === label && !entry.ok);
}

function buildGatewayViewModel() {
    const classification = state.discovery?.classification || {};
    const suggested = state.discovery?.suggested_form || {};
    const db = state.discovery?.db_record || {};
    const webserviceLookup = state.discovery?.webservice_lookup || {};
    const webserviceMatch = webserviceLookup.match || {};
    const runtimeConnections = state.runtime?.connections || [];
    const webserviceConnection = runtimeConnections.find((entry) => entry.service === "webservice");
    const webserviceOk = webserviceConnection?.ok === true;
    const webserviceAuthFailed = !webserviceOk && isWebserviceAuthFailure(webserviceConnection?.message);
    const discrepancies = effectiveDiscrepancies();
    const gatewayDiscrepancies = gatewayRelevantDiscrepancies(discrepancies);
    const hasGatewayDiscrepancies = gatewayDiscrepancies.length > 0;
    const isGolden = Boolean(classification.is_golden);
    const isConfigured = Boolean(classification.is_configured);
    const hasClientId = Boolean(formData().client_id || suggested.client_id);
    const dbConfirmed = !hasOpenItem(discrepancies, "DB Freigabe erfolgt");
    const missingWebserviceEntry = hasOpenItem(discrepancies, "Webservice-Eintrag vorhanden");
    const missingCustomerAssignment = hasOpenItem(discrepancies, "Kunde zugeordnet");
    const canCreateWebserviceEntry = vmCanCreateWebserviceEntry({
        isConfigured,
        webserviceOk,
        missingWebserviceEntry,
        hasClientId,
    });
    const canSaveDraft = vmCanSaveDraft({
        isConfigured,
        webserviceOk,
        missingWebserviceEntry,
        missingCustomerAssignment,
    });

    return {
        classification,
        suggested,
        db,
        webserviceLookup,
        webserviceMatch,
        webserviceOk,
        webserviceAuthFailed,
        discrepancies,
        hasDiscrepancies: discrepancies.some((entry) => !entry.ok),
        gatewayDiscrepancies,
        hasGatewayDiscrepancies,
        isGolden,
        isConfigured,
        hasClientId,
        dbConfirmed,
        missingWebserviceEntry,
        missingCustomerAssignment,
        canCreateWebserviceEntry,
        canSaveDraft,
    };
}

function vmCanCreateWebserviceEntry({ isConfigured, webserviceOk, missingWebserviceEntry, hasClientId }) {
    return Boolean(isConfigured && webserviceOk && missingWebserviceEntry && hasClientId);
}

function vmCanSaveDraft({ isConfigured, webserviceOk, missingWebserviceEntry, missingCustomerAssignment }) {
    return Boolean(isConfigured && webserviceOk && (missingCustomerAssignment || missingWebserviceEntry));
}

function configuredBadge(vm) {
    if (vm.isGolden) return { text: "Neu konfigurieren", className: "state state-warn" };
    if (vm.isConfigured && vm.hasGatewayDiscrepancies) return { text: "Technisch unvollstaendig", className: "state state-fail" };
    if (vm.isConfigured && vm.missingCustomerAssignment) return { text: "Technisch ok, Draft", className: "state state-warn" };
    if (vm.isConfigured && vm.missingWebserviceEntry) return { text: "Technisch ok, Webservice offen", className: "state state-warn" };
    if (vm.isConfigured && vm.dbConfirmed) return { text: "Technisch ok + freigegeben", className: "state state-ok" };
    if (vm.isConfigured) return { text: "Technisch ok, Freigabe offen", className: "state state-warn" };
    return { text: "Gateway erkannt", className: "state state-neutral" };
}

function actionSectionCopy(vm) {
    if (vm.isConfigured && vm.hasGatewayDiscrepancies) {
        return {
            title: "2. Abweichungen korrigieren",
            note: "Dieser Gateway ist bereits konfiguriert. Nutze die Schritte nur fuer die noch offenen Abweichungen.",
        };
    }
    if (vm.isConfigured && vm.missingCustomerAssignment) {
        return {
            title: "2. Kunde zuordnen oder Draft speichern",
            note: vm.webserviceOk
                ? "Technisch passt das Gateway bereits. Jetzt die Interne Kunden-ID eintragen, damit der Gateway dem Kunden zugeordnet und danach im Webservice angelegt werden kann. Alternativ bewusst als Draft speichern."
                : "Technisch passt das Gateway bereits. Ohne Interne Kunden-ID wird es nur als Draft in der Cloud DB gespeichert.",
        };
    }
    if (vm.isConfigured && (!vm.dbConfirmed || !vm.webserviceOk || vm.missingWebserviceEntry)) {
        return {
            title: "2. Noch offen",
            note: vm.webserviceAuthFailed
                ? "Technisch passt das Gateway bereits. Zuerst den Webservice Login korrigieren. Erst danach kann der Webservice-Eintrag geprueft oder angelegt werden."
                : "Technisch passt das Gateway bereits. Jetzt nur noch Webservice pruefen/anlegen und danach final freigeben.",
        };
    }
    if (vm.isConfigured) {
        return {
            title: "2. Keine Aktion noetig",
            note: "Dieser Gateway ist bereits sauber konfiguriert und freigegeben.",
        };
    }
    if (vm.isGolden) {
        return {
            title: "2. Neu konfigurieren",
            note: "Dieser Gateway ist noch nicht fertig. Reserviere neue Zielwerte und setze die finale SSID ganz am Ende.",
        };
    }
    return {
        title: "2. Pruefen und korrigieren",
        note: "Pruefe zuerst den Ist-Zustand. Nur Abweichungen muessen korrigiert werden.",
    };
}

function sortWorkItems(items) {
    const rank = {
        "Gateway neu konfigurieren": 10,
        "SSID im Gateway pruefen": 20,
        "VPN-IP im Gateway korrigieren": 30,
        "SSID an Zielwert anpassen": 40,
        "Gateway ID / EUI korrigieren": 50,
        "VPN-Verbindung ueber Cloud pruefen": 60,
        "LoRa / LNS Verbindung reparieren": 70,
        "DB-Eintrag zuordnen": 80,
        "Kunde zuordnen oder Draft speichern": 90,
        "Webservice pruefen": 100,
        "Webservice-Eintrag anlegen": 110,
        "Gateway final freigeben": 900,
        "Keine Korrekturen noetig": 1000,
    };
    return [...items].sort((a, b) => (rank[a.title] || 500) - (rank[b.title] || 500));
}

function effectiveDiscrepancies() {
    if (!state.discovery) return [];
    const runtimeConnections = state.runtime?.connections || [];
    const webserviceConnection = runtimeConnections.find((entry) => entry.service === "webservice");
    const webserviceLookup = state.discovery.webservice_lookup || {};
    const discrepancies = [...(state.discovery.discrepancies || [])];
    const currentClientId = formData().client_id || state.discovery?.suggested_form?.client_id || "";

    if (webserviceConnection?.ok !== true) {
        discrepancies.push({
            label: "Webservice geprueft",
            ok: false,
            detail: isWebserviceAuthFailure(webserviceConnection?.message)
                ? "Webservice Login fehlgeschlagen. User oder Passwort pruefen."
                : (webserviceConnection?.message || "Webservice Login fehlt oder Webservice ist nicht erreichbar."),
        });
    } else if (webserviceLookup && webserviceLookup.exists === false) {
        discrepancies.push({
            label: "Webservice-Eintrag vorhanden",
            ok: false,
            detail: "Noch nicht im Webservice beim Kunden angelegt.",
        });
    }
    if (!currentClientId) {
        discrepancies.push({
            label: "Kunde zugeordnet",
            ok: false,
            detail: "Noch keinem Kunden zugeordnet. Gateway kann nur als Draft gespeichert werden.",
        });
    }

    return discrepancies;
}

function buildWifiQrValue(ssid) {
    if (!ssid) return "";
    return `WIFI:T:WPA;S:${ssid};P:rat4all!;;`;
}

async function copyImageToClipboard(url) {
    if (!navigator.clipboard || !window.ClipboardItem || !url) return false;
    try {
        const response = await fetch(url);
        const blob = await response.blob();
        await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
        return true;
    } catch (_) {
        return false;
    }
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
        ? "Runtime unvollstaendig"
        : "v2 Runtime bereit";
    issues.innerHTML = "";
    [...missingCloud, ...missingInventory].forEach((entry) => {
        const div = document.createElement("div");
        div.textContent = `${entry.group}: ${entry.missing.join(", ")}`;
        issues.appendChild(div);
    });

    const select = document.getElementById("simVendor");
    const currentSimVendor = document.querySelector('[name="sim_vendor_id"]')?.value || "";
    select.innerHTML = '<option value="">Bitte waehlen</option>';
    (state.runtime.sim_vendors || []).forEach((vendor) => {
        const option = document.createElement("option");
        option.value = vendor.id;
        option.textContent = `${vendor.name}${vendor.apn ? ` (${vendor.apn})` : ""}`;
        select.appendChild(option);
    });
    if (currentSimVendor) {
        select.value = String(currentSimVendor);
    }

    connectionGrid.innerHTML = "";
    (state.runtime.connections || []).forEach((connection) => {
        const item = document.createElement("div");
        item.className = "connection-item";
        const stateClass = connection.ok === true ? "state-ok" : connection.ok === false ? "state-fail" : "state-neutral";
        const label = connection.service || "service";
        const shortMessage = String(connection.message || "-")
            .replace(/^Gateway erreichbar,\s*/i, "")
            .replace(/^Cloud API erreichbar,\s*/i, "")
            .replace(/^Webservice erreichbar$/i, "erreichbar")
            .replace(/^ChirpStack erreichbar$/i, "erreichbar")
            .replace(/^Milesight erreichbar$/i, "erreichbar");
        item.innerHTML = `<strong>${label}</strong><span class="state ${stateClass}">${connection.ok === true ? "OK" : connection.ok === false ? "Fehler" : "Offen"}</span><small>${shortMessage}</small>`;
        connectionGrid.appendChild(item);
    });
}

function renderDiscovery() {
    const badge = document.getElementById("gatewayClassBadge");
    const summary = document.getElementById("gatewaySummary");
    const warnings = document.getElementById("gatewayWarnings");
    const actionTitle = document.getElementById("actionTitle");
    const actionNote = document.getElementById("actionNote");
    const gate = document.getElementById("discoveryGate");
    const correctionToggleRow = document.getElementById("correctionToggleRow");
    const showCorrections = document.getElementById("showCorrections");
    const actionContent = document.getElementById("actionContent");
    const gatewayConnectSection = document.getElementById("gatewayConnectSection");
    const gatewayHelpSection = document.getElementById("gatewayHelpSection");
    const cloudSyncButton = document.querySelector('[data-action="cloud-sync"]');
    const saveDraftButton = document.querySelector('[data-action="save-draft"]');
    const targetGrid = document.getElementById("targetGrid");
    const targetTitle = document.getElementById("targetTitle");

    if (!state.discovery) {
        badge.textContent = "Discovery fehlt";
        badge.className = "state state-fail";
        summary.textContent = "Gateway konnte nicht gelesen werden.";
        return;
    }

    const loraHealth = state.discovery.lora_health || {};
    const vm = buildGatewayViewModel();
    const disableActions = vm.isConfigured && !vm.hasDiscrepancies;
    const showHelperSections = vm.hasGatewayDiscrepancies || vm.isGolden;
    const webserviceLookupKnown = Object.prototype.hasOwnProperty.call(vm.webserviceLookup || {}, "exists");
    const shouldOfferWebserviceCreate = Boolean(
        vm.isConfigured
        && vm.webserviceOk
        && (vm.missingWebserviceEntry || (!webserviceLookupKnown && !vm.webserviceMatch.client_id))
    );
    const shouldOfferCloudDbUpdate = Boolean(
        vm.isConfigured
        && !vm.dbConfirmed
        && !vm.missingCustomerAssignment
        && !vm.missingWebserviceEntry
    );
    const showTargetValues = vm.isGolden || vm.hasGatewayDiscrepancies || !vm.isConfigured;
    const createRunBtn = document.getElementById("createRunBtn");
    const runState = state.run?.state || "";
    const badgeState = configuredBadge(vm);
    badge.textContent = badgeState.text;
    badge.className = badgeState.className;

    summary.innerHTML = `
        <strong>Aktueller Gateway-Zustand wurde automatisch gelesen.</strong>
        <div class="gateway-facts">
            <div class="fact-item"><span class="fact-label">SSID</span><span class="fact-value">${vm.suggested.current_ssid || "-"}</span></div>
            <div class="fact-item"><span class="fact-label">VPN</span><span class="fact-value">${vm.suggested.current_vpn_ip || "-"}</span></div>
            <div class="fact-item"><span class="fact-label">EUI</span><span class="fact-value">${vm.suggested.current_eui || "-"}</span></div>
            <div class="fact-item"><span class="fact-label">DB Name</span><span class="fact-value">${vm.db.gateway_name || "-"}</span></div>
            <div class="fact-item"><span class="fact-label">Serial</span><span class="fact-value">${vm.db.serial_number || "-"}</span></div>
            <div class="fact-item"><span class="fact-label">SIM ICCID</span><span class="fact-value">${vm.db.sim_iccid || "-"}</span></div>
            <div class="fact-item"><span class="fact-label">Kunde</span><span class="fact-value">${vm.webserviceMatch.client_name || vm.webserviceMatch.client_id || "-"}</span></div>
            <div class="fact-item"><span class="fact-label">LoRa</span><span class="fact-value">${loraHealth.status || "-"} / LNS ${String(!!loraHealth.lns_connected)}</span></div>
        </div>
    `;

    warnings.innerHTML = "";
    const warningTexts = [];
    if (vm.isGolden) {
        warningTexts.push("SSID ist `bbdbmon_golden`: Gateway gilt als noch nicht fertig konfiguriert.");
        warningTexts.push(`Naechste freie VPN-IP laut Inventar: ${vm.suggested.next_free_vpn_ip || "-"}.`);
    }
    if (vm.isGolden && vm.classification.ssid_change_must_be_last) {
        warningTexts.push("SSID-Wechsel ist der letzte Schritt. Erst VPN, LoRa und Cloud-Sync sauber setzen.");
    }
    if (!vm.isConfigured && vm.webserviceLookup.exists) {
        warningTexts.push(
            `Webservice-Zuordnung erkannt: ${vm.webserviceMatch.client_name || vm.webserviceMatch.client_id || "Kunde bekannt"}`
        );
    }
    warnings.style.display = warningTexts.length ? "" : "none";
    warningTexts.forEach((text) => {
        const item = document.createElement("div");
        item.className = "warning-item";
        item.textContent = text;
        warnings.appendChild(item);
    });

    if (!vm.hasDiscrepancies) {
        gate.textContent = vm.dbConfirmed ? "KONFIG OK" : "FREIGABE OFFEN";
        gate.className = "release release-pass";
    } else {
        gate.textContent = "NOCH NICHT FERTIG";
        gate.className = "release release-block";
    }

    correctionToggleRow.style.display = vm.hasGatewayDiscrepancies ? "inline-flex" : "none";
    if (!vm.hasDiscrepancies) {
        showCorrections.checked = false;
    }
    actionContent.style.display = vm.hasGatewayDiscrepancies && !showCorrections.checked ? "none" : "";
    gatewayConnectSection.style.display = vm.suggested.current_ssid ? "" : "none";
    gatewayHelpSection.style.display = showHelperSections ? "" : "none";
    if (targetGrid && targetTitle) {
        targetGrid.style.display = showTargetValues ? "" : "none";
        targetTitle.textContent = showTargetValues ? "3. Erwartete Zielwerte" : "3. Keine neuen Zielwerte noetig";
    }
    const sectionCopy = actionSectionCopy(vm);
    actionTitle.textContent = sectionCopy.title;
    actionNote.textContent = sectionCopy.note;

    document.querySelectorAll("[data-action]").forEach((button) => {
        if (!disableActions) {
            button.disabled = false;
            return;
        }
        button.disabled = true;
    });

    if (createRunBtn) {
        if (vm.isConfigured) {
            createRunBtn.style.display = "none";
        } else if (vm.isGolden) {
            createRunBtn.style.display = "";
            createRunBtn.textContent = "Provisionierung starten";
        } else {
            createRunBtn.style.display = "";
            createRunBtn.textContent = "Pruefung starten";
        }
    }

    if (cloudSyncButton) {
        if (!vm.webserviceOk) {
            cloudSyncButton.textContent = "Webservice Login pruefen";
        } else if (shouldOfferWebserviceCreate) {
            cloudSyncButton.textContent = "Gateway im Webservice beim Kunden anlegen";
        } else if (shouldOfferCloudDbUpdate) {
            cloudSyncButton.textContent = "Cloud DB aktualisieren";
        } else {
            cloudSyncButton.textContent = "Cloud Sync";
        }
    }
    if (saveDraftButton) {
        saveDraftButton.textContent = "Als Draft in Cloud DB speichern";
    }

    const actionVisibility = {
        precheck: !vm.isConfigured || vm.hasGatewayDiscrepancies,
        reserve: !vm.isConfigured || vm.hasGatewayDiscrepancies,
        "confirm-config": !vm.isConfigured || vm.hasGatewayDiscrepancies,
        "save-draft": vm.canSaveDraft,
        "cloud-sync": shouldOfferWebserviceCreate || shouldOfferCloudDbUpdate || !vm.webserviceOk || !vm.isConfigured || vm.hasGatewayDiscrepancies,
        verify: ["CLOUD_SYNCED", "FAILED", "VERIFIED"].includes(runState),
        finalize: runState === "VERIFIED",
    };
    document.querySelectorAll("[data-action]").forEach((button) => {
        button.style.display = actionVisibility[button.dataset.action] ? "" : "none";
    });

    renderStatusWork(vm.discrepancies);
    renderQuickActions();
    renderGatewayQr();
    renderSuggestedGatewayName();
}

function prefillFormFromDiscovery() {
    if (!state.discovery) return;
    const suggested = state.discovery.suggested_form || {};
    setField("serial_number", suggested.serial_number);
    setField("gateway_name", suggested.gateway_name);
    setField("sim_vendor_id", suggested.sim_vendor_id);
    setField("sim_iccid", suggested.sim_iccid);
    setField("client_id", suggested.client_id, true);
    setField("client_name", suggested.client_name);
    setField("lns", suggested.lns);
    setField("operation_mode", suggested.operation_mode, true);
    document.getElementById("modeSummary").textContent = suggested.operation_mode === "new_config"
        ? "Neu konfigurieren aktiv. Bestehende Zuordnungen muessen bewusst ersetzt werden."
        : "Standard: Bestehenden Gateway pruefen und nur Abweichungen korrigieren.";
    document.getElementById("cleanupConfirmed").value = "";
    renderSuggestedGatewayName();
}

function renderQuickActions() {
    const box = document.getElementById("gatewayQuickActions");
    box.innerHTML = "";
    const targetVpn = state.run?.context?.vpn_ip || state.discovery?.suggested_form?.next_free_vpn_ip || "";
    const targetSsid = state.run?.context?.wifi_ssid || state.discovery?.db_record?.wifi_ssid || "";
    const targetEui = state.run?.context?.discovered_eui || state.discovery?.suggested_form?.current_eui || "";
    const targetApn = state.run?.context?.apn || state.discovery?.db_record?.apn || "";
    const canRevealKey = Boolean(currentRunId());
    const failedLabels = new Set(gatewayRelevantDiscrepancies(state.discovery?.discrepancies || []).map((entry) => entry.label));
    const showHelpers = state.discovery?.classification?.is_golden || failedLabels.size > 0;
    if (!showHelpers) {
        return;
    }
    const actions = [
        { label: "Gateway ID / EUI", value: targetEui, path: "/#packetforward/general", match: ["EUI stimmt mit DB ueberein", "Gateway ist Golden"] },
        { label: "VPN IP", value: targetVpn ? `${targetVpn}/32` : "", path: "/#network/vpn/wireguard", match: ["VPN stimmt mit DB ueberein", "Gateway ist Golden", "VPN Health Check"] },
        { label: "WiFi SSID", value: targetSsid, path: "/#network/interfaces/wlan", match: ["SSID stimmt mit DB ueberein", "SSID zeigt konfigurierten Zustand", "SSID wirkt unklar", "Gateway ist Golden"] },
        { label: "APN", value: targetApn, path: "/#network/interfaces/cellular", match: ["Gateway ist Golden"] },
        { label: "VPN Key", value: "Einmalig aus Lauf laden", path: "/#network/vpn/wireguard", secret: true, match: ["VPN stimmt mit DB ueberein", "Gateway ist Golden", "VPN Health Check"] },
    ].filter((entry) => failedLabels.size === 0 || entry.match.some((label) => failedLabels.has(label)));
    actions.forEach((entry) => {
        const row = document.createElement("div");
        row.className = "check-item";
        row.innerHTML = `<div class="quick-action-row"><div><strong>${entry.label}</strong><small>${entry.value || "-"}</small></div></div>`;
        const controls = row.querySelector(".quick-action-row");
        const copyBtn = document.createElement("button");
        copyBtn.type = "button";
        copyBtn.textContent = "Copy";
        if (entry.secret) {
            copyBtn.disabled = !canRevealKey;
            copyBtn.addEventListener("click", async () => {
                if (!currentRunId()) return;
                const result = await api(`/gatewaychef-v2/api/runs/${currentRunId()}/secret-bundle`, {
                    method: "POST",
                    body: JSON.stringify({ confirm_secret_access: true }),
                });
                await copyText(result.private_key || "");
            });
        } else {
            copyBtn.disabled = !entry.value;
            copyBtn.addEventListener("click", () => copyText(entry.value));
        }
        const openBtn = document.createElement("button");
        openBtn.type = "button";
        openBtn.textContent = "Open";
        openBtn.addEventListener("click", () => openGatewayUrl(entry.path));
        const showBtn = document.createElement("button");
        showBtn.type = "button";
        showBtn.textContent = entry.secret ? "Anzeigen" : "Info";
        if (entry.secret) {
            showBtn.disabled = !canRevealKey;
            showBtn.addEventListener("click", async () => {
                if (!currentRunId()) return;
                const result = await api(`/gatewaychef-v2/api/runs/${currentRunId()}/secret-bundle`, {
                    method: "POST",
                    body: JSON.stringify({ confirm_secret_access: true }),
                });
                window.alert(`VPN Key:\n${result.private_key}`);
            });
        } else {
            showBtn.disabled = true;
        }
        controls.appendChild(copyBtn);
        controls.appendChild(openBtn);
        controls.appendChild(showBtn);
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
    if (!qrValue) {
        card.className = "summary-card";
        card.innerHTML = "<strong>Gateway verbinden</strong><small>SSID noch nicht bekannt.</small>";
        return;
    }
    card.className = "summary-card qr-card";
    card.innerHTML = `
        <div class="qr-sticker">
            <div class="qr-sticker-head">Gateway verbinden</div>
            <div class="qr-sticker-body">
                ${qrUrl ? `<img src="${qrUrl}" alt="Gateway QR">` : ""}
                <div class="qr-copy">
                    <div><strong>SSID</strong><span>${ssid || "-"}</span></div>
                    <div><strong>PW</strong><span>rat4all!</span></div>
                    <div><strong>VPN</strong><span>${suffix || (vpnIp ? vpnIp.split(".").slice(-2).join(".") : "-")}</span></div>
                    <div class="qr-warning">
                        <span>NICHT fuer private</span>
                        <span>oder datenhungrige Anwendungen</span>
                        <span>(Musik, Video)!</span>
                    </div>
                </div>
            </div>
        </div>
    `;
    const actions = document.createElement("div");
    actions.className = "qr-actions";
    const imageBtn = document.createElement("button");
    imageBtn.type = "button";
    imageBtn.textContent = "QR kopieren";
    imageBtn.addEventListener("click", async () => {
        const copied = await copyImageToClipboard(qrUrl);
        if (!copied) {
            await copyText(qrValue);
            window.alert("Bild konnte nicht direkt kopiert werden. QR-Inhalt wurde in die Zwischenablage gelegt.");
        }
    });
    const infoBtn = document.createElement("button");
    infoBtn.type = "button";
    infoBtn.textContent = "Sticker-Text kopieren";
    infoBtn.addEventListener("click", async () => {
        await copyText(
            `Gateway verbinden\nSSID ${ssid}\nPW rat4all!\nVPN ${suffix || (vpnIp ? vpnIp.split(".").slice(-2).join(".") : "-")}\nNICHT fuer private\noder datenhungrige Anwendungen\n(Musik, Video)!`
        );
    });
    actions.appendChild(imageBtn);
    actions.appendChild(infoBtn);
    card.appendChild(actions);
}

function buildWorkItems(discrepancies) {
    const suggested = state.discovery?.suggested_form || {};
    const db = state.discovery?.db_record || {};
    const targetVpn = state.run?.context?.vpn_ip || suggested.next_free_vpn_ip || db.vpn_ip || "";
    const targetSsid = state.run?.context?.wifi_ssid || db.wifi_ssid || (targetVpn ? `bbdbmon_${targetVpn.split(".").slice(-2).join(".")}` : "");
    const targetEui = state.run?.context?.discovered_eui || suggested.current_eui || db.eui || "";

    const map = {
        "Gateway ist Golden": {
            title: "Gateway neu konfigurieren",
            detail: `1. Neue VPN-IP reservieren. 2. Zielwerte im Gateway setzen. 3. Finale SSID ${targetSsid || "bbdbmon_x.xxx"} erst ganz am Ende setzen.`,
        },
        "SSID wirkt unklar": {
            title: "SSID im Gateway pruefen",
            detail: `Im Gateway-Menue WLAN die SSID auf ${targetSsid || "bbdbmon_x.xxx"} setzen.`,
        },
        "VPN stimmt mit DB ueberein": {
            title: "VPN-IP im Gateway korrigieren",
            detail: `Im Gateway WireGuard auf ${targetVpn || "-"} setzen und danach den VPN Health Check erneut pruefen.`,
        },
        "SSID stimmt mit DB ueberein": {
            title: "SSID an Zielwert anpassen",
            detail: `SSID auf ${targetSsid || "-"} setzen. Diesen Schritt wirklich zuletzt ausfuehren.`,
        },
        "EUI stimmt mit DB ueberein": {
            title: "Gateway ID / EUI korrigieren",
            detail: `Gateway ID / EUI im Gateway auf ${targetEui || "-"} setzen und speichern.`,
        },
        "VPN Health Check": {
            title: "VPN-Verbindung ueber Cloud pruefen",
            detail: "WireGuard und Routing pruefen, bis der Health Check ueber VPN erfolgreich ist.",
        },
        "LoRa-Verbindung gesund": {
            title: "LoRa / LNS Verbindung reparieren",
            detail: "Packet Forwarder, Server und LNS-Anbindung im Gateway pruefen, bis der Status wieder ONLINE ist.",
        },
        "DB-Zuordnung vorhanden": {
            title: "DB-Eintrag zuordnen",
            detail: "Bestehenden DB-Eintrag fortfuehren. Nur wenn wirklich noetig bewusst neu konfigurieren.",
        },
        "Webservice geprueft": {
            title: "Webservice Login pruefen",
            detail: isWebserviceAuthFailure((state.runtime?.connections || []).find((entry) => entry.service === "webservice")?.message)
                ? "Webservice Login fehlgeschlagen. User oder Passwort korrigieren und erneut pruefen."
                : "Webservice User und Passwort oben eintragen. Danach wird die Zuordnung automatisch erneut geprueft.",
        },
        "Webservice-Eintrag vorhanden": {
            title: "Webservice-Eintrag anlegen",
            detail: (formData().client_id || state.discovery?.suggested_form?.client_id)
                ? "Noch nicht im Webservice beim Kunden angelegt. Mit dem naechsten Schritt jetzt beim Kunden anlegen."
                : "Interne Kunden-ID fehlt. Ohne Zuordnung wird nur ein Draft in der Cloud DB gespeichert.",
        },
        "Kunde zugeordnet": {
            title: "Kunde zuordnen oder Draft speichern",
            detail: ((state.runtime?.connections || []).find((entry) => entry.service === "webservice")?.ok === true)
                ? "Interne Kunden-ID jetzt eintragen, damit der Gateway dem Kunden zugeordnet und im naechsten Schritt im Webservice angelegt werden kann. Sonst bewusst als Draft speichern."
                : "Interne Kunden-ID eintragen, wenn der Gateway sofort einem Kunden zugeordnet werden soll. Sonst bewusst als Draft speichern.",
        },
        "DB Freigabe erfolgt": {
            title: "Gateway final freigeben",
            detail: "Gateway ist technisch fertig, aber noch nicht final bestaetigt. Erst nach gruener Verifikation freigeben.",
        },
    };

    const todos = discrepancies
        .filter((entry) => !entry.ok)
        .map((entry) => ({
            title: map[entry.label]?.title || entry.label,
            detail: map[entry.label]?.detail || entry.detail || "",
            source: entry.label,
        }));

    if (todos.length) {
        return sortWorkItems(todos);
    }

    return [
        {
            title: "Keine Korrekturen noetig",
            detail: "Alle aktuell geprueften Punkte passen. Falls die DB-Freigabe noch offen ist, jetzt nur noch final bestaetigen.",
            source: "clean",
            ok: true,
        },
    ];
}

function renderStatusWork(discrepancies) {
    const box = document.getElementById("statusWorkGrid");
    if (!box) return;
    box.innerHTML = "";
    const items = buildWorkItems(discrepancies);
    items.forEach((entry) => {
        const item = document.createElement("div");
        item.className = `work-item ${entry.ok ? "done" : "todo"}`;
        item.innerHTML = `<strong>${entry.title}</strong><small>${entry.detail || ""}</small>`;
        box.appendChild(item);
    });
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
    release.textContent = report.release_gate || "OFFEN";
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
}

async function reloadRun() {
    if (!currentRunId()) return;
    state.run = await api(`/gatewaychef-v2/api/runs/${currentRunId()}`);
    renderRun();
}

async function syncRunWithForm() {
    if (!currentRunId()) return;
    const payload = formData();
    const db = state.discovery?.db_record || {};
    const suggested = state.discovery?.suggested_form || {};
    payload.gateway_name = payload.gateway_name || db.gateway_name || suggested.gateway_name || "";
    payload.serial_number = payload.serial_number || db.serial_number || suggested.serial_number || "";
    payload.sim_vendor_id = payload.sim_vendor_id || db.sim_vendor_id || suggested.sim_vendor_id || "";
    payload.sim_iccid = payload.sim_iccid || db.sim_iccid || suggested.sim_iccid || "";
    payload.client_id = payload.client_id || suggested.client_id || "";
    payload.client_name = payload.client_name || suggested.client_name || "";
    payload.lns = payload.lns || suggested.lns || "chirpstack";
    state.run = await api(`/gatewaychef-v2/api/runs/${currentRunId()}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
    });
}

async function createRun(options = {}) {
    const { render = true } = options;
    const payload = formData();
    const db = state.discovery?.db_record || {};
    const suggested = state.discovery?.suggested_form || {};
    payload.gateway_name = payload.gateway_name || db.gateway_name || suggested.gateway_name || "";
    payload.serial_number = payload.serial_number || db.serial_number || suggested.serial_number || "";
    payload.sim_vendor_id = payload.sim_vendor_id || db.sim_vendor_id || suggested.sim_vendor_id || "";
    payload.sim_iccid = payload.sim_iccid || db.sim_iccid || suggested.sim_iccid || "";
    payload.client_id = payload.client_id || suggested.client_id || "";
    payload.client_name = payload.client_name || suggested.client_name || "";
    payload.lns = payload.lns || suggested.lns || "chirpstack";
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
    if (render) {
        renderRun();
    }
}

async function ensureRunForAction(action) {
    if (currentRunId()) return;
    await createRun({ render: false });
    const isConfigured = Boolean(state.discovery?.classification?.is_configured);
    const hasGatewayDiscrepancies = gatewayRelevantDiscrepancies(effectiveDiscrepancies()).length > 0;
    const autoPrepare = isConfigured && !hasGatewayDiscrepancies;
    if (autoPrepare) {
        state.run = await api(`/gatewaychef-v2/api/runs/${currentRunId()}/precheck`, {
            method: "POST",
            body: JSON.stringify({}),
        });
        state.run = await api(`/gatewaychef-v2/api/runs/${currentRunId()}/reserve`, {
            method: "POST",
            body: JSON.stringify({}),
        });
        state.run = await api(`/gatewaychef-v2/api/runs/${currentRunId()}/confirm-config`, {
            method: "POST",
            body: JSON.stringify({
                confirm_apply: true,
                note: "Bestehender Gateway automatisch als technisch konfiguriert uebernommen.",
            }),
        });
        return;
    }
    if (action !== "precheck") {
        throw new Error("Vor diesem Schritt muessen die offenen Gateway-Abweichungen zuerst bearbeitet werden.");
    }
}

function validateActionBeforeRunCreation(action) {
    if (action !== "cloud-sync") {
        return true;
    }
    const form = formData();
    const missingWebserviceEntry = effectiveDiscrepancies().some((entry) => entry.label === "Webservice-Eintrag vorhanden" && !entry.ok);
    const hasClientId = Boolean(form.client_id || state.discovery?.suggested_form?.client_id);
    if (missingWebserviceEntry && !hasClientId) {
        setClientIdAttention(true);
        alert("Interne Kunden-ID fehlt. Fuer die Kundenanlage im Webservice zuerst die Interne Kunden-ID eintragen oder bewusst den separaten Draft-Button verwenden.");
        return false;
    }
    return true;
}

function shouldSkipRunReloadAfterError(action) {
    if (action !== "cloud-sync") {
        return false;
    }
    const vm = buildGatewayViewModel();
    return Boolean(vm.isConfigured && !vm.hasGatewayDiscrepancies);
}

function shouldSuppressRunPanel(action) {
    if (!["cloud-sync", "save-draft"].includes(action)) {
        return false;
    }
    const vm = buildGatewayViewModel();
    return Boolean(vm.isConfigured && !vm.hasGatewayDiscrepancies);
}

async function executeAction(action) {
    if (!validateActionBeforeRunCreation(action)) {
        return;
    }
    if (!currentRunId()) {
        await ensureRunForAction(action);
    }
    if (["cloud-sync", "save-draft", "verify", "finalize"].includes(action)) {
        await syncRunWithForm();
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
    if (action === "save-draft") {
        const confirmed = window.confirm(
            "Gateway nur als Draft in der Cloud DB speichern?\n\nDer Gateway wird dabei nicht im Webservice beim Kunden angelegt und bleibt spaeter zuzuordnen."
        );
        if (!confirmed) return;
        payload.force_draft = true;
    }
    if (action === "secret-bundle") {
        const confirmed = window.confirm("VPN-Key nur lokal und nur einmalig anzeigen?");
        if (!confirmed) return;
        payload.confirm_secret_access = true;
    }
    if (action === "cloud-sync" || action === "save-draft" || action === "verify") {
        const form = formData();
        payload.webservice_username = form.webservice_username;
        payload.webservice_password = form.webservice_password;
    }
    const endpoint = {
        precheck: "precheck",
        reserve: "reserve",
        "confirm-config": "confirm-config",
        "secret-bundle": "secret-bundle",
        "save-draft": "cloud-sync",
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
    if (action === "cloud-sync") {
        const syncStatus = result?.status || {};
        await refreshConnections();
        await loadDiscovery();
        if (syncStatus.webservice_created) {
            window.alert("Gateway wurde erfolgreich im Webservice angelegt.");
        } else if (syncStatus.webservice_exists) {
            window.alert("Gateway ist bereits im Webservice vorhanden.");
        }
    }
    if (!shouldSuppressRunPanel(action)) {
        renderRun();
    }
    renderDiscovery();
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
                discovered_eui: state.discovery?.suggested_form?.current_eui || "",
                client_id: form.client_id || state.discovery?.suggested_form?.client_id || "",
            }),
        });
        state.runtime = { ...(state.runtime || {}), connections: data.connections || [] };
        if (Object.prototype.hasOwnProperty.call(data, "webservice_lookup")) {
            const match = data.webservice_lookup?.match || {};
            state.discovery = {
                ...(state.discovery || {}),
                webservice_lookup: data.webservice_lookup,
                suggested_form: {
                    ...((state.discovery || {}).suggested_form || {}),
                    client_id: match.client_id || ((state.discovery || {}).suggested_form || {}).client_id || "",
                    client_name: match.client_name || ((state.discovery || {}).suggested_form || {}).client_name || "",
                    gateway_name: match.gateway_name || ((state.discovery || {}).suggested_form || {}).gateway_name || "",
                    serial_number: match.serial_number || ((state.discovery || {}).suggested_form || {}).serial_number || "",
                    lns: match.lns || ((state.discovery || {}).suggested_form || {}).lns || "chirpstack",
                },
            };
        }
        if (Object.prototype.hasOwnProperty.call(data, "client_lookup")) {
            const match = data.client_lookup?.match || {};
            state.discovery = {
                ...(state.discovery || {}),
                client_lookup: data.client_lookup,
                suggested_form: {
                    ...((state.discovery || {}).suggested_form || {}),
                    client_id: match.client_id || ((state.discovery || {}).suggested_form || {}).client_id || "",
                    client_name: match.client_name || "",
                },
            };
        }
        renderRuntime();
        prefillFormFromDiscovery();
        renderDiscovery();
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
                if (!shouldSkipRunReloadAfterError(button.dataset.action)) {
                    await reloadRun();
                }
                renderDebugError();
                alert(error.message);
            }
        });
    });

    const applySuggestedNameBtn = document.getElementById("applySuggestedNameBtn");
    if (applySuggestedNameBtn) {
        applySuggestedNameBtn.addEventListener("click", () => {
            const gatewayNameField = document.querySelector('[name="gateway_name"]');
            const suggestion = buildSuggestedGatewayName();
            if (!gatewayNameField || !suggestion) return;
            gatewayNameField.value = suggestion;
            state.lastSuggestedGatewayName = suggestion;
            renderSuggestedGatewayName();
        });
    }

    document.getElementById("newConfigBtn").addEventListener("click", () => {
        const confirmed = window.confirm(
            "Gateway in allen Cloud Services neu konfigurieren?\n\nVorherige Zuordnungen in Milesight, ChirpStack, Webservice und Cloud DB muessen bewusst bereinigt werden. Bestehende Zuordnung wird sonst standardmaessig weiterverwendet."
        );
        if (!confirmed) return;
        document.getElementById("operationMode").value = "new_config";
        document.getElementById("cleanupConfirmed").value = "true";
        document.getElementById("modeSummary").textContent = "Neu konfigurieren aktiv. Bestehende Zuordnungen muessen bewusst bereinigt oder ersetzt werden.";
    });

    ["webservice_username", "webservice_password"].forEach((name) => {
        const field = document.querySelector(`[name="${name}"]`);
        if (!field) return;
        field.addEventListener("input", refreshConnections);
        field.addEventListener("change", refreshConnections);
        field.addEventListener("blur", refreshConnections);
    });

    ["lns"].forEach((name) => {
        const field = document.querySelector(`[name="${name}"]`);
        if (!field) return;
        const rerender = () => {
            renderDiscovery();
            renderSuggestedGatewayName();
        };
        field.addEventListener("input", rerender);
        field.addEventListener("change", rerender);
        field.addEventListener("blur", rerender);
    });

    const gatewayNameField = document.querySelector('[name="gateway_name"]');
    if (gatewayNameField) {
        gatewayNameField.addEventListener("input", () => {
            if (gatewayNameField.value !== state.lastSuggestedGatewayName) {
                state.lastSuggestedGatewayName = buildSuggestedGatewayName();
            }
        });
    }

    const clientSearchField = document.getElementById("clientSearchQuery");
    if (clientSearchField) {
        const clearAttention = () => {
            if (String(formData().client_id || "").trim()) {
                setClientIdAttention(false);
            }
        };
        let timer = null;
        clientSearchField.addEventListener("input", () => {
            setField("client_id", "", true);
            setField("client_name", "", true);
            renderSuggestedGatewayName();
            clearAttention();
            window.clearTimeout(timer);
            timer = window.setTimeout(() => {
                searchClients(clientSearchField.value);
            }, 250);
        });
    }

    const correctionToggle = document.getElementById("showCorrections");
    correctionToggle.addEventListener("change", () => {
        const content = document.getElementById("actionContent");
        const shouldShow = correctionToggle.checked;
        content.style.display = shouldShow || !(state.discovery?.discrepancies || []).some((entry) => !entry.ok) ? "" : "none";
    });

    renderDebugError();
}

window.addEventListener("DOMContentLoaded", init);
