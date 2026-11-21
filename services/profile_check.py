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
