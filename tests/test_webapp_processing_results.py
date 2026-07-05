import threading
from pathlib import Path

import pytest

import WebApp.app as webapp
from housing_enhanced import ExtractionResult, ScreeningResult


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
        "processing_summary": None,
        "processing_error": "",
        "processing_report_errors": [],
        "processing_reports": {},
    })

    webapp.app.config.update(TESTING=True)
    return webapp


def _make_pdf_folder(app_module, names=("server-a.pdf", "server-b.pdf", "server-c.pdf")):
    pdf_dir = app_module.PDF_UPLOAD_ROOT / "batch"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (pdf_dir / name).write_bytes(b"%PDF-1.4\n")
    app_module.session["pdf_folder"] = str(pdf_dir)
    app_module.session["pdf_display_names"] = {
        "server-a.pdf": "Included Paper.pdf",
        "server-b.pdf": "Excluded Paper.pdf",
        "server-c.pdf": "Flagged Paper.pdf",
    }
    return pdf_dir


class FakeProcessingAutomation:
    def __init__(self, **kwargs):
        output_dir = Path(kwargs["output_folder"])
        self.stats = {
            "total_files": 3,
            "processed_files": 0,
            "likely_include": 0,
            "likely_exclude": 0,
            "flag_for_review": 0,
            "flag_for_human_review": 0,
            "failed_files": 0,
            "total_api_tokens": 123,
            "total_processing_time": 1.5,
            "current_file": "",
        }
        self.screening_results = []
        self.extraction_results = []
        self.screening_csv = output_dir / "screening.csv"
        self.screening_excel = output_dir / "screening.xlsx"
        self.extraction_csv = output_dir / "extraction.csv"
        self.extraction_excel = output_dir / "extraction.xlsx"
        self.summary_report = output_dir / "summary.txt"
        self.audit_ledger = output_dir / "audit.jsonl"

    def process_pdfs(self):
        self.screening_results = [
            ScreeningResult("server-a.pdf", "Likely Include", "Meets criteria", "", processing_time=0.1, api_tokens_used=10),
            ScreeningResult("server-b.pdf", "Likely Exclude", "Wrong population", "", processing_time=0.2, api_tokens_used=11),
            ScreeningResult("server-c.pdf", "Flag for Review", "Needs human review", "", processing_time=0.3, api_tokens_used=12),
        ]
        self.extraction_results = [
            ExtractionResult("server-a.pdf", {"title": "Included Paper"}, processing_time=0.4, api_tokens_used=90),
        ]
        for path in (
            self.screening_csv,
            self.screening_excel,
            self.extraction_csv,
            self.extraction_excel,
            self.summary_report,
            self.audit_ledger,
        ):
            path.write_text("fake report", encoding="utf-8")
        return {"screened_count": 3, "extracted_count": 1}


def test_pdf_processing_status_results_and_reports_use_canonical_results(isolated_webapp, monkeypatch):
    pdf_dir = _make_pdf_folder(isolated_webapp)
    monkeypatch.setattr(isolated_webapp, "SystematicReviewAutomation", FakeProcessingAutomation)
    client = isolated_webapp.app.test_client()

    response = client.post("/api/processing/start", json={"pdf_folder": str(pdf_dir)})
    assert response.status_code == 200
    isolated_webapp.session["processing_thread"].join(timeout=2)

    progress = client.get("/api/progress").get_json()
    assert progress["active"] is False
    assert progress["error"] == ""
    assert progress["counters"] == {
        "total_files": 3,
        "processed_files": 3,
        "included": 1,
        "excluded": 1,
        "flagged": 1,
        "failed": 0,
    }
    assert progress["stats"]["likely_include"] == 1
    assert progress["stats"]["likely_exclude"] == 1
    assert progress["stats"]["flag_for_review"] == 1
    assert progress["reports"]["screening_excel"]["exists"] is True
    assert progress["reports"]["summary_report"]["exists"] is True

    results = client.get("/api/processing/results").get_json()
    assert [r["decision"] for r in results["screening"]] == [
        "Likely Include",
        "Likely Exclude",
        "Flag for Review",
    ]
    assert results["screening"][0]["display_filename"] == "Included Paper.pdf"
    assert results["screening"][0]["rationale"] == "Meets criteria"
    assert results["extraction"][0]["display_filename"] == "Included Paper.pdf"

    export = client.post("/api/processing/export", json={"which": "screening"})
    assert export.status_code == 200


def test_webapp_pdf_subfolder_option_controls_list_and_processing_count(isolated_webapp, monkeypatch):
    pdf_dir = _make_pdf_folder(isolated_webapp, names=("server-a.pdf",))
    nested = pdf_dir / "nested"
    nested.mkdir()
    (nested / "server-b.pdf").write_bytes(b"%PDF-1.4\n")
    captured = {}

    class CapturingAutomation(FakeProcessingAutomation):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(isolated_webapp, "SystematicReviewAutomation", CapturingAutomation)
    client = isolated_webapp.app.test_client()

    direct_list = client.get("/api/pdfs/list").get_json()["files"]
    recursive_list = client.get("/api/pdfs/list?include_subfolders=1").get_json()["files"]

    assert [item["name"] for item in direct_list] == ["server-a.pdf"]
    assert [item["name"] for item in recursive_list] == ["nested/server-b.pdf", "server-a.pdf"]
    assert recursive_list[0]["display_name"] == "nested/server-b.pdf"

    response = client.post(
        "/api/processing/start",
        json={"pdf_folder": str(pdf_dir), "include_subfolders": True},
    )
    assert response.status_code == 200
    assert response.get_json()["total"] == 2
    assert captured["include_subfolders"] is True
    isolated_webapp.session["processing_thread"].join(timeout=2)


