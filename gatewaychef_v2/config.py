from config import (
    API_SERVICE_TOKEN,
    CHIRPSTACK_API_TOKEN,
    CHIRPSTACK_TENANT_ID,
    CHIRPSTACK_URL,
    DB_API_PROVIDER_URL,
    DB_HOST,
    DB_PASSWORD,
    DATABASE_URL,
    MILESIGHT_CLIENT_ID,
    MILESIGHT_CLIENT_SECRET,
    MILESIGHT_URL,
    VPN_PING_PROVIDER_URL,
)


STAGE_ENV_REQUIREMENTS = {
    "precheck": [],
    "cloud_sync": [
        ("chirpstack", ["CHIRPSTACK_URL", "CHIRPSTACK_API_TOKEN", "CHIRPSTACK_TENANT_ID"]),
        ("milesight", ["MILESIGHT_URL", "MILESIGHT_CLIENT_ID", "MILESIGHT_CLIENT_SECRET"]),
    ],
    "inventory": [
        ("inventory", ["DB_API_PROVIDER_URL|DATABASE_URL|DB_HOST", "API_SERVICE_TOKEN|DB_PASSWORD|DATABASE_URL"])
    ],
}


def current_env_status():
    values = {
        "CHIRPSTACK_URL": bool(CHIRPSTACK_URL),
        "CHIRPSTACK_API_TOKEN": bool(CHIRPSTACK_API_TOKEN),
        "CHIRPSTACK_TENANT_ID": bool(CHIRPSTACK_TENANT_ID),
        "MILESIGHT_URL": bool(MILESIGHT_URL),
        "MILESIGHT_CLIENT_ID": bool(MILESIGHT_CLIENT_ID),
        "MILESIGHT_CLIENT_SECRET": bool(MILESIGHT_CLIENT_SECRET),
        "DATABASE_URL": bool(DATABASE_URL),
        "DB_HOST": bool(DB_HOST),
        "DB_PASSWORD": bool(DB_PASSWORD),
        "DB_API_PROVIDER_URL": bool(DB_API_PROVIDER_URL),
        "API_SERVICE_TOKEN": bool(API_SERVICE_TOKEN),
        "VPN_PING_PROVIDER_URL": bool(VPN_PING_PROVIDER_URL),
    }
    return values


def missing_for_stage(stage):
    env = current_env_status()
    missing = []
    for group, requirements in STAGE_ENV_REQUIREMENTS.get(stage, []):
        group_missing = []
        for key in requirements:
            if "|" in key:
                variants = key.split("|")
                if not any(env.get(item, False) for item in variants):
                    group_missing.append(key)
            elif not env.get(key, False):
                group_missing.append(key)
        if group_missing:
            missing.append({"group": group, "missing": group_missing})
    return missing
