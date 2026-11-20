import os
import tempfile
import unittest
from unittest import mock

from services import firmware as fw
from services import fleet as fl
from services.gateway_config import UG65Client
from tests.test_fleet import GW, FakeNodeRed, FLOW_V1, Http, Inv, Resp
from tests.test_gateway_config import FakeSession, _configured_state

ENV = {"FIRMWARE_UPLOAD_TYPE": "T", "FIRMWARE_UPLOAD_FILE": "F"}


class UploadSession(FakeSession):
    """FakeSession that also takes the multipart upload and 'flashes' the new firmware."""

    def __init__(self, state, firmware, new_firmware, answer=None):
        super().__init__(state, firmware)
        self.new_firmware, self.answer, self.uploads = new_firmware, answer, []

    def post(self, url, data=None, timeout=None, files=None):
        if url.endswith("/cgi-bin/file-import"):
            self.uploads.append(dict(data))
            self.firmware = self.new_firmware
            return self.answer or Resp({"size": 3, "checksum": "abc", "filename": "x"})
        return super().post(url, data, timeout)


class Flaky(Http):
    """Online, then down for one poll after the upload, then up again."""

    def __init__(self):
        super().__init__()
        self.pattern = iter([True, True, False, True])

    def get(self, url, timeout=None):
        import requests
        if url.endswith("/device-info") and not next(self.pattern, True):
            raise requests.ConnectionError("rebooting")
        if "/node-red/status" in url:
            seq = 2 if "since=" in url else 1
            items = [{"payload": 'JSON up 0: {"stat":{}}'}, {"payload": 'JSON up 0: {"rxpk":[]}'}] if seq == 2 else []
            return Resp({"latest_seq": seq, "items": items})
        if url.endswith("/islogin"):
            return Resp({"status": 0, "result": [{"upgrade_error": 0}]})
        return super().get(url, timeout)


def _images(tmp, version="60.0.0.50"):
    path = os.path.join(tmp, f"UG65 {version}-r1.bin")
    with open(path, "wb") as fh:
        fh.write(b"bin")
    return fw.find_images(tmp)


def _fleet(session, http):
    return fl.Fleet(Inv(), gateway_password="pw", http=http, sleep=lambda s: None, reachable_wait=0,
                    client_factory=lambda host: UG65Client(host, session=session),
                    nodered_factory=lambda host: FakeNodeRed(FLOW_V1))


class FirmwareTest(unittest.TestCase):
    def test_find_images_parses_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            imgs = _images(tmp)
            open(os.path.join(tmp, "notes.txt"), "w").close()
            self.assertEqual(list(imgs), ["60.0.0.50"])
            self.assertEqual(imgs["60.0.0.50"]["label"], "60.0.0.50-r1")

    def test_wait_reboot(self):
        seq = iter([True, False, False, True])
        self.assertTrue(fw.wait_reboot(lambda: next(seq), 60, sleep=lambda s: None, interval=0)[0])
        self.assertEqual(fw.wait_reboot(lambda: True, 0, sleep=lambda s: None)[1], "kein Neustart erkannt")

    def test_dry_run_and_refuse_without_form_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            imgs = _images(tmp)
            session = UploadSession(_configured_state(), "60.0.0.49", "60.0.0.50")
            f = _fleet(session, Flaky())
            res = fl.firmware_upgrade(f, GW, "60.0.0.50", images=imgs)
            self.assertEqual(res["result"], "would_change")
            self.assertIn("60.0.0.49 -> 60.0.0.50-r1", res["detail"])
            with mock.patch.dict(os.environ, {"FIRMWARE_UPLOAD_TYPE": "", "FIRMWARE_UPLOAD_FILE": ""}):
                with self.assertRaises(fw.FirmwareError):
                    fl.firmware_upgrade(f, GW, "60.0.0.50", apply=True, images=imgs, wait_secs=5)
            self.assertEqual(session.uploads, [])

    def test_upgrade_with_post_checks(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, ENV):
            imgs = _images(tmp)
            session = UploadSession(_configured_state(), "60.0.0.49", "60.0.0.50")
            session.cookies = {"td": "SID"}
            f = _fleet(session, Flaky())
            res = fl.firmware_upgrade(f, GW, "60.0.0.50", apply=True, images=imgs, wait_secs=60)
            self.assertEqual(res["result"], "updated", res)
            self.assertEqual(session.uploads[0], {"sessionid": "SID", "size": "3", "filename": "type=T&file=F"})
            labels = {c["label"]: c["ok"] for c in res["checks"]}
            self.assertEqual((labels["Firmware"], labels["Schnittstelle"], labels["Node-RED-Flows erhalten"],
                              labels["Drive-by-Datenweg"]), (True, True, True, True))

    def test_upgrade_failure_when_firmware_did_not_change(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, ENV):
            imgs = _images(tmp)
            session = UploadSession(_configured_state(), "60.0.0.49", "60.0.0.49")
            session.cookies = {"td": "SID"}
            res = fl.firmware_upgrade(_fleet(session, Flaky()), GW, "60.0.0.50", apply=True, images=imgs, wait_secs=60)
            self.assertEqual(res["result"], "failed")

    def test_rejected_upload_raises(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, ENV):
            imgs = _images(tmp)
            session = UploadSession(_configured_state(), "60.0.0.49", "60.0.0.50",
                                    answer=Resp({"templet_code": "E1"}, 400))
            session.cookies = {"td": "SID"}
            with self.assertRaises(fw.FirmwareError):
                fl.firmware_upgrade(_fleet(session, Flaky()), GW, "60.0.0.50", apply=True, images=imgs, wait_secs=5)


if __name__ == "__main__":
    unittest.main()
