import time
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from flask import Flask

from auth import oidc

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ISS = "https://authentik.test/application/o/gatewaychef/"
META = {"issuer": ISS, "authorization_endpoint": "https://authentik.test/authorize",
        "token_endpoint": "https://authentik.test/token", "jwks_uri": "https://authentik.test/jwks",
        "end_session_endpoint": "https://authentik.test/end"}


class FakeHttp:
    def __init__(self):
        self.claims = {}

    def get(self, url, timeout=None):
        return mock.Mock(status_code=200, json=lambda: META, raise_for_status=lambda: None)

    def post(self, url, data=None, timeout=None):
        tok = jwt.encode(self.claims, KEY, algorithm="RS256", headers={"kid": "k"})
        return mock.Mock(status_code=200, json=lambda: {"id_token": tok})


class FakeJwks:
    def __init__(self, uri):
        pass

    def get_signing_key_from_jwt(self, token):
        return mock.Mock(key=KEY.public_key())


def make_app(group="gatewaychef"):
    app = Flask(__name__)
    oidc.init_app(app, ISS, "cid", "secret", group, "x" * 40)
    http = FakeHttp()
    app.config["OIDC"].http = http

    @app.route("/")
    def index():
        return "UI"

    @app.route("/api/fleet/x")
    def fleet():
        return "fleet"

    @app.route("/api/db/x")
    def db():
        return "db"
    return app, http


class OidcTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(oidc.jwt, "PyJWKClient", FakeJwks)
        p.start()
        self.addCleanup(p.stop)
        self.app, self.http = make_app()
        self.c = self.app.test_client()

    def _login(self, groups=("gatewaychef",)):
        r = self.c.get("/auth/login?next=/api/fleet/x", base_url="https://gw.test")
        q = parse_qs(urlparse(r.location).query)
        self.assertEqual(q["code_challenge_method"], ["S256"])
        self.assertEqual(q["redirect_uri"], ["https://gw.test/auth/callback"])
        self.http.claims = {"iss": ISS, "aud": "cid", "sub": "u1", "nonce": q["nonce"][0],
                            "exp": int(time.time()) + 300, "email": "a@b.de", "name": "A", "groups": list(groups)}
        return self.c.get(f"/auth/callback?code=c&state={q['state'][0]}", base_url="https://gw.test")

    def test_page_redirects_api_401(self):
        self.assertEqual(self.c.get("/").status_code, 302)
        self.assertIn("/auth/login", self.c.get("/").location)
        self.assertEqual(self.c.get("/api/fleet/x").status_code, 401)

    def test_login_flow(self):
        r = self._login()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.location, "/api/fleet/x")
        self.assertEqual(self.c.get("/api/fleet/x", base_url="https://gw.test").data, b"fleet")
        self.assertEqual(self.c.get("/auth/me", base_url="https://gw.test").json["data"]["email"], "a@b.de")

    def test_wrong_group_denied(self):
        self.assertEqual(self._login(groups=("andere",)).status_code, 403)
        self.assertEqual(self.c.get("/api/fleet/x").status_code, 401)

    def test_bad_state_denied(self):
        self.c.get("/auth/login")
        self.assertEqual(self.c.get("/auth/callback?code=c&state=falsch").status_code, 400)

    def test_api_token_only_for_machine_paths(self):
        with mock.patch("config.API_SERVICE_TOKEN", "tok"):
            self.assertEqual(self.c.get("/api/db/x", headers={"X-API-Token": "tok"}).data, b"db")
            self.assertEqual(self.c.get("/api/db/x", headers={"X-API-Token": "nein"}).status_code, 401)
            self.assertEqual(self.c.get("/api/fleet/x", headers={"X-API-Token": "tok"}).status_code, 401)

    def test_missing_config_refuses_start(self):
        with self.assertRaises(RuntimeError):
            oidc.init_app(Flask("x"), ISS, "", "s", "", "x" * 40)
        with self.assertRaises(RuntimeError):
            oidc.init_app(Flask("y"), ISS, "c", "s", "", "kurz")


if __name__ == "__main__":
    unittest.main()
