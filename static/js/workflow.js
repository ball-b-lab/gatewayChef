import { state, vars } from './state.js';
import { safeJson, unwrap } from './api.js';
import {
    log,
    setGatewayBlocked,
    setConnectionState,
    setHeadlineConnection,
    setBadge,
    setServiceStatus,
    renderMismatchList,
    setMatchStyle,
    setText,
    getText,
    setValue,
    setStatusIcon,
    setRowState,
    setTooltip,
    refreshTooltips,
    updateTopStatusBanner,
    setStepStatus,
    setRuntimeHint
} from './ui.js';

function getWebserviceCredentials() {
        const user = document.getElementById('wsUser')?.value || '';
        const pass = document.getElementById('wsPass')?.value || '';
        if (!user || !pass) return null;
        return { username: user, password: pass };
    }

async function webserviceRequest(path, payload) {
        const creds = getWebserviceCredentials();
        if (!creds) {
            log('!! Webservice Login fehlt: Benutzer/Passwort nicht gesetzt.', 'error');
            return { ok: false, error: 'Webservice Login fehlt (Benutzer/Passwort).' };
        }
        log(`.. Webservice Request: ${path} (user=${creds.username || '-'})`, 'info');
        try {
            const res = await safeJson(path, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ...(payload || {}), ...creds })
            });
            const status = res.res?.status;
            const unwrapped = unwrap(res.data);
            if (!unwrapped.ok) {
                const hint = describeWebserviceError(status, unwrapped.error);
                const detail = formatDetailedError(unwrapped);
                log(`!! Webservice Error (${path}): HTTP ${status || '?'} - ${hint}`, 'error');
                if (detail && detail !== hint) {
                    log(`!! Webservice Details (${path}): ${detail}`, 'error');
                }
                return { ok: false, error: hint, data: unwrapped.data, status };
            }
            log(`.. Webservice OK (${path}): HTTP ${status || '?'}`, 'success');
            return { ok: true, data: unwrapped.data };
        } catch (e) {
            log(`!! Webservice Exception (${path}): ${e}`, 'error');
            return { ok: false, error: String(e) };
        }
    }

    function normalizeList(payload) {
        if (!payload) return [];
        if (Array.isArray(payload)) return payload;
        if (Array.isArray(payload.data)) return payload.data;
        if (Array.isArray(payload.clients)) return payload.clients;
        if (Array.isArray(payload.gateways)) return payload.gateways;
        if (Array.isArray(payload.items)) return payload.items;
        return [];
    }

function normalizeHexId(value) {
        const clean = String(value || '').replace(/[^a-fA-F0-9]/g, '').toUpperCase();
        return clean || '';
    }

function normalizeIdentity(value) {
        const hex = normalizeHexId(value);
        return hex || String(value || '').trim();
    }

function isMissingValue(value) {
        if (value === null || value === undefined) return true;
        const text = String(value).trim();
        return !text || text === '-';
    }

function compareStatusValue(currentValue, targetValue, options = {}) {
        if (isMissingValue(targetValue) || isMissingValue(currentValue)) {
            return null;
        }
        const current = options.normalize ? options.normalize(currentValue) : String(currentValue).trim();
        const target = options.normalize ? options.normalize(targetValue) : String(targetValue).trim();
        if (!current || !target) return null;
        return current === target;
    }

function describeWebserviceError(status, errorText) {
        const base = (errorText || '').toString().trim() || 'Webservice Fehler';
        if (status === 401 || status === 403) {
            return `${base} (Login/Passwort prüfen)`;
        }
        if (status === 404) {
            return `${base} (Endpoint nicht gefunden)`;
        }
        if (status >= 500) {
            return `${base} (Webservice aktuell nicht verfügbar)`;
        }
        return base;
    }

function setOperatorHintForError(errorText) {
        const msg = (errorText || '').toString();
        if (!msg) return;
        if (msg.includes('DB API Proxy Fehler')) {
            setRuntimeHint('DB-Proxy nicht erreichbar: DB_API_PROVIDER_URL/API_SERVICE_TOKEN in Local-App prüfen.', 'warn');
            return;
        }
        if (msg.includes('VPN Ping Proxy Fehler')) {
            setRuntimeHint('VPN-Ping-Proxy nicht erreichbar: VPN_PING_PROVIDER_URL/VPN_PING_SERVICE_TOKEN prüfen.', 'warn');
            return;
        }
        if (msg.includes('Gateway Health Proxy Fehler') || msg.includes('Gateway Health Fehler')) {
            setRuntimeHint('VPN Health Check fehlgeschlagen: Cloud API, Gateway oder VPN-Tunnel pruefen.', 'warn');
            return;
        }
        if (msg.includes('Gateway nicht erreichbar')) {
            setRuntimeHint('Gateway offline oder WLAN falsch: mit Gateway-SSID verbinden und "Gateway lesen" erneut ausführen.', 'warn');
            return;
        }
    }

function formatDetailedError(result) {
        if (!result || result.ok) return '';
        const parts = [];
        if (result.error) parts.push(result.error);
        const details = result.data || {};
        if (details.service) parts.push(`Service: ${details.service}`);
        if (details.http_status) parts.push(`HTTP ${details.http_status}`);
        if (details.response_body) parts.push(`Body: ${details.response_body}`);
        return parts.filter(Boolean).join(' | ');
    }

function findWebserviceGatewayMatch(list, eui) {
        const normalizedEui = normalizeIdentity(eui);
        return normalizeList(list).find(gateway => {
            const gatewayIdentity = normalizeIdentity(
                gateway.gatewayEui || gateway.gateway_eui || gateway.gatewayId || gateway.gateway_id || ''
            );
            return gatewayIdentity === normalizedEui;
        }) || null;
    }

function applyExternalExistenceStatus(serviceKey, options = {}) {
        const {
            exists = null,
            error = null,
            missing = [],
            tooltip = '',
            observed = null,
            idleText = '-',
            connectedOverride = null
        } = options;
        const now = new Date().toISOString();
        const targetStatusId = {
            chirpstack: 'chirpstackStatus',
            milesight: 'milesightStatus',
            webservice: 'webserviceStatus'
        }[serviceKey];
        const targetRowId = {
            chirpstack: 'rowChirpstackService',
            milesight: 'rowMilesightService',
            webservice: 'rowWebserviceService'
        }[serviceKey];
        const targetButtonId = {
            chirpstack: 'btnChirpstackCreate',
            milesight: 'btnMilesightCreate'
        }[serviceKey];

        let statusText = idleText;
        let connected = connectedOverride;
        let rowState = 'na';
        let detailText = '';

        if (error) {
            statusText = missing.length ? 'Fehlt' : 'Fehler';
            connected = false;
            rowState = 'bad';
            detailText = error;
        } else if (exists === true) {
            statusText = 'Vorhanden';
            connected = true;
            rowState = 'ok';
            detailText = 'Eintrag vorhanden';
        } else if (exists === false) {
            statusText = 'Fehlt';
            connected = true;
            rowState = 'bad';
            detailText = 'Eintrag fehlt';
        } else {
            connected = connectedOverride === null ? false : connectedOverride;
        }

        if (targetStatusId) {
            document.getElementById(targetStatusId).textContent = statusText;
        }
        if (targetButtonId) {
            document.getElementById(targetButtonId).disabled = false;
        }
        if (targetRowId) {
            setRowState(targetRowId, rowState);
        }
        setServiceStatus(serviceKey, {
            connected,
            statusText,
            updatedAt: now,
            error: error || '-',
            connectionText: connected ? 'API erreichbar' : 'API nicht erreichbar',
            detailText,
            tooltip
        });
        state.observed[serviceKey] = observed;
    }

function applyExternalConfigStatus(serviceKey, result) {
        if (!result || result.ok === false) {
            applyExternalExistenceStatus(serviceKey, {
                error: result?.error || 'Konfiguration konnte nicht geprueft werden',
                observed: state.observed[serviceKey],
                connectedOverride: false
            });
            return;
        }
        if (result.data && result.data.ready === false) {
            applyExternalExistenceStatus(serviceKey, {
                error: result.data.missing?.length ? result.data.missing.join(', ') : 'Konfiguration unvollstaendig',
                missing: result.data.missing || [],
                observed: state.observed[serviceKey],
                connectedOverride: false
            });
        }
    }

async function syncWebserviceByEui(options = {}) {
        const {
            eui = document.getElementById('gwEui')?.value || '',
            populateCustomer = false,
            logMissingAsSuccess = false
        } = options;
        const normalizedEui = normalizeHexId(eui);
        const statusEl = document.getElementById('webserviceStatus');

        if (!isValidEui(normalizedEui)) {
            applyExternalExistenceStatus('webservice', {
                error: 'Ungueltige EUI',
                observed: null,
                connectedOverride: false
            });
            updateSectionStatuses();
            return { ok: false, invalid: true, error: 'Ungueltige EUI' };
        }

        if (statusEl) statusEl.textContent = 'checking...';
        const res = await webserviceRequest('/api/webservice/search-by-eui', { eui: normalizedEui });
        if (!res.ok) {
            setOperatorHintForError(res.error);
            applyExternalExistenceStatus('webservice', {
                error: res.error,
                observed: null,
                connectedOverride: false
            });
            updateSectionStatuses();
            return { ok: false, error: res.error, data: res.data };
        }

        const list = normalizeList(res.data);
        const match = findWebserviceGatewayMatch(list, normalizedEui);
        const exists = !!match;
        const observed = exists
            ? {
                exists: true,
                gateway: match,
                clientId: match.clientId || match.client_id || '',
                clientName: match.clientName || match.customerName || match.customer_name || match.name || ''
            }
            : { exists: false };

        applyExternalExistenceStatus('webservice', {
            exists,
            observed,
            connectedOverride: true
        });

        if (exists && populateCustomer) {
            const clientId = observed.clientId;
            const clientName = observed.clientName;
            if (clientId) {
                document.getElementById('clientId').value = clientId;
                vars.selectedClientId = clientId;
            }
            if (clientName) {
                vars.selectedClientName = clientName;
                const clientSearch = document.getElementById('clientSearch');
                if (clientSearch) clientSearch.value = clientName;
            }
            if (clientId) {
                loadClientGateways(clientId);
            }
            updateSuggestedNameLabel();
            syncDesiredState();
        }

        updateSectionStatuses();
        scheduleFinalCheck();

        if (exists) {
            log(`.. Webservice: Gateway existiert bereits.${observed.clientId ? ` Kunde ${observed.clientId}` : ''}`, 'warn');
        } else if (logMissingAsSuccess) {
            log('.. Webservice: Gateway nicht gefunden (bereit zum Anlegen).', 'success');
        }
        return { ok: true, exists, match, list, observed };
    }

function sleep(ms) {
        return new Promise(resolve => window.setTimeout(resolve, ms));
    }

async function verifyWebserviceCreation(retries = 3, delayMs = 700) {
        let lastResult = null;
        for (let attempt = 0; attempt < retries; attempt += 1) {
            lastResult = await syncWebserviceByEui({ logMissingAsSuccess: false });
            if (lastResult.ok && state.observed.webservice && state.observed.webservice.exists) {
                return { ok: true, confirmed: true };
            }
            if (attempt < retries - 1) {
                await sleep(delayMs);
            }
        }
        return { ok: !!(lastResult && lastResult.ok), confirmed: false, lastResult };
    }

function collectReadinessChecks() {
        const name = document.getElementById('gwName').value;
        const sn = document.getElementById('gwSn').value;
        const eui = document.getElementById('gwEui').value;
        const vpnIp = document.getElementById('vpnIp').value;
        const vpnKey = document.getElementById('vpnKey').value;
        const targetWifiSsid = getText('targetWifiSsid');
        const currentWifiSsid = document.getElementById('gwWifiSsid').value;
        const simIccid = document.getElementById('simIccid').value;
        const simVendor = document.getElementById('simVendor').value;
        const gwVpnReported = document.getElementById('gwVpnReported').value;
        const loraGatewayId = document.getElementById('loraGatewayId').value;
        const targetGatewayId = getText('targetGatewayId');
        const targetVpnIp = getText('targetVpnIp');
        const loraActiveServer = document.getElementById('loraActiveServer').value;
        const loraStatus = document.getElementById('loraStatus').value;
        const normalizedLoraGatewayId = normalizeIdentity(loraGatewayId);
        const normalizedTargetGatewayId = normalizeIdentity(targetGatewayId);
        const normalizedGwVpnReported = normalizeVpnIp(gwVpnReported);
        const normalizedTargetVpnIp = normalizeVpnIp(targetVpnIp);
        const chirp = state.observed.chirpstack;
        const mile = state.observed.milesight;
        const web = state.observed.webservice;
        const dbRecord = state.observed.db;
        const knownGatewayAck = !isKnownGatewayPendingAcknowledgement();

        return [
            { label: `Gateway erfolgreich gelesen`, ok: state.readPhaseComplete },
            { label: `Gateway-Name gesetzt`, ok: !!name },
            { label: `Seriennummer gesetzt`, ok: !!sn },
            { label: `Gateway-EUI erkannt`, ok: !!eui },
            { label: `VPN-IP gesetzt`, ok: !!vpnIp },
            { label: `VPN-Key vorhanden`, ok: !!vpnKey },
            { label: `WiFi-SSID stimmt (${currentWifiSsid || '-'} -> ${targetWifiSsid || '-'})`, ok: !!currentWifiSsid && currentWifiSsid === targetWifiSsid },
            { label: `SIM-Vendor gesetzt`, ok: !!simVendor },
            { label: `SIM-ICCID gesetzt`, ok: !!simIccid },
            { label: `Gateway meldet die richtige VPN-IP (${gwVpnReported || '-'} -> ${targetVpnIp || '-'})`, ok: !!normalizedGwVpnReported && normalizedGwVpnReported === normalizedTargetVpnIp },
            { label: `LoRa Gateway-ID stimmt (${loraGatewayId || '-'} -> ${targetGatewayId || '-'})`, ok: !!normalizedLoraGatewayId && normalizedLoraGatewayId === normalizedTargetGatewayId },
            { label: `LoRa Active Server gesetzt`, ok: !!loraActiveServer },
            { label: `LoRa Status ist online`, ok: String(loraStatus) === '1' },
            { label: `ChirpStack Eintrag vorhanden`, ok: !!(chirp && chirp.exists === true) },
            { label: `Milesight Eintrag vorhanden`, ok: !!(mile && mile.exists === true) },
            { label: `Webservice Eintrag vorhanden`, ok: !!(web && web.exists === true) },
            { label: `Bekannter Gateway wurde bewusst bestaetigt`, ok: knownGatewayAck },
            { label: `Cloud DB Stand ist gespeichert`, ok: vars.lastProvisionSavedOk || !!dbRecord }
        ];
    }