class MissingReportAutomation(FakeProcessingAutomation):
    def process_pdfs(self):
        self.screening_results = [
            ScreeningResult("server-a.pdf", "Likely Include", "Meets criteria", "", processing_time=0.1),
        ]
        return {"screened_count": 1}

    def write_screening_csv(self):
        return None

    def write_screening_excel(self):
        return None

    def _generate_summary(self):
        return {"screened_count": len(self.screening_results)}


def test_pdf_processing_missing_reports_are_exposed(isolated_webapp, monkeypatch):
    pdf_dir = _make_pdf_folder(isolated_webapp, names=("server-a.pdf",))
    monkeypatch.setattr(isolated_webapp, "SystematicReviewAutomation", MissingReportAutomation)
    client = isolated_webapp.app.test_client()

    response = client.post("/api/processing/start", json={"pdf_folder": str(pdf_dir)})
    assert response.status_code == 200
    isolated_webapp.session["processing_thread"].join(timeout=2)

    progress = client.get("/api/processing/status").get_json()
    assert progress["active"] is False
    assert progress["report_errors"]
    assert any("screening_excel" in err for err in progress["report_errors"])
    assert any("summary_report" in err for err in progress["report_errors"])

    export = client.post("/api/processing/export", json={"which": "screening"})
    assert export.status_code == 404
    assert "screening_excel" in export.get_json()["error"]


class ExplodingAutomation(FakeProcessingAutomation):
    def process_pdfs(self):
        raise RuntimeError("background failure")


def test_pdf_processing_background_exception_is_exposed(isolated_webapp, monkeypatch):
    pdf_dir = _make_pdf_folder(isolated_webapp, names=("server-a.pdf",))
    monkeypatch.setattr(isolated_webapp, "SystematicReviewAutomation", ExplodingAutomation)
    client = isolated_webapp.app.test_client()

    response = client.post("/api/processing/start", json={"pdf_folder": str(pdf_dir)})
    assert response.status_code == 200
    isolated_webapp.session["processing_thread"].join(timeout=2)

    progress = client.get("/api/processing/status").get_json()
    assert progress["active"] is False
    assert progress["error"] == "background failure"
    assert any(event["type"] == "processing_error" for event in isolated_webapp.session["progress"])

    results = client.get("/api/processing/results").get_json()
    assert results["error"] == "background failure"
    assert results["screening"] == []


class PartialFailureAutomation(FakeProcessingAutomation):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.stats["total_files"] = 2

    def process_pdfs(self):
        self.screening_results = [
            ScreeningResult("server-a.pdf", "Likely Include", "Meets criteria", "", processing_time=0.1),
            ScreeningResult("server-b.pdf", "Error", "LLM call failed after retries", "Screening failed", processing_time=0.2),
        ]
        self.extraction_results = [
            ExtractionResult("server-a.pdf", {"title": "Included Paper"}, processing_time=0.3),
        ]
        for path in (
            self.screening_csv,
            self.screening_excel,
            self.extraction_csv,
            self.extraction_excel,
            self.summary_report,
            self.audit_ledger,
        ):
            path.write_text("fake report", encoding="utf-8")
        return {"screened_count": 2, "extracted_count": 1}


def test_pdf_processing_counters_survive_one_failed_pdf_and_one_success(isolated_webapp, monkeypatch):
    pdf_dir = _make_pdf_folder(isolated_webapp, names=("server-a.pdf", "server-b.pdf"))
    isolated_webapp.session["pdf_display_names"] = {
        "server-a.pdf": "Included Paper.pdf",
        "server-b.pdf": "Failed Paper.pdf",
    }
    monkeypatch.setattr(isolated_webapp, "SystematicReviewAutomation", PartialFailureAutomation)
    client = isolated_webapp.app.test_client()

    response = client.post("/api/processing/start", json={"pdf_folder": str(pdf_dir)})
    assert response.status_code == 200
    isolated_webapp.session["processing_thread"].join(timeout=2)

    progress = client.get("/api/progress").get_json()
    assert progress["active"] is False
    assert progress["counters"] == {
        "total_files": 2,
        "processed_files": 2,
        "included": 1,
        "excluded": 0,
        "flagged": 0,
        "failed": 1,
    }

    results = client.get("/api/processing/results").get_json()
    assert [r["decision"] for r in results["screening"]] == ["Likely Include", "Error"]
    assert results["screening"][1]["error"] == "LLM call failed after retries"
    assert results["reports"]["screening_excel"]["exists"] is True
