import { state, vars } from './state.js';
import { refreshTooltips, updateTopStatusBanner, setBadge, setServiceStatus } from './ui.js';
import {
    runReadPipeline,
    refreshGatewayStatus,
    toggleAutoRefresh,
    pauseAutoRefresh,
    resumeAutoRefresh,
    copyText,
    copyAndOpen,
    copyField,
    copyVpnCidr,
    formatVpnCidr,
    applyVpnIp,
    saveCustomerData,
    fetchSimVendors,
    handleSimVendorChange,
    fetchNextSim,
    fetchIp,
    fetchVpnKeyForGateway,
    pushData,
    dryRunChirpstack,
    createChirpstackDevice,
    checkChirpstackExists,
    checkChirpstackConfig,
    checkMilesightExists,
    checkMilesightConfig,
    checkWebserviceStatus,
    dryRunWebservice,
    printWebserviceCommand,
    createWebserviceGateway,
    printMilesightCommand,
    createMilesightDevice,
    dryRunMilesightCreate,
    runFinalCheck,
    handleEuiChange,
    openHelp,
    updateServiceNames,
    syncDesiredState,
    renderFinalSummary,
    updateGatewayStatus,
    updateConfigTargets,
    checkReady,
    invalidateFinalCheck,
    updateSectionStatuses,
    handleClientSearchInput,
    loadClientGateways,
    setSuggestedName,
    updateSuggestedNameLabel,
    setSerialNumberFromStatus,
    toggleSerialNumberEdit
} from './workflow.js';

// Expose handlers for inline onclick attributes
window.runReadPipeline = runReadPipeline;
window.refreshGatewayStatus = refreshGatewayStatus;
window.toggleAutoRefresh = toggleAutoRefresh;
window.copyText = copyText;
window.copyAndOpen = copyAndOpen;
window.copyField = copyField;
window.copyVpnCidr = copyVpnCidr;
window.formatVpnCidr = formatVpnCidr;
window.applyVpnIp = applyVpnIp;
window.saveCustomerData = saveCustomerData;
window.fetchSimVendors = fetchSimVendors;
window.handleSimVendorChange = handleSimVendorChange;
window.fetchNextSim = fetchNextSim;
window.fetchIp = fetchIp;
window.fetchVpnKeyForGateway = fetchVpnKeyForGateway;
window.pushData = pushData;
window.dryRunChirpstack = dryRunChirpstack;
window.createChirpstackDevice = createChirpstackDevice;
window.checkChirpstackExists = checkChirpstackExists;
window.checkChirpstackConfig = checkChirpstackConfig;
window.checkMilesightExists = checkMilesightExists;
window.checkMilesightConfig = checkMilesightConfig;
window.checkWebserviceStatus = checkWebserviceStatus;
window.dryRunWebservice = dryRunWebservice;
window.printWebserviceCommand = printWebserviceCommand;
window.createWebserviceGateway = createWebserviceGateway;
window.printMilesightCommand = printMilesightCommand;
window.createMilesightDevice = createMilesightDevice;
window.dryRunMilesightCreate = dryRunMilesightCreate;
window.runFinalCheck = runFinalCheck;
window.handleEuiChange = handleEuiChange;
window.openHelp = openHelp;
window.loadClientGateways = loadClientGateways;
window.setSuggestedName = setSuggestedName;
window.setSerialNumberFromStatus = setSerialNumberFromStatus;
window.toggleSerialNumberEdit = toggleSerialNumberEdit;

function bindAutoRefreshPause() {
    const formElements = document.querySelectorAll('input, select, textarea');
    formElements.forEach(el => {
        el.addEventListener('focusin', () => {
            pauseAutoRefresh('editing');
        });
        el.addEventListener('focusout', () => {
            resumeAutoRefresh();
        });
    });
}

