"""
New firmware image: does the /cgi interface still match our profile?

check(client, profile) reads every section of the existing profile from a
gateway that runs the new firmware and reports per section:
  - section missing (core/base unknown to the new firmware)
  - field missing   (renamed or removed)
  - type changed    (e.g. "1" -> 1)
  - index missing
It also builds a draft profile for the new firmware that keeps only what the
gateway still understands. The draft is never used automatically: it is
written as ug65-<fw>.json.draft, reviewed, renamed, and then a dry run on a
correctly configured gateway with the new firmware must show no difference.
"""
import copy

from services import gateway_config as gc


def _type(v):
    return type(v).__name__


def check(client, profile):
    sections, report = [], []
    for section in profile["sections"]:
        label = section.get("label", f"{section['core']}/{section['base']}")
        try:
            entries = client.get(section["core"], section["base"])
        except gc.GatewayConfigError as exc:
            report.append({"label": label, "problem": "Abschnitt fehlt", "detail": str(exc)})
            continue
        entry = gc._find_entry(entries, section.get("index"))
        if entry is None:
            report.append({"label": label, "problem": "Index fehlt", "detail": f"index={section.get('index')}"})
            continue
        have = entry.get("value") or {}
        draft = copy.deepcopy(section)
        for key, want in section["value"].items():
            if key not in have:
                report.append({"label": label, "problem": "Feld fehlt", "detail": key})
                del draft["value"][key]
            elif not isinstance(want, str) or "{{" not in want:
                if have[key] is not None and want is not None and _type(have[key]) != _type(want):
                    report.append({"label": label, "problem": "Typ geaendert",
                                   "detail": f"{key}: {_type(want)} -> {_type(have[key])}"})
        new_fields = sorted(set(have) - set(section["value"]))
        if new_fields:
            report.append({"label": label, "problem": "neue Felder (Info)", "detail": ", ".join(new_fields[:15])})
        if draft["value"]:
            sections.append(draft)
    draft_profile = dict(profile, name=f"ug65-{client.firmware}", firmware=client.firmware,
                         source=f"Entwurf aus {profile['name']}, geprueft gegen FW {client.firmware}",
                         sections=sections)
    blocking = [r for r in report if r["problem"] != "neue Felder (Info)"]
    return {"firmware": client.firmware, "report": report, "compatible": not blocking, "draft": draft_profile}


def format_check(result, profile_name):
    lines = [f"Firmware {result['firmware']} gegen Profil {profile_name}:"]
    if not result["report"]:
        lines.append("  Schnittstelle unveraendert.")
    for r in result["report"]:
        lines.append(f"  {r['label']}: {r['problem']} ({r['detail']})")
    lines.append("  -> kompatibel" if result["compatible"] else "  -> NICHT kompatibel, Entwurf pruefen")
    return "\n".join(lines)


# ------------------------------------------------------------ qualify a new firmware
def network_summary(device_info):
    """Interfaces/routes the setup relies on, from Node-RED /device-info: (label, ok, info)."""
    dev = (device_info or {}).get("device") or {}
    ifs = dev.get("interfaces") or {}
    out = []
    # Interface must exist (blocking); up/down and addresses are information only: a
    # gateway fresh from the factory has no SIM, no VPN and no uplink yet.
    for name, needed in (("eth0", True), ("cellular0", True), ("wlan0", True), ("wg0", False)):
        i = ifs.get(name)
        if i is None:
            out.append((f"Interface {name}", False if needed else None, "fehlt" + ("" if needed else " (noch kein VPN)")))
            continue
        out.append((f"Interface {name}", True, f"{'up' if i.get('up') else 'down'} {i.get('ip') or ''}".strip()
                    + (" (Route)" if i.get("primary") else "")))
    primary = [n for n, i in ifs.items() if i.get("primary")]
    out.append(("Default-Route", True if primary else None, ", ".join(primary) or "keine (noch kein Uplink)"))
    out.append(("VPN-IP", True if dev.get("vpn_ip") else None, dev.get("vpn_ip") or "noch keine"))
    return out


def qualify(client, profile, device_info=None):
    """Interface check + network summary for a firmware without own profile."""
    result = check(client, profile)
    net = network_summary(device_info) if device_info is not None else []
    result["network"] = net
    result["qualifiable"] = result["compatible"] and not any(ok is False for _, ok, _ in net)
    return result


def format_qualify(result, profile_name):
    lines = [format_check(result, profile_name), "Netz:"]
    for label, ok, info in result.get("network", []):
        lines.append(f"  [{'OK' if ok else '--' if ok is None else 'FEHLT'}] {label}: {info}")
    lines.append(f"  => {'qualifizierbar (--approve legt Profil an)' if result['qualifiable'] else 'NICHT qualifizierbar'}")
    return "\n".join(lines)


def approve(result, profile_dir, source_note=""):
    """Write the draft as the approved profile ug65-<fw>.json (only if qualifiable)."""
    import json
    import os
    if not result.get("qualifiable"):
        raise ValueError("nicht qualifizierbar")
    prof = dict(result["draft"])
    prof["source"] = (f"Qualifiziert {source_note}: Schnittstelle wie {prof['source'].split(' aus ')[-1].split(',')[0]}"
                      ).strip()
    path = os.path.join(profile_dir, f"{prof['name']}.json")
    if os.path.exists(path):
        raise ValueError(f"{path} existiert schon")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(prof, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return path
