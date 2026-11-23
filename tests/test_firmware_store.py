import io
import os
import tempfile
import unittest
from unittest import mock

from services import firmware as fw


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        p = mock.patch.object(fw, "MIN_IMAGE_BYTES", 10)
        p.start()
        self.addCleanup(p.stop)

    def test_store_normalizes_name(self):
        out = fw.store_image(io.BytesIO(b"x" * 50), "UG65 60.0.0.49-r4.bin", self.dir)
        self.assertEqual(out["file"], "60.0.0.49-r4.bin")
        self.assertEqual(fw.find_images(self.dir)["60.0.0.49"]["label"], "60.0.0.49-r4")
        self.assertEqual(os.listdir(self.dir), ["60.0.0.49-r4.bin"])

    def test_rejects_bad_name_and_tiny_file(self):
        with self.assertRaises(fw.FirmwareError):
            fw.store_image(io.BytesIO(b"x" * 50), "../evil.sh", self.dir)
        with self.assertRaises(fw.FirmwareError):
            fw.store_image(io.BytesIO(b"x"), "60.0.0.50.bin", self.dir)
        self.assertEqual(os.listdir(self.dir), [])

    def test_delete(self):
        fw.store_image(io.BytesIO(b"x" * 50), "60.0.0.50.bin", self.dir)
        fw.delete_image("60.0.0.50", self.dir)
        self.assertEqual(fw.find_images(self.dir), {})


if __name__ == "__main__":
    unittest.main()
