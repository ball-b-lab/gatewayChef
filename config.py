import os
import sys
from dotenv import load_dotenv

def _app_base_dir():
    return os.path.abspath(os.path.dirname(__file__))

def _candidate_dotenv_paths():
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        meipass = getattr(sys, '_MEIPASS', '')
        candidates = []
        if meipass:
            candidates.append(os.path.join(meipass, '.env'))
        candidates.append(os.path.join(exe_dir, '.env'))
        return candidates
    return [os.path.join(_app_base_dir(), '.env')]

# override=True ensures .env values replace any existing system environment variables
loaded = False
for dotenv_path in _candidate_dotenv_paths():
    if dotenv_path and os.path.exists(dotenv_path):
        load_dotenv(dotenv_path, override=True)
        loaded = True
        break
if not loaded:
    load_dotenv(override=True)

# Database
DATABASE_URL = os.getenv("DATABASE_URL")
# Explicitly NO default value here to prevent connecting to the wrong host if .env fails
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER = os.getenv("DB_USER", "gateway_admin")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME", "postgres")

# Port Configuration
PORT = int(os.getenv("PORT", 5000))
HOST = os.getenv("HOST", "0.0.0.0")

# ChirpStack Configuration
CHIRPSTACK_URL = os.getenv("CHIRPSTACK_URL", "https://chirpstack.example.com")
CHIRPSTACK_API_TOKEN = os.getenv("CHIRPSTACK_API_TOKEN", "")
CHIRPSTACK_TENANT_ID = os.getenv("CHIRPSTACK_TENANT_ID", "")
CHIRPSTACK_STATS_INTERVAL_SECS = int(os.getenv("CHIRPSTACK_STATS_INTERVAL_SECS", "30"))

# Optional cloud ping proxy (for local app that cannot reach VPN)
VPN_PING_PROVIDER_URL = os.getenv("VPN_PING_PROVIDER_URL", "").rstrip("/")
VPN_PING_SERVICE_TOKEN = os.getenv("VPN_PING_SERVICE_TOKEN", "")

# Milesight Developer Platform
MILESIGHT_URL = os.getenv("MILESIGHT_URL", "https://eu-openapi.milesight.com")
MILESIGHT_CLIENT_ID = os.getenv("MILESIGHT_CLIENT_ID", "")
MILESIGHT_CLIENT_SECRET = os.getenv("MILESIGHT_CLIENT_SECRET", "")
MILESIGHT_TOKEN_URL = os.getenv("MILESIGHT_TOKEN_URL", "")

# Gateway Configuration
GATEWAY_IP = os.getenv("GATEWAY_IP", "192.168.1.1")
GATEWAY_URL = f"http://{GATEWAY_IP}"
DEVICE_INFO_PATH = "/node-red/device-info"
DEVICE_INFO_LORA_PATH = "/node-red/device-info-lora"
CELLULAR_STATUS_PATH = "/status/cellular"

# Auth
JWT_SECRET = os.getenv("JWT_SECRET", "change-this-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRES_HOURS = int(os.getenv("JWT_EXPIRES_HOURS", "24"))
