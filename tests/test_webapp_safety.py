import io
import re
import threading
from pathlib import Path

import pytest

import WebApp.app as webapp


@pytest.fixture()
def isolated_webapp(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    ref_dir = upload_dir / "references"
    pdf_root = upload_dir / "pdfs"
    output_dir = tmp_path / "output"
    for path in (ref_dir, pdf_root, output_dir):
        path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(webapp, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(webapp, "REFERENCE_UPLOAD_DIR", ref_dir)
    monkeypatch.setattr(webapp, "PDF_UPLOAD_ROOT", pdf_root)
    monkeypatch.setattr(webapp, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(webapp, "SETTINGS_FILE", tmp_path / "webapp_settings.json")

    webapp.session.clear()
    webapp.session.update({
        "references": [],
        "dedup_stats": None,
        "screening_results": [],
        "pdf_folder": "",
        "automation": None,
        "stop_event": threading.Event(),
        "processing_thread": None,
        "progress": [],
        "progress_lock": threading.Lock(),
        "pdf_display_names": {},
    })

    webapp.app.config.update(TESTING=True)
    return webapp


def test_webapp_debug_defaults_off():
    assert webapp.WEBAPP_DEBUG is False
    assert webapp.app.debug is False


def test_webapp_cors_header_is_absent(isolated_webapp):
    client = isolated_webapp.app.test_client()

    response = client.get("/api/settings", headers={"Origin": "https://example.com"})

    assert "Access-Control-Allow-Origin" not in response.headers


def test_webapp_settings_strip_legacy_api_key(isolated_webapp):
    isolated_webapp.SETTINGS_FILE.write_text(
        '{"provider": "OpenAI", "api_key": "legacy-secret"}',
        encoding="utf-8",
    )
    client = isolated_webapp.app.test_client()

    response = client.get("/api/settings")

    assert response.status_code == 200
    assert response.get_json() == {"provider": "OpenAI"}
    assert "api_key" not in isolated_webapp.SETTINGS_FILE.read_text(encoding="utf-8")


@pytest.mark.parametrize("filename", ["../evil.ris", r"..\evil.ris"])
def test_reference_upload_rejects_path_traversal_filenames(isolated_webapp, filename):
    client = isolated_webapp.app.test_client()

    response = client.post(
        "/api/references/upload",
        data={"file": (io.BytesIO(b"TY  - JOUR\nTI  - Test\nER  -\n"), filename)},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400


def test_reference_upload_uses_generated_safe_filename(isolated_webapp):
    client = isolated_webapp.app.test_client()

    response = client.post(
        "/api/references/upload",
        data={"file": (io.BytesIO(b"TY  - JOUR\nTI  - Test\nER  -\n"), "My References.ris")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    data = response.get_json()
    stored_path = Path(data["path"])
    stored_path.resolve().relative_to(isolated_webapp.REFERENCE_UPLOAD_DIR.resolve())
    assert data["original_filename"] == "My References.ris"
    assert data["filename"] != "My References.ris"
    assert re.fullmatch(r"[0-9a-f]{32}\.ris", data["filename"])
    assert stored_path.name == data["filename"]


def test_pdf_upload_uses_generated_safe_filename_and_display_metadata(isolated_webapp):
    client = isolated_webapp.app.test_client()

    response = client.post(
        "/api/pdfs/upload",
        data={"files": (io.BytesIO(b"%PDF-1.4\n"), "Paper One.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["count"] == 1
    item = data["files"][0]
    stored_path = Path(item["path"])
    stored_path.resolve().relative_to(isolated_webapp.PDF_UPLOAD_ROOT.resolve())
    assert item["original_filename"] == "Paper One.pdf"
    assert item["filename"] != "Paper One.pdf"
    assert re.fullmatch(r"[0-9a-f]{32}\.pdf", item["filename"])

    list_response = client.get("/api/pdfs/list")
    listed = list_response.get_json()["files"][0]
    assert listed["name"] == item["filename"]
    assert listed["display_name"] == "Paper One.pdf"


def test_reference_parse_path_cannot_point_outside_upload_dir(isolated_webapp, tmp_path, monkeypatch):
    outside = tmp_path / "outside.ris"
    outside.write_text("TY  - JOUR\nTI  - Outside\nER  -\n", encoding="utf-8")
    monkeypatch.setattr(
        isolated_webapp,
        "parse_references",
        lambda path: pytest.fail("parse_references should not be called for outside paths"),
    )
    client = isolated_webapp.app.test_client()

    response = client.post("/api/references/parse", json={"path": str(outside)})

    assert response.status_code == 400


def test_pdf_processing_path_cannot_point_outside_upload_dir(isolated_webapp, tmp_path, monkeypatch):
    outside = tmp_path / "outside_pdfs"
    outside.mkdir()
    (outside / "paper.pdf").write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        isolated_webapp,
        "SystematicReviewAutomation",
        lambda **kwargs: pytest.fail("Automation should not start for outside paths"),
    )
    client = isolated_webapp.app.test_client()

    response = client.post("/api/processing/start", json={"pdf_folder": str(outside)})

    assert response.status_code == 400
