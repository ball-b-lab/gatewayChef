import { state } from './state.js';

export function log(msg, type='info') {
    const logDiv = document.getElementById('statusLog');
    const entry = document.createElement('div');
    entry.textContent = msg;
    if (type === 'error') entry.style.color = '#ff6b6b';
    if (type === 'success') entry.style.color = '#51cf66';
    logDiv.appendChild(entry);
    logDiv.scrollTop = logDiv.scrollHeight;
}

export function setGatewayBlocked(isBlocked, message, hint) {
    const overlay = document.getElementById('appBlocked');
    const hintEl = document.getElementById('blockedSsidHint');
    const errorEl = document.getElementById('gatewayConnectionError');
    overlay.style.display = isBlocked ? 'block' : 'none';
    if (hint) hintEl.textContent = hint;
    if (message) {
        errorEl.textContent = message;
        errorEl.style.display = 'block';
    } else {
        errorEl.textContent = '';
        errorEl.style.display = 'none';
    }
}

export function setHeadlineConnection(connected, ssid) {
    const badge = document.getElementById('gatewayConnectionState');
    const text = document.getElementById('gatewayConnectionHint');
    if (!badge || !text) return;
    badge.classList.remove('bg-secondary', 'bg-success', 'bg-danger', 'bg-warning', 'text-dark');
    if (connected === null) {
        badge.textContent = 'Pruefe...';
        badge.classList.add('bg-warning', 'text-dark');
    } else if (connected) {
        badge.textContent = 'Verbunden';
        badge.classList.add('bg-success');
    } else {
        badge.textContent = 'Nicht verbunden';
        badge.classList.add('bg-danger');
    }
    text.textContent = `SSID: ${ssid || '-'}`;
    text.classList.add('ssid-emphasis');
    setTooltip(text, 'Verbindung gilt als OK, wenn /api/gateway/device-info erreichbar ist. Gateway lesen startet den Read-Workflow (Device-Info → LoRa → Sekundärquellen).');
}

export function setConnectionState(connected, detail) {
    const badge = document.getElementById('gatewayConnectionState');
    const hint = document.getElementById('gatewayConnectionHint');
    badge.classList.remove('bg-secondary', 'bg-success', 'bg-danger', 'bg-warning', 'text-dark');
    hint.classList.remove('ssid-emphasis');
    if (connected === null) {
        badge.textContent = 'Pruefe...';
        badge.classList.add('bg-warning', 'text-dark');
    } else if (connected) {
        badge.textContent = 'Verbunden';
        badge.classList.add('bg-success');
    } else {
        badge.textContent = 'Nicht verbunden';
        badge.classList.add('bg-danger');
    }
    hint.textContent = detail || 'Bitte mit dem Gateway-WLAN verbinden.';
    if (detail && detail.startsWith('SSID:')) {
        hint.classList.add('ssid-emphasis');
        setTooltip(hint, 'Verbindung gilt als OK, wenn /api/gateway/device-info erreichbar ist. Gateway lesen startet den Read-Workflow (Device-Info → LoRa → Sekundärquellen).');
    }
    const rawSsid = detail && detail.startsWith('SSID:') ? detail.replace('SSID:', '').trim() : '';
    const fallbackSsid = document.getElementById('gwWifiSsid')?.value || document.getElementById('statusWifiSsid')?.textContent || '';
    if (rawSsid || fallbackSsid) {
        setHeadlineConnection(connected, rawSsid || fallbackSsid || '-');
    }
    updateTopStatusBanner();
}

export function formatTimestamp(date) {
    if (!date) return '-';
    return new Date(date).toLocaleString('de-DE');
}

export function setBadge(el, text, stateName) {
    const badge = document.getElementById(el);
    badge.textContent = text;
    badge.classList.remove('bg-secondary', 'bg-success', 'bg-danger', 'bg-warning', 'text-dark');
    if (stateName === 'ok') {
        badge.classList.add('bg-success');
    } else if (stateName === 'warn') {
        badge.classList.add('bg-warning', 'text-dark');
    } else if (stateName === 'error') {
        badge.classList.add('bg-danger');
    } else {
        badge.classList.add('bg-secondary');
    }
}

export function setServiceStatus(serviceKey, payload) {
    const config = {
        chirpstack: {
            conn: 'serviceConnChirpstack',
            status: 'chirpstackStatus',
            updated: 'serviceUpdatedChirpstack'
        },
        milesight: {
            conn: 'serviceConnMilesight',
            status: 'milesightStatus',
            updated: 'serviceUpdatedMilesight'
        },
        webservice: {
            conn: 'serviceConnWebservice',
            status: 'webserviceStatus',
            updated: 'serviceUpdatedWebservice'
        }
    };
    const target = config[serviceKey];
    if (!target) return;
    const connected = payload.connected;
    const statusText = payload.statusText || '-';
    const errorText = payload.error || '-';
    const updatedAt = payload.updatedAt || null;
    document.getElementById(target.conn).textContent = connected ? 'Connected' : 'Not connected';
    const combined = (errorText && errorText !== '-' && errorText !== 'none')
        ? `${statusText} | ${errorText}`
        : statusText;
    document.getElementById(target.status).textContent = combined;
    document.getElementById(target.updated).textContent = formatTimestamp(updatedAt);
    if (payload.tooltip) {
        document.getElementById(target.status).title = payload.tooltip;
    } else {
        document.getElementById(target.status).title = '';
    }
    if (state.statuses[serviceKey]) {
        state.statuses[serviceKey] = {
            connected: !!connected,
            updatedAt: updatedAt,
            error: errorText === '-' ? null : errorText
        };
    }
}