function hydrateDbRecord(record) {
        state.observed.db = record || null;
        const vendorSelect = document.getElementById('simVendor');
        const simInventoryId = document.getElementById('simInventoryId');
        if (record) {
            if (vendorSelect) vendorSelect.value = record.sim_vendor_id ? String(record.sim_vendor_id) : '';
            document.getElementById('simIccid').value = record.sim_iccid || '';
            document.getElementById('simCardId').value = record.sim_card_id || '';
            if (simInventoryId) simInventoryId.value = record.sim_id || '';
            document.getElementById('gwName').value = record.gateway_name || '';
            document.getElementById('gwSn').value = record.serial_number || '';
            updateSerialStatus(document.getElementById('gwSn').value);
        } else {
            if (vendorSelect) vendorSelect.value = '';
            document.getElementById('simIccid').value = '';
            document.getElementById('simCardId').value = '';
            if (simInventoryId) simInventoryId.value = '';
            document.getElementById('gwName').value = '';
            document.getElementById('gwSn').value = '';
            updateSerialStatus('');
        }
        updateServiceNames();
        updateConfigTargets();
        syncDesiredState();
        updateKnownGatewayNotice();
        updateFinalizeActions();
    }

function updateFinalizeActions() {
        const saveBtn = document.getElementById('btnPush');
        const confirmBtn = document.getElementById('btnConfirmProvision');
        const hintEl = document.getElementById('finalActionHint');
        const ip = normalizeVpnIp(vars.manualVpnTarget || document.getElementById('vpnIp')?.value || '');
        const knownGatewayNeedsAck = isKnownGatewayPendingAcknowledgement();
        const readyToSave = !!(
            state.readPhaseComplete &&
            vars.finalCheckOk &&
            !knownGatewayNeedsAck &&
            ip &&
            document.getElementById('gwName')?.value &&
            document.getElementById('gwSn')?.value
        );
        const readyToConfirm = !!(vars.finalCheckOk && vars.lastProvisionSavedOk && ip && !vars.lastProvisionConfirmed && !knownGatewayNeedsAck);

        if (saveBtn) saveBtn.disabled = !readyToSave;
        if (confirmBtn) confirmBtn.disabled = !readyToConfirm;
        if (hintEl) {
            if (!vars.finalCheckOk) {
                hintEl.textContent = 'Erst Schritt 4 Pruefung & Integrationen abschliessen.';
            } else if (knownGatewayNeedsAck) {
                hintEl.textContent = 'Bekannten Gateway zuerst bestaetigen.';
            } else if (vars.lastProvisionConfirmed) {
                hintEl.textContent = 'Gateway ist final freigegeben.';
            } else if (!vars.lastProvisionSavedOk) {
                hintEl.textContent = 'Pruefung & Integrationen sind gruen. Jetzt in Cloud DB speichern.';
            } else {
                hintEl.textContent = 'Cloud DB ist aktualisiert. Jetzt final freigeben.';
            }
        }
    }

function buildKnownGatewaySignature(record, gatewayEui) {
        if (!record) return '';
        return [
            record.eui || '',
            gatewayEui || '',
            record.vpn_ip || '',
            record.gateway_name || '',
            record.status_overall || ''
        ].join('|');
    }

function isKnownGatewayPendingAcknowledgement() {
        const notice = document.getElementById('knownGatewayNotice');
        return !!notice && !notice.classList.contains('d-none') && !vars.knownGatewayAcknowledged;
    }

function updateKnownGatewayNotice() {
        const notice = document.getElementById('knownGatewayNotice');
        const textEl = document.getElementById('knownGatewayNoticeText');
        const metaEl = document.getElementById('knownGatewayNoticeMeta');
        const stateEl = document.getElementById('knownGatewayNoticeState');
        if (!notice || !textEl || !metaEl || !stateEl) return;

        const record = state.observed.db;
        const gatewayEui = normalizeIdentity(document.getElementById('gwEui')?.value || '');
        const recordEui = normalizeIdentity(record?.eui || '');
        if (!record || !gatewayEui || !recordEui || recordEui !== gatewayEui) {
            notice.classList.add('d-none');
            textEl.textContent = '-';
            metaEl.textContent = '-';
            stateEl.textContent = 'Bestaetigung offen';
            vars.knownGatewayAcknowledged = false;
            vars.lastKnownGatewaySignature = '';
            updateFinalizeActions();
            return;
        }

        const signature = buildKnownGatewaySignature(record, gatewayEui);
        if (signature !== vars.lastKnownGatewaySignature) {
            vars.knownGatewayAcknowledged = false;
            vars.lastKnownGatewaySignature = signature;
        }

        notice.classList.remove('d-none');
        textEl.textContent = `DB-Eintrag gefunden: ${record.gateway_name || '-'} | VPN ${record.vpn_ip || '-'} | Serial ${record.serial_number || '-'}`;
        metaEl.textContent = `Status: ${record.status_overall || '-'} | EUI: ${record.eui || '-'}`;
        stateEl.textContent = vars.knownGatewayAcknowledged ? 'Bestaetigt' : 'Bestaetigung offen';
        stateEl.classList.remove('bg-warning', 'text-dark', 'bg-success');
        if (vars.knownGatewayAcknowledged) {
            stateEl.classList.add('bg-success');
        } else {
            stateEl.classList.add('bg-warning', 'text-dark');
        }
        updateFinalizeActions();
    }

export function acknowledgeKnownGateway() {
        if (!state.observed.db) return;
        vars.knownGatewayAcknowledged = true;
        updateKnownGatewayNotice();
        log('.. Bekannter Gateway bestaetigt.', 'success');
    }

function renderClientSearchResults(items) {
        const container = document.getElementById('clientSearchResults');
        if (!container) return;
        container.innerHTML = '';
        if (!items.length) return;
        items.forEach(item => {
            const id = item.clientId || item.id || item.client_id || '';
            const name = item.name || item.clientName || item.customerName || item.title || id || '-';
            if (!id) return;
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'list-group-item list-group-item-action';
            button.textContent = `${name} (${id})`;
            button.dataset.clientId = String(id);
            button.dataset.clientName = name;
            button.addEventListener('click', () => {
                document.getElementById('clientId').value = id;
                vars.selectedClientId = id;
                vars.selectedClientName = name;
                const status = document.getElementById('clientGatewaysStatus');
                if (status) status.textContent = 'Gateways werden geladen...';
                const results = document.getElementById('clientSearchResults');
                if (results) results.innerHTML = '';
                loadClientGateways(id);
                updateSuggestedNameLabel();
            });
            container.appendChild(button);
        });
    }

function scheduleFinalCheck(delayMs = 800) {
        if (!state.readPhaseComplete) return;
        const signature = JSON.stringify({
            name: document.getElementById('gwName')?.value || '',
            sn: document.getElementById('gwSn')?.value || '',
            eui: document.getElementById('gwEui')?.value || '',
            vpnIp: document.getElementById('vpnIp')?.value || '',
            simVendor: document.getElementById('simVendor')?.value || '',
            simIccid: document.getElementById('simIccid')?.value || '',
            chirp: state.observed.chirpstack?.exists ?? null,
            mile: state.observed.milesight?.exists ?? null,
            web: state.observed.webservice?.exists ?? null
        });
        if (signature === vars.lastFinalCheckSignature) return;
        vars.lastFinalCheckSignature = signature;
        if (vars.finalCheckTimer) {
            clearTimeout(vars.finalCheckTimer);
        }
        vars.finalCheckTimer = setTimeout(() => {
            vars.finalCheckTimer = null;
            runFinalCheck();
        }, delayMs);
    }

function renderClientGateways(items) {
        const list = document.getElementById('clientGatewaysList');
        const status = document.getElementById('clientGatewaysStatus');
        if (!list || !status) return;
        list.innerHTML = '';
        if (!items.length) {
            status.textContent = 'Keine Gateways gefunden.';
            return;
        }
        status.textContent = `${items.length} Gateway(s) gefunden.`;
        items.forEach(item => {
            const name = item.name || item.gatewayName || '-';
            const id = item.gatewayId || item.gateway_id || item.gatewayEui || item.gateway_eui || '-';
            const lns = item.lns || item.network || '';
            const li = document.createElement('li');
            li.className = 'list-group-item';
            li.textContent = `${name} | ${id}${lns ? ` | LNS ${lns}` : ''}`;
            list.appendChild(li);
        });
    }

export async function handleClientSearchInput(query) {
        const status = document.getElementById('clientGatewaysStatus');
        const results = document.getElementById('clientSearchResults');
        const normalizedQuery = String(query || '').trim();
        if (results) results.innerHTML = '';
        if (!normalizedQuery || normalizedQuery.length < 3) {
            if (status) status.textContent = 'Bitte mindestens 3 Zeichen eingeben.';
            return;
        }
        if (status) status.textContent = 'Suche...';
        const res = await webserviceRequest('/api/webservice/clientsearch', { query: normalizedQuery });
        if (!res.ok) {
            if (status) status.textContent = `Fehler: ${res.error || 'Suche fehlgeschlagen'}`;
            return;
        }
        const list = normalizeList(res.data);
        renderClientSearchResults(list);
        if (status) status.textContent = list.length ? 'Kunden auswählen.' : 'Keine Treffer.';
    }

export async function loadClientGateways(forcedClientId) {
        const rawId = forcedClientId !== undefined && forcedClientId !== null
            ? forcedClientId
            : (document.getElementById('clientId')?.value || '');
        const clientId = String(rawId).trim();
        if (clientId) vars.selectedClientId = clientId;
        updateSuggestedNameLabel();
        const status = document.getElementById('clientGatewaysStatus');
        if (!clientId) {
            if (status) status.textContent = 'Bitte Kunden-ID eingeben.';
            return;
        }
        if (status) status.textContent = 'Gateways werden geladen...';
        const res = await webserviceRequest('/api/webservice/gateways', { clientId });
        if (!res.ok) {
            if (status) status.textContent = `Fehler: ${res.error || 'Gateway-Check fehlgeschlagen'}`;
            return;
        }
    const list = normalizeList(res.data);
    renderClientGateways(list);
    if (status) {
        status.textContent = list.length ? `${list.length} Gateway(s) gefunden.` : 'Keine Gateways gefunden.';
    }
}

function deriveVpnSuffix(ip) {
        if (!ip) return '';
        const parts = ip.split('.');
        if (parts.length < 2) return '';
        return parts.slice(-2).join('.');
    }

export function buildSuggestedName() {
        const vpnIpRaw = document.getElementById('vpnIp')?.value || '';
        const vpnSuffix = deriveVpnSuffix(normalizeVpnIp(vpnIpRaw));
        const clientId = (document.getElementById('clientId')?.value || vars.selectedClientId || '').trim();
        const clientName = (vars.selectedClientName || '').trim();
        const parts = [];
        if (vpnSuffix) parts.push(vpnSuffix);
        if (clientId && clientName) {
            parts.push(`${clientId} - ${clientName}`);
        } else {
            if (clientId) parts.push(clientId);
            if (clientName) parts.push(clientName);
        }
        return parts.join(' ').trim();
    }

export function updateSuggestedNameLabel() {
        const label = document.getElementById('suggestedNameLabel');
        if (!label) return;
        const suggestion = buildSuggestedName();
        label.textContent = `Vorschlag: ${suggestion || '-'}`;
    }

export function setSuggestedName() {
        const suggestion = buildSuggestedName();
        if (!suggestion) {
            log('!! Kein Namensvorschlag verfügbar (VPN IP / Kunden-ID / Name fehlt).', 'error');
            return;
        }
        const gwName = document.getElementById('gwName');
        if (gwName) {
            gwName.value = suggestion;
            vars.manualNameEdited = true;
            updateServiceNames();
            syncDesiredState();
            invalidateFinalCheck();
            checkReady();
        }
    }

const GatewayAdapter = {
        async fetchDevice() {
            try {
                const device = await safeJson('/api/gateway/device-info');
                const unwrapped = unwrap(device.data);
                if (!unwrapped.ok) return { ok: false, error: unwrapped.error };
                return { ok: true, data: unwrapped.data };
            } catch (e) {
                return { ok: false, error: String(e) };
            }
        },
        async fetchLora() {
            try {
                log('.. Request /api/gateway/device-info-lora', 'info');
                const lora = await safeJson('/api/gateway/device-info-lora');
                const unwrapped = unwrap(lora.data);
                if (!unwrapped.ok) return { ok: false, error: unwrapped.error };
                return { ok: true, data: unwrapped.data };
            } catch (e) {
                return { ok: false, error: String(e) };
            }
        }
    };

const DatabaseAdapter = {
        async fetch(vpnIp, eui, serialNumber) {
            if (!vpnIp && !eui && !serialNumber) return { ok: false, error: 'VPN IP, EUI oder Serial fehlt.' };
            try {
                const res = await safeJson('/api/db/gateway', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ vpn_ip: vpnIp, eui: eui, serial_number: serialNumber })
                });
                const unwrapped = unwrap(res.data);
                if (!unwrapped.ok) return { ok: false, error: unwrapped.error };
                return { ok: true, data: unwrapped.data };
            } catch (e) {
                return { ok: false, error: String(e) };
            }
        },
        async fetchTable(query, limit) {
            const params = new URLSearchParams();
            if (query) params.set('q', query);
            if (limit) params.set('limit', String(limit));
            try {
                const res = await safeJson(`/api/db/table-view?${params.toString()}`);
                const unwrapped = unwrap(res.data);
                if (!unwrapped.ok) return { ok: false, error: unwrapped.error };
                return { ok: true, data: unwrapped.data };
            } catch (e) {
                return { ok: false, error: String(e) };
            }
        }
    };

