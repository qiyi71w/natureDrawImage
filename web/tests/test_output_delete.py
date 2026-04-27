import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app


class OutputDeleteTests(unittest.TestCase):
    def setUp(self):
        self.orig_output_dir = app.OUTPUT_DIR
        self.orig_featured_outputs_file = app.FEATURED_OUTPUTS_FILE
        self.orig_cache = dict(app._WEBP_CACHE)
        self.tmp = tempfile.TemporaryDirectory()
        app.OUTPUT_DIR = Path(self.tmp.name)
        app.FEATURED_OUTPUTS_FILE = Path(self.tmp.name) / "featured_outputs.json"
        app._WEBP_CACHE.clear()
        self.client = TestClient(app.app)

    def tearDown(self):
        self.tmp.cleanup()
        app.OUTPUT_DIR = self.orig_output_dir
        app.FEATURED_OUTPUTS_FILE = self.orig_featured_outputs_file
        app._WEBP_CACHE.clear()
        app._WEBP_CACHE.update(self.orig_cache)

    def test_delete_output_image_removes_file(self):
        target = app.OUTPUT_DIR / "sample.png"
        target.write_bytes(b"png")

        res = self.client.delete("/api/output/file", params={"path": "sample.png"})

        self.assertEqual(res.status_code, 200)
        self.assertFalse(target.exists())
        self.assertEqual(res.json()["deleted"], "sample.png")

    def test_delete_output_rejects_path_traversal(self):
        res = self.client.delete("/api/output/file", params={"path": "../sample.png"})

        self.assertEqual(res.status_code, 400)

    def test_featured_outputs_can_be_toggled_and_are_removed_when_file_deleted(self):
        target = app.OUTPUT_DIR / "sample.png"
        target.write_bytes(b"png")

        add = self.client.post("/api/output/featured", json={"path": "sample.png"})
        self.assertEqual(add.status_code, 200)
        self.assertEqual(self.client.get("/api/output/featured").json()["items"], [{"path": "sample.png"}])

        delete_file = self.client.delete("/api/output/file", params={"path": "sample.png"})
        self.assertEqual(delete_file.status_code, 200)
        self.assertEqual(self.client.get("/api/output/featured").json()["items"], [])
