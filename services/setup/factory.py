"""
Builds the adapters from the environment. This is the ONE place that decides
which implementation is used:

  INVENTORY_BACKEND   api | db   (default: api if DB_API_PROVIDER_URL is set and no DB host,
                                  i.e. no DB credentials on the operator laptop)
  WEBSERVICE_BACKEND  ws1 (default) | ws2 | off
  MILESIGHT_ENABLED   true (default) | false
  CHIRPSTACK_ENABLED  false (default) | true
"""
import os

from services.setup.adapters.inventory import ApiInventory, DbInventory
from services.setup.adapters.platforms import ChirpStackLns, MilesightPlatform
from services.setup.adapters.webservice import Ws1Webservice, Ws2Webservice


def _flag(name, default):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def build_inventory():
    default = "api" if os.getenv("DB_API_PROVIDER_URL") and not (os.getenv("DB_HOST") or os.getenv("DATABASE_URL")) else "db"
    backend = (os.getenv("INVENTORY_BACKEND") or default).strip().lower()
    if backend == "api":
        url = os.getenv("DB_API_PROVIDER_URL", "")
        if not url:
            raise ValueError("INVENTORY_BACKEND=api braucht DB_API_PROVIDER_URL")
        return ApiInventory(url, os.getenv("API_SERVICE_TOKEN", ""))
    return DbInventory()


def build_webservice():
    backend = os.getenv("WEBSERVICE_BACKEND", "ws1").strip().lower()
    if backend == "off":
        return None
    if backend == "ws2":
        return Ws2Webservice(os.getenv("WS2_URL", ""), os.getenv("WS2_READ_KEY", ""), os.getenv("WS2_WRITE_KEY", ""))
    return Ws1Webservice(os.getenv("WEBSERVICE_URL", "https://webservice.ball-b.de"),
                         os.getenv("WEBSERVICE_USER", ""), os.getenv("WEBSERVICE_PASSWORD", ""))


def build_registries():
    """Ordered list of external registrations."""
    regs = []
    if _flag("MILESIGHT_ENABLED", True):
        regs.append(MilesightPlatform(os.getenv("MILESIGHT_URL", "https://eu-openapi.milesight.com"),
                                      os.getenv("MILESIGHT_CLIENT_ID", ""), os.getenv("MILESIGHT_CLIENT_SECRET", ""),
                                      os.getenv("MILESIGHT_TOKEN_URL", "")))
    if _flag("CHIRPSTACK_ENABLED", False):
        regs.append(ChirpStackLns(os.getenv("CHIRPSTACK_URL", ""), os.getenv("CHIRPSTACK_API_TOKEN", ""),
                                  os.getenv("CHIRPSTACK_TENANT_ID", ""),
                                  int(os.getenv("CHIRPSTACK_STATS_INTERVAL_SECS", "30"))))
    ws = build_webservice()
    if ws:
        regs.append(ws)
    return regs
