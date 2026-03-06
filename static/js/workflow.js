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
    setStepStatus
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
                log(`!! Webservice Error (${path}): HTTP ${status || '?'} - ${unwrapped.error}`, 'error');
                return { ok: false, error: unwrapped.error, data: unwrapped.data, status };
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
        if (results) results.innerHTML = '';
        if (!query || query.length < 3) {
            if (status) status.textContent = 'Bitte mindestens 3 Zeichen eingeben.';
            return;
        }
        if (status) status.textContent = 'Suche...';
        const res = await webserviceRequest('/api/webservice/clientsearch', { query });
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
        }
    };
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
        updateGatewayStatus();
        checkVpnReachability();
        updateSectionStatuses();
        scheduleFinalCheck();
    }
export function applyGatewayState(deviceInfo, loraInfo) {
        if (!deviceInfo) return;
        const rawMac = deviceInfo.mac || '';
        const derivedEui = deriveEuiFromMac(rawMac);
        const rawEui = deviceInfo.eui || derivedEui || '';
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
        updateSerialStatus(deviceInfo.serial_number || deviceInfo.sn || document.getElementById('gwSn').value || '');
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
        const gatewayIdDisplay = (loraInfo && loraInfo.gatewayId) || rawEui || '';
        setText('statusGatewayEui', rawEui);
        setText('statusGatewayId', gatewayIdDisplay);
        setText('statusVpnReported', deviceInfo.vpn_ip);
        setText('statusWifiSsid', deviceInfo.wifi_ssid);
        if (statusGatewayEuiEl) setTooltip(statusGatewayEuiEl, 'Quelle: device-info-lora');
        if (statusGatewayIdEl) setTooltip(statusGatewayIdEl, 'Quelle: device-info-lora');
        if (statusVpnEl) setTooltip(statusVpnEl, 'Quelle: device-info');
        if (statusWifiEl) setTooltip(statusWifiEl, 'Quelle: device-info');
        const gatewayIdValue = (loraInfo && loraInfo.gatewayId) || deviceInfo.gatewayId || deviceInfo.eui || '';
        const isGolden = String(gatewayIdValue).toLowerCase() === 'cafe';
        if (isGolden) {
            document.getElementById('gatewayGoldenBadge').style.display = 'inline-block';
            if (!vars.manualVpnTarget) {
                if (deviceInfo.vpn_ip === '0.0.0.0') {
                    document.getElementById('vpnIp').value = '';
                } else if (deviceInfo.vpn_ip) {
                    document.getElementById('vpnIp').value = deviceInfo.vpn_ip;
                }
                log('.. Golden Device erkannt (Gateway ID cafe). Hole neue IP...', 'info');
                fetchIp();
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
        state.observed.db = dbResult.ok ? dbResult.data : null;
        if (dbResult.ok && dbResult.data) {
            const vendorSelect = document.getElementById('simVendor');
            if (dbResult.data.sim_vendor_id) {
                vendorSelect.value = String(dbResult.data.sim_vendor_id);
            }
            if (dbResult.data.sim_iccid) {
                document.getElementById('simIccid').value = dbResult.data.sim_iccid;
            }
            updateConfigTargets();
            syncDesiredState();
        }
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
        scheduleFinalCheck(1200);
    }
export function renderDesiredDiff() {
        const list = document.getElementById('desiredDiffList');
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
            const li = document.createElement('li');
            li.textContent = 'Gateway Status noch nicht gelesen.';
            list.appendChild(li);
            return;
        }

        if (!diffs.length) {
            const li = document.createElement('li');
            li.textContent = 'Keine Aenderungen.';
            list.appendChild(li);
            return;
        }

        diffs.forEach(entry => {
            const li = document.createElement('li');
            li.textContent = `${entry.label}: ${entry.current} -> ${entry.desired}`;
            list.appendChild(li);
        });
    }
export function renderFinalSummary() {
        const reasons = document.getElementById('finalCheckReasons');
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
        const customerName = document.getElementById('gwName').value || '-';
        const eui = document.getElementById('gwEui').value || '-';
        document.getElementById('serviceNameChirpstack').textContent = eui;
        document.getElementById('serviceNameMilesight').textContent = eui;
        document.getElementById('serviceNameWebservice').textContent = customerName;
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
        state.observed.db = dbResult.ok ? dbResult.data : null;
        if (dbResult.ok && dbResult.data) {
            const vendorSelect = document.getElementById('simVendor');
            if (dbResult.data.sim_vendor_id) {
                vendorSelect.value = String(dbResult.data.sim_vendor_id);
            } else {
                vendorSelect.value = '';
            }
            document.getElementById('simIccid').value = dbResult.data.sim_iccid || '';
            document.getElementById('simCardId').value = dbResult.data.sim_card_id || '';
            
            const simInvEl = document.getElementById('simInventoryId');
            if (simInvEl) simInvEl.value = dbResult.data.sim_id || '';
            
            document.getElementById('gwName').value = dbResult.data.gateway_name || '';
            document.getElementById('gwSn').value = dbResult.data.serial_number || '';
            updateSerialStatus(document.getElementById('gwSn').value);
        } else {
            document.getElementById('simVendor').value = '';
            document.getElementById('simIccid').value = '';
            document.getElementById('simCardId').value = '';
            const simInvEl = document.getElementById('simInventoryId');
            if (simInvEl) simInvEl.value = '';
            document.getElementById('gwName').value = '';
            document.getElementById('gwSn').value = '';
            updateSerialStatus('');
        }
        updateServiceNames();
        updateConfigTargets();
        syncDesiredState();
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
        state.observed.db = null;
        state.observed.chirpstack = null;
        state.observed.milesight = null;
        setBadge('badgeChirpstack', 'ChirpStack: -', 'idle');
        setBadge('badgeMilesight', 'Milesight: -', 'idle');
        setServiceStatus('chirpstack', { connected: false, statusText: 'ChirpStack Status: -', updatedAt: null, error: '-' });
        setServiceStatus('milesight', { connected: false, statusText: 'Milesight Status: -', updatedAt: null, error: '-' });
    }
export function updateGatewayStatus() {
        const gateway = state.observed.gateway || {};
        const lora = state.observed.lora || {};
        const currentEui = lora.gatewayEui || gateway.eui || document.getElementById('gwEui').value || document.getElementById('loraGatewayEui').value || getText('statusGatewayEui') || '';
        const currentId = lora.gatewayId || gateway.eui || document.getElementById('gwEui').value || document.getElementById('loraGatewayId').value || getText('statusGatewayId') || '';
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
        const targetEui = getText('targetGatewayEui');
        const targetId = getText('targetGatewayId');
        const targetVpn = getText('targetVpnIp');
        const targetWifiSsid = getText('targetWifiSsid');
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

        const matchEui = currentEui && currentEui === targetEui;
        const matchId = currentId && currentId === targetId;
        const matchVpn = currentVpn && currentVpn === targetVpn;
        const matchWifiSsid = currentWifiSsid && currentWifiSsid === targetWifiSsid;

        setMatchStyle('statusGatewayEui', matchEui);
        setMatchStyle('statusGatewayId', matchId);
        setMatchStyle('statusVpnReported', matchVpn);
        setMatchStyle('statusWifiSsid', matchWifiSsid);

        setStatusIcon('statusGatewayEuiState', matchEui);
        setStatusIcon('statusGatewayIdState', matchId);
        setStatusIcon('statusVpnReportedState', matchVpn);
        setStatusIcon('statusWifiSsidState', matchWifiSsid);
        setRowState('rowGatewayId', matchId ? 'ok' : 'bad');
        setRowState('rowVpnIp', matchVpn ? 'ok' : 'bad');
        setRowState('rowWifiSsid', matchWifiSsid ? 'ok' : 'bad');
        if (currentLteState) {
            setRowState('rowCellularStatus', currentLteState === 'connected' ? 'ok' : 'bad');
        } else {
            setRowState('rowCellularStatus', 'na');
        }

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
export async function checkVpnReachability() {
        const vpnIpRaw = document.getElementById('targetVpnIp').textContent;
        const vpnIp = normalizeVpnIp(vpnIpRaw);
        const statusEl = document.getElementById('statusVpnReach');
        if (!vpnIp || vpnIp === '-') {
            statusEl.textContent = '-';
            setRowState('rowVpnReach', 'na');
            return;
        }
        const reportedVpn = normalizeVpnIp(document.getElementById('gwVpnReported').value || '');
        const reportedMatch = reportedVpn && reportedVpn === vpnIp;
        if (!reportedVpn && !reportedMatch) {
            statusEl.textContent = 'disconnected';
            statusEl.title = 'Gateway reports no VPN IP';
            setRowState('rowVpnReach', 'bad');
        } else {
            statusEl.textContent = reportedMatch ? 'connected' : 'checking...';
        }
        if (reportedMatch) {
            statusEl.title = 'Gateway reports matching VPN IP';
            setRowState('rowVpnReach', 'ok');
        }
        try {
            const res = await fetch('/api/network/vpn-check', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ vpn_ip: vpnIp })
            });
            const data = await res.json();
            const result = unwrap(data);
            if (!result.ok) {
                if (!reportedMatch) {
                    statusEl.textContent = 'unknown';
                    statusEl.title = result.error;
                    setRowState('rowVpnReach', 'na');
                }
                return;
            }
            const reachable = result.data && result.data.ok;
            if (!reportedMatch) {
                statusEl.textContent = reachable ? 'connected' : 'disconnected';
                statusEl.title = (result.data && result.data.output) || '';
                setRowState('rowVpnReach', reachable ? 'ok' : 'bad');
            } else if (reachable) {
                statusEl.title = (result.data && result.data.output) || statusEl.title;
            }
        } catch (e) {
            if (!reportedMatch) {
                statusEl.textContent = 'unknown';
                statusEl.title = String(e);
                setRowState('rowVpnReach', 'na');
            }
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
        document.getElementById('finalCheckResult').textContent = 'Konfigurations Check: -';
        document.getElementById('btnPush').disabled = false;
        setBadge('badgeFinalCheck', 'Konfigurations Check: -', 'idle');
        renderFinalSummary();
        updateSectionStatuses();
    }
