import unittest

from gatewaychef_v2.connectors import (
    FakeCloudConnector,
    FakeGatewayConnector,
    FakeInventoryConnector,
    FakeNetworkConnector,
)
from gatewaychef_v2.errors import GatewayChefV2Error
from gatewaychef_v2.repository import InMemoryProvisioningRepository
from gatewaychef_v2.services import ProvisioningOrchestrator
from gatewaychef_v2.workflow import STATE_DONE, STATE_FAILED, STATE_VERIFIED


class ProvisioningOrchestratorTest(unittest.TestCase):
    def build_service(self, *, network_ok=True, web_exists=True):
        repository = InMemoryProvisioningRepository()
        inventory = FakeInventoryConnector()
        chirpstack = FakeCloudConnector(exists=False)
        milesight = FakeCloudConnector(exists=False)
        webservice = FakeCloudConnector(exists=web_exists)
        service = ProvisioningOrchestrator(
            repository,
            gateway=FakeGatewayConnector(),
            inventory=inventory,
            chirpstack=chirpstack,
            milesight=milesight,
            webservice=webservice,
            network=FakeNetworkConnector(ok=network_ok),
            enforce_env_guards=False,
        )
        return service, inventory, chirpstack, milesight, webservice

    def create_run(self, service):
        run = service.create_run(
            {
                "operator_name": "Max Mustermann",
                "gateway_name": "kunde-01",
                "serial_number": "SER-001",
                "sim_vendor_id": "1",
                "sim_iccid": "8949001",
                "client_id": "42",
                "manufacturer": "Milesight",
                "gateway_type": "UG67",
            }
        )
        return run["run_id"]

    def test_happy_path_reaches_done(self):
        service, inventory, chirpstack, milesight, webservice = self.build_service()
        run_id = self.create_run(service)

        service.precheck(run_id)
        service.reserve(run_id)
        service.confirm_config_applied(run_id, {"confirm_apply": True, "note": "Set values"})
        service.sync_cloud(run_id, webservice_credentials={"username": "u", "password": "p"})
        run = service.verify(run_id, webservice_credentials={"username": "u", "password": "p"})
        self.assertEqual(run["state"], STATE_VERIFIED)
        self.assertEqual(run["report"]["release_gate"], "PASS")

        run = service.finalize(run_id)
        self.assertEqual(run["state"], STATE_DONE)
        self.assertEqual(inventory.done, "10.10.10.10")
        self.assertTrue(chirpstack.exists)
        self.assertTrue(milesight.exists)
        self.assertTrue(webservice.exists)

    def test_verify_failure_marks_run_failed(self):
        service, _, _, _, _ = self.build_service(network_ok=False)
        run_id = self.create_run(service)

        service.precheck(run_id)
        service.reserve(run_id)
        service.confirm_config_applied(run_id, {"confirm_apply": True})
        service.sync_cloud(run_id, webservice_credentials={"username": "u", "password": "p"})

        with self.assertRaises(GatewayChefV2Error) as ctx:
            service.verify(run_id, webservice_credentials={"username": "u", "password": "p"})

        self.assertEqual(ctx.exception.code, "verification_failed")
        run = service.get_run(run_id)
        self.assertEqual(run["state"], STATE_FAILED)


if __name__ == "__main__":
    unittest.main()
