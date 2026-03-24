import unittest
from unittest.mock import patch

from flask import Flask

from routes.gateway import bp as gateway_bp


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class GatewayRouteTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(gateway_bp)
        self.client = app.test_client()

    @patch("routes.gateway.requests.get")
    def test_device_info_exposes_firmware_version(self, get_mock):
        get_mock.return_value = FakeResponse(
            payload={
                "device": {
                    "mac": "AA:BB:CC:DD:EE:FF",
                    "firmwareVersion": "60.0.0.44",
                    "hardwareVersion": "2.0",
                },
                "vpn_ip": "172.30.1.10",
                "ssid": "bbdbmon_1.10",
            }
        )

        response = self.client.get("/api/gateway/device-info")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertEqual(data["firmware_version"], "60.0.0.44")
        self.assertEqual(data["hardware_version"], "2.0")
        self.assertEqual(data["wifi_ssid"], "bbdbmon_1.10")


if __name__ == "__main__":
    unittest.main()