export function checkReady() {
        const ip = document.getElementById('vpnIp').value;
        const eui = document.getElementById('gwEui').value;
        const name = document.getElementById('gwName').value;
        const sn = document.getElementById('gwSn').value;
        const ready = ip && eui && name && sn;

        if (!state.readPhaseComplete || !ready) {
            invalidateFinalCheck();
            document.getElementById('btnPush').disabled = true;
        } else {
            document.getElementById('btnPush').disabled = false;
        }
        updateSectionStatuses();
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

        if (!confirm(`Soll Gateway '${name}' mit IP ${ip} provisioniert werden?`)) return;

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

        log('.. Sende Daten an Cloud-Datenbank...');
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
                return;
            }

            const result = unwrap(data);
            if (!result.ok) {
                const missing = result.data && result.data.missing ? result.data.missing.join(', ') : '';
                const suffix = missing ? ` (fehlend: ${missing})` : '';
                log('!! Provisioning Fehler: ' + result.error + suffix, 'error');
                alert('Provisioning fehlgeschlagen: ' + result.error + suffix);
                document.getElementById('btnPush').disabled = false;
            } else {
                log('.. Provisionierung erfolgreich abgeschlossen!', 'success');
                if (vars.finalCheckOk) {
                    alert("Erfolg! Das Gateway wurde provisioniert.");
                } else {
                    alert("Gespeichert. Achtung: Konfiguration ist noch nicht fertig.");
                    setBadge('badgeFinalCheck', 'Konfigurations Check: nicht fertig', 'warn');
                }
            }
        } catch (e) {
            log('!! Kritischer Fehler beim Push: ' + e, 'error');
            document.getElementById('btnPush').disabled = false;
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
                if (result.data && result.data.missing && result.data.missing.length) {
                    document.getElementById('chirpstackStatus').textContent =
                        'ChirpStack Status: missing ' + result.data.missing.join(', ');
                    setBadge('badgeChirpstack', 'ChirpStack: missing', 'error');
                } else {
                    document.getElementById('chirpstackStatus').textContent = 'ChirpStack Status: error';
                    setBadge('badgeChirpstack', 'ChirpStack: error', 'error');
                }
                setServiceStatus('chirpstack', {
                    connected: false,
                    statusText: 'ChirpStack Status: error',
                    updatedAt: new Date().toISOString(),
                    error: result.error || 'error'
                });
                return;
            }
            log('.. ChirpStack Gateway angelegt.', 'success');
            document.getElementById('chirpstackStatus').textContent = 'created';
            setBadge('badgeChirpstack', 'ChirpStack: created', 'ok');
            setServiceStatus('chirpstack', {
                connected: true,
                statusText: 'created',
                updatedAt: new Date().toISOString(),
                error: '-'
            });
            state.observed.chirpstack = { exists: true };
        } catch (e) {
            log('!! Fehler beim ChirpStack Create: ' + e, 'error');
            document.getElementById('chirpstackStatus').textContent = 'ChirpStack Status: error';
            setBadge('badgeChirpstack', 'ChirpStack: error', 'error');
            setServiceStatus('chirpstack', {
                connected: false,
                statusText: 'ChirpStack Status: error',
                updatedAt: new Date().toISOString(),
                error: String(e)
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
                statusText: 'ChirpStack Status: -',
                updatedAt: new Date().toISOString(),
                error: 'EUI fehlt'
            });
            state.observed.chirpstack = null;
            buildMismatchList();
            updateSectionStatuses();
            return;
        }

        log('.. Pruefe ChirpStack Gateway (EUI)...');
        document.getElementById('chirpstackStatus').textContent = 'ChirpStack Status: checking...';
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
                setServiceStatus('chirpstack', {
                    connected: false,
                    statusText: 'error',
                    updatedAt: new Date().toISOString(),
                    error: result.error
                });
                if (result.data && result.data.missing && result.data.missing.length) {
                    document.getElementById('chirpstackStatus').textContent =
                        'missing ' + result.data.missing.join(', ');
                    setBadge('badgeChirpstack', 'ChirpStack: missing', 'error');
                } else {
                    document.getElementById('chirpstackStatus').textContent = 'error';
                    setBadge('badgeChirpstack', 'ChirpStack: error', 'error');
                }
            } else {
                if (result.data.exists) {
                    log('!! ChirpStack Gateway existiert bereits.', 'error');
                    document.getElementById('chirpstackStatus').textContent = 'exists';
                    document.getElementById('btnChirpstackCreate').disabled = false;
                    setBadge('badgeChirpstack', 'ChirpStack: exists', 'ok');
                    setServiceStatus('chirpstack', {
                        connected: true,
                        statusText: 'exists',
                        updatedAt: new Date().toISOString(),
                        error: '-'
                    });
                    state.observed.chirpstack = { exists: true };
                } else {
                    log('.. ChirpStack Gateway nicht gefunden.', 'success');
                    document.getElementById('chirpstackStatus').textContent = 'not found';
                    document.getElementById('btnChirpstackCreate').disabled = false;
                    setBadge('badgeChirpstack', 'ChirpStack: not found', 'ok');
                    setServiceStatus('chirpstack', {
                        connected: true,
                        statusText: 'not found',
                        updatedAt: new Date().toISOString(),
                        error: '-'
                    });
                    state.observed.chirpstack = { exists: false };
                }
            }
        } catch (e) {
            log('!! Fehler beim ChirpStack Check: ' + e, 'error');
            document.getElementById('chirpstackStatus').textContent = 'ChirpStack Status: error';
            document.getElementById('btnChirpstackCreate').disabled = false;
            setBadge('badgeChirpstack', 'ChirpStack: error', 'error');
            setServiceStatus('chirpstack', {
                connected: false,
                statusText: 'ChirpStack Status: error',
                updatedAt: new Date().toISOString(),
                error: String(e)
            });
            state.observed.chirpstack = null;
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
            if (!result.ok) {
                document.getElementById('chirpstackStatus').textContent = 'ChirpStack Status: error';
                setBadge('badgeChirpstack', 'ChirpStack: error', 'error');
                setServiceStatus('chirpstack', {
                    connected: false,
                    statusText: 'ChirpStack Status: error',
                    updatedAt: new Date().toISOString(),
                    error: result.error
                });
                return;
            }
            if (!result.data.ready) {
                document.getElementById('chirpstackStatus').textContent =
                    'ChirpStack Status: missing ' + result.data.missing.join(', ');
                document.getElementById('btnChirpstackCreate').disabled = false;
                setBadge('badgeChirpstack', 'ChirpStack: missing', 'error');
                setServiceStatus('chirpstack', {
                    connected: false,
                    statusText: 'ChirpStack Status: missing',
                    updatedAt: new Date().toISOString(),
                    error: result.data.missing.join(', ')
                });
            }
        } catch (e) {
            document.getElementById('chirpstackStatus').textContent = 'ChirpStack Status: error';
            document.getElementById('btnChirpstackCreate').disabled = false;
            setBadge('badgeChirpstack', 'ChirpStack: error', 'error');
            setServiceStatus('chirpstack', {
                connected: false,
                statusText: 'ChirpStack Status: error',
                updatedAt: new Date().toISOString(),
                error: String(e)
            });
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
                statusText: 'Milesight Status: -',
                updatedAt: new Date().toISOString(),
                error: 'EUI fehlt'
            });
            state.observed.milesight = null;
            buildMismatchList();
            updateSectionStatuses();
            return;
        }

        log('.. Pruefe Milesight Device (EUI)...');
        document.getElementById('milesightStatus').textContent = 'Milesight Status: checking...';
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
                setServiceStatus('milesight', {
                    connected: false,
                    statusText: 'error',
                    updatedAt: new Date().toISOString(),
                    error: result.error
                });
                if (result.data && result.data.missing && result.data.missing.length) {
                    document.getElementById('milesightStatus').textContent =
                        'missing ' + result.data.missing.join(', ');
                    setBadge('badgeMilesight', 'Milesight: missing', 'error');
                } else {
                    document.getElementById('milesightStatus').textContent = 'error';
                    setBadge('badgeMilesight', 'Milesight: error', 'error');
                }
            } else {
                if (result.data.exists) {
                    log('!! Milesight Device existiert bereits.', 'error');
                    document.getElementById('milesightStatus').textContent = 'exists';
                    document.getElementById('btnMilesightCreate').disabled = false;
                    setBadge('badgeMilesight', 'Milesight: exists', 'ok');
                    setServiceStatus('milesight', {
                        connected: true,
                        statusText: 'exists',
                        updatedAt: new Date().toISOString(),
                        error: '-',
                        tooltip: [result.data.name, result.data.model].filter(Boolean).join(' · ')
                    });
                    state.observed.milesight = { exists: true, name: result.data.name, model: result.data.model, details: result.data.details || {} };
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
                    document.getElementById('milesightStatus').textContent = 'not found';
                    document.getElementById('btnMilesightCreate').disabled = false;
                    setBadge('badgeMilesight', 'Milesight: not found', 'ok');
                    setServiceStatus('milesight', {
                        connected: true,
                        statusText: 'not found',
                        updatedAt: new Date().toISOString(),
                        error: '-'
                    });
                    state.observed.milesight = { exists: false };
                }
            }
        } catch (e) {
            log('!! Fehler beim Milesight Check: ' + e, 'error');
            document.getElementById('milesightStatus').textContent = 'Milesight Status: error';
            document.getElementById('btnMilesightCreate').disabled = false;
            setBadge('badgeMilesight', 'Milesight: error', 'error');
            setServiceStatus('milesight', {
                connected: false,
                statusText: 'Milesight Status: error',
                updatedAt: new Date().toISOString(),
                error: String(e)
            });
            state.observed.milesight = null;
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
            if (!result.ok) {
                document.getElementById('milesightStatus').textContent = 'Milesight Status: error';
                setBadge('badgeMilesight', 'Milesight: error', 'error');
                setServiceStatus('milesight', {
                    connected: false,
                    statusText: 'Milesight Status: error',
                    updatedAt: new Date().toISOString(),
                    error: result.error
                });
                return;
            }
            if (!result.data.ready) {
                document.getElementById('milesightStatus').textContent =
                    'Milesight Status: missing ' + result.data.missing.join(', ');
                document.getElementById('btnMilesightCreate').disabled = false;
                setBadge('badgeMilesight', 'Milesight: missing', 'error');
                setServiceStatus('milesight', {
                    connected: false,
                    statusText: 'Milesight Status: missing',
                    updatedAt: new Date().toISOString(),
                    error: result.data.missing.join(', ')
                });
            }
        } catch (e) {
            document.getElementById('milesightStatus').textContent = 'Milesight Status: error';
            document.getElementById('btnMilesightCreate').disabled = false;
            setBadge('badgeMilesight', 'Milesight: error', 'error');
            setServiceStatus('milesight', {
                connected: false,
                statusText: 'Milesight Status: error',
                updatedAt: new Date().toISOString(),
                error: String(e)
            });
        }
    }
