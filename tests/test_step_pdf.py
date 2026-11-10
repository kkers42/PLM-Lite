import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from app import config
from app.auth import get_current_user
from app.database import Database
from app.main import app

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "demo-bracket.step"


class StepPdfTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.db = Database(root / "plm.db")
        self.db.initialize()
        self.user = {"id": 1, "is_active": 1, "can_view": 1, "can_upload": 1}
        self.part = self.db.create_part({"part_number": "BRKT", "part_name": "Bracket"}, 1)
        self.source = root / "files" / "STEP" / FIXTURE.name
        self.source.parent.mkdir(parents=True)
        shutil.copyfile(FIXTURE, self.source)
        self.doc = self.db.create_document(
            FIXTURE.name, str(self.source), "step", "", 1, self.part["id"]
        )
        self.url = f"/api/documents/{self.doc['id']}/publish-3d-pdf"
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.addCleanup(app.dependency_overrides.clear)
        self.enterContext(patch("app.routers.documents_router._db", return_value=self.db))
        self.enterContext(patch.object(config, "FILES_ROOT", self.source.parent.parent))
        self.enterContext(patch.object(config, "STEP_PDF_CONVERTER", "/mock/converter"))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def assert_no_output(self):
        self.assertEqual(len(self.db.list_documents(self.part["id"])), 1)
        self.assertEqual(list(config.FILES_ROOT.rglob("*.pdf")), [])

    def test_upload_permission_required(self):
        self.user["can_upload"] = 0
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.assert_no_output()

    def test_released_part_is_locked(self):
        self.db.release_part(self.part["id"], 1)
        self.assertEqual(self.client.post(self.url).status_code, 423)
        self.assert_no_output()

    def test_failed_conversion_leaves_no_attachment(self):
        with patch("app.step_pdf.subprocess.run", side_effect=subprocess.CalledProcessError(1, "converter")):
            self.assertEqual(self.client.post(self.url).status_code, 422)
        self.assert_no_output()

    def test_converter_reason_is_shown(self):
        failure = subprocess.CalledProcessError(
            2, "converter", stderr=b"noise\nSTEP_PDF_ERROR: the STEP file contains 3 solids\n"
        )
        with patch("app.step_pdf.subprocess.run", side_effect=failure):
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 422)
        self.assertIn("contains 3 solids", response.json()["detail"])
        self.assert_no_output()

    def test_converter_does_not_inherit_app_secrets(self):
        seen = {}

        def capture_environment(args, **kwargs):
            seen.update(kwargs["env"])
            raise subprocess.CalledProcessError(1, "converter")

        with patch.dict(os.environ, {"SECRET_KEY": "not-for-the-converter"}):
            with patch("app.step_pdf.subprocess.run", side_effect=capture_environment):
                self.client.post(self.url)
        self.assertIn("STEP_PDF_TITLE", seen)
        self.assertNotIn("SECRET_KEY", seen)
        self.assertNotIn("not-for-the-converter", seen.values())

    def test_busy_converter_returns_429(self):
        from app import step_pdf

        self.assertTrue(step_pdf._slots.acquire(blocking=False))
        self.addCleanup(step_pdf._slots.release)
        with patch("app.step_pdf.subprocess.run") as run:
            self.assertEqual(self.client.post(self.url).status_code, 429)
        run.assert_not_called()
        self.assert_no_output()

    def test_static_pdf_is_rejected(self):
        def write_static_pdf(args, **kwargs):
            pdf = PdfWriter()
            pdf.add_blank_page(width=612, height=792)
            pdf.write(args[2])

        with patch("app.step_pdf.subprocess.run", side_effect=write_static_pdf):
            self.assertEqual(self.client.post(self.url).status_code, 422)
        self.assert_no_output()

    def test_revision_change_rejects_result(self):
        def revise_during_conversion(args, **kwargs):
            Path(args[2]).write_bytes(b"test output")
            with self.db._connect() as conn:
                conn.execute("UPDATE parts SET part_revision='B' WHERE id=?", (self.part["id"],))

        with patch("app.step_pdf.subprocess.run", side_effect=revise_during_conversion):
            with patch("app.step_pdf._validate_pdf"):
                self.assertEqual(self.client.post(self.url).status_code, 409)
        self.assert_no_output()

    @unittest.skipUnless(os.environ.get("STEP_PDF_TEST_CONVERTER"), "requires real converter")
    def test_publish_download_and_retry(self):
        config.STEP_PDF_CONVERTER = os.environ["STEP_PDF_TEST_CONVERTER"]
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200, response.text)
        document = response.json()
        self.assertIn("Revision A", document["description"])
        self.assertEqual(document["part_id"], self.part["id"])
        downloaded = self.client.get(f"/api/documents/{document['id']}/download")
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.content, Path(document["stored_path"]).read_bytes())
        page = PdfReader(document["stored_path"], strict=True).pages[0]
        annotation = page["/Annots"][0].get_object()
        self.assertEqual(annotation["/Subtype"], "/3D")
        self.assertEqual(annotation["/3DD"]["/Subtype"], "/PRC")
        self.assertGreater(len(annotation["/3DD"].get_data()), 100)
        self.assertEqual(self.client.post(self.url).json()["id"], document["id"])
        self.assertEqual(len(self.db.list_documents(self.part["id"])), 2)