function formatCloudTableDate(value) {
        if (!value) return '-';
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) return value;
        return parsed.toLocaleString();
    }

function escapeHtml(value) {
        return String(value ?? '-')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

function renderCloudTableRows(rows) {
        const tbody = document.getElementById('cloudTableBody');
        if (!tbody) return;

        if (!rows || !rows.length) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="9" class="text-muted">Keine Eintraege gefunden.</td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = rows.map(row => `
            <tr>
                <td>${escapeHtml(row.vpn_ip)}</td>
                <td>${escapeHtml(row.gateway_name)}</td>
                <td>${escapeHtml(row.serial_number)}</td>
                <td>${escapeHtml(row.eui)}</td>
                <td>${escapeHtml(row.wifi_ssid)}</td>
                <td>${escapeHtml(row.status_overall)}</td>
                <td>${escapeHtml(row.sim_iccid || row.sim_id)}</td>
                <td>${escapeHtml(row.sim_vendor_name)}</td>
                <td>${escapeHtml(formatCloudTableDate(row.last_gateway_sync_at || row.assigned_at))}</td>
            </tr>
        `).join('');
    }

function deriveCloudTableQuery() {
        return document.getElementById('vpnIp')?.value?.trim()
            || document.getElementById('gwEui')?.value?.trim()
            || document.getElementById('gwSn')?.value?.trim()
            || document.getElementById('gwName')?.value?.trim()
            || '';
    }

function setCloudTableSearchQuery(query) {
        const searchInput = document.getElementById('cloudTableSearch');
        if (!searchInput) return;
        searchInput.value = (query || '').trim();
    }

export async function loadCloudTableViewer() {
        const searchInput = document.getElementById('cloudTableSearch');
        const limitInput = document.getElementById('cloudTableLimit');
        const statusEl = document.getElementById('cloudTableStatus');
        const query = searchInput?.value?.trim() || '';
        const limit = limitInput?.value || '50';

        if (statusEl) {
            statusEl.textContent = 'Lade Cloud Tabelle...';
        }

        const result = await DatabaseAdapter.fetchTable(query, limit);
        if (!result.ok) {
            renderCloudTableRows([]);
            if (statusEl) {
                statusEl.textContent = `Fehler: ${result.error}`;
            }
            log(`!! Cloud Tabellenansicht fehlgeschlagen: ${result.error}`, 'error');
            setOperatorHintForError(result.error);
            return;
        }

        renderCloudTableRows(result.data.rows || []);
        if (statusEl) {
            statusEl.textContent = `${result.data.count || 0} Eintraege geladen.`;
            if (result.data.query) {
                statusEl.textContent += ` Filter: "${result.data.query}"`;
            }
        }
        log(`.. Cloud Tabelle geladen (${result.data.count || 0} Eintraege).`, 'success');
    }

export async function openCloudTableViewer(query = '') {
        const modalEl = document.getElementById('cloudTableModal');
        if (!modalEl || !window.bootstrap?.Modal) return;

        const requestedQuery = (query || '').trim();
        const currentSearch = document.getElementById('cloudTableSearch')?.value?.trim() || '';
        if (requestedQuery) {
            setCloudTableSearchQuery(requestedQuery);
        } else if (!currentSearch) {
            setCloudTableSearchQuery(deriveCloudTableQuery());
        }

        window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
        await loadCloudTableViewer();
    }
export async function runReadPipeline(options = {}) {
        const includeSecondary = options.includeSecondary !== false;
        log('.. Starte Gateway Read...', 'info');
        setConnectionState(null);
        state.readPhaseComplete = false;
        const deviceResult = await GatewayAdapter.fetchDevice();
        if (!deviceResult.ok) {
            state.statuses.gateway = { connected: false, updatedAt: null, error: deviceResult.error };
            setConnectionState(false, 'Bitte mit dem Gateway-WLAN verbinden.');
            setGatewayBlocked(true, deviceResult.error);
            setOperatorHintForError('Gateway nicht erreichbar');
            log('!! Gateway nicht erreichbar: ' + deviceResult.error, 'error');
            return;
        }

        state.statuses.gateway = { connected: true, updatedAt: new Date().toISOString(), error: null };
        state.observed.gateway = deviceResult.data;
        state.readPhaseComplete = true;
        setGatewayBlocked(false);
        setConnectionState(true, 'Gateway erreichbar.');
        try {
            applyGatewayState(deviceResult.data, null);
        } catch (e) {
            log('!! Fehler beim Anwenden der Gateway-Daten: ' + e, 'error');
        }

        log('.. Lese LoRa Status...');
        try {
            const loraResult = await GatewayAdapter.fetchLora();
            if (loraResult.ok) {
                state.observed.lora = loraResult.data;
                try {
                    applyGatewayState(deviceResult.data, loraResult.data);
                } catch (e) {
                    log('!! Fehler beim Anwenden der LoRa-Daten: ' + e, 'error');
                }
                log('.. LoRa Status geladen.', 'success');
            } else {
                state.observed.lora = null;
                try {
                    applyGatewayState(deviceResult.data, null);
                } catch (e) {
                    log('!! Fehler beim Anwenden der Gateway-Daten: ' + e, 'error');
                }
                log('!! LoRa Info nicht verfuegbar: ' + loraResult.error, 'error');
            }
        } catch (e) {
            log('!! LoRa Fetch Fehler: ' + e, 'error');
        }

        if (includeSecondary) {
            await fetchSecondarySources();
        }
        setRuntimeHint('', 'muted');
        updateGatewayStatus();
        checkVpnReachability();
        updateSectionStatuses();
        scheduleFinalCheck();
    }
export function applyGatewayState(deviceInfo, loraInfo) {
        if (!deviceInfo) return;
        const rawMac = deviceInfo.mac || '';
        const derivedEui = deriveEuiFromMac(rawMac);
        const loraGatewayEui = normalizeHexId(loraInfo && loraInfo.gatewayEui ? loraInfo.gatewayEui : '');
        const deviceGatewayEui = normalizeHexId(deviceInfo.eui || '');
        const derivedGatewayEui = normalizeHexId(derivedEui || '');
        const rawEui = loraGatewayEui || deviceGatewayEui || derivedGatewayEui || '';
        const gatewayVpnIp = normalizeVpnIp(deviceInfo.vpn_ip || '');
        if ((gatewayVpnIp && gatewayVpnIp !== vars.lastGatewayVpnIp) || (!gatewayVpnIp && vars.lastGatewayVpnIp)) {
            resetGatewayScopedFields();
            vars.lastGatewayVpnIp = gatewayVpnIp;
            document.getElementById('vpnIp').value = gatewayVpnIp;
            if (gatewayVpnIp) {
                log(`.. Neues Gateway erkannt (VPN IP ${gatewayVpnIp}). Lade DB-Daten...`, 'info');
                loadDbForGateway(gatewayVpnIp, rawEui, '');
            } else {
                log('.. Gateway ohne VPN IP erkannt. Felder geleert.', 'info');
            }
        }
        document.getElementById('gwMac').value = rawMac;
        const statusMacEl = document.getElementById('statusMacAddress');
        if (statusMacEl) statusMacEl.textContent = rawMac || '-';
        setRowState('rowMacAddress', rawMac ? 'ok' : 'na');
        const gatewaySerial = deviceInfo.serial_number || deviceInfo.sn || document.getElementById('gwSn').value || '';
        if (gatewaySerial) {
            document.getElementById('gwSn').value = gatewaySerial;
        }
        updateSerialStatus(gatewaySerial);
        const macDetailsEl = document.getElementById('statusMacDetails');
        if (macDetailsEl) macDetailsEl.textContent = rawMac ? 'Vom Gateway gelesen' : 'Quelle device-info';
        document.getElementById('gwEui').value = rawEui;
        if (rawEui) {
            const targetGatewayEui = document.getElementById('targetGatewayEui');
            const targetGatewayId = document.getElementById('targetGatewayId');
            if (targetGatewayEui) targetGatewayEui.textContent = rawEui;
            if (targetGatewayId) targetGatewayId.textContent = rawEui;
        }
        document.getElementById('gwVpnReported').value = deviceInfo.vpn_ip || '';
        document.getElementById('gwWifiSsid').value = deviceInfo.wifi_ssid || '';
        const statusGatewayEuiEl = document.getElementById('statusGatewayEui');
        const statusGatewayIdEl = document.getElementById('statusGatewayId');
        const statusVpnEl = document.getElementById('statusVpnReported');
        const statusWifiEl = document.getElementById('statusWifiSsid');
        const gatewayIdDisplay = normalizeIdentity((loraInfo && loraInfo.gatewayId) || rawEui || '');
        setText('statusGatewayEui', rawEui);
        setText('statusGatewayId', gatewayIdDisplay);
        setText('statusVpnReported', deviceInfo.vpn_ip);
        setText('statusWifiSsid', deviceInfo.wifi_ssid);
        const euiDetailsEl = document.getElementById('statusGatewayEuiDetails');
        if (euiDetailsEl) euiDetailsEl.textContent = rawEui ? 'Vom Gateway gelesen' : 'Quelle device-info-lora';
        if (statusGatewayEuiEl) setTooltip(statusGatewayEuiEl, 'Quelle: device-info-lora');
        if (statusGatewayIdEl) setTooltip(statusGatewayIdEl, 'Quelle: device-info-lora');
        if (statusVpnEl) setTooltip(statusVpnEl, 'Quelle: device-info');
        if (statusWifiEl) setTooltip(statusWifiEl, 'Quelle: device-info');
        const gatewayIdValue = normalizeIdentity((loraInfo && loraInfo.gatewayId) || deviceInfo.gatewayId || rawEui || '');
        const isGolden = String(gatewayIdValue).toLowerCase() === 'cafe';
        if (isGolden) {
            document.getElementById('gatewayGoldenBadge').style.display = 'inline-block';
            if (!vars.manualVpnTarget) {
                if (deviceInfo.vpn_ip === '0.0.0.0') {
                    document.getElementById('vpnIp').value = '';
                } else if (deviceInfo.vpn_ip) {
                    document.getElementById('vpnIp').value = deviceInfo.vpn_ip;
                }
                log('.. Golden Device erkannt (Gateway ID cafe). Pruefe zuerst bestehenden DB-Eintrag per EUI...', 'info');
                resolveKnownGatewayOrReserveIp(rawEui);
            }
        } else {
            document.getElementById('gatewayGoldenBadge').style.display = 'none';
            if (!vars.manualVpnTarget && deviceInfo.vpn_ip) {
                document.getElementById('vpnIp').value = deviceInfo.vpn_ip;
                fetchVpnKeyForGateway(deviceInfo.vpn_ip);
            }
        }
        if (deviceInfo.wifi_ssid) {
            const hint = document.getElementById('gatewayConnectionHint');
            hint.textContent = `SSID: ${deviceInfo.wifi_ssid}`;
            hint.classList.add('ssid-emphasis');
            hint.title = 'Verbindung gilt als OK, wenn /api/gateway/device-info erreichbar ist. Gateway lesen startet den Read-Workflow (Device-Info → LoRa → Sekundärquellen).';
            setHeadlineConnection(state.statuses.gateway.connected, deviceInfo.wifi_ssid);
        }

        const interfaces = deviceInfo.interfaces || {};
        const cellular = interfaces.cellular0 || interfaces.cellular || {};
        const wifiInterface = interfaces.wlan0 || interfaces.wifi0 || {};
        const wifiIp = wifiInterface.ip || '';
        const cellularUp = cellular.up;
        const cellularIp = cellular.ip;
        const cellularOnline = deviceInfo.cellular_online;
        const lteConnected = cellularOnline === undefined ? !!cellularUp : (cellularOnline || !!cellularUp);
        const statusText = lteConnected ? 'connected' : 'disconnected';
        const lteText = formatConnection(lteConnected);
        const ipAssigned = cellularIp ? 'yes' : 'no';

        document.getElementById('gwCellularStatus').value = statusText;
        document.getElementById('gwLteState').value = lteText;
        document.getElementById('gwLteConnected').value = lteConnected ? 'true' : 'false';
        document.getElementById('gwIpAssigned').value = ipAssigned;
        document.getElementById('gwCellularIp').value = cellularIp || '';
        document.getElementById('gwWifiIp').value = wifiIp;
        const cellularStatusEl = document.getElementById('statusCellularStatus');
        if (cellularStatusEl) {
            const ipHint = cellularIp || '-';
            const lteHint = lteConnected ? 'connected' : 'disconnected';
            setTooltip(cellularStatusEl, `Quelle: device-info | IP: ${ipHint} | LTE: ${lteHint}`);
        }

        if (loraInfo) {
            setValue('loraGatewayEui', loraInfo.gatewayEui || '');
            setValue('loraGatewayId', loraInfo.gatewayId || '');
            setValue('loraStatus', loraInfo.status ?? '');
            setValue('loraPending', loraInfo.pendingData ?? '');

            const activeServer = getLoraActiveServer(loraInfo);
            setValue('loraActiveServer', activeServer);
            setText('statusLns', activeServer || '-');
            const loraStatusRow = document.getElementById('rowLoraStatus');
            if (loraStatusRow) {
                loraStatusRow.classList.remove('row-ok', 'row-bad', 'row-na');
                if (String(loraInfo.status) === '1' && activeServer) {
                    loraStatusRow.classList.add('row-ok');
                } else {
                    loraStatusRow.classList.add('row-bad');
                }
            }
        } else {
            setValue('loraGatewayEui', '');
            setValue('loraGatewayId', '');
            setValue('loraStatus', '');
            setValue('loraActiveServer', '');
            setValue('loraPending', '');
            setText('statusLns', '-');
            const loraStatusRow = document.getElementById('rowLoraStatus');
            if (loraStatusRow) {
                loraStatusRow.classList.remove('row-ok', 'row-bad', 'row-na');
                loraStatusRow.classList.add('row-na');
            }
        }

        updateServiceNames();
        updateConfigTargets();
        syncDesiredState();
        updateGatewayStatus();
        invalidateFinalCheck();
        checkReady();
        handleEuiChange();
        buildMismatchList();
    }
export async function fetchSecondarySources() {
        await checkChirpstackConfig();
        await checkMilesightConfig();
        await Promise.all([
            checkChirpstackExists({ silent: true }),
            checkMilesightExists({ silent: true }),
            checkWebserviceStatus()
        ]);
        const vpnIp = document.getElementById('gwVpnReported').value || '';
        const eui = document.getElementById('gwEui').value || '';
        const serialNumber = document.getElementById('gwSn').value || '';
        let dbResult = await DatabaseAdapter.fetch(vpnIp, eui, '');
        if (!dbResult.ok && serialNumber) {
            dbResult = await DatabaseAdapter.fetch('', '', serialNumber);
        }
        if (!dbResult.ok) {
            setOperatorHintForError(dbResult.error);
        }
        hydrateDbRecord(dbResult.ok ? dbResult.data : null);
        buildMismatchList();
    }
export function buildMismatchList() {
        const items = [];
        const gateway = state.observed.gateway || {};
        const lora = state.observed.lora || {};
        const chirpstack = state.observed.chirpstack;
        const milesight = state.observed.milesight;
        const eui = gateway.eui;

        const euiValid = isValidEui(eui);

        if (euiValid && lora.gatewayEui && lora.gatewayEui !== eui) {
            items.push({ text: `LoRa Gateway EUI (${lora.gatewayEui}) weicht von Gateway EUI (${eui}) ab.` });
        }
        if (euiValid && lora.gatewayId && lora.gatewayId !== eui) {
            items.push({ text: `LoRa Gateway ID (${lora.gatewayId}) weicht von Gateway EUI (${eui}) ab.` });
        }
        if (euiValid && chirpstack && chirpstack.exists === false) {
            items.push({ text: `ChirpStack: Gateway ${eui} nicht gefunden.` });
        }
        if (euiValid && milesight && milesight.exists === false) {
            items.push({ text: `Milesight: Device ${eui} nicht gefunden.` });
        }

        renderMismatchList(items);
    }
export function syncDesiredState() {
        const vendorId = document.getElementById('simVendor').value;
        const vendor = vars.simVendors.find(item => String(item.id) === String(vendorId));
        state.desired = {
            gateway_name: document.getElementById('gwName').value,
            serial_number: document.getElementById('gwSn').value,
            eui: document.getElementById('gwEui').value,
            vpn_ip: document.getElementById('vpnIp').value,
            sim_vendor_id: vendorId,
            sim_vendor_name: vendor ? vendor.name : '',
            sim_iccid: document.getElementById('simIccid').value
        };
        renderDesiredDiff();
        updateSectionStatuses();
        updateFinalizeActions();
        scheduleFinalCheck(1200);
    }
export function renderDesiredDiff() {
        const list = document.getElementById('desiredDiffList');
        const panel = document.getElementById('desiredDiffPanel');
        const headline = document.getElementById('desiredDiffHeadline');
        if (!list || !panel || !headline) return;
        list.innerHTML = '';
        const gateway = state.observed.gateway || {};
        const desired = state.desired;
        const entries = [
            { key: 'gateway_name', label: 'Gateway Name', current: '-', desired: desired.gateway_name },
            { key: 'serial_number', label: 'Serial Number', current: '-', desired: desired.serial_number },
            { key: 'eui', label: 'EUI', current: gateway.eui || '-', desired: desired.eui },
            { key: 'vpn_ip', label: 'VPN IP', current: gateway.vpn_ip || '-', desired: desired.vpn_ip },
            { key: 'sim_vendor', label: 'SIM Vendor', current: '-', desired: desired.sim_vendor_name || desired.sim_vendor_id },
            { key: 'sim_iccid', label: 'SIM ICCID', current: '-', desired: desired.sim_iccid }
        ];
        const diffs = [];
        entries.forEach(entry => {
            if (!entry.desired) return;
            if (String(entry.current) !== String(entry.desired)) {
                diffs.push(entry);
            }
        });
        state.diff = diffs;

        if (!state.readPhaseComplete) {
            if (headline) headline.textContent = 'Geplante Aenderungen (Gateway -> Gewuenscht)';
            if (panel) panel.classList.remove('d-none');
            const li = document.createElement('li');
            li.textContent = 'Gateway Status noch nicht gelesen.';
            list.appendChild(li);
            return;
        }

        if (!diffs.length) {
            if (headline) headline.textContent = 'Keine offenen Sollabweichungen';
            if (panel) panel.classList.remove('d-none');
            const li = document.createElement('li');
            li.textContent = 'Gateway entspricht bereits den Zielwerten.';
            list.appendChild(li);
            return;
        }

        if (headline) headline.textContent = 'Noch offene Sollabweichungen';
        if (panel) panel.classList.remove('d-none');
        diffs.forEach(entry => {
            const li = document.createElement('li');
            li.textContent = `${entry.label}: ${entry.current} -> ${entry.desired}`;
            list.appendChild(li);
        });
    }
export function renderFinalSummary() {
        const reasons = document.getElementById('finalCheckReasons');
        if (!reasons) return;
        reasons.innerHTML = '';
        if (!vars.lastFinalChecks.length) {
            const li = document.createElement('li');
            li.textContent = 'Noch kein Check ausgefuehrt.';
            reasons.appendChild(li);
        } else {
            vars.lastFinalChecks.forEach(item => {
                const li = document.createElement('li');
                li.textContent = `${item.ok ? 'OK' : 'FEHLT'}: ${item.label}`;
                li.style.color = item.ok ? '#2b8a3e' : '#c92a2a';
                reasons.appendChild(li);
            });
        }

    }
export function updateServiceNames() {
        const eui = document.getElementById('gwEui').value || '-';
        const chirpDetails = document.getElementById('serviceDetailsChirpstack');
        const mileDetails = document.getElementById('serviceDetailsMilesight');
        const webDetails = document.getElementById('serviceDetailsWebservice');
        if (chirpDetails && chirpDetails.textContent === '-') chirpDetails.textContent = `Gateway ${eui}`;
        if (mileDetails && mileDetails.textContent === '-') mileDetails.textContent = `Gateway ${eui}`;
        if (webDetails && webDetails.textContent === '-') webDetails.textContent = `Gateway ${eui}`;
    }
export function deriveWifiSsid(ip) {
        if (!ip) return '';
        const parts = ip.split('.');
        if (parts.length < 2) return '';
        const lastTwo = parts.slice(-2).join('.');
        return `bbdbmon_${lastTwo}`;
    }
export function formatVpnCidr(ip) {
        if (!ip) return '';
        if (ip.includes('/')) return ip;
        return `${ip}/32`;
    }
export function normalizeVpnIp(ip) {
        if (!ip) return '';
        return ip.split('/')[0];
    }
function updateSerialStatus(value) {
        const statusSnEl = document.getElementById('statusSerialNumber');
        if (statusSnEl) statusSnEl.textContent = value || '-';
        const serialDetailsEl = document.getElementById('statusSerialDetails');
        if (serialDetailsEl) serialDetailsEl.textContent = value ? 'Vorhanden' : 'Seriennummer am Gateway';
        setRowState('rowSerialNumber', value && value !== '-' ? 'ok' : 'na');
        const serialInput = document.getElementById('serialNumberInput');
        if (serialInput && document.activeElement !== serialInput) {
            serialInput.value = value || '';
        }
    }
export function toggleSerialNumberEdit(forceOpen) {
        const editGroup = document.getElementById('serialNumberEditGroup');
        if (!editGroup) return;
        const shouldOpen = typeof forceOpen === 'boolean'
            ? forceOpen
            : editGroup.classList.contains('d-none');
        editGroup.classList.toggle('d-none', !shouldOpen);
        if (shouldOpen) {
            const serialInput = document.getElementById('serialNumberInput');
            if (serialInput) {
                serialInput.focus();
                serialInput.select();
            }
        }
    }
export async function setSerialNumberFromStatus() {
        const serialInput = document.getElementById('serialNumberInput');
        const raw = serialInput ? serialInput.value : '';
        const value = (raw || '').trim();
        if (!value) {
            alert('Bitte Serial Number eingeben.');
            return;
        }
        const gwSn = document.getElementById('gwSn');
        if (gwSn) gwSn.value = value;
        vars.allowMilesightSerialFill = false;
        updateSerialStatus(value);
        toggleSerialNumberEdit(false);
        invalidateFinalCheck();
        checkReady();
        syncDesiredState();
        buildMismatchList();
        await saveCustomerData();
    }
export function getLoraActiveServer(loraInfo) {
        if (!loraInfo || !Array.isArray(loraInfo.servs)) return '';
        const active = loraInfo.servs.find(s => s.servEnabled);
        if (!active) return '';
        return `${active.servType}@${active.servAddr}:${active.servPortUp}`;
    }
export function updateConfigTargets() {
        const vpnIp = document.getElementById('vpnIp').value;
        const vpnKey = document.getElementById('vpnKey').value;
        const vpnTarget = vars.manualVpnTarget || vpnIp;
        const wifiSsid = deriveWifiSsid(vpnTarget);
        const currentEui = document.getElementById('gwEui').value;
        const currentMac = document.getElementById('gwMac').value;
        let derivedEui = currentEui || deriveEuiFromMac(currentMac);
        if (!derivedEui || derivedEui === '000000FFFE000000') {
            const statusEui = getText('statusGatewayEui');
            derivedEui = statusEui && statusEui !== '-' ? statusEui : derivedEui;
        }
        const vendorId = document.getElementById('simVendor').value;
        const vendor = vars.simVendors.find(item => String(item.id) === String(vendorId));
        const apn = vendor ? vendor.apn : '';
        const cfgGatewayId = document.getElementById('cfgGatewayId');
        const cfgVpnIp = document.getElementById('cfgVpnIp');
        const cfgVpnKey = document.getElementById('cfgVpnKey');
        const cfgWifiSsid = document.getElementById('cfgWifiSsid');
        const cfgApn = document.getElementById('cfgApnValue') || document.getElementById('cfgApn');
        if (cfgGatewayId) cfgGatewayId.textContent = derivedEui || '-';
        if (cfgVpnIp) cfgVpnIp.textContent = formatVpnCidr(vpnTarget) || '-';
        if (cfgVpnKey) cfgVpnKey.textContent = '-';
        if (cfgWifiSsid) cfgWifiSsid.textContent = wifiSsid || '-';
        if (cfgApn) cfgApn.textContent = apn || '-';

        const targetGatewayEui = document.getElementById('targetGatewayEui');
        const targetGatewayId = document.getElementById('targetGatewayId');
        const targetVpnIp = document.getElementById('targetVpnIp');
        const targetWifiSsid = document.getElementById('targetWifiSsid');
        const targetVpnKey = document.getElementById('targetVpnKey');
        const targetApn = document.getElementById('targetApn');
        if (targetGatewayEui) targetGatewayEui.textContent = derivedEui || '-';
        if (targetGatewayId) targetGatewayId.textContent = derivedEui || '-';
        if (targetVpnIp) targetVpnIp.textContent = vpnTarget || '-';
        if (targetWifiSsid) targetWifiSsid.textContent = wifiSsid || '-';
        if (targetVpnKey) {
            const key = vpnKey || '';
            targetVpnKey.dataset.full = key;
            targetVpnKey.textContent = key ? `${key.slice(0, 5)}...` : '-';
            targetVpnKey.title = key || '';
        }
        if (targetApn) targetApn.textContent = apn || '-';
    }
export async function loadDbForGateway(vpnIp, eui, serialNumber) {
        if (!vpnIp && !eui && !serialNumber) return;
        const dbResult = await DatabaseAdapter.fetch(vpnIp, eui, serialNumber);
        if (!dbResult.ok) {
            setOperatorHintForError(dbResult.error);
        }
        hydrateDbRecord(dbResult.ok ? dbResult.data : null);
        return dbResult.ok ? dbResult.data : null;
    }

async function resolveKnownGatewayOrReserveIp(eui) {
        const normalizedEui = normalizeIdentity(eui || document.getElementById('gwEui')?.value || '');
        if (normalizedEui) {
            const dbRecord = await loadDbForGateway('', normalizedEui, '');
            if (dbRecord && normalizeIdentity(dbRecord.eui) === normalizedEui && dbRecord.vpn_ip) {
                vars.manualVpnTarget = dbRecord.vpn_ip;
                document.getElementById('vpnIp').value = dbRecord.vpn_ip;
                await fetchVpnKeyForGateway(dbRecord.vpn_ip);
                updateConfigTargets();
                syncDesiredState();
                updateGatewayStatus();
                checkVpnReachability();
                log(`.. Bekannter Gateway in DB gefunden. Nutze bestehende VPN IP ${dbRecord.vpn_ip}.`, 'success');
                return true;
            }
        }
        await fetchIp();
        checkVpnReachability();
        return false;
    }
export function resetGatewayScopedFields() {
        document.getElementById('gwName').value = '';
        document.getElementById('gwSn').value = '';
        updateSerialStatus('');
        document.getElementById('simIccid').value = '';
        document.getElementById('simVendor').value = '';
        document.getElementById('simCardId').value = '';
        vars.manualVpnTarget = '';
        vars.manualNameEdited = false;
        vars.allowMilesightSerialFill = true;
        vars.knownGatewayAcknowledged = false;
        vars.lastKnownGatewaySignature = '';
        state.observed.db = null;
        state.observed.chirpstack = null;
        state.observed.milesight = null;
        setServiceStatus('chirpstack', { connected: false, statusText: '-', updatedAt: null, error: '-' });
        setServiceStatus('milesight', { connected: false, statusText: '-', updatedAt: null, error: '-' });
        updateKnownGatewayNotice();
    }
export function updateGatewayStatus() {
        const gateway = state.observed.gateway || {};
        const lora = state.observed.lora || {};
        const serialValue = document.getElementById('gwSn').value || document.getElementById('statusSerialNumber')?.textContent || '';
        const macValue = document.getElementById('gwMac').value || document.getElementById('statusMacAddress')?.textContent || '';
        const currentEui = normalizeIdentity(
            lora.gatewayEui ||
            gateway.eui ||
            document.getElementById('gwEui').value ||
            document.getElementById('loraGatewayEui').value ||
            getText('statusGatewayEui') ||
            ''
        );
        const currentId = normalizeIdentity(
            lora.gatewayId ||
            gateway.eui ||
            document.getElementById('gwEui').value ||
            document.getElementById('loraGatewayId').value ||
            getText('statusGatewayId') ||
            currentEui
        );
        const currentVpn = gateway.vpn_ip || document.getElementById('gwVpnReported').value || getText('statusVpnReported') || '';
        const currentWifiSsid = gateway.wifi_ssid || document.getElementById('gwWifiSsid').value || getText('statusWifiSsid') || '';
        const currentCellularStatus = document.getElementById('gwCellularStatus').value || '';
        const currentCellularIp = document.getElementById('gwCellularIp').value || '';
        let currentLteState = document.getElementById('gwLteState').value || '';
        const currentIpAssigned = document.getElementById('gwIpAssigned').value || '';
        if (!currentLteState && gateway.interfaces) {
            const cellular = gateway.interfaces.cellular0 || gateway.interfaces.cellular || {};
            const cellularOnline = gateway.cellular_online;
            const lteConnected = cellularOnline === undefined ? !!cellular.up : (cellularOnline || !!cellular.up);
            currentLteState = formatConnection(lteConnected);
        }
        const targetEui = normalizeIdentity(getText('targetGatewayEui'));
        const targetId = normalizeIdentity(getText('targetGatewayId'));
        const targetVpn = normalizeVpnIp(getText('targetVpnIp'));
        const targetWifiSsid = String(getText('targetWifiSsid') || '').trim();
        const db = state.observed.db || {};

        setText('statusGatewayEui', currentEui);
        setText('statusGatewayId', currentId);
        setText('statusVpnReported', currentVpn);
        setText('statusWifiSsid', currentWifiSsid);
        const cellularStatusEl = document.getElementById('statusCellularStatus');
        if (cellularStatusEl) {
            cellularStatusEl.textContent = currentCellularStatus || '-';
        }
        setTooltip(document.getElementById('statusGatewayEui'), 'Quelle: device-info-lora');
        setTooltip(document.getElementById('statusGatewayId'), 'Quelle: device-info-lora');
        setTooltip(document.getElementById('statusVpnReported'), 'Quelle: device-info');
        setTooltip(document.getElementById('statusWifiSsid'), 'Quelle: device-info');
        if (cellularStatusEl) {
            const lteHint = currentLteState || '-';
            const ipHint = currentCellularIp || '-';
            setTooltip(cellularStatusEl, `Quelle: device-info | IP: ${ipHint} | LTE: ${lteHint}`);
        }

        const matchEui = compareStatusValue(currentEui, targetEui, { normalize: normalizeIdentity });
        const matchId = compareStatusValue(currentId, targetId, { normalize: normalizeIdentity });
        const matchVpn = compareStatusValue(currentVpn, targetVpn, { normalize: normalizeVpnIp });
        const matchWifiSsid = compareStatusValue(currentWifiSsid, targetWifiSsid);

        setMatchStyle('statusGatewayEui', matchEui);
        setMatchStyle('statusGatewayId', matchId);
        setMatchStyle('statusVpnReported', matchVpn);
        setMatchStyle('statusWifiSsid', matchWifiSsid);

        setStatusIcon('statusGatewayEuiState', matchEui);
        setStatusIcon('statusGatewayIdState', matchId);
        setStatusIcon('statusVpnReportedState', matchVpn);
        setStatusIcon('statusWifiSsidState', matchWifiSsid);
        setRowState('rowGatewayId', matchId === null ? 'na' : (matchId ? 'ok' : 'bad'));
        setRowState('rowVpnIp', matchVpn === null ? 'na' : (matchVpn ? 'ok' : 'bad'));
        setRowState('rowWifiSsid', matchWifiSsid === null ? 'na' : (matchWifiSsid ? 'ok' : 'bad'));
        if (currentLteState) {
            setRowState('rowCellularStatus', currentLteState === 'connected' ? 'ok' : 'bad');
        } else {
            setRowState('rowCellularStatus', 'na');
        }
        setRowState('rowGatewayEuiStatus', currentEui ? 'ok' : 'na');
        setRowState('rowMacAddress', macValue && macValue !== '-' ? 'ok' : 'na');
        setRowState('rowSerialNumber', serialValue && serialValue !== '-' ? 'ok' : 'na');

        applyDbMismatch('statusGatewayEuiState', currentEui, db.eui);
        applyDbMismatch('statusGatewayIdState', currentId, db.eui);
        applyDbMismatch('statusVpnReportedState', currentVpn, db.vpn_ip);
        applyDbMismatch('statusWifiSsidState', currentWifiSsid, db.wifi_ssid);

        updateConfigStatus(matchEui, matchId, matchVpn);
        updateSectionStatuses();
    }
export function formatConnection(value) {
        if (value === '' || value === null || value === undefined) return '';
        if (typeof value === 'boolean') return value ? 'connected' : 'disconnected';
        if (typeof value === 'number') return value ? 'connected' : 'disconnected';
        return String(value);
    }
export function deriveEuiFromMac(mac) {
        if (!mac) return '';
        const clean = mac.replace(/:/g, '').toUpperCase();
        if (clean.length !== 12) return '';
        if (clean === '000000000000') return '';
        return clean.slice(0, 6) + 'FFFE' + clean.slice(6);
    }
function getSelectedVpnTarget() {
        const candidates = [
            vars.manualVpnTarget,
            document.getElementById('vpnIp')?.value || '',
            getText('targetVpnIp')
        ];
        for (const candidate of candidates) {
            const normalized = normalizeVpnIp(candidate || '');
            if (normalized && normalized !== '-') return normalized;
        }
        return '';
    }
export async function checkVpnReachability() {
        const vpnIp = getSelectedVpnTarget();
        const statusEl = document.getElementById('statusVpnReach');
        const detailsEl = document.getElementById('statusVpnReachDetails');
        if (!vpnIp || vpnIp === '-') {
            statusEl.textContent = 'Fehler';
            if (detailsEl) detailsEl.textContent = 'Keine Ziel-VPN verfuegbar';
            setRowState('rowVpnReach', 'bad');
            setRuntimeHint('VPN-Pruefung fehlgeschlagen: keine Ziel-VPN verfuegbar.', 'warn');
            return;
        }
        const reportedVpn = normalizeVpnIp(document.getElementById('gwVpnReported').value || '');
        const reportedMatch = reportedVpn && reportedVpn === vpnIp;
        if (!reportedVpn && !reportedMatch) {
            statusEl.textContent = 'Fehlt';
            if (detailsEl) detailsEl.textContent = 'Gateway meldet keine VPN-IP';
            statusEl.title = 'Gateway reports no VPN IP';
            setRowState('rowVpnReach', 'bad');
            setRuntimeHint('Gateway meldet keine VPN-IP: WireGuard am Gateway pruefen (VPN IP + Private Key + Save/Apply).', 'warn');
        } else {
            statusEl.textContent = 'Pruefung...';
            if (detailsEl) detailsEl.textContent = reportedMatch ? 'Gateway meldet passende VPN-IP, Health-Pruefung laeuft' : 'Automatische Health-Pruefung laeuft';
            setRowState('rowVpnReach', 'na');
        }
        if (reportedMatch) {
            statusEl.title = 'Gateway reports matching VPN IP';
        }
        try {
            const res = await fetch('/api/network/gateway-health', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ vpn_ip: vpnIp })
            });
            const data = await res.json();
            const result = unwrap(data);
            if (!result.ok) {
                setOperatorHintForError(result.error);
                statusEl.textContent = 'Fehler';
                statusEl.title = result.error;
                if (detailsEl) detailsEl.textContent = result.error || 'VPN Health Check fehlgeschlagen';
                setRowState('rowVpnReach', 'bad');
                return;
            }
            const reachable = result.data && result.data.ok;
            const via = result.data && result.data.via ? ` | via ${result.data.via}` : '';
            statusEl.textContent = reachable ? 'OK' : 'Fehler';
            statusEl.title = (result.data && result.data.url ? `${result.data.url}${via}` : via).trim();
            if (detailsEl) detailsEl.textContent = reachable
                ? `Automatisch geprueft${via}`
                : `Health Check fehlgeschlagen${via}`;
            setRowState('rowVpnReach', reachable ? 'ok' : 'bad');
            if (!reachable) {
                setRuntimeHint('VPN Health Check fehlgeschlagen: Cloud API, Firewall oder VPN-Tunnel pruefen.', 'warn');
            } else {
                setRuntimeHint('', 'muted');
            }
        } catch (e) {
            statusEl.textContent = 'Fehler';
            statusEl.title = String(e);
            if (detailsEl) detailsEl.textContent = String(e);
            setRowState('rowVpnReach', 'bad');
            setOperatorHintForError(String(e));
        }
    }