export async function searchWebserviceByEui(eui) {
        if (!eui) return;
        
        // Ensure credentials are present (simple check)
        const creds = getWebserviceCredentials();
        if (!creds) return; // Silent return if no login

        log('.. Webservice: Suche nach EUI...', 'info');
        const status = document.getElementById('webserviceStatus');
        if (status) status.textContent = 'Webservice: searching EUI...';

        const res = await webserviceRequest('/api/webservice/search-by-eui', { eui });
        if (!res.ok) {
            // It's common that it doesn't exist yet, so just info/warn
            // log('Webservice EUI Search failed: ' + res.error, 'warn');
            if (status) status.textContent = 'Webservice: EUI not found (or error)';
            return;
        }

        const list = normalizeList(res.data);
        if (!list.length) {
            if (status) status.textContent = 'Webservice: EUI not known';
            return;
        }

        // Find exact match if possible
        const match = list.find(g => (g.gatewayEui || g.gateway_eui || '').toLowerCase() === eui.toLowerCase()) || list[0];

        if (match) {
            const clientId = match.clientId || match.client_id;
            const clientName = match.clientName || match.customerName || match.customer_name || match.name;
            
            if (clientId) {
                log(`.. Webservice: Gateway gefunden. Setze Kunde ${clientId} (${clientName || '?'})`, 'success');
                if (status) status.textContent = 'Webservice: Client found';

                document.getElementById('clientId').value = clientId;
                vars.selectedClientId = clientId;
                if (clientName) {
                    vars.selectedClientName = clientName;
                    const clientSearch = document.getElementById('clientSearch');
                    if (clientSearch) clientSearch.value = clientName;
                }

                // Load gateways for this client
                loadClientGateways(clientId);
                updateSuggestedNameLabel();
                syncDesiredState();
                updateSectionStatuses();
            }
        }
    }
