import os
import stat
import tempfile
import unittest
from unittest import mock

from utils import station_credentials as creds


class CredentialsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"STATION_CREDENTIALS_FILE": os.path.join(self.dir, "c.json"),
                                                "WEBSERVICE_USER": "jochen", "WEBSERVICE_PASSWORD": "envpw"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_env_until_stored_then_station_wins(self):
        self.assertEqual(creds.webservice_login(), ("jochen", "envpw", "env"))
        creds.save("werkstatt", "geheim")
        self.assertEqual(creds.webservice_login(), ("werkstatt", "geheim", "station"))
        self.assertEqual(creds.status(), {"source": "station", "user": "werkstatt"})
        self.assertEqual(stat.S_IMODE(os.stat(creds.path()).st_mode), 0o600)
        creds.clear()
        self.assertEqual(creds.webservice_login()[2], "env")

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            creds.save("x", "")
        with self.assertRaises(ValueError):
            creds.save("", "y")

    def test_status_none(self):
        os.environ.pop("WEBSERVICE_USER")
        self.assertEqual(creds.status()["source"], "none")

    def test_factory_uses_stored_login(self):
        from services.setup import factory
        os.environ["WEBSERVICE_BACKEND"] = "ws1"
        creds.save("werkstatt", "geheim")
        ws = factory.build_webservice()
        self.assertEqual(ws.missing_config(), [])
        self.assertIn("werkstatt", str(ws.auth))

    def test_routes_never_return_password(self):
        os.environ.setdefault("OPEN_BROWSER", "false")
        import app as A
        if A.APP_MODE == "cloud":
            self.skipTest("station routes only local")
        c = A.app.test_client()
        r = c.post("/api/station/credentials", json={"webservice_user": "werkstatt", "webservice_password": "geheim"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("geheim", r.get_data(as_text=True))
        self.assertEqual(c.get("/api/station/credentials").get_json()["data"]["source"], "station")
        self.assertEqual(c.delete("/api/station/credentials").get_json()["data"]["source"], "env")


if __name__ == "__main__":
    unittest.main()