export function applyDbMismatch(statusCellId, gatewayVal, dbVal) {
        const cell = document.getElementById(statusCellId);
        if (!cell) return;
        cell.classList.remove('db-mismatch');
        cell.title = '';
        if (!dbVal || !gatewayVal || String(gatewayVal) === String(dbVal)) {
            return;
        }
        cell.classList.add('db-mismatch');
        cell.title = `Gateway: ${gatewayVal} | DB: ${dbVal}`;
        if (!cell.textContent.includes('!')) {
            cell.textContent = `${cell.textContent} !`;
        }
    }
export function updateConfigStatus(matchEui, matchId, matchVpn) {
        const cfgGatewayIdState = document.getElementById('cfgGatewayIdState');
        const cfgVpnIpState = document.getElementById('cfgVpnIpState');
        const cfgVpnKeyState = document.getElementById('cfgVpnKeyState');
        const cfgWifiSsidState = document.getElementById('cfgWifiSsidState');
        const cfgApnState = document.getElementById('cfgApnState');
        if (cfgGatewayIdState) setStatusIcon('cfgGatewayIdState', matchId);
        if (cfgVpnIpState) setStatusIcon('cfgVpnIpState', matchVpn);
        if (cfgVpnKeyState) setStatusIcon('cfgVpnKeyState', null);
        if (cfgWifiSsidState) setStatusIcon('cfgWifiSsidState', null);
        if (cfgApnState) setStatusIcon('cfgApnState', null);
        setRowState('rowVpnKey', 'na');
        setRowState('rowApn', 'na');
    }
