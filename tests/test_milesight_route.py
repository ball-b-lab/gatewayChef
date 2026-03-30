import unittest
from unittest.mock import patch

from flask import Flask

from routes.milesight import bp as milesight_bp


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class MilesightRouteTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(milesight_bp)
        self.client = app.test_client()

    @patch("routes.milesight.get_milesight_missing", return_value=[])
    @patch("routes.milesight.milesight_get_token", return_value="token-1")
    @patch("routes.milesight.requests.post")
    def test_check_falls_back_to_dev_eui_search(self, post_mock, _token_mock, _missing_mock):
        post_mock.side_effect = [
            FakeResponse(payload={"data": {"content": [
                {
                    "devEUI": "FFFFFFFFFFFFFFFF",
                    "sn": "SN-OTHER",
                    "name": "Other GW",
                    "model": "UG65",
                }
            ]}}),
            FakeResponse(payload={"data": {"content": [
                {
                    "devEUI": "ABCDEF1234567890",
                    "snDevEUI": "SERIAL-XYZ",
                    "sn": "SN-1",
                    "name": "GW-1",
                    "model": "UG65",
                }
            ]}})
        ]

        response = self.client.post("/api/milesight/check", json={"eui": "ABCDEF1234567890"})

        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertTrue(data["exists"])
        self.assertEqual(data["serial_number"], "SN-1")
        self.assertEqual(post_mock.call_count, 2)

    @patch("routes.milesight.get_milesight_missing", return_value=[])
    @patch("routes.milesight.milesight_get_token", return_value="token-1")
    @patch("routes.milesight.requests.post")
    def test_check_falls_back_to_serial_search(self, post_mock, _token_mock, _missing_mock):
        post_mock.side_effect = [
            FakeResponse(payload={"data": {"content": []}}),
            FakeResponse(payload={"data": {"content": []}}),
            FakeResponse(payload={"data": {"content": [
                {
                    "devEUI": "",
                    "snDevEUI": "GW-3D74",
                    "sn": "GW-3D74",
                    "name": "GW-Old",
                    "model": "UG65",
                }
            ]}})
        ]

        response = self.client.post("/api/milesight/check", json={
            "eui": "C0BA1FFFFE003D74",
            "serial_number": "GW-3D74"
        })

        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertTrue(data["exists"])
        self.assertEqual(data["serial_number"], "GW-3D74")
        self.assertEqual(post_mock.call_count, 3)


if __name__ == "__main__":
    unittest.main()
