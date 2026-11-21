"""
Interfaces for the external systems. Each system has one interface and one or
more implementations; which one is used is decided in factory.py from the
environment. Swapping the webservice (WS1 -> WS2) means: new adapter class,
one env var, no change to the pipeline.
"""
from abc import ABC, abstractmethod


class Inventory(ABC):
    """gateway_inventory: VPN pool, gateway master data, status."""
    name = "inventory"

    @abstractmethod
    def get(self, vpn_ip):
        """dict with vpn_ip, private_key, eui, serial_number, gateway_name, sim_iccid, sim_id, status_overall | None"""

    @abstractmethod
    def find_by_eui(self, eui):
        """same dict as get() or None"""

    @abstractmethod
    def next_free(self):
        """dict with vpn_ip, private_key (only a preview, not reserved; for dry runs)"""

    @abstractmethod
    def reserve(self, eui):
        """atomically bind the next FREE row to eui (or return the row already bound);
        dict with vpn_ip, private_key, server_public_key"""

    def list_gateways(self):
        """[{vpn_ip, eui, gateway_name, serial_number, status_overall, last_sync}] for all non-FREE rows"""
        raise NotImplementedError

    def pool_status(self):
        """dict with free, total, vpn_ips"""
        raise NotImplementedError

    @abstractmethod
    def save(self, gw):
        """write eui/serial/name/ssid/sim for gw.vpn_ip, status -> IN_PROGRESS; returns dict (sim_id ...)"""

    @abstractmethod
    def mark_deployed(self, vpn_ip):
        pass


class Registry(ABC):
    """An external system where the gateway must be registered once
    (webservice, Milesight platform, LNS)."""
    name = "registry"

    def missing_config(self):
        return []

    def required_fields(self):
        """Gateway attributes needed for create()."""
        return ["eui"]

    @abstractmethod
    def find(self, gw):
        """dict describing the existing entry, or None"""

    @abstractmethod
    def create(self, gw):
        """create entry, return dict"""

    def describe_create(self, gw):
        """what create() would send (for dry runs, secrets masked)"""
        return {}