export async function copyText(text, label) {
        if (!text) {
            log(`!! Nichts zu kopieren (${label})`, 'error');
            return;
        }
        try {
            await navigator.clipboard.writeText(text);
            log(`.. Copied: ${label}`, 'success');
        } catch (e) {
            log(`!! Copy fehlgeschlagen (${label}): ${e}`, 'error');
        }
    }
export async function copyAndOpen(text, label, url) {
        await copyText(text, label);
        if (!url) return;
        window.open(url, '_blank', 'noopener');
    }
export function copyField(fieldId) {
        const value = document.getElementById(fieldId).value;
        copyText(value, fieldId);
    }
export function copyVpnCidr() {
        const ip = document.getElementById('vpnIp').value;
        copyText(formatVpnCidr(ip), 'vpn_ip/32');
    }
export async function applyVpnIp() {
        const ip = document.getElementById('vpnIp').value;
        if (!ip) {
            alert('Bitte eine VPN IP eingeben.');
            return;
        }
        const gateway = state.observed.gateway || {};
        const lora = state.observed.lora || {};
        const currentEui =
            lora.gatewayEui ||
            gateway.eui ||
            document.getElementById('gwEui').value ||
            document.getElementById('loraGatewayEui').value ||
            getText('statusGatewayEui') ||
            '';
        const dbResult = await DatabaseAdapter.fetch(ip, '', '');
        if (dbResult.ok && dbResult.data) {
            const dbEui = dbResult.data.eui || '';
            const dbStatus = dbResult.data.status_overall || '';
            const currentEuiValid = isValidEui(currentEui);
            const dbEuiValid = isValidEui(dbEui);
            if (dbEuiValid && currentEuiValid && dbEui.toUpperCase() !== currentEui.toUpperCase()) {
                alert(`VPN IP ist bereits einem anderen Gateway zugeordnet.\nDB EUI: ${dbEui}\nAktuelles Gateway EUI: ${currentEui}`);
                log(`!! Apply abgebrochen: VPN IP ${ip} gehoert zu EUI ${dbEui} (aktuelles ${currentEui})`, 'error');
                return;
            }
            if (dbStatus === 'DEPLOYED' && (!currentEuiValid || (dbEuiValid && dbEui.toUpperCase() !== currentEui.toUpperCase()))) {
                alert(`VPN IP ist bereits DEPLOYED und kann nicht zugeordnet werden.\nStatus: ${dbStatus}\nDB EUI: ${dbEui || '-'}\nAktuelles Gateway EUI: ${currentEui || '-'}`);
                log(`!! Apply abgebrochen: VPN IP ${ip} ist DEPLOYED (DB EUI ${dbEui || '-'}, aktuelles ${currentEui || '-'})`, 'error');
                return;
            }
        }
        vars.manualVpnTarget = ip;
        await fetchVpnKeyForGateway(ip);
        await loadDbForGateway(ip, document.getElementById('gwEui').value || '', '');
        updateConfigTargets();
        syncDesiredState();
        updateGatewayStatus();
        checkVpnReachability();
        invalidateFinalCheck();
        checkReady();
    }
