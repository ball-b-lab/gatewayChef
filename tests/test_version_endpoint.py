import unittest

from app import app


class VersionEndpointTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_version_endpoint_returns_build_info(self):
        response = self.client.get("/api/version")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload.get("ok"))
        data = payload.get("data") or {}
        self.assertIn("app_mode", data)
        self.assertIn("build_sha", data)
        self.assertIn("build_tag", data)
        self.assertIn("build_time", data)
        self.assertIn("service", data)


if __name__ == "__main__":
    unittest.main()
