def calculate_eui(mac):
    """
    Calculates EUI from MAC address:
    Removes colons, inserts 'FFFE' in the middle.
    Example: C0:BA... -> C0BA1FFFFE...
    """
    if not mac:
        return None
    clean_mac = mac.replace(":", "").upper()
    if len(clean_mac) == 12:
        return clean_mac[:6] + "FFFE" + clean_mac[6:]
    return clean_mac


def derive_wifi_ssid(vpn_ip):
    if not vpn_ip:
        return None
    parts = str(vpn_ip).split(".")
    if len(parts) < 2:
        return None
    return f"bbdbmon_{parts[-2]}.{parts[-1]}"


def normalize_vpn_ip(vpn_ip):
    if vpn_ip is None:
        return None
    if isinstance(vpn_ip, str):
        normalized = vpn_ip.strip()
        if "/" in normalized:
            normalized = normalized.split("/")[0]
        if normalized.lower() in {"", "0.0.0.0", "not_configured", "not-configured", "unset", "-"}:
            return None
        return normalized
    return vpn_ip
