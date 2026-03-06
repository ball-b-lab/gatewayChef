from config import CHIRPSTACK_URL, CHIRPSTACK_API_TOKEN, CHIRPSTACK_TENANT_ID


def get_chirpstack_missing():
    missing = []
    if not CHIRPSTACK_URL:
        missing.append("CHIRPSTACK_URL")
    if not CHIRPSTACK_API_TOKEN:
        missing.append("CHIRPSTACK_API_TOKEN")
    if not CHIRPSTACK_TENANT_ID:
        missing.append("CHIRPSTACK_TENANT_ID")
    return missing
