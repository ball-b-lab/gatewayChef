import io
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from flask import Flask

from routes.db import bp as db_bp, _normalize_optional_bool


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


class NormalizeOptionalBoolTest(unittest.TestCase):
    def test_normalizes_common_boolean_variants(self):
        self.assertIs(_normalize_optional_bool(True), True)
        self.assertIs(_normalize_optional_bool(False), False)
        self.assertIs(_normalize_optional_bool(1), True)
        self.assertIs(_normalize_optional_bool(0), False)
        self.assertIs(_normalize_optional_bool("1"), True)
        self.assertIs(_normalize_optional_bool("0"), False)
        self.assertIs(_normalize_optional_bool("true"), True)
        self.assertIs(_normalize_optional_bool("false"), False)
        self.assertIsNone(_normalize_optional_bool(""))
        self.assertIsNone(_normalize_optional_bool(None))


class ProvisionRouteBoolNormalizationTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(db_bp)
        self.client = app.test_client()

    @patch("routes.db.DB_API_PROVIDER_URL", "")
    @patch("routes.db.APP_MODE", "local")
    @patch("routes.db.assign_sim", return_value=321)
    @patch("routes.db.get_db_connection")
    def test_provision_normalizes_lora_pending_integer_to_boolean(self, get_db_connection_mock, _assign_sim_mock):
        executed = []

        class FakeCursor:
            rowcount = 1

            def execute(self, sql, params=None):
                executed.append((sql, params))

            def fetchone(self):
                return (123,)

        class FakeConnection:
            def __init__(self):
                self.cursor_obj = FakeCursor()
                self.closed = False

            def cursor(self):
                return self.cursor_obj

            def rollback(self):
                pass

            def commit(self):
                pass

            def close(self):
                self.closed = True

        get_db_connection_mock.return_value = FakeConnection()

        response = self.client.post(
            "/api/provision",
            json={
                "vpn_ip": "172.30.1.10",
                "eui": "AA55AA55AA55AA55",
                "serial_number": "SN-123",
                "gateway_name": "gw-test",
                "sim_vendor_id": 7,
                "sim_iccid": "8949",
                "lora_pending": 0,
            },
        )

        self.assertEqual(response.status_code, 200)
        update_sql, update_params = executed[-1]
        self.assertIn("lora_pending = %s", update_sql)
        self.assertIs(update_params[17], False)


class ManualGatewayRouteTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(db_bp)
        self.client = app.test_client()

    @patch("routes.db.DB_API_PROVIDER_URL", "")
    @patch("routes.db.APP_MODE", "local")
    @patch("routes.db.get_db_connection")
    def test_manual_gateway_route_creates_seed_row(self, get_db_connection_mock):
        executed = []

        class FakeCursor:
            def execute(self, sql, params=None):
                executed.append((sql, params))

            def fetchone(self):
                return (77,)

        class FakeConnection:
            def __init__(self):
                self.cursor_obj = FakeCursor()
                self.closed = False

            def cursor(self):
                return self.cursor_obj

            def commit(self):
                pass

            def rollback(self):
                pass

            def close(self):
                self.closed = True

        get_db_connection_mock.return_value = FakeConnection()

        response = self.client.post(
            "/api/db/manual-gateway",
            json={
                "vpn_ip": "172.30.1.10",
                "private_key": "priv-key-1",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertEqual(payload["vpn_ip"], "172.30.1.10")
        self.assertEqual(payload["wifi_ssid"], "bbdbmon_1.10")
        self.assertEqual(payload["status_overall"], "FREE")
        insert_sql, insert_params = executed[-1]
        self.assertIn("INSERT INTO gateway_inventory", insert_sql)
        self.assertEqual(insert_params, ("172.30.1.10", "priv-key-1", "bbdbmon_1.10"))

    @patch("routes.db.DB_API_PROVIDER_URL", "")
    @patch("routes.db.APP_MODE", "local")
    def test_manual_gateway_route_requires_private_key(self):
        response = self.client.post(
            "/api/db/manual-gateway",
            json={
                "vpn_ip": "172.30.1.10",
                "private_key": "",
            },
        )

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["message"], "Private Key fehlt.")


class MarkDeployedRouteTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(db_bp)
        self.client = app.test_client()

    @patch("routes.db.DB_API_PROVIDER_URL", "")
    @patch("routes.db.APP_MODE", "local")
    @patch("routes.db.get_db_connection")
    def test_mark_deployed_updates_existing_row(self, get_db_connection_mock):
        executed = []

        class FakeCursor:
            rowcount = 1

            def execute(self, sql, params=None):
                executed.append((sql, params))

        class FakeConnection:
            def __init__(self):
                self.cursor_obj = FakeCursor()

            def cursor(self):
                return self.cursor_obj

            def commit(self):
                pass

            def rollback(self):
                pass

            def close(self):
                pass

        get_db_connection_mock.return_value = FakeConnection()

        response = self.client.post(
            "/api/db/mark-deployed",
            json={"vpn_ip": "172.30.1.10"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertEqual(payload["status"], "success")
        self.assertIn("DEPLOYED", payload["message"])
        update_sql, update_params = executed[-1]
        self.assertIn("SET status_overall = 'DEPLOYED'", update_sql)
        self.assertEqual(update_params, ("172.30.1.10",))


if __name__ == "__main__":
    unittest.main()