export async function checkWebserviceStatus() {
        const eui = document.getElementById('gwEui')?.value;
        if (!isValidEui(eui)) {
            setServiceStatus('webservice', {
                connected: false,
                statusText: 'Ungueltige EUI',
                updatedAt: new Date().toISOString(),
                error: 'Ungueltige EUI'
            });
            state.observed.webservice = null;
            updateSectionStatuses();
            return;
        }

        log('.. Pruefe Webservice Status (EUI)...');
        const statusEl = document.getElementById('webserviceStatus');
        if (statusEl) statusEl.textContent = 'Webservice: checking...';

        const res = await webserviceRequest('/api/webservice/search-by-eui', { eui });
        
        if (!res.ok) {
            setServiceStatus('webservice', {
                connected: false,
                statusText: 'error',
                updatedAt: new Date().toISOString(),
                error: res.error
            });
            state.observed.webservice = null;
            updateSectionStatuses();
            return;
        }

        const list = normalizeList(res.data);
        // Check exact match on EUI or Gateway ID (as fallback)
        const match = list.find(g => {
             const gEui = g.gatewayEui || g.gateway_eui || g.gatewayId || g.gateway_id || '';
             return gEui.toLowerCase() === eui.toLowerCase();
        });
        const exists = !!match;

        setServiceStatus('webservice', {
            connected: true,
            statusText: exists ? 'exists' : 'not found',
            updatedAt: new Date().toISOString(),
            error: '-'
        });
        
        if (statusEl) statusEl.textContent = exists ? 'exists' : 'not found';
        
        state.observed.webservice = { exists: exists };
        updateSectionStatuses();
        scheduleFinalCheck();
        
        if (exists) {
            log('.. Webservice: Gateway existiert bereits.', 'warn');
        } else {
            log('.. Webservice: Gateway nicht gefunden (bereit zum Anlegen).', 'success');
        }
    }