export async function saveCustomerData() {
        const ip = document.getElementById('vpnIp').value;
        const name = document.getElementById('gwName').value;
        const sn = document.getElementById('gwSn').value;
        const simIccid = document.getElementById('simIccid').value;
        const simVendorId = document.getElementById('simVendor').value;
        const simCardId = document.getElementById('simCardId').value;

        if (!ip) {
            alert('Bitte eine VPN IP setzen.');
            return;
        }
        if (!name && !sn && !simIccid) {
            alert('Bitte mindestens Name, Serial oder SIM ICCID eingeben.');
            return;
        }

        log('.. Speichere Kundendaten in DB...');
        try {
            const res = await fetch('/api/db/customer-update', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    vpn_ip: ip,
                    gateway_name: name,
                    serial_number: sn,
                    sim_iccid: simIccid,
                    sim_vendor_id: simVendorId,
                    sim_card_id: simCardId
                })
            });
            const data = await res.json();
            const result = unwrap(data);
            if (!result.ok) {
                log('!! Kundendaten speichern fehlgeschlagen: ' + result.error, 'error');
                return;
            }
            if (result.data.sim_card_id) {
                document.getElementById('simCardId').value = result.data.sim_card_id;
            }
            // If we have a sim_id string (inventory ID), store it too
            if (result.data.sim_id) {
                const simInventoryId = document.getElementById('simInventoryId');
                if (simInventoryId) simInventoryId.value = result.data.sim_id;
            }
            
            log('.. Kundendaten gespeichert.', 'success');
        } catch (e) {
            log('!! Fehler beim Speichern der Kundendaten: ' + e, 'error');
        }
    }
export async function fetchSimVendors() {
        try {
            const res = await fetch('/api/sim/vendors');
            const data = await res.json();
            const result = unwrap(data);
            if (!result.ok) {
                log('!! SIM Vendor Fehler: ' + result.error, 'error');
                return;
            }
            vars.simVendors = Array.isArray(result.data.vendors) ? result.data.vendors : [];
            const select = document.getElementById('simVendor');
            select.innerHTML = '<option value="">Bitte waehlen</option>';
            vars.simVendors.forEach(vendor => {
                const option = document.createElement('option');
                option.value = vendor.id;
                option.textContent = vendor.name;
                select.appendChild(option);
            });
        } catch (e) {
            log('!! SIM Vendor Fehler: ' + e, 'error');
        }
    }
export function handleSimVendorChange() {
        const simCardId = document.getElementById('simCardId');
        simCardId.value = '';
        updateConfigTargets();
        syncDesiredState();
        updateGatewayStatus();
        invalidateFinalCheck();
        checkReady();
    }
export async function fetchNextSim() {
        const vendorId = document.getElementById('simVendor').value;
        if (!vendorId) {
            alert('Bitte zuerst einen SIM Vendor auswaehlen.');
            return;
        }
        try {
            const res = await fetch('/api/sim/next', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ vendor_id: vendorId })
            });
            const data = await res.json();
            const result = unwrap(data);
            if (!result.ok) {
                log('!! SIM Auswahl fehlgeschlagen: ' + result.error, 'error');
                return;
            }
            document.getElementById('simIccid').value = result.data.iccid || '';
            document.getElementById('simCardId').value = result.data.id || '';
            
            const simInventoryId = document.getElementById('simInventoryId');
            if (simInventoryId) simInventoryId.value = result.data.sim_id || '';
            
            updateConfigTargets();
            syncDesiredState();
            invalidateFinalCheck();
            checkReady();
            log('.. SIM ICCID geladen.', 'success');
        } catch (e) {
            log('!! SIM Auswahl fehlgeschlagen: ' + e, 'error');
        }
    }
export async function fetchIp() {
        const gatewayVpn = state.observed.gateway ? state.observed.gateway.vpn_ip : '';
        const gatewayId = state.observed.lora ? state.observed.lora.gatewayId : (state.observed.gateway ? state.observed.gateway.eui : '');
        if (gatewayVpn && String(gatewayId || '').toLowerCase() !== 'cafe') {
            log('.. Gateway VPN ist gesetzt. DB-IP nur manuell/optional.', 'info');
            return;
        }
        log('.. Verbinde mit Cloud-DB (Port 5432)...');
        try {
            const res = await fetch('/api/db/fetch-ip');
            const data = await res.json();
            const result = unwrap(data);

            if (!result.ok) {
                log('!! Fehler: ' + result.error, 'error');
            } else {
                vars.reservedVpnIp = result.data.vpn_ip || '';
                vars.reservedWifiSsid = deriveWifiSsid(vars.reservedVpnIp);
                vars.reservedVpnKey = result.data.private_key || '';

                document.getElementById('vpnIp').value = vars.reservedVpnIp;
                document.getElementById('vpnKey').value = vars.reservedVpnKey;
                vars.manualVpnTarget = vars.reservedVpnIp;
                updateConfigTargets();
                syncDesiredState();
                updateGatewayStatus();
                log('.. VPN IP gefunden: ' + result.data.vpn_ip, 'success');
                invalidateFinalCheck();
                checkReady();
            }
        } catch (e) {
            log('!! Netzwerkfehler beim Fetch: ' + e, 'error');
        }
    }
export async function fetchVpnKeyForGateway(vpnIp) {
        if (!vpnIp) return;
        try {
            const res = await fetch('/api/db/vpn-key', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ vpn_ip: vpnIp })
            });
            const data = await res.json();
            const result = unwrap(data);
            if (!result.ok) {
                log('!! VPN Key nicht gefunden: ' + result.error, 'error');
                return;
            }
            if (result.data.private_key) {
                document.getElementById('vpnKey').value = result.data.private_key;
            }
            if (result.data.serial_number && !document.getElementById('gwSn').value) {
                document.getElementById('gwSn').value = result.data.serial_number;
            }
            updateConfigTargets();
            syncDesiredState();
            updateGatewayStatus();
            invalidateFinalCheck();
            checkReady();
        } catch (e) {
            log('!! Fehler beim Laden des VPN Keys: ' + e, 'error');
        }
    }
export function refreshGatewayStatus(includeSecondary = false) {
        log('.. Hole Gateway Status...');
        runReadPipeline({ includeSecondary });
    }
export function toggleAutoRefresh(enabled, skipImmediate = false) {
    state.ui.autoRefreshEnabled = enabled;
    if (vars.gwAutoRefreshTimer) {
        clearInterval(vars.gwAutoRefreshTimer);
        vars.gwAutoRefreshTimer = null;
    }
    if (enabled && !state.ui.isEditing) {
        if (!skipImmediate) {
            refreshGatewayStatus(true);
        }
        vars.gwAutoRefreshTimer = setInterval(() => refreshGatewayStatus(true), 30000);
        log('.. Auto-Refresh aktiviert (30s).', 'success');
    } else if (!enabled) {
        log('.. Auto-Refresh deaktiviert.', 'info');
    }
    updateTopStatusBanner();
}

export function pauseAutoRefresh(reason = 'editing') {
    state.ui.isEditing = true;
    state.ui.editingReason = reason;
    if (vars.gwAutoRefreshTimer) {
        clearInterval(vars.gwAutoRefreshTimer);
        vars.gwAutoRefreshTimer = null;
    }
    updateTopStatusBanner();
}

export function resumeAutoRefresh() {
    state.ui.isEditing = false;
    state.ui.editingReason = null;
    if (state.ui.autoRefreshEnabled) {
        toggleAutoRefresh(true, true);
    } else {
        updateTopStatusBanner();
    }
}
export function invalidateFinalCheck() {
        vars.finalCheckOk = false;
        vars.lastFinalChecks = [];
        vars.lastProvisionSavedOk = false;
        vars.lastProvisionConfirmed = false;
        setBadge('badgeFinalCheck', 'Konfigurations Check: -', 'idle');
        renderFinalSummary();
        updateSectionStatuses();
        updateFinalizeActions();
    }
export function checkReady() {
        const ip = document.getElementById('vpnIp').value;
        const eui = document.getElementById('gwEui').value;
        const name = document.getElementById('gwName').value;
        const sn = document.getElementById('gwSn').value;
        const ready = ip && eui && name && sn;

        if (!state.readPhaseComplete || !ready) {
            invalidateFinalCheck();
        }
        updateSectionStatuses();
        updateFinalizeActions();
    }
export async function pushData() {
        const ipInput = document.getElementById('vpnIp').value;
        const ip = normalizeVpnIp(vars.manualVpnTarget || ipInput);
        const gateway = state.observed.gateway || {};
        const loraInfo = state.observed.lora || {};
        const interfaces = gateway.interfaces || {};
        const wifiInterface = interfaces.wlan0 || interfaces.wifi0 || {};
        const cellular = interfaces.cellular0 || interfaces.cellular || {};
        const mac = gateway.mac || document.getElementById('gwMac').value;
        const derivedEui = deriveEuiFromMac(mac);
        const eui = gateway.eui || document.getElementById('gwEui').value || getText('targetGatewayEui') || derivedEui;
        const sn = document.getElementById('gwSn').value;
        const name = document.getElementById('gwName').value;
        const simIccid = document.getElementById('simIccid').value;
        const simVendorId = document.getElementById('simVendor').value;
        const simCardId = document.getElementById('simCardId').value;
        const wifiSsid = gateway.wifi_ssid || document.getElementById('gwWifiSsid').value || document.getElementById('targetWifiSsid').textContent || deriveWifiSsid(ip);
        const wifiIp = wifiInterface.ip || document.getElementById('gwWifiIp').value || '';
        const vendor = vars.simVendors.find(item => String(item.id) === String(simVendorId));
        const apn = vendor ? vendor.apn : (document.getElementById('cfgApn').textContent || '');
        const cellularOnline = gateway.cellular_online;
        const lteConnected = cellularOnline === undefined ? !!cellular.up : (cellularOnline || !!cellular.up);
        const cellularStatus = cellular.up === undefined ? (lteConnected ? 'up' : 'down') : (cellular.up ? 'up' : 'down');
        const cellularIp = cellular.ip || document.getElementById('gwCellularIp').value || '';
        const vpnKeyPresent = document.getElementById('vpnKey').value ? true : false;
        const loraGatewayEui = loraInfo.gatewayEui || document.getElementById('loraGatewayEui').value;
        const loraGatewayId = loraInfo.gatewayId || document.getElementById('loraGatewayId').value;
        const loraActiveServer = getLoraActiveServer(loraInfo) || document.getElementById('loraActiveServer').value;
        const loraStatus = loraInfo.status ?? document.getElementById('loraStatus').value;
        const loraPending = loraInfo.pendingData ?? document.getElementById('loraPending').value;
        const milesightInfo = state.observed.milesight || {};
        const gatewayVendor = milesightInfo.exists ? 'Milesight' : '';
        const gatewayModel = milesightInfo.model || '';

        if (!state.readPhaseComplete) {
            alert("Bitte zuerst den Gateway Status lesen.");
            return;
        }

        const gatewayVpnIp = normalizeVpnIp(gateway.vpn_ip || document.getElementById('gwVpnReported').value || '');
        if (!gatewayVpnIp || !ip || gatewayVpnIp !== ip) {
            alert(`VPN IP stimmt nicht. Gateway: ${gatewayVpnIp || '-'} | Eingabe: ${ip || '-'}`);
            log(`!! Abbruch: VPN IP stimmt nicht (Gateway ${gatewayVpnIp || '-'} vs Eingabe ${ip || '-'})`, 'error');
            return;
        }

        if (!name || !sn) {
            alert("Bitte geben Sie einen Gateway Namen und die Serial Number ein!");
            return;
        }
        if (isKnownGatewayPendingAcknowledgement()) {
            alert("Dieser Gateway ist in der DB bereits bekannt. Bitte den Hinweis zuerst bestaetigen.");
            return;
        }
        if (!vars.finalCheckOk) {
            alert("Bitte zuerst Schritt 4 Pruefung & Integrationen erfolgreich abschliessen.");
            return;
        }

        if (!confirm(`Soll Gateway '${name}' mit IP ${ip} in der Cloud DB gespeichert werden?`)) return;

        const payloadPreview = {
            vpn_ip: ip,
            eui: eui,
            serial_number: sn,
            gateway_name: name,
            sim_iccid: simIccid,
            sim_vendor_id: simVendorId,
            sim_card_id: simCardId,
            wifi_ssid: wifiSsid,
            wifi_ip: wifiIp,
            apn: apn,
            cellular_status: cellularStatus,
            lte_connected: !!lteConnected,
            cellular_ip: cellularIp,
            vpn_key_present: vpnKeyPresent,
            gateway_vendor: gatewayVendor,
            gateway_model: gatewayModel,
            lora_gateway_eui: loraGatewayEui,
            lora_gateway_id: loraGatewayId,
            lora_active_server: loraActiveServer,
            lora_status: loraStatus,
            lora_pending: loraPending,
            final_check_ok: vars.finalCheckOk
        };

        log('.. Provisioning Payload: ' + JSON.stringify(payloadPreview), 'info');

        log('.. Speichere Daten in Cloud-Datenbank...');
        document.getElementById('btnPush').disabled = true;

        try {
            const res = await fetch('/api/provision', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payloadPreview)
            });
            let data = null;
            try {
                data = await res.json();
            } catch (e) {
                const text = await res.text();
                log(`!! Provisioning Fehler (HTTP ${res.status}): ${text || 'Antwort nicht lesbar'}`, 'error');
                document.getElementById('btnPush').disabled = false;
                updateFinalizeActions();
                return;
            }

            const result = unwrap(data);
            if (!result.ok) {
                const missing = result.data && result.data.missing ? result.data.missing.join(', ') : '';
                const suffix = missing ? ` (fehlend: ${missing})` : '';
                log('!! Provisioning Fehler: ' + formatDetailedError(result) + suffix, 'error');
                alert('Cloud DB speichern fehlgeschlagen: ' + (formatDetailedError(result) || result.error) + suffix);
                document.getElementById('btnPush').disabled = false;
            } else {
                vars.lastProvisionSavedOk = true;
                vars.lastProvisionConfirmed = false;
                log('.. Cloud DB erfolgreich aktualisiert.', 'success');
                alert("Cloud DB aktualisiert. Bitte jetzt final freigeben.");
            }
        } catch (e) {
            log('!! Kritischer Fehler beim Push: ' + e, 'error');
            document.getElementById('btnPush').disabled = false;
        } finally {
            updateFinalizeActions();
        }
    }
