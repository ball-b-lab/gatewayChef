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

    def test_new_config_requires_confirmed_cleanup_when_record_exists(self):
        service, inventory, _, _, _ = self.build_service()
        inventory.record = {
            "vpn_ip": "10.10.10.10",
            "eui": "C0BA1FFFFE003D74",
            "wifi_ssid": "bbdbmon_10.10",
            "serial_number": "SER-001",
            "gateway_name": "kunde-01",
            "status_overall": "VERIFIED",
        }
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
                "operation_mode": "new_config",
                "current_vpn_ip": "10.10.10.10",
            }
        )
        run_id = run["run_id"]

        service.precheck(run_id)

        with self.assertRaises(GatewayChefV2Error) as ctx:
            service.reserve(run_id)

        self.assertEqual(ctx.exception.code, "cleanup_confirmation_required")

    def test_missing_client_assignment_stays_draft(self):
        service, inventory, _, _, _ = self.build_service()
        run = service.create_run(
            {
                "operator_name": "Max Mustermann",
                "gateway_name": "kunde-01",
                "serial_number": "SER-001",
                "sim_vendor_id": "1",
                "sim_iccid": "8949001",
                "manufacturer": "Milesight",
                "gateway_type": "UG67",
            }
        )
        run_id = run["run_id"]

        service.precheck(run_id)
        service.reserve(run_id)
        service.confirm_config_applied(run_id, {"confirm_apply": True})
        service.sync_cloud(run_id, webservice_credentials={"username": "u", "password": "p"})

        with self.assertRaises(GatewayChefV2Error) as ctx:
            service.verify(run_id, webservice_credentials={"username": "u", "password": "p"})

        self.assertEqual(ctx.exception.code, "verification_failed")
        self.assertEqual(inventory.saved["status_overall"], "IN_PROGRESS")
        self.assertFalse(inventory.saved["conf_gateway_done"])

    def test_failed_verify_does_not_degrade_existing_deployed_record(self):
        service, inventory, _, _, _ = self.build_service(network_ok=False, web_exists=True)
        inventory.record = {
            "vpn_ip": "10.10.10.10",
            "eui": "AA11BB22CC33DD44",
            "wifi_ssid": "bbdbmon_10.10",
            "serial_number": "SER-001",
            "gateway_name": "kunde-01",
            "status_overall": "DEPLOYED",
        }
        run_id = self.create_run(service)

        service.precheck(run_id)
        service.reserve(run_id)
        service.confirm_config_applied(run_id, {"confirm_apply": True})
        service.sync_cloud(run_id, webservice_credentials={"username": "u", "password": "p"})

        with self.assertRaises(GatewayChefV2Error):
            service.verify(run_id, webservice_credentials={"username": "u", "password": "p"})

        self.assertEqual(inventory.record["status_overall"], "DEPLOYED")

    def test_force_draft_skips_webservice_creation_even_with_customer_assignment(self):
        service, inventory, _, _, webservice = self.build_service(web_exists=False)
        run_id = self.create_run(service)

        service.precheck(run_id)
        service.reserve(run_id)
        service.confirm_config_applied(run_id, {"confirm_apply": True})
        run = service.sync_cloud(run_id, webservice_credentials={"username": "u", "password": "p"}, force_draft=True)

        self.assertEqual(run["state"], "CLOUD_SYNCED")
        self.assertFalse(webservice.exists)
        self.assertEqual(inventory.saved["status_overall"], "IN_PROGRESS")
        self.assertFalse(inventory.saved["conf_gateway_done"])


if __name__ == "__main__":
    unittest.main()
