import unittest
from datetime import datetime
from unittest.mock import patch

from flask import Flask

from routes.db import bp as db_bp


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed = None

    def execute(self, query, params=None):
        self.executed = (query, params)

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.cursor_obj = FakeCursor(rows)
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


class DbTableViewTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(db_bp)
        self.client = app.test_client()

    @patch("routes.db.DB_API_PROVIDER_URL", "")
    @patch("routes.db.get_db_connection")
    def test_table_view_returns_rows(self, get_db_connection_mock):
        conn = FakeConnection([
            (
                7,
                "172.30.1.10",
                "kunde-gw-01",
                "SN123",
                "ABCDEF1234567890",
                "bbdbmon_172_30_1_10",
                "priv-key-123",
                "IN_PROGRESS",
                "8949000000001",
                "SIM-42",
                "Telekom",
                datetime(2026, 3, 8, 10, 0, 0),
                datetime(2026, 3, 8, 11, 15, 0),
            )
        ])
        get_db_connection_mock.return_value = conn

        response = self.client.get("/api/db/table-view?q=172.30&limit=25&sort_by=vpn_ip&sort_dir=asc")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["query"], "172.30")
        self.assertEqual(payload["sort_by"], "vpn_ip")
        self.assertEqual(payload["sort_dir"], "asc")
        self.assertEqual(payload["rows"][0]["vpn_ip"], "172.30.1.10")
        self.assertEqual(payload["rows"][0]["private_key"], "priv-key-123")
        self.assertEqual(payload["rows"][0]["sim_vendor_name"], "Telekom")
        self.assertEqual(payload["rows"][0]["last_gateway_sync_at"], "2026-03-08T11:15:00")
        self.assertEqual(conn.cursor_obj.executed[1][-1], 25)
        self.assertTrue(conn.closed)

    @patch("routes.db.DB_API_PROVIDER_URL", "")
    def test_table_view_rejects_invalid_limit(self):
        response = self.client.get("/api/db/table-view?limit=abc")

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["message"], "Limit muss eine Zahl sein.")

    @patch("routes.db.DB_API_PROVIDER_URL", "")
    def test_table_view_rejects_invalid_sort(self):
        response = self.client.get("/api/db/table-view?sort_by=status_overall")

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["message"], "Ungueltige Sortierung.")


if __name__ == "__main__":
    unittest.main()
