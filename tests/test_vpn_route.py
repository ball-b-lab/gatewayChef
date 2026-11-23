import unittest
from unittest import mock

from flask import Flask

from routes import vpn


class VpnRouteTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(vpn.bp)
        self.c = app.test_client()

    def test_joins_db_names(self):
        doc = {"generated": 1, "peers": [{"ip": "172.30.1.5", "name": "ug65_x", "handshake": 1, "live": True},
                                          {"ip": "172.30.0.2", "name": "JK-MAC"}]}
        resp = mock.Mock(json=lambda: doc, raise_for_status=lambda: None)
        gw = [{"vpn_ip": "172.30.1.5", "gateway_name": "GW Halle", "serial_number": "S1", "eui": "E", "status_overall": "DEPLOYED"}]
        with mock.patch.object(vpn.requests, "get", return_value=resp), \
                mock.patch.object(vpn, "get_db_connection"), mock.patch.object(vpn, "DB_API_PROVIDER_URL", ""), \
                mock.patch.object(vpn, "ProvisioningService") as ps:
            ps.return_value.list_gateways.return_value = gw
            data = self.c.get("/api/vpn/peers").json["data"]["peers"]
        self.assertEqual(data[0]["gateway_name"], "GW Halle")
        self.assertNotIn("gateway_name", data[1])

    def test_server_down_is_502(self):
        with mock.patch.object(vpn.requests, "get", side_effect=vpn.requests.ConnectionError("x")):
            self.assertEqual(self.c.get("/api/vpn/peers").status_code, 502)


if __name__ == "__main__":
    unittest.main()