export function renderMismatchList(items) {
    const list = document.getElementById('mismatchList');
    list.innerHTML = '';
    if (!items.length) {
        const li = document.createElement('li');
        li.textContent = 'Keine Abweichungen gefunden.';
        list.appendChild(li);
        return;
    }
    items.forEach(item => {
        const li = document.createElement('li');
        li.textContent = item.text;
        list.appendChild(li);
    });
}

export function setMatchStyle(el, isMatch) {
    const node = document.getElementById(el);
    if (!node) return;
    node.classList.toggle('match', !!isMatch);
}

export function setText(id, value) {
    const node = document.getElementById(id);
    if (!node) return;
    node.textContent = value || '-';
}

export function getText(id) {
    const node = document.getElementById(id);
    return node ? node.textContent : '';
}

export function setValue(id, value) {
    const node = document.getElementById(id);
    if (!node) return;
    node.value = value ?? '';
}

export function setStatusIcon(el, ok) {
    const node = document.getElementById(el);
    if (!node) return;
    node.classList.remove('text-success', 'text-danger', 'text-muted');
    if (ok === null) {
        node.textContent = 'N/A';
        node.classList.add('text-muted');
        return;
    }
    node.textContent = ok ? 'OK' : 'NO';
    node.classList.add(ok ? 'text-success' : 'text-danger');
}

export function setRowState(rowId, stateName) {
    const row = document.getElementById(rowId);
    if (!row) return;
    row.classList.remove('row-ok', 'row-bad', 'row-na');
    if (stateName === 'ok') row.classList.add('row-ok');
    if (stateName === 'bad') row.classList.add('row-bad');
    if (stateName === 'na') row.classList.add('row-na');
}

export function setTooltip(el, title) {
    if (!el) return;
    el.setAttribute('title', title || '');
    el.setAttribute('data-bs-toggle', 'tooltip');
    el.setAttribute('data-bs-placement', 'top');
    if (window.bootstrap && window.bootstrap.Tooltip) {
        refreshTooltips();
    }
}

export function refreshTooltips() {
    const nodes = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    nodes.forEach(node => {
        const instance = bootstrap.Tooltip.getInstance(node);
        if (instance) {
            instance.dispose();
        }
        new bootstrap.Tooltip(node);
    });
}

export function updateTopStatusBanner() {
    const banner = document.getElementById('appStatusInfo');
    if (!banner) return;
    const gateway = state.statuses.gateway || {};
    const editing = state.ui.isEditing;
    const autoRefresh = state.ui.autoRefreshEnabled;
    let text = gateway.connected ? 'Gateway verbunden.' : 'Gateway nicht verbunden.';
    if (editing) {
        text += ' Auto-Refresh pausiert (Eingabe aktiv).';
    } else if (autoRefresh) {
        text += ' Auto-Refresh aktiv.';
    } else {
        text += ' Auto-Refresh aus.';
    }
    if (gateway.updatedAt) {
        text += ` Letztes Update: ${formatTimestamp(gateway.updatedAt)}.`;
    }
    banner.textContent = text;
}

export function setRuntimeHint(message, level = 'muted') {
    const node = document.getElementById('runtimeHintInfo');
    if (!node) return;
    node.classList.remove('text-muted', 'text-warning', 'text-danger', 'text-success');
    if (!message) {
        node.textContent = '';
        node.classList.add('text-muted');
        return;
    }
    if (level === 'error') {
        node.classList.add('text-danger');
    } else if (level === 'warn') {
        node.classList.add('text-warning');
    } else if (level === 'success') {
        node.classList.add('text-success');
    } else {
        node.classList.add('text-muted');
    }
    node.textContent = message;
}

export function setStepStatus(stepKey, stateName, text) {
    const badge = document.getElementById(`step-status-${stepKey}`);
    const status = document.getElementById(`section-status-${stepKey}`);
    if (status) {
        status.textContent = text || 'Status: -';
    }
    if (!badge) return;
    badge.textContent = stateName === 'ok' ? 'OK' : stateName === 'warn' ? 'WARN' : stateName === 'error' ? 'ERR' : '-';
    badge.classList.remove('bg-secondary', 'bg-success', 'bg-warning', 'bg-danger', 'text-dark');
    if (stateName === 'ok') {
        badge.classList.add('bg-success');
    } else if (stateName === 'warn') {
        badge.classList.add('bg-warning', 'text-dark');
    } else if (stateName === 'error') {
        badge.classList.add('bg-danger');
    } else {
        badge.classList.add('bg-secondary');
    }
}