export async function dryRunWebservice() {
        // For now, dry run is just checking if it exists
        await checkWebserviceStatus();
        const wsState = state.observed.webservice;
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
        const clientId = document.getElementById('clientId')?.value;
        const name = document.getElementById('gwName')?.value;
        const eui = document.getElementById('gwEui')?.value;
        const serialNumber = document.getElementById('gwSn')?.value;
        const simIccid = document.getElementById('simIccid')?.value;
        
        if (!isValidEui(eui)) {
            alert('Ungueltige EUI (' + eui + '). Bitte pruefen.');
            return;
        }
        
        // Try to get the string ID first (simInventoryId), then fallback to DB ID (simCardId)
        let simId = document.getElementById('simInventoryId')?.value;
        if (!simId) simId = document.getElementById('simCardId')?.value;
        
        // Get LNS Address
        const lnsAddress = document.getElementById('loraActiveServer')?.value || '';

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
        await checkWebserviceStatus();
        const wsState = state.observed.webservice;
        if (!wsState) {
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
            log('!! Webservice Create Failed: ' + res.error, 'error');
            if (statusEl) statusEl.textContent = 'error';
            setServiceStatus('webservice', {
                connected: false,
                statusText: 'error',
                updatedAt: new Date().toISOString(),
                error: res.error
            });
            return;
        }
        
        log('.. Webservice Gateway angelegt.', 'success');
        if (statusEl) statusEl.textContent = 'created';
        setServiceStatus('webservice', {
            connected: true,
            statusText: 'created',
            updatedAt: new Date().toISOString(),
            error: '-'
        });
        state.observed.webservice = { exists: true };
        
        // Reload list to confirm
        loadClientGateways(clientId);
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
                if (result.data && result.data.missing && result.data.missing.length) {
                    document.getElementById('milesightStatus').textContent =
                        'missing ' + result.data.missing.join(', ');
                } else {
                    document.getElementById('milesightStatus').textContent = 'error';
                }
                setBadge('badgeMilesight', 'Milesight: error', 'error');
                setServiceStatus('milesight', {
                    connected: false,
                    statusText: 'error',
                    updatedAt: new Date().toISOString(),
                    error: result.error || 'error'
                });
                return;
            }
            log('.. Milesight Device angelegt.', 'success');
            document.getElementById('milesightStatus').textContent = 'created';
            setBadge('badgeMilesight', 'Milesight: created', 'ok');
            setServiceStatus('milesight', {
                connected: true,
                statusText: 'created',
                updatedAt: new Date().toISOString(),
                error: '-'
            });
            state.observed.milesight = { exists: true, details: result.data.data || {} };
        } catch (e) {
            log('!! Fehler beim Milesight Create: ' + e, 'error');
            document.getElementById('milesightStatus').textContent = 'error';
            setBadge('badgeMilesight', 'Milesight: error', 'error');
            setServiceStatus('milesight', {
                connected: false,
                statusText: 'error',
                updatedAt: new Date().toISOString(),
                error: e.toString()
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
                document.getElementById('finalCheckResult').textContent = 'Konfigurations Check: Gateway nicht gelesen';
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
        const name = document.getElementById('gwName').value;
        const sn = document.getElementById('gwSn').value;
        const eui = document.getElementById('gwEui').value;
        const vpnIp = document.getElementById('vpnIp').value;
        const vpnKey = document.getElementById('vpnKey').value;
        const targetWifiSsid = getText('targetWifiSsid');
        const currentWifiSsid = document.getElementById('gwWifiSsid').value;
        const simIccid = document.getElementById('simIccid').value;
        const simVendor = document.getElementById('simVendor').value;
        const chirpStatus = document.getElementById('chirpstackStatus').textContent;
        const milesightStatus = document.getElementById('milesightStatus').textContent;
        const gwVpnReported = document.getElementById('gwVpnReported').value;
        const loraGatewayEui = document.getElementById('loraGatewayEui').value;
        const loraGatewayId = document.getElementById('loraGatewayId').value;
        const targetGatewayEui = getText('targetGatewayEui');
        const targetGatewayId = getText('targetGatewayId');
        const targetVpnIp = getText('targetVpnIp');
        const loraActiveServer = document.getElementById('loraActiveServer').value;
        const loraStatus = document.getElementById('loraStatus').value;

        const checks = [
            { label: `Gateway gelesen: ${state.readPhaseComplete ? 'OK' : '-'}`, ok: state.readPhaseComplete },
            { label: `Gateway Name: ${name || '-'}`, ok: !!name },
            { label: `Serial Number: ${sn || '-'}`, ok: !!sn },
            { label: `EUI: ${eui || '-'}`, ok: !!eui },
            { label: `VPN IP: ${vpnIp || '-'}`, ok: !!vpnIp },
            { label: `VPN Key: ${vpnKey ? 'gesetzt' : '-'}`, ok: !!vpnKey },
            { label: `WiFi SSID: ${currentWifiSsid || '-'} (soll ${targetWifiSsid || '-'})`, ok: !!currentWifiSsid && currentWifiSsid === targetWifiSsid },
            { label: `SIM Vendor: ${simVendor || '-'}`, ok: !!simVendor },
            { label: `SIM ICCID: ${simIccid || '-'}`, ok: !!simIccid },
            { label: `Gateway VPN-IP reported: ${gwVpnReported || '-'} (soll ${targetVpnIp || '-'})`, ok: !!gwVpnReported && gwVpnReported === targetVpnIp },
            { label: `LoRa Gateway ID: ${loraGatewayId || '-'} (soll ${targetGatewayId || '-'})`, ok: !!loraGatewayId && loraGatewayId === targetGatewayId },
            { label: `LoRa Active Server: ${loraActiveServer || '-'}`, ok: !!loraActiveServer },
            { label: `LoRa Status: ${loraStatus || '-'}`, ok: String(loraStatus) === '1' },
            { label: `ChirpStack: ${chirpStatus}`, ok: chirpStatus.includes('not found') || chirpStatus.includes('exists') },
            { label: `Milesight: ${milesightStatus}`, ok: milesightStatus.includes('not found') || milesightStatus.includes('exists') }
        ];

        const failed = checks.filter(c => !c.ok);
        const summary = failed.length === 0 ? 'OK' : `WARN (${failed.length})`;
        vars.finalCheckOk = failed.length === 0;
        vars.lastFinalChecks = checks;
        document.getElementById('finalCheckResult').textContent = `Konfigurations Check: ${summary}`;
        document.getElementById('btnPush').disabled = false;

        setBadge('badgeFinalCheck', `Konfigurations Check: ${summary}`, vars.finalCheckOk ? 'ok' : 'warn');
        renderFinalSummary();
        log('.. Konfigurations Check gestartet: ' + summary, failed.length === 0 ? 'success' : 'error');
        updateSectionStatuses();
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

        const statusOk = !!state.readPhaseComplete;
        setStepStatus('gateway-status', statusOk ? 'ok' : 'warn', statusOk ? 'Status verfügbar' : 'Status fehlt');

        const chirp = state.observed.chirpstack;
        const mile = state.observed.milesight;
        const web = state.observed.webservice;
        const externalOk = !!(
            chirp && chirp.exists === true &&
            mile && mile.exists === true &&
            web && web.exists === true
        );
        setStepStatus('external', externalOk ? 'ok' : 'warn', externalOk ? 'Integrationen ok' : 'Integrationen fehlen');

        setStepStatus('final', vars.finalCheckOk ? 'ok' : 'warn', vars.finalCheckOk ? 'Final Check OK' : 'Final Check ausstehend');
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





    
