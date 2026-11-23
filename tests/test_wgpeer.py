import importlib.util
import pathlib
import unittest

spec = importlib.util.spec_from_file_location(
    "wgpeer", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "vpn" / "wgpeer.py")
wp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wp)

CONF = """# This file was generated using wireguard-ui
[Interface]
Address = 172.30.0.1/24
ListenPort = 51820
PrivateKey = SECRET
PostUp =

# ID:   x
# Name: JK-MAC
[Peer]
PublicKey = A
PresharedKey = P
AllowedIPs = 172.30.0.2/32

[Peer]
# ug65_102
PublicKey = C
AllowedIPs = 172.30.0.102/32, 192.168.1.0/24
PersistentKeepalive = 25

[Peer]
# ug65_101
PublicKey = B
AllowedIPs = 172.30.0.101/32, 192.168.1.0/24
PersistentKeepalive = 25
"""


class WgpeerTest(unittest.TestCase):
    def test_parse_names(self):
        _, peers = wp.parse(CONF)
        self.assertEqual([p.name for p in peers], ["JK-MAC", "ug65_102", "ug65_101"])
        self.assertEqual(peers[1].ip, "172.30.0.102")

    def test_normalize_drops_lan_and_sorts(self):
        iface, peers = wp.parse(CONF)
        out = wp.render(iface, wp.normalize(peers))
        self.assertNotIn("192.168.1.0/24", out)
        self.assertLess(out.index("ug65_101"), out.index("ug65_102"))
        self.assertNotIn("PostUp", out)
        self.assertIn("PrivateKey = SECRET", out)
        self.assertIn("PresharedKey = P", out)

    def test_roundtrip_stable(self):
        iface, peers = wp.parse(CONF)
        once = wp.render(iface, wp.normalize(peers))
        i2, p2 = wp.parse(once)
        self.assertEqual(wp.render(i2, wp.normalize(p2)), once)

    def test_redact(self):
        self.assertNotIn("SECRET", wp.redact(CONF))


if __name__ == "__main__":
    unittest.main()
