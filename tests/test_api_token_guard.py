import unittest
from unittest.mock import patch

from flask import Flask

from routes.db import bp as db_bp


class FakeUpstreamResponse:
    def __init__(self, status_code=200, content=b'{"ok":true}', content_type="application/json"):
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Type": content_type}


class ApiTokenGuardTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(db_bp)
        self.client = app.test_client()

    @patch("routes.db.APP_MODE", "cloud_api")
    @patch("utils.api_token.API_SERVICE_TOKEN", "guard-token")
    def test_db_route_requires_token_when_configured(self):
        response = self.client.get("/api/db/fetch-ip")
        self.assertEqual(response.status_code, 401)

    @patch("routes.db.requests.request")
    @patch("routes.db.API_SERVICE_TOKEN", "proxy-token")
    @patch("routes.db.DB_API_PROVIDER_URL", "https://cloud.example.com")
    @patch("routes.db.APP_MODE", "local")
    def test_local_mode_proxies_db_calls_to_cloud_api(self, request_mock):
        request_mock.return_value = FakeUpstreamResponse()

        response = self.client.get("/api/db/fetch-ip")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(request_mock.call_count, 1)
        self.assertEqual(request_mock.call_args.kwargs["url"], "https://cloud.example.com/api/db/fetch-ip")
        self.assertEqual(request_mock.call_args.kwargs["headers"]["X-API-Token"], "proxy-token")


if __name__ == "__main__":
    unittest.main()
