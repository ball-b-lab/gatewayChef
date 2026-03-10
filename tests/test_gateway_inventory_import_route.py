import io
import unittest
from unittest.mock import patch

from flask import Flask

from routes.db import bp as db_bp


class GatewayInventoryImportRouteTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(db_bp)
        self.client = app.test_client()

    @patch("routes.db.DB_API_PROVIDER_URL", "")
    @patch("routes.db.APP_MODE", "local")
    @patch("routes.db.get_db_connection")
    def test_import_route_accepts_csv_upload(self, get_db_connection_mock):
        service_conn = get_db_connection_mock.return_value
        with patch("routes.db.ProvisioningService.import_gateway_inventory_csv") as import_mock:
            import_mock.return_value = {
                "inserted": 2,
                "skipped_existing": 1,
                "ignored_non_gateway": 1,
                "processed_gateway_rows": 3,
            }

            response = self.client.post(
                "/api/db/import-gateway-inventory",
                data={
                    "file": (
                        io.BytesIO(b"profile,vpn_ip,private_key\ngateway,172.30.1.10,priv-a\n"),
                        "peer_inventory.csv",
                    )
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["inserted"], 2)
        service_conn.close.assert_called_once()

    @patch("routes.db.DB_API_PROVIDER_URL", "")
    @patch("routes.db.APP_MODE", "local")
    def test_import_route_requires_file(self):
        response = self.client.post("/api/db/import-gateway-inventory", data={}, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
