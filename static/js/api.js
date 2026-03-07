export async function fetchWithTimeout(url, options = {}, timeoutMs = 6000) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const res = await fetch(url, { ...options, signal: controller.signal });
        return res;
    } finally {
        clearTimeout(timeout);
    }
}

export async function safeJson(url, options = {}, timeoutMs = 6000) {
    const res = await fetchWithTimeout(url, options, timeoutMs);
    const data = await res.json();
    return { res, data };
}

export function unwrap(payload) {
    if (!payload || payload.ok !== true) {
        const message = payload && payload.error && payload.error.message ? payload.error.message : 'Unbekannter Fehler';
        return { ok: false, error: message, data: payload ? payload.data : null };
    }
    return { ok: true, data: payload.data };
}
