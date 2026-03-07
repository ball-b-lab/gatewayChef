import unittest

from flask import Flask

from gatewaychef_v2.blueprint import bp
from gatewaychef_v2.connectors import (
    FakeCloudConnector,
    FakeGatewayConnector,
    FakeInventoryConnector,
    FakeNetworkConnector,
)
from gatewaychef_v2.repository import InMemoryProvisioningRepository


class GatewayChefV2ApiTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__, template_folder="gatewaychef_v2/templates", static_folder="gatewaychef_v2/static")
        app.register_blueprint(bp)
        app.config["TESTING"] = True
        app.config["GATEWAYCHEF_V2_RUNTIME"] = {
            "repository": InMemoryProvisioningRepository(),
            "gateway": FakeGatewayConnector(),
            "inventory": FakeInventoryConnector(),
            "chirpstack": FakeCloudConnector(exists=False),
            "milesight": FakeCloudConnector(exists=False),
            "webservice": FakeCloudConnector(exists=False),
            "network": FakeNetworkConnector(ok=True),
            "enforce_env_guards": False,
        }
        self.client = app.test_client()

    def test_full_api_smoke_flow(self):
        create = self.client.post(
            "/gatewaychef-v2/api/runs",
            json={
                "operator_name": "Alice",
                "gateway_name": "kunde-02",
                "serial_number": "SER-002",
                "sim_vendor_id": "1",
                "sim_iccid": "8949002",
                "client_id": "77",
            },
        )
        self.assertEqual(create.status_code, 201)
        run_id = create.get_json()["data"]["run_id"]

        for endpoint in ("precheck", "reserve"):
            response = self.client.post(f"/gatewaychef-v2/api/runs/{run_id}/{endpoint}", json={})
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            f"/gatewaychef-v2/api/runs/{run_id}/confirm-config",
            json={"confirm_apply": True, "note": "values applied"},
        )
        self.assertEqual(response.status_code, 200)

        for endpoint in ("cloud-sync", "verify", "finalize"):
            response = self.client.post(
                f"/gatewaychef-v2/api/runs/{run_id}/{endpoint}",
                json={"webservice_username": "u", "webservice_password": "p"},
            )
            self.assertEqual(response.status_code, 200)

        report = self.client.get(f"/gatewaychef-v2/api/runs/{run_id}/report")
        payload = report.get_json()["data"]
        self.assertEqual(payload["state"], "DONE")
        self.assertEqual(payload["release_gate"], "PASS")

    def test_missing_fields_are_rejected(self):
        response = self.client.post("/gatewaychef-v2/api/runs", json={"operator_name": "Alice"})
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload["error"]["code"], "missing_fields")


if __name__ == "__main__":
    unittest.main()