export async function confirmProvisioning() {
        const ip = normalizeVpnIp(vars.manualVpnTarget || document.getElementById('vpnIp')?.value || '');
        if (!vars.finalCheckOk) {
            alert('Finale Freigabe erst nach gruener Pruefung & Integrationen.');
            return;
        }
        if (isKnownGatewayPendingAcknowledgement()) {
            alert('Bitte zuerst bestaetigen, dass der bereits bekannte Gateway bewusst bearbeitet wird.');
            return;
        }
        if (!vars.lastProvisionSavedOk) {
            alert('Bitte zuerst in Cloud DB speichern.');
            return;
        }
        if (!ip) {
            alert('VPN IP fehlt.');
            return;
        }
        if (!confirm(`Soll Gateway ${ip} jetzt final freigegeben werden?`)) return;
        const confirmBtn = document.getElementById('btnConfirmProvision');
        if (confirmBtn) confirmBtn.disabled = true;
        try {
            const res = await fetch('/api/confirm', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ vpn_ip: ip })
            });
            const data = await res.json();
            const result = unwrap(data);
            if (!result.ok) {
                log('!! Finale Freigabe fehlgeschlagen: ' + formatDetailedError(result), 'error');
                alert('Finale Freigabe fehlgeschlagen: ' + (formatDetailedError(result) || result.error));
                return;
            }
            log('.. Gateway final freigegeben.', 'success');
            alert('Gateway wurde final als DEPLOYED freigegeben.');
            vars.lastProvisionConfirmed = true;
            if (state.observed.db) {
                state.observed.db.status_overall = 'DEPLOYED';
            }
        } catch (e) {
            log('!! Fehler bei finaler Freigabe: ' + e, 'error');
            alert('Finale Freigabe fehlgeschlagen: ' + e);
        } finally {
            updateFinalizeActions();
            updateSectionStatuses();
        }
    }
export async function dryRunChirpstack() {
        const eui = document.getElementById('gwEui').value;
        const sn = document.getElementById('gwSn').value;
        const name = document.getElementById('gwName').value;

        if (!eui || !sn || !name) {
            alert("Bitte EUI, Serial und Gateway Name setzen.");
            return;
        }

        log('.. ChirpStack Dry-Run (Payload im Log)...');

        try {
            const res = await fetch('/api/chirpstack/command', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    eui: eui,
                    serial_number: sn,
                    gateway_name: name
                })
            });
            const data = await res.json();
            const result = unwrap(data);

            if (!result.ok) {
                log('!! ChirpStack Dry-Run fehlgeschlagen: ' + result.error, 'error');
            } else {
                log('.. ChirpStack Dry-Run Payload: ' + JSON.stringify(result.data.payload || {}, null, 2), 'success');
            }
        } catch (e) {
            log('!! Fehler beim ChirpStack Dry-Run: ' + e, 'error');
        }
    }
export async function createChirpstackDevice() {
        const eui = document.getElementById('gwEui').value;
        const sn = document.getElementById('gwSn').value;
        const name = document.getElementById('gwName').value;

        if (!isValidEui(eui)) {
            alert('Ungueltige EUI (' + eui + ').');
            return;
        }
        if (!eui || !sn || !name) {
            alert("Bitte EUI, Serial und Gateway Name setzen.");
            return;
        }

        log('.. ChirpStack Gateway anlegen...');
        document.getElementById('btnChirpstackCreate').disabled = true;

        try {
            const res = await fetch('/api/chirpstack/create', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    eui: eui,
                    serial_number: sn,
                    gateway_name: name
                })
            });
            const data = await res.json();
            const result = unwrap(data);
            if (!result.ok) {
                log('!! ChirpStack Create fehlgeschlagen: ' + result.error, 'error');
                setServiceStatus('chirpstack', {
                    connected: false,
                    statusText: result.data && result.data.missing && result.data.missing.length ? 'Fehlt' : 'Fehler',
                    updatedAt: new Date().toISOString(),
                    error: result.error || 'error',
                    connectionText: 'API erreichbar',
                    detailText: result.error || 'Anlegen fehlgeschlagen'
                });
                return;
            }
            log('.. ChirpStack Gateway angelegt.', 'success');
            setServiceStatus('chirpstack', {
                connected: true,
                statusText: 'Angelegt',
                updatedAt: new Date().toISOString(),
                error: '-',
                connectionText: 'API erreichbar',
                detailText: 'Eintrag angelegt'
            });
            state.observed.chirpstack = { exists: true };
            await checkChirpstackExists({ silent: true });
        } catch (e) {
            log('!! Fehler beim ChirpStack Create: ' + e, 'error');
            setServiceStatus('chirpstack', {
                connected: false,
                statusText: 'Fehler',
                updatedAt: new Date().toISOString(),
                error: String(e),
                connectionText: 'API nicht erreichbar',
                detailText: String(e)
            });
        } finally {
            document.getElementById('btnChirpstackCreate').disabled = false;
        }
    }
export async function checkChirpstackExists(options = {}) {
        const eui = document.getElementById('gwEui').value;
        if (!eui) {
            if (!options.silent) {
                alert("Bitte EUI setzen.");
            }
            setServiceStatus('chirpstack', {
                connected: false,
                statusText: '-',
                updatedAt: new Date().toISOString(),
                error: 'EUI fehlt',
                connectionText: '',
                detailText: 'EUI fehlt'
            });
            state.observed.chirpstack = null;
            buildMismatchList();
            updateSectionStatuses();
            return;
        }

        log('.. Pruefe ChirpStack Gateway (EUI)...');
        document.getElementById('chirpstackStatus').textContent = 'Pruefung...';
        document.getElementById('btnChirpstackCreate').disabled = false;

        try {
            const res = await fetch('/api/chirpstack/check', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ eui: eui })
            });
            const data = await res.json();
            const result = unwrap(data);

            if (!result.ok) {
                log('!! ChirpStack Check fehlgeschlagen: ' + result.error, 'error');
                applyExternalExistenceStatus('chirpstack', {
                    error: result.error,
                    missing: result.data && result.data.missing ? result.data.missing : [],
                    observed: null,
                    connectedOverride: false
                });
            } else {
                applyExternalExistenceStatus('chirpstack', {
                    exists: !!result.data.exists,
                    observed: { exists: !!result.data.exists },
                    connectedOverride: true
                });
                log(result.data.exists ? '!! ChirpStack Gateway existiert bereits.' : '.. ChirpStack Gateway nicht gefunden.', result.data.exists ? 'error' : 'success');
            }
        } catch (e) {
            log('!! Fehler beim ChirpStack Check: ' + e, 'error');
            applyExternalExistenceStatus('chirpstack', {
                error: String(e),
                observed: null,
                connectedOverride: false
            });
        }
        buildMismatchList();
        updateSectionStatuses();
        scheduleFinalCheck();
    }
export async function checkChirpstackConfig() {
        try {
            const res = await fetch('/api/chirpstack/config');
            const data = await res.json();
            const result = unwrap(data);
            applyExternalConfigStatus('chirpstack', result);
        } catch (e) {
            applyExternalConfigStatus('chirpstack', { ok: false, error: String(e) });
        }
    }
export async function checkMilesightExists(options = {}) {
        const eui = document.getElementById('gwEui').value;
        if (!eui) {
            if (!options.silent) {
                alert("Bitte EUI setzen.");
            }
            setServiceStatus('milesight', {
                connected: false,
                statusText: '-',
                updatedAt: new Date().toISOString(),
                error: 'EUI fehlt',
                connectionText: '',
                detailText: 'EUI fehlt'
            });
            state.observed.milesight = null;
            buildMismatchList();
            updateSectionStatuses();
            return;
        }

        log('.. Pruefe Milesight Device (EUI)...');
        document.getElementById('milesightStatus').textContent = 'Pruefung...';
        document.getElementById('btnMilesightCreate').disabled = false;

        try {
            const res = await fetch('/api/milesight/check', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ eui: eui })
            });
            const data = await res.json();
            const result = unwrap(data);

            if (!result.ok) {
                log('!! Milesight Check fehlgeschlagen: ' + result.error, 'error');
                applyExternalExistenceStatus('milesight', {
                    error: result.error,
                    missing: result.data && result.data.missing ? result.data.missing : [],
                    observed: null,
                    connectedOverride: false
                });
            } else {
                if (result.data.exists) {
                    log('!! Milesight Device existiert bereits.', 'error');
                    applyExternalExistenceStatus('milesight', {
                        exists: true,
                        observed: { exists: true, name: result.data.name, model: result.data.model, details: result.data.details || {} },
                        tooltip: [result.data.name, result.data.model].filter(Boolean).join(' · '),
                        connectedOverride: true
                    });
                    if (vars.allowMilesightSerialFill && !document.getElementById('gwSn').value && result.data.serial_number) {
                        document.getElementById('gwSn').value = result.data.serial_number;
                    }
                    if (!document.getElementById('gwName').value && result.data.name) {
                        document.getElementById('gwName').value = result.data.name;
                    }
                    if (!document.getElementById('gwMac').value && result.data.details && result.data.details.mac) {
                        document.getElementById('gwMac').value = result.data.details.mac.toUpperCase();
                    }
                    syncDesiredState();
                    checkReady();
                } else {
                    log('.. Milesight Device nicht gefunden.', 'success');
                    applyExternalExistenceStatus('milesight', {
                        exists: false,
                        observed: { exists: false },
                        connectedOverride: true
                    });
                }
            }
        } catch (e) {
            log('!! Fehler beim Milesight Check: ' + e, 'error');
            applyExternalExistenceStatus('milesight', {
                error: String(e),
                observed: null,
                connectedOverride: false
            });
        }
        buildMismatchList();
        updateSectionStatuses();
        scheduleFinalCheck();
    }
export async function checkMilesightConfig() {
        try {
            const res = await fetch('/api/milesight/config');
            const data = await res.json();
            const result = unwrap(data);
            applyExternalConfigStatus('milesight', result);
        } catch (e) {
            applyExternalConfigStatus('milesight', { ok: false, error: String(e) });
        }
    }
export async function searchWebserviceByEui(eui) {
        const normalizedEui = normalizeHexId(eui);
        if (!normalizedEui || !getWebserviceCredentials()) return;
        log('.. Webservice: Suche nach EUI...', 'info');
        await syncWebserviceByEui({ eui: normalizedEui, populateCustomer: true });
    }
export async function checkWebserviceStatus() {
        log('.. Pruefe Webservice Status (EUI)...');
        await syncWebserviceByEui({ logMissingAsSuccess: true });
    }
export async function dryRunWebservice() {
        const wsResult = await syncWebserviceByEui({ logMissingAsSuccess: true });
        const wsState = state.observed.webservice;
        if (!wsResult.ok) return;
        if (wsState && !wsState.exists) {
            log('.. Webservice Dry-Run: Gateway wuerde angelegt werden.', 'success');
        } else if (wsState && wsState.exists) {
             log('!! Webservice Dry-Run: Gateway existiert bereits.', 'error');
        }
    }
export function printWebserviceCommand() {
        log('.. Webservice: API folgt.', 'info');
        document.getElementById('webserviceStatus').textContent = 'Webservice Status: API folgt';
        setServiceStatus('webservice', {
            connected: false,
            statusText: 'Webservice Status: API folgt',
            updatedAt: new Date().toISOString(),
            error: 'API folgt'
        });
    }
export function isValidEui(eui) {
    if (!eui) return false;
    const clean = eui.replace(/[^a-fA-F0-9]/g, '').toUpperCase();
    if (clean.length !== 16) return false;
    if (clean === '0000000000000000') return false;
    if (clean === 'FFFFFFFFFFFFFFFF') return false;
    if (clean === '000000FFFE000000') return false;
    return true;
}

