import unittest
from unittest.mock import patch

from flask import Flask

from routes.chirpstack import bp as chirpstack_bp


class FakeResponse:
    def __init__(self, status_code=201, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = b"{}"

    def json(self):
        return self._payload


class ChirpstackRouteTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(chirpstack_bp)
        self.client = app.test_client()

    @patch("routes.chirpstack.get_chirpstack_missing", return_value=[])
    def test_command_payload_sets_stats_interval(self, _missing_mock):
        response = self.client.post(
            "/api/chirpstack/command",
            json={
                "eui": "a1b2c3d4e5f6a7b8",
                "serial_number": "SER-1",
                "gateway_name": "GW-1",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]["payload"]
        self.assertEqual(payload["gateway"]["gatewayId"], "a1b2c3d4e5f6a7b8")
        self.assertEqual(payload["gateway"]["statsInterval"], 30)
        self.assertEqual(payload["gateway"]["tags"]["serial_number"], "SER-1")

    @patch("routes.chirpstack.get_chirpstack_missing", return_value=[])
    @patch("routes.chirpstack.requests.post")
    def test_create_sends_stats_interval(self, post_mock, _missing_mock):
        post_mock.return_value = FakeResponse(status_code=201, payload={"id": "ok"})

        response = self.client.post(
            "/api/chirpstack/create",
            json={
                "eui": "a1b2c3d4e5f6a7b8",
                "serial_number": "SER-1",
                "gateway_name": "GW-1",
            },
        )

        self.assertEqual(response.status_code, 200)
        post_mock.assert_called_once()

        sent_json = post_mock.call_args.kwargs["json"]
        self.assertEqual(sent_json["gateway"]["gatewayId"], "a1b2c3d4e5f6a7b8")
        self.assertEqual(sent_json["gateway"]["statsInterval"], 30)
        self.assertEqual(sent_json["gateway"]["tags"]["serial_number"], "SER-1")


if __name__ == "__main__":
    unittest.main()
