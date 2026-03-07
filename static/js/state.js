export const state = {
    readPhaseComplete: false,
    observed: {
        gateway: null,
        lora: null,
        milesight: null,
        chirpstack: null,
        db: null,
        webservice: null
    },
    desired: {},
    diff: [],
    statuses: {
        gateway: { connected: false, updatedAt: null, error: null },
        milesight: { connected: false, updatedAt: null, error: null },
        chirpstack: { connected: false, updatedAt: null, error: null },
        db: { connected: false, updatedAt: null, error: null }
    },
    ui: {
        autoRefreshEnabled: true,
        isEditing: false,
        editingReason: null
    }
};

export const vars = {
    reservedVpnIp: '',
    reservedVpnKey: '',
    reservedWifiSsid: '',
    finalCheckOk: false,
    lastFinalChecks: [],
    lastCheckedEui: '',
    lastMilesightCheckedEui: '',
    gwAutoRefreshTimer: null,
    simVendors: [],
    manualVpnTarget: '',
    manualNameEdited: false,
    allowMilesightSerialFill: true,
    lastVpnInput: '',
    lastGatewayVpnIp: '',
    clientSearchTimer: null,
    selectedClientId: '',
    selectedClientName: '',
    finalCheckTimer: null,
    lastFinalCheckSignature: ''
};
