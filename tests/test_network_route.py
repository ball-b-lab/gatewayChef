import unittest
from unittest.mock import patch

from flask import Flask
from requests import ReadTimeout

from routes.network import bp as network_bp


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"ok": True, "data": {"ok": True, "output": "pong"}}
        self.content = b"{}"

    def json(self):
        return self._payload


class NetworkRouteTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(network_bp)
        self.client = app.test_client()

    @patch("routes.network._fetch_gateway_health_direct", return_value=({"ok": True, "via": "http_health"}, None))
    def test_vpn_check_local(self, health_mock):
        with patch("routes.network.VPN_PING_PROVIDER_URL", ""):
            response = self.client.post("/api/network/vpn-check", json={"vpn_ip": "172.30.1.10"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["via"], "http_health")
        health_mock.assert_called_once_with("172.30.1.10")

    @patch("routes.network.requests.post")
    def test_vpn_check_proxy(self, post_mock):
        post_mock.return_value = FakeResponse(
            status_code=200,
            payload={"ok": True, "data": {"ok": True, "via": "cloud_http_health"}},
        )
        with patch("routes.network.VPN_PING_PROVIDER_URL", "https://cloud.example.com"), patch(
            "routes.network.VPN_PING_SERVICE_TOKEN", "secret"
        ):
            response = self.client.post("/api/network/vpn-check", json={"vpn_ip": "172.30.1.10"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["via"], "cloud_http_health")
        self.assertEqual(post_mock.call_args.kwargs["headers"]["X-Ping-Service-Token"], "secret")

    @patch("routes.network.time.sleep", return_value=None)
    @patch("routes.network.requests.post")
    def test_vpn_check_proxy_retries_after_timeout(self, post_mock, _sleep_mock):
        post_mock.side_effect = [
            ReadTimeout("read timed out"),
            FakeResponse(status_code=200, payload={"ok": True, "data": {"ok": True, "via": "cloud_http_health"}}),
        ]
        with patch("routes.network.VPN_PING_PROVIDER_URL", "https://cloud.example.com"), patch(
            "routes.network.VPN_PING_SERVICE_TOKEN", "secret"
        ):
            response = self.client.post("/api/network/vpn-check", json={"vpn_ip": "172.30.1.10"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["via"], "cloud_http_health")
        self.assertEqual(post_mock.call_count, 2)

    @patch("routes.network._fetch_gateway_health_direct", return_value=({"ok": True, "via": "http_health"}, None))
    def test_gateway_health_local(self, health_mock):
        with patch("routes.network.VPN_PING_PROVIDER_URL", ""):
            response = self.client.post("/api/network/gateway-health", json={"vpn_ip": "172.30.1.10"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertEqual(payload["via"], "http_health")
        health_mock.assert_called_once_with("172.30.1.10")


if __name__ == "__main__":
    unittest.main()
