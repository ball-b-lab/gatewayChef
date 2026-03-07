import unittest
from unittest.mock import patch

from flask import Flask

from routes.db import bp as db_bp


class ApiTokenGuardTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(db_bp)
        self.client = app.test_client()

    @patch("utils.api_token.API_SERVICE_TOKEN", "guard-token")
    def test_db_route_requires_token_when_configured(self):
        response = self.client.get("/api/db/fetch-ip")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
