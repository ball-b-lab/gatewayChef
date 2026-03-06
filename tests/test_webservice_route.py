import unittest
from unittest.mock import patch

from flask import Flask

from routes.webservice import bp as webservice_bp


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"ok": True}
        self.text = "{}"
        self.request = type(
            "Req",
            (),
            {
                "url": "https://webservice.ball-b.de/api/v2/gateway",
                "headers": {"Authorization": "Basic xxx"},
                "body": "",
            },
        )()

    def json(self):
        return self._payload


class WebserviceRouteTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(webservice_bp)
        self.client = app.test_client()

    @patch("routes.webservice.requests.post")
    def test_create_gateway_sends_serial_aliases(self, post_mock):
        post_mock.return_value = FakeResponse(status_code=200, payload={"status": "ok"})

        payload = {
            "username": "u",
            "password": "p",
            "clientId": "123",
            "lns": 2,
            "name": "GW-1",
            "gatewayId": "A1B2C3D4E5F6A7B8",
            "gatewayEui": "A1B2C3D4E5F6A7B8",
            "simIccid": "8941",
            "simId": "SIM-1",
            "manufacturer": "Milesight",
            "type": "UG65",
            "serialNumber": "SER-123",
        }

        response = self.client.post("/api/webservice/create-gateway", json=payload)

        self.assertEqual(response.status_code, 200)
        sent_data = post_mock.call_args.kwargs["data"]
        self.assertEqual(sent_data["serialNumber"], "SER-123")
        self.assertEqual(sent_data["serial"], "SER-123")
        self.assertEqual(sent_data["serial_number"], "SER-123")


if __name__ == "__main__":
    unittest.main()
