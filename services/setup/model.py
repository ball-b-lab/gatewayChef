"""Shared data types for the gateway setup pipeline."""
from dataclasses import dataclass, field, asdict

OK, CHANGED, WOULD_CHANGE, SKIPPED, WARN, FAIL = "ok", "changed", "would_change", "skipped", "warn", "fail"


class SetupError(Exception):
    pass


@dataclass
class Gateway:
    """Everything known about the gateway being set up. Filled step by step."""
    vpn_ip: str = None
    private_key: str = None
    eui: str = None
    mac: str = None
    serial_number: str = None
    name: str = None
    model: str = None
    firmware: str = None
    sim_iccid: str = None
    sim_id: str = None
    sim_vendor_id: str = None
    client_id: str = None
    client_name: str = None
    lns_address: str = None
    wifi_ssid: str = None

    def public(self):
        data = asdict(self)
        data["private_key"] = "***" if self.private_key else None
        return data


@dataclass
class StepResult:
    step: str
    status: str
    detail: str = ""
    checks: list = field(default_factory=list)   # [(label, ok_bool, info)]

    @property
    def failed(self):
        return self.status == FAIL


def normalize_eui(value):
    return "".join(ch for ch in str(value or "") if ch in "0123456789abcdefABCDEF").upper()


def is_valid_eui(value):
    eui = normalize_eui(value)
    return len(eui) == 16 and eui not in {"0" * 16, "F" * 16, "000000FFFE000000"}