export async function createWebserviceGateway() {
        const clientId = (document.getElementById('clientId')?.value || '').trim();
        const name = (document.getElementById('gwName')?.value || '').trim();
        const eui = normalizeHexId(document.getElementById('gwEui')?.value || '');
        const serialNumber = (document.getElementById('gwSn')?.value || '').trim();
        const simIccid = (document.getElementById('simIccid')?.value || '').trim();
        
        if (!isValidEui(eui)) {
            alert('Ungueltige EUI (' + eui + '). Bitte pruefen.');
            return;
        }
        
        // Try to get the string ID first (simInventoryId), then fallback to DB ID (simCardId)
        let simId = (document.getElementById('simInventoryId')?.value || '').trim();
        if (!simId) simId = (document.getElementById('simCardId')?.value || '').trim();
        
        // Get LNS Address
        const lnsAddress = (document.getElementById('loraActiveServer')?.value || '').trim();

        // Defaults / Inferred
        const lns = 2; // Chirpstack
        const manufacturer = 'Milesight';
        // Try to get model from Milesight state or default
        const model = (state.observed.milesight && state.observed.milesight.model) || 'UG65';
        
        if (!clientId || !name || !eui || !simIccid || !simId || !serialNumber) {
            alert('Bitte alle Felder prüfen: Client ID, Name, EUI, Serial, SIM ICCID, SIM ID sind pflicht. (ggf. "Zuordnung speichern" klicken)');
            return;
        }

        // Pre-check: Does it already exist?
        const wsResult = await syncWebserviceByEui({ logMissingAsSuccess: false });
        const wsState = state.observed.webservice;
        if (!wsResult.ok || !wsState) {
            log('!! Webservice Check fehlgeschlagen. Erstellung abgebrochen.', 'error');
            return;
        }
        if (wsState.exists) {
            log('.. Webservice: Gateway existiert bereits. Erstellung abgebrochen.', 'warn');
            alert('Gateway existiert bereits im Webservice.');
            return;
        }
        
        log('.. Erstelle Gateway im Webservice...', 'info');
        const statusEl = document.getElementById('webserviceStatus');
        if (statusEl) statusEl.textContent = 'creating...';
        
        const payload = {
            clientId,
            lns,
            lnsAddress,
            name,
            serialNumber,
            gatewayId: eui, // Using EUI as ID for consistency in Chirpstack/TTN
            gatewayEui: eui,
            simIccid,
            simId,
            manufacturer,
            type: model,
            active: true
        };

        const res = await webserviceRequest('/api/webservice/create-gateway', payload);
        
        if (!res.ok) {
            setOperatorHintForError(res.error);
            log('!! Webservice Create Failed: ' + res.error, 'error');
            if (statusEl) statusEl.textContent = 'error';
            setServiceStatus('webservice', {
                connected: false,
                statusText: 'Fehler',
                updatedAt: new Date().toISOString(),
                error: res.error,
                connectionText: 'API erreichbar',
                detailText: res.error
            });
            return;
        }
        
        log('.. Webservice Gateway angelegt.', 'success');
        if (statusEl) statusEl.textContent = 'created';
        setServiceStatus('webservice', {
            connected: true,
            statusText: 'Angelegt',
            updatedAt: new Date().toISOString(),
            error: '-',
            connectionText: 'API erreichbar',
            detailText: 'Eintrag angelegt'
        });
        state.observed.webservice = { exists: true };
        
        // Reload list and verify with a short retry window because the webservice
        // may expose the new entry with a small delay.
        loadClientGateways(clientId);
        const verification = await verifyWebserviceCreation();
        if (verification.confirmed) {
            log('.. Webservice Gateway bestaetigt.', 'success');
        } else {
            log('.. Webservice Gateway angelegt, Nachpruefung noch ausstehend.', 'info');
            setServiceStatus('webservice', {
                connected: true,
                statusText: 'Angelegt',
                updatedAt: new Date().toISOString(),
                error: '-',
                connectionText: 'API erreichbar',
                detailText: 'Angelegt, Nachpruefung ausstehend'
            });
            setRowState('rowWebserviceService', 'na');
        }
    }
export async function printMilesightCommand() {
        const eui = document.getElementById('gwEui').value;
        const name = document.getElementById('gwName').value;
        if (!isValidEui(eui)) {
            alert('Ungueltige EUI (' + eui + ').');
            return;
        }
        if (!name) {
            alert("Bitte EUI und Gateway Name setzen.");
            return;
        }

        log('.. Erzeuge Milesight Kommandos (nur Terminal-Ausgabe)...');

        try {
            const res = await fetch('/api/milesight/command', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    eui: eui,
                    gateway_name: name
                })
            });
            const data = await res.json();
            const result = unwrap(data);

            if (!result.ok) {
                log('!! Milesight Kommando fehlgeschlagen: ' + result.error, 'error');
            } else {
                log('.. Milesight Kommandos ins Terminal geschrieben.', 'success');
                alert("Milesight Kommandos wurden ins Terminal geschrieben.");
            }
        } catch (e) {
            log('!! Fehler beim Milesight Kommando: ' + e, 'error');
        }
    }
export async function createMilesightDevice() {
        const eui = document.getElementById('gwEui').value;
        const name = document.getElementById('gwName').value;
        const sn = document.getElementById('gwSn').value;
        
        if (!isValidEui(eui)) {
            alert('Ungueltige EUI (' + eui + ').');
            return;
        }
        if (!name || (!sn && !eui)) {
            alert("Bitte Name und Serial (oder EUI) setzen.");
            return;
        }

        log('.. Milesight Device anlegen...');
        document.getElementById('btnMilesightCreate').disabled = true;

        try {
            const res = await fetch('/api/milesight/create', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    eui: eui,
                    serial_number: sn,
                    gateway_name: name
                })
            });
            const data = await res.json();
            const result = unwrap(data);
            if (!result.ok) {
                log('!! Milesight Create fehlgeschlagen: ' + result.error, 'error');
                setServiceStatus('milesight', {
                    connected: false,
                    statusText: result.data && result.data.missing && result.data.missing.length ? 'Fehlt' : 'Fehler',
                    updatedAt: new Date().toISOString(),
                    error: result.error || 'error',
                    connectionText: 'API erreichbar',
                    detailText: result.error || 'Anlegen fehlgeschlagen'
                });
                return;
            }
            log('.. Milesight Device angelegt.', 'success');
            setServiceStatus('milesight', {
                connected: true,
                statusText: 'Angelegt',
                updatedAt: new Date().toISOString(),
                error: '-',
                connectionText: 'API erreichbar',
                detailText: 'Eintrag angelegt'
            });
            state.observed.milesight = { exists: true, details: result.data.data || {} };
            await checkMilesightExists({ silent: true });
        } catch (e) {
            log('!! Fehler beim Milesight Create: ' + e, 'error');
            setServiceStatus('milesight', {
                connected: false,
                statusText: 'Fehler',
                updatedAt: new Date().toISOString(),
                error: e.toString(),
                connectionText: 'API nicht erreichbar',
                detailText: e.toString()
            });
        } finally {
            document.getElementById('btnMilesightCreate').disabled = false;
        }
    }
export async function dryRunMilesightCreate() {
        const eui = document.getElementById('gwEui').value;
        const name = document.getElementById('gwName').value;
        if (!isValidEui(eui)) {
            alert('Ungueltige EUI (' + eui + ').');
            return;
        }
        if (!name) {
            alert("Bitte EUI und Gateway Name setzen.");
            return;
        }

        log('.. Milesight Dry-Run pruefen...');

        try {
            const res = await fetch('/api/milesight/dry-run', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    eui: eui,
                    gateway_name: name
                })
            });
            const data = await res.json();
            const result = unwrap(data);

            if (!result.ok) {
                log('!! Milesight Dry-Run fehlgeschlagen: ' + result.error, 'error');
                if (result.data && result.data.missing && result.data.missing.length) {
                    document.getElementById('milesightStatus').textContent =
                        'missing ' + result.data.missing.join(', ');
                }
            } else if (result.data.exists) {
                log('!! Milesight Dry-Run: Device existiert bereits.', 'error');
                document.getElementById('milesightStatus').textContent = 'exists';
            } else {
                log('.. Milesight Dry-Run: wuerde angelegt werden.', 'success');
                document.getElementById('milesightStatus').textContent = 'not found';
            }
            if (result.ok && result.data.create_payload) {
                log('.. Milesight Dry-Run Payload: ' + JSON.stringify(result.data.create_payload, null, 2), 'info');
            }
        } catch (e) {
            log('!! Fehler beim Milesight Dry-Run: ' + e, 'error');
        }
    }
export async function runFinalCheck() {
        if (!state.readPhaseComplete) {
            log('.. Gateway noch nicht gelesen. Starte Read...', 'info');
            await runReadPipeline({ includeSecondary: true });
            if (!state.readPhaseComplete) {
                log('!! Konfigurations Check abgebrochen: Gateway nicht gelesen.', 'error');
                setBadge('badgeFinalCheck', 'Konfigurations Check: nicht bereit', 'warn');
                return;
            }
        }
        await Promise.all([
            checkChirpstackConfig(),
            checkMilesightConfig()
        ]);
        await Promise.all([
            checkChirpstackExists({ silent: true }),
            checkMilesightExists({ silent: true })
        ]);
        await syncWebserviceByEui({ logMissingAsSuccess: false });
        const checks = collectReadinessChecks();

        const failed = checks.filter(c => !c.ok);
        const summary = failed.length === 0 ? 'OK' : `WARN (${failed.length})`;
        vars.finalCheckOk = failed.length === 0;
        vars.lastFinalChecks = checks;
        setBadge('badgeFinalCheck', `Konfigurations Check: ${summary}`, vars.finalCheckOk ? 'ok' : 'warn');
        renderFinalSummary();
        log('.. Konfigurations Check gestartet: ' + summary, failed.length === 0 ? 'success' : 'error');
        updateSectionStatuses();
        updateFinalizeActions();
    }

export function updateSectionStatuses() {
        const connected = state.statuses.gateway && state.statuses.gateway.connected;
        setStepStatus('connection', connected ? 'ok' : 'warn', connected ? 'Gateway verbunden' : 'Gateway nicht verbunden');

        const name = document.getElementById('gwName').value;
        const sn = document.getElementById('gwSn').value;
        const vpnIp = document.getElementById('vpnIp').value;
        const clientId = document.getElementById('clientId')?.value || '';
        const hasCustomerInfo = !!clientId;
        setStepStatus('customer', 'ok', hasCustomerInfo ? 'Kundendaten erfasst' : 'Optional');

        const gatewayDataOk = !!(name && vpnIp);
        setStepStatus('gateway-data', gatewayDataOk ? 'ok' : 'warn', gatewayDataOk ? 'Gateway-Daten vollständig' : 'Gateway-Daten fehlen');

        const configOk = !!state.readPhaseComplete;
        setStepStatus('config', configOk ? 'ok' : 'warn', configOk ? 'Gateway gelesen' : 'Gateway Status fehlt');

        const readinessChecks = collectReadinessChecks();
        const gatewayChecks = readinessChecks.filter(item =>
            item.label.startsWith('Gateway ') ||
            item.label.startsWith('VPN-') ||
            item.label.startsWith('WiFi-') ||
            item.label.startsWith('SIM-') ||
            item.label.startsWith('LoRa ')
        );
        const externalChecks = readinessChecks.filter(item =>
            item.label.startsWith('ChirpStack ') ||
            item.label.startsWith('Milesight ') ||
            item.label.startsWith('Webservice ')
        );
        const inspectionChecks = gatewayChecks.concat(externalChecks);
        const inspectionOpen = inspectionChecks.filter(item => !item.ok).length;
        setStepStatus('inspection', inspectionOpen === 0 ? 'ok' : 'warn', inspectionOpen === 0 ? 'Gateway und Integrationen ok' : `${inspectionOpen} Punkt(e) offen`);

        const finalStepReady = vars.lastProvisionConfirmed;
        const finalStepState = finalStepReady ? 'ok' : 'warn';
        const finalStepText = finalStepReady
            ? 'Final freigegeben'
            : (vars.finalCheckOk
                ? (vars.lastProvisionSavedOk ? 'Bereit fuer finale Freigabe' : 'Cloud DB noch nicht gespeichert')
                : 'Final Check ausstehend');
        setStepStatus('final', finalStepState, finalStepText);
    }
export function handleEuiChange() {
        const eui = document.getElementById('gwEui').value;
        if (!eui || eui === vars.lastCheckedEui) {
            return;
        }
        vars.lastCheckedEui = eui;
        vars.allowMilesightSerialFill = true;
        invalidateFinalCheck();
        checkChirpstackExists();
        if (eui !== vars.lastMilesightCheckedEui) {
            vars.lastMilesightCheckedEui = eui;
            checkMilesightExists();
        }
        searchWebserviceByEui(eui);
    }
export async function openHelp(key) {
        const modalTitle = document.getElementById('helpModalTitle');
        const modalBody = document.getElementById('helpModalBody');
        modalTitle.textContent = 'Hilfe';
        modalBody.textContent = 'Lade...';

        try {
            const res = await fetch(`/static/help/${key}.md`);
            const md = await res.text();
            const parsed = parseHelpMarkdown(md);
            modalTitle.textContent = parsed.title || 'Hilfe';
            modalBody.innerHTML = parsed.body || 'Keine Hilfe verfuegbar.';
        } catch (e) {
            modalBody.textContent = 'Hilfe konnte nicht geladen werden.';
        }

        const modal = new bootstrap.Modal(document.getElementById('helpModal'));
        modal.show();
    }
export function parseHelpMarkdown(md) {
        const lines = md.split('\n');
        let title = '';
        let body = '';
        let inList = false;
        let inParagraph = false;
        let paragraphBuffer = [];

        const flushParagraph = () => {
            if (!paragraphBuffer.length) return;
            const text = paragraphBuffer.join(' ').trim();
            if (text) {
                body += `<p class="small text-muted">${text}</p>`;
            }
            paragraphBuffer = [];
            inParagraph = false;
        };

        lines.forEach(line => {
            const trimmed = line.trim();
            if (!trimmed) {
                flushParagraph();
                if (inList) {
                    body += '</ol>';
                    inList = false;
                }
                return;
            }
            if (trimmed.startsWith('# ')) {
                flushParagraph();
                if (inList) {
                    body += '</ol>';
                    inList = false;
                }
                title = trimmed.slice(2).trim();
                return;
            }
            if (trimmed.startsWith('## ')) {
                flushParagraph();
                if (inList) {
                    body += '</ol>';
                    inList = false;
                }
                body += `<h6>${trimmed.slice(3).trim()}</h6>`;
                return;
            }
            if (trimmed.startsWith('![')) {
                flushParagraph();
                if (inList) {
                    body += '</ol>';
                    inList = false;
                }
                const match = trimmed.match(/!\[(.*?)\]\((.*?)\)/);
                if (match) {
                    const alt = match[1];
                    const src = match[2];
                    body += `<div class="mb-3"><img src="/static/help/${src}" class="img-fluid border rounded" alt="${alt}"/></div>`;
                }
                return;
            }
            const orderedMatch = trimmed.match(/^(\d+)[.)]\s+(.*)/);
            if (orderedMatch) {
                flushParagraph();
                if (!inList) {
                    body += '<ol class="small text-muted mb-3">';
                    inList = true;
                }
                body += `<li value="${orderedMatch[1]}">${orderedMatch[2]}</li>`;
                return;
            }
            inParagraph = true;
            paragraphBuffer.push(trimmed);
        });

        flushParagraph();
        if (inList) {
            body += '</ol>';
        }

        return { title, body };
    }





    