function bindInputListeners() {
    const gwName = document.getElementById('gwName');
    const gwSn = document.getElementById('gwSn');
    const gwEui = document.getElementById('gwEui');
    const simIccid = document.getElementById('simIccid');
    const vpnIp = document.getElementById('vpnIp');
    const clientSearch = document.getElementById('clientSearch');
    const clientId = document.getElementById('clientId');
    const wsUser = document.getElementById('wsUser');
    const wsPass = document.getElementById('wsPass');

    if (gwName) {
        gwName.addEventListener('input', () => {
            vars.manualNameEdited = true;
            invalidateFinalCheck();
            checkReady();
            updateServiceNames();
            syncDesiredState();
        });
    }
    if (gwSn) {
        gwSn.addEventListener('input', () => {
            vars.allowMilesightSerialFill = false;
            invalidateFinalCheck();
            checkReady();
            syncDesiredState();
        });
    }
    if (gwEui) {
        gwEui.addEventListener('input', handleEuiChange);
        gwEui.addEventListener('input', updateServiceNames);
    }
    if (simIccid) {
        simIccid.addEventListener('input', () => {
            invalidateFinalCheck();
            checkReady();
            syncDesiredState();
        });
    }
    if (vpnIp) {
        vpnIp.addEventListener('input', () => {
            const value = vpnIp.value.trim();
            if (!value || value === vars.lastVpnInput) return;
            vars.lastVpnInput = value;
            vars.allowMilesightSerialFill = false;
            document.getElementById('gwSn').value = '';
            document.getElementById('simIccid').value = '';
            document.getElementById('simCardId').value = '';
            if (!vars.manualNameEdited) {
                document.getElementById('gwName').value = '';
            }
            updateServiceNames();
            updateConfigTargets();
            syncDesiredState();
            updateGatewayStatus();
            invalidateFinalCheck();
            checkReady();
            if (document.getElementById('gwEui').value) {
                checkMilesightExists({ silent: true });
            }
            updateSuggestedNameLabel();
        });
    }
    if (clientSearch) {
        clientSearch.addEventListener('input', () => {
            const value = clientSearch.value.trim();
            if (vars.clientSearchTimer) {
                clearTimeout(vars.clientSearchTimer);
            }
            vars.clientSearchTimer = setTimeout(() => {
                handleClientSearchInput(value);
            }, 300);
        });
    }
    if (clientId) {
        const triggerClientLoad = () => {
            if (clientId.value.trim()) {
                loadClientGateways(clientId.value.trim());
            }
            updateSuggestedNameLabel();
        };
        clientId.addEventListener('change', triggerClientLoad);
        clientId.addEventListener('input', () => {
            if (vars.clientSearchTimer) {
                clearTimeout(vars.clientSearchTimer);
            }
            vars.clientSearchTimer = setTimeout(triggerClientLoad, 300);
        });
    }
    
    // Trigger Webservice check when credentials change
    const triggerWsCheck = () => {
        if (vars.wsCheckTimer) clearTimeout(vars.wsCheckTimer);
        vars.wsCheckTimer = setTimeout(() => {
            checkWebserviceStatus();
        }, 800);
    };

    if (wsUser) {
        wsUser.addEventListener('input', () => {
            const value = wsUser.value.trim();
            if (value) {
                localStorage.setItem('wsLastUser', value);
            } else {
                localStorage.removeItem('wsLastUser');
            }
            triggerWsCheck();
        });
    }
    if (wsPass) {
        wsPass.addEventListener('input', triggerWsCheck);
    }
}

function initStepperObserver() {
    const links = document.querySelectorAll('#stepperNav a');
    const sections = document.querySelectorAll('[data-step]');
    if (!sections.length) return;
    const observer = new IntersectionObserver(entries => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            const step = entry.target.getAttribute('data-step');
            if (!step) return;
            links.forEach(link => link.classList.remove('active'));
            const activeLink = document.getElementById(`step-link-${step}`);
            if (activeLink) activeLink.classList.add('active');
        });
    }, { rootMargin: '-20% 0px -60% 0px', threshold: 0.1 });
    sections.forEach(section => observer.observe(section));
}

window.addEventListener('load', () => {
    const savedUser = localStorage.getItem('wsLastUser');
    const wsUser = document.getElementById('wsUser');
    if (savedUser && wsUser) {
        wsUser.value = savedUser;
    }
    setBadge('badgeChirpstack', 'ChirpStack: -', 'idle');
    setBadge('badgeMilesight', 'Milesight: -', 'idle');
    setBadge('badgeFinalCheck', 'Konfigurations Check: -', 'idle');
    renderFinalSummary();
    updateServiceNames();
    fetchSimVendors();
    syncDesiredState();
    setServiceStatus('chirpstack', { connected: false, statusText: 'ChirpStack Status: -', updatedAt: null, error: '-' });
    setServiceStatus('milesight', { connected: false, statusText: 'Milesight Status: -', updatedAt: null, error: '-' });
    setServiceStatus('webservice', { connected: false, statusText: 'Webservice Status: -', updatedAt: null, error: '-' });
    refreshTooltips();
    refreshGatewayStatus(true);
    const autoRefresh = document.getElementById('gwAutoRefresh');
    autoRefresh.checked = true;
    toggleAutoRefresh(true, true);
    updateTopStatusBanner();
    updateSectionStatuses();
    updateSuggestedNameLabel();
    bindAutoRefreshPause();
    bindInputListeners();
    initStepperObserver();
});

// Keep banner updated when manual changes happen
window.addEventListener('focusin', () => updateTopStatusBanner());
window.addEventListener('focusout', () => updateTopStatusBanner());
