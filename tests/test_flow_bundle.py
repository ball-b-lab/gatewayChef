import glob
import json
import os
import shutil
import subprocess
import unittest

from services import nodered as nr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLES = sorted(glob.glob(os.path.join(ROOT, "gateway_profiles", "flows", "*.json")))


class FlowBundleTest(unittest.TestCase):
    def test_bundles_are_clean_and_consistent(self):
        for path in BUNDLES:
            text = open(path, encoding="utf-8").read()
            flows = json.loads(text)
            version = os.path.splitext(os.path.basename(path))[0]
            self.assertEqual(nr.declared_version(flows), version, path)
            ids = {n["id"] for n in flows}
            dangling = [w for n in flows for ws in n.get("wires", []) for w in ws if w not in ids]
            self.assertEqual(dangling, [], path)
            self.assertNotIn('"credentials"', text)
            # a password may only appear as placeholder
            for n in flows:
                if "password" in str(n.get("func", "")):
                    self.assertIn("{{gateway_login_password_enc}}", n["func"], path)

    def test_secret_is_rendered_for_deploy_only(self):
        bundles = nr.load_bundles(secrets={"gateway_login_password_enc": "ENC=="})
        func = next(n["func"] for n in bundles["1.1.0"]["flows"] if n.get("name") == "set login credentials")
        self.assertIn('"ENC=="', func)
        self.assertNotIn("1.1.0", nr.load_bundles(secrets={}))

    @unittest.skipUnless(shutil.which("node"), "node nicht installiert")
    def test_function_nodes_in_node(self):
        # oldest supported bundle plus the current target (latest) one
        for version in ("1.1.0", nr.latest_version(nr.load_bundles(secrets={"gateway_login_password_enc": "x"}))):
            out = subprocess.run(["node", os.path.join(ROOT, "tests", "nodered", "flow_functions.test.js"),
                                  os.path.join(ROOT, "gateway_profiles", "flows", f"{version}.json")],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(out.returncode, 0, version + ": " + out.stdout + out.stderr)
