import unittest

from services import rename


class Inv:
    def __init__(self): self.saved = []
    def get(self, ip): return {"vpn_ip": ip, "gateway_name": "0.116 10999 - Alt GmbH", "eui": "24E124FFFEF783E6"}
    def save(self, gw): self.saved.append((gw.vpn_ip, gw.name))


class Resp:
    def __init__(self, code, text=""): self.status_code, self.text = code, text


class Http:
    def __init__(self): self.puts = []
    def put(self, url, json=None, headers=None, timeout=None): self.puts.append((url, json)); return Resp(200)


class Cs:
    base, token, timeout = "https://cs", "t", 5
    def __init__(self): self.http = Http()
    def find(self, gw): return {"gateway": {"gatewayId": "24e124fffef783e6", "name": "0.116 10999 - Alt GmbH", "tenantId": "x"}}


class Ws:
    def find(self, gw): return {"name": "0.116 10999 - Alt GmbH", "clientId": 10999}


class RenameTest(unittest.TestCase):
    def test_split(self):
        self.assertEqual(rename.split_name("0.116 10999 - Muster GmbH"),
                         {"prefix": "0.116", "client_id": "10999", "client_name": "Muster GmbH"})
        self.assertEqual(rename.split_name("JK_Test"), {})

    def test_plan_and_apply(self):
        inv, cs = Inv(), Cs()
        r = rename.Renamer(inventory=inv, chirpstack=cs, webservice=Ws())
        p = r.plan("172.30.0.116", "0.116 20001 - Neu AG")
        self.assertTrue(p["client_change"])
        self.assertEqual([t["action"] for t in p["targets"]], ["change", "change", "manual"])
        self.assertEqual(inv.saved, [])
        out = r.apply("172.30.0.116", "0.116 20001 - Neu AG")
        self.assertEqual([t["action"] for t in out["targets"]], ["done", "done", "manual"])
        self.assertEqual(inv.saved, [("172.30.0.116", "0.116 20001 - Neu AG")])
        url, body = cs.http.puts[0]
        self.assertTrue(url.endswith("/api/gateways/24e124fffef783e6"))
        self.assertEqual(body["gateway"]["name"], "0.116 20001 - Neu AG")
        self.assertEqual(body["gateway"]["tenantId"], "x")

    def test_bad_name(self):
        with self.assertRaises(rename.RenameError):
            rename.Renamer(inventory=Inv(), chirpstack=None, webservice=None).plan("172.30.0.116", "<script>")


if __name__ == "__main__":
    unittest.main()
