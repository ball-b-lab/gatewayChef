# Help Popups

Files in this folder define the help popups for the Gateway Konfiguration section.

## Structure
- One JSON file per help topic: `login.json`, `gateway-id.json`, `vpn-address.json`, `vpn-key.json`, `wifi-ssid.json`, `apn.json`.
- Each JSON has:
  - `title`: string shown in the modal header
  - `images`: array of image filenames (relative to this folder)
  - `sections`: array of objects with `heading` and `text`

## Images
Default images are placeholders:
- `step-1.svg`
- `step-2.svg`
- `step-3.svg`

Replace them with your screenshots (keep the same filenames), or update the `images` list in each JSON.

## Editing Text
Update the `sections` in each JSON file to match your real instructions.
