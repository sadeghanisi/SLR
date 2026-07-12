import csv
import io
import json
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import WebApp.app as webapp
from WebApp.services import export_service, processing_service, response_builders, workspace_service
import workspace_store
from housing_enhanced import ScreeningResult
from ingestion import AbstractScreener, AbstractScreeningResult


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
        "pdf_folder": "",
        "pdf_display_names": {},
        "workspace": None,
        "reference_uploads": {},
    })
    webapp.runtime_state.initialize(webapp.session)

    webapp.app.config.update(TESTING=True)
    return webapp


def _create_workspace(client, root: Path, name: str = "Review"):
    response = client.post(
        "/api/workspaces/create",
        json={"path": str(root), "name": name, "api_key": "sk-should-not-persist"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["is_open"] is True
    assert data["workspace"]["name"] == name
    assert "path" not in data["workspace"]
    return data


def _db_dump(root: Path) -> str:
    with sqlite3.connect(root / workspace_store.DATABASE_NAME) as conn:
        return "\n".join(conn.iterdump())


def _screening_runtime(app_module):
    return app_module.runtime_state.screening(app_module.session)


def _processing_runtime(app_module):
    return app_module.runtime_state.processing(app_module.session)


def _reset_webapp_session(app_module):
    app_module.session.clear()
    app_module.session.update({
        "references": [],
        "dedup_stats": None,
        "pdf_folder": "",
        "pdf_display_names": {},
        "workspace": None,
        "reference_uploads": {},
    })
    app_module.runtime_state.initialize(app_module.session)


PROCESSING_START_KEYS = {"status", "total"}
PROCESSING_STATUS_KEYS = {
    "active",
    "stats",
    "counters",
    "screening_count",
    "extraction_count",
    "reports",
    "report_errors",
    "error",
    "summary",
}
PROCESSING_RESULT_KEYS = {
    "screening",
    "extraction",
    "counters",
    "reports",
    "report_errors",
    "error",
    "summary",
}
PROCESSING_REPORT_KEYS = {
    "screening_csv",
    "screening_excel",
    "extraction_csv",
    "extraction_excel",
    "summary_report",
    "audit_ledger",
}
PROCESSING_COUNTER_KEYS = {
    "total_files",
    "processed_files",
    "included",
    "excluded",
    "flagged",
    "failed",
}


def _assert_processing_status_shape(payload):
    assert set(payload) == PROCESSING_STATUS_KEYS
    assert set(payload["counters"]) == PROCESSING_COUNTER_KEYS
    assert set(payload["reports"]) == PROCESSING_REPORT_KEYS
    assert isinstance(payload["report_errors"], list)
    assert isinstance(payload["error"], str)


def _assert_processing_results_shape(payload):
    assert set(payload) == PROCESSING_RESULT_KEYS
    assert set(payload["counters"]) == PROCESSING_COUNTER_KEYS
    assert set(payload["reports"]) == PROCESSING_REPORT_KEYS
    assert isinstance(payload["screening"], list)
    assert isinstance(payload["extraction"], list)
    assert isinstance(payload["report_errors"], list)
    assert isinstance(payload["error"], str)


class ContractAutomation:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        output_dir = Path(kwargs["output_folder"])
        output_dir.mkdir(parents=True, exist_ok=True)
        pdfs = sorted(Path(kwargs["pdf_folder"]).glob("*.pdf"))
        self.filename = pdfs[0].name if pdfs else "paper.pdf"
        self.stats = {
            "total_files": len(pdfs),
            "processed_files": 0,
            "likely_include": 0,
            "likely_exclude": 0,
            "flag_for_review": 0,
            "flag_for_human_review": 0,
            "failed_files": 0,
            "total_api_tokens": 0,
            "total_processing_time": 0.0,
            "current_file": "",
        }
        self.screening_results = []
        self.extraction_results = []
        self.screening_csv = output_dir / "screening.csv"
        self.screening_excel = output_dir / "screening.xlsx"
        self.extraction_csv = output_dir / "extraction.csv"
        self.extraction_excel = output_dir / "extraction.xlsx"
        self.summary_report = output_dir / "summary.txt"
        self.audit_ledger = Path(kwargs.get("audit_ledger", output_dir / "audit.jsonl"))
        self.text_cache_path = Path(kwargs.get("text_cache_folder", output_dir / "text_cache")) / "paper.txt"

    def process_pdfs(self):
        self.screening_results = [
            ScreeningResult(
                filename=self.filename,
                decision="Likely Include",
                reasoning="Meets criteria",
                notes="",
                stage="Full-text",
                processing_time=0.1,
                text_length=64,
                api_tokens_used=5,
            )
        ]
        self.stats.update({
            "processed_files": 1,
            "likely_include": 1,
            "total_api_tokens": 5,
            "total_processing_time": 0.1,
        })
        self.text_cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.text_cache_path.write_text("full paper text should not be returned", encoding="utf-8")
        self.audit_ledger.parent.mkdir(parents=True, exist_ok=True)
        self.audit_ledger.write_text(
            json.dumps({
                "kind": "screening",
                "filename": self.filename,
                "stage": "Full-text",
                "provider_profile": {"provider": "FakeProvider"},
                "model": "fake-model",
                "prompt_hash": "prompt-hash",
                "text_hash": "text-hash",
                "cache_key": "cache-key",
            }) + "\n",
            encoding="utf-8",
        )
        for path in (self.screening_csv, self.screening_excel, self.summary_report):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fake report", encoding="utf-8")
        return {
            "screening_csv": str(self.screening_csv),
            "screening_excel": str(self.screening_excel),
            "summary_report": str(self.summary_report),
            "audit_ledger": str(self.audit_ledger),
            "screened_count": 1,
        }

    def get_paper_text_metadata(self, filename):
        return {
            "text_hash": "text-hash",
            "text_cache_path": str(self.text_cache_path),
            "extraction_method": "fake",
            "extraction_status": "ok",
            "extracted_char_count": 64,
        }

    def write_screening_csv(self):
        self.screening_csv.write_text("fake csv", encoding="utf-8")

    def write_screening_excel(self):
        self.screening_excel.write_text("fake xlsx", encoding="utf-8")

    def _generate_summary(self):
        self.summary_report.write_text("fake summary", encoding="utf-8")


def test_workspace_endpoints_create_open_close_and_recent_are_sanitized(isolated_webapp, tmp_path):
    client = isolated_webapp.app.test_client()
    root = tmp_path / "workspace"

    created = _create_workspace(client, root, name="Workspace A")
    workspace_id = created["workspace"]["workspace_id"]
    assert set(created) == {"is_open", "workspace"}
    assert {
        "workspace_id",
        "name",
        "schema_version",
        "pdf_folder",
        "counts",
    }.issubset(created["workspace"])

    current = client.get("/api/workspaces/current").get_json()
    assert set(current) == {"is_open", "workspace"}
    assert current["is_open"] is True
    assert current["workspace"]["workspace_id"] == workspace_id
    assert "path" not in current["workspace"]

    recent = client.get("/api/workspaces/recent").get_json()["recent"]
    assert recent == [{
        "workspace_id": workspace_id,
        "name": "Workspace A",
        "review_title": "",
        "review_type": "",
        "last_opened_at": recent[0]["last_opened_at"],
    }]
    assert "path" not in recent[0]
    assert "api_key" not in str(recent)
    assert "sk-should-not-persist" not in isolated_webapp.SETTINGS_FILE.read_text(encoding="utf-8")

    closed = client.post("/api/workspaces/close").get_json()
    assert closed == {"is_open": False, "workspace": None}

    opened = client.post("/api/workspaces/open", json={"workspace_id": workspace_id}).get_json()
    assert opened["is_open"] is True
    assert opened["workspace"]["workspace_id"] == workspace_id
    assert "sk-should-not-persist" not in _db_dump(root)


def test_workspace_direct_and_recent_reopen_reconcile_stale_automation_run(
    isolated_webapp,
    tmp_path,
):
    from WebApp.services import job_guard

    client = isolated_webapp.app.test_client()
    root = tmp_path / "workspace"
    created = _create_workspace(client, root, name="Recovery Workspace")
    workspace_id = created["workspace"]["workspace_id"]
    with workspace_store.workspace_connection(root) as conn:
        assert conn.execute("SELECT COUNT(*) FROM automation_runs").fetchone()[0] == 0

    client.post("/api/workspaces/close")
    run_id = workspace_store.create_automation_run(
        root,
        run_id="abandoned-run",
        run_type="full_text_processing",
        input_count=2,
        metadata={"output_folder": "exports/abandoned"},
    )
    partial = root / "exports" / "abandoned" / "partial.csv"
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_text("partial output", encoding="utf-8")
    screening = _screening_runtime(isolated_webapp)
    processing = _processing_runtime(isolated_webapp)
    state_identity = (
        screening,
        screening.stop_event,
        processing,
        processing.stop_event,
    )

    recent_open = client.post("/api/workspaces/open", json={"workspace_id": workspace_id})
    recent_payload = recent_open.get_json()
    with workspace_store.workspace_connection(root) as conn:
        first = dict(conn.execute(
            "SELECT run_id, status, finished_at, output_count, metadata_json "
            "FROM automation_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone())

    assert recent_open.status_code == 200
    assert set(recent_payload) == {"is_open", "workspace"}
    assert recent_payload["workspace"]["workspace_id"] == workspace_id
    assert first["status"] == "interrupted"
    assert first["finished_at"]
    assert first["output_count"] == 0
    assert json.loads(first["metadata_json"]) == {"output_folder": "exports/abandoned"}
    assert partial.read_text(encoding="utf-8") == "partial output"
    assert _screening_runtime(isolated_webapp) is state_identity[0]
    assert _screening_runtime(isolated_webapp).stop_event is state_identity[1]
    assert _processing_runtime(isolated_webapp) is state_identity[2]
    assert _processing_runtime(isolated_webapp).stop_event is state_identity[3]
    assert processing.thread is None
    assert processing.automation is None
    assert processing.reports == {}
    assert job_guard.active_job() is None
    current = client.get("/api/workspaces/current")
    assert current.status_code == 200
    assert set(current.get_json()) == {"is_open", "workspace"}

    client.post("/api/workspaces/close")
    direct_open = client.post("/api/workspaces/open", json={"path": str(root)})
    with workspace_store.workspace_connection(root) as conn:
        second = dict(conn.execute(
            "SELECT run_id, status, finished_at, output_count, metadata_json "
            "FROM automation_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone())

    assert direct_open.status_code == 200
    assert set(direct_open.get_json()) == {"is_open", "workspace"}
    assert second == first
    assert len(workspace_store.get_export_metadata(root)["automation_runs"]) == 1
    assert workspace_store.get_export_metadata(root)["automation_runs"][0]["status"] == "interrupted"


def test_workspace_create_rejects_unsafe_root(isolated_webapp, tmp_path):
    client = isolated_webapp.app.test_client()

    response = client.post("/api/workspaces/create", json={"path": tmp_path.anchor})

    assert response.status_code == 400


def test_references_persist_in_workspace_mode(isolated_webapp, tmp_path):
    client = isolated_webapp.app.test_client()
    root = tmp_path / "workspace"
    _create_workspace(client, root)

    upload = client.post(
        "/api/references/upload",
        data={"file": (io.BytesIO(
            b"TY  - JOUR\nTI  - Workspace Study\nAU  - Doe, Jane\nPY  - 2025\nDO  - 10.1/workspace\nER  -\n"
        ), "refs.ris")},
        content_type="multipart/form-data",
    )
    assert upload.status_code == 200
    uploaded = upload.get_json()
    assert uploaded["path"].startswith("workspace-upload:")
    assert not Path(uploaded["path"]).is_absolute()

    parsed = client.post("/api/references/parse", json={"path": uploaded["path"]})
    assert parsed.status_code == 200
    data = parsed.get_json()
    assert data["count"] == 1
    assert data["workspace"]["record_count"] == 1
    assert data["workspace"]["summary"]["counts"]["records_by_origin"]["imported_reference"] == 1

    with workspace_store.workspace_connection(root) as conn:
        source = conn.execute("SELECT original_filename, record_count FROM sources").fetchone()
        record = conn.execute("SELECT title, doi FROM records").fetchone()
        links = conn.execute("SELECT COUNT(*) AS count FROM record_sources").fetchone()["count"]

    assert source["original_filename"] == "refs.ris"
    assert source["record_count"] == 1
    assert record["title"] == "Workspace Study"
    assert record["doi"] == "10.1/workspace"
    assert links == 1


def test_workspace_deduplicate_endpoint_persists_active_queue_counts(isolated_webapp, tmp_path):
    client = isolated_webapp.app.test_client()
    root = tmp_path / "workspace"
    created = _create_workspace(client, root)
    workspace_id = created["workspace"]["workspace_id"]
    ris = (
        "TY  - JOUR\nTI  - First DOI Study\nPY  - 2024\nDO  - 10.2/dup\nER  -\n"
        "TY  - JOUR\nTI  - Alternate DOI Study\nPY  - 2025\nDO  - 10.2/DUP\nER  -\n"
        "TY  - JOUR\nTI  - Deep learning for screening records\nPY  - 2024\nER  -\n"
        "TY  - JOUR\nTI  - Deep-learning for record screening\nPY  - 2024\nER  -\n"
    )

    upload = client.post(
        "/api/references/upload",
        data={"file": (io.BytesIO(ris.encode("utf-8")), "refs.ris")},
        content_type="multipart/form-data",
    ).get_json()
    parsed = client.post("/api/references/parse", json={"path": upload["path"]}).get_json()
    assert parsed["count"] == 4

    deduped = client.post("/api/references/deduplicate", json={"threshold": 80})
    assert deduped.status_code == 200
    payload = deduped.get_json()

    assert payload["stats"]["total_before"] == 4
    assert payload["stats"]["total_after"] == 2
    assert payload["stats"]["removed_doi"] == 1
    assert payload["stats"]["removed_fuzzy"] == 1
    assert payload["remaining"] == 2
    assert payload["workspace"]["summary"]["counts"]["active_unique_records"] == 2
    assert payload["workspace"]["summary"]["counts"]["duplicate_records"] == 2

    client.post("/api/workspaces/close")
    reopened = client.post("/api/workspaces/open", json={"workspace_id": workspace_id}).get_json()
    queue = client.get("/api/workspace/review/queue").get_json()

    assert reopened["workspace"]["counts"]["active_unique_records"] == 2
    assert reopened["workspace"]["counts"]["duplicate_records"] == 2
    assert queue["total_count"] == 2
    assert queue["visible_count"] == 2
    assert queue["active_review_item_count"] == 2
    assert queue["filter_scope_count"] == 2
    assert queue["active_unique_records"] == 2
    assert queue["duplicate_records"] == 2
    assert queue["raw_imported_records"] == 4
    assert queue["active_records_by_origin"]["imported_reference"] == 2
    assert queue["imported_reference_records"] == 2
    assert queue["pdf_only_records"] == 0
    assert queue["manual_records"] == 0
    assert queue["workspace_counts"]["raw_imported_records"] == 4
    assert queue["workspace_counts"]["active_unique_records"] == 2
    with workspace_store.workspace_connection(root) as conn:
        duplicate_methods = {
            row["dedup_method"]
            for row in conn.execute(
                "SELECT dedup_method FROM record_sources WHERE dedup_status = 'duplicate'"
            ).fetchall()
        }
        source_links = conn.execute("SELECT COUNT(*) AS count FROM record_sources").fetchone()["count"]

    assert duplicate_methods == {workspace_store.DEDUP_METHOD_DOI, workspace_store.DEDUP_METHOD_FUZZY_TITLE}
    assert source_links == 4


def test_pdfs_persist_in_workspace_mode_and_duplicate_basenames_are_distinct(isolated_webapp, tmp_path):
    client = isolated_webapp.app.test_client()
    root = tmp_path / "workspace"
    _create_workspace(client, root)

    response = client.post(
        "/api/pdfs/upload",
        data={
            "files": [
                (io.BytesIO(b"%PDF-1.4 one\n"), "Paper.pdf"),
                (io.BytesIO(b"%PDF-1.4 two\n"), "Paper.pdf"),
            ]
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["folder"] == workspace_store.WORKSPACE_PDF_TOKEN
    assert data["count"] == 2
    assert all(not Path(item["path"]).is_absolute() for item in data["files"])

    listed = client.get("/api/pdfs/list").get_json()["files"]
    assert len(listed) == 2
    assert listed[0]["display_name"] == "Paper.pdf"
    assert listed[1]["display_name"] == "Paper.pdf"
    assert listed[0]["name"] != listed[1]["name"]
    assert all(not Path(item["path"]).is_absolute() for item in listed)

    rows = workspace_store.list_pdf_metadata(root)
    assert len(rows) == 2
    assert {row["display_name"] for row in rows} == {"Paper.pdf"}
    assert all(row["sha256"] for row in rows)


def test_workspace_pdf_view_and_delete_reject_traversal(isolated_webapp, tmp_path):
    client = isolated_webapp.app.test_client()
    root = tmp_path / "workspace"
    _create_workspace(client, root)

    upload = client.post(
        "/api/pdfs/upload",
        data={"files": (io.BytesIO(b"%PDF-1.4\n"), "Paper.pdf")},
        content_type="multipart/form-data",
    )
    assert upload.status_code == 200
    outside = root / "workspace.sqlite3"
    assert outside.exists()

    view = client.get("/api/pdfs/file/..%2Fworkspace.sqlite3")
    delete = client.post("/api/pdfs/delete", json={"filename": "../workspace.sqlite3"})

    assert view.status_code != 200
    assert delete.status_code == 400
    assert outside.exists()


def test_workspace_summary_survives_close_and_open(isolated_webapp, tmp_path):
    client = isolated_webapp.app.test_client()
    root = tmp_path / "workspace"
    created = _create_workspace(client, root)
    workspace_id = created["workspace"]["workspace_id"]

    client.post(
        "/api/references/upload",
        data={"file": (io.BytesIO(b"TY  - JOUR\nTI  - Study\nER  -\n"), "refs.ris")},
        content_type="multipart/form-data",
    )
    upload = client.post(
        "/api/references/upload",
        data={"file": (io.BytesIO(b"TY  - JOUR\nTI  - Study\nER  -\n"), "refs2.ris")},
        content_type="multipart/form-data",
    ).get_json()
    client.post("/api/references/parse", json={"path": upload["path"]})
    client.post(
        "/api/pdfs/upload",
        data={"files": (io.BytesIO(b"%PDF-1.4\n"), "Paper.pdf")},
        content_type="multipart/form-data",
    )

    client.post("/api/workspaces/close")
    reopened = client.post("/api/workspaces/open", json={"workspace_id": workspace_id}).get_json()

    assert reopened["workspace"]["counts"]["records"] == 1
    assert reopened["workspace"]["counts"]["pdfs"] == 1
    assert reopened["workspace"]["counts"]["records_by_origin"]["imported_reference"] == 1
    assert "path" not in reopened["workspace"]


def test_workspace_reopens_after_session_reset_from_recent_metadata(isolated_webapp, tmp_path):
    client = isolated_webapp.app.test_client()
    root = tmp_path / "workspace"
    created = _create_workspace(client, root)
    workspace_id = created["workspace"]["workspace_id"]

    upload = client.post(
        "/api/references/upload",
        data={"file": (io.BytesIO(b"TY  - JOUR\nTI  - Restart Study\nER  -\n"), "refs.ris")},
        content_type="multipart/form-data",
    ).get_json()
    client.post("/api/references/parse", json={"path": upload["path"]})
    client.post(
        "/api/pdfs/upload",
        data={"files": (io.BytesIO(b"%PDF-1.4\n"), "Restart.pdf")},
        content_type="multipart/form-data",
    )
    item = workspace_store.get_review_queue(root)[0]
    workspace_store.add_ai_suggestion(
        root,
        record_id=item["record_id"],
        stage="title_abstract",
        decision="Likely Include",
        rationale="AI include",
    )
    workspace_store.add_human_decision(
        root,
        review_item_id=item["item_id"],
        reviewer_id=workspace_store.DEFAULT_REVIEWER_ID,
        decision="include",
        rationale="Human include",
    )

    _reset_webapp_session(isolated_webapp)
    assert client.get("/api/workspaces/current").get_json() == {"is_open": False, "workspace": None}

    reopened = client.post("/api/workspaces/open", json={"workspace_id": workspace_id}).get_json()
    refs = client.get("/api/references/list").get_json()
    pdfs = client.get("/api/pdfs/list").get_json()
    queue = client.get("/api/workspace/review/queue").get_json()

    assert reopened["is_open"] is True
    assert reopened["workspace"]["counts"]["records"] == 1
    assert reopened["workspace"]["counts"]["pdfs"] == 1
    assert refs["total"] == 1
    assert refs["records"][0]["title"] == "Restart Study"
    assert len(pdfs["files"]) == 1
    assert pdfs["files"][0]["display_name"] == "Restart.pdf"
    assert queue["items"][0]["status"] == "included"
    assert queue["items"][0]["latest_ai_suggestion"]["decision"] == "include"
    assert queue["items"][0]["latest_human_decision"]["decision"] == "include"


def test_workspace_review_endpoints_accept_override_and_summary(isolated_webapp, tmp_path):
    client = isolated_webapp.app.test_client()
    root = tmp_path / "workspace"
    _create_workspace(client, root)

    upload = client.post(
        "/api/references/upload",
        data={"file": (io.BytesIO(b"TY  - JOUR\nTI  - Decision Study\nER  -\n"), "refs.ris")},
        content_type="multipart/form-data",
    ).get_json()
    client.post("/api/references/parse", json={"path": upload["path"]})

    item = workspace_store.get_review_queue(root)[0]
    workspace_store.add_ai_suggestion(
        root,
        record_id=item["record_id"],
        stage="title_abstract",
        decision="Likely Include",
        rationale="AI include",
        metadata={"api_key": "sk-not-stored", "full_prompt": "prompt not stored"},
    )

    queue = client.get("/api/workspace/review/queue").get_json()
    assert set(queue) == {
        "items",
        "total",
        "visible_count",
        "total_count",
        "active_review_item_count",
        "filter_scope_count",
        "current_filter",
        "records_by_origin",
        "active_records_by_origin",
        "active_unique_records",
        "duplicate_records",
        "raw_imported_records",
        "imported_reference_records",
        "pdf_only_records",
        "manual_records",
        "review_items_by_status",
        "ai_suggestion_count",
        "human_decision_count",
        "workspace_counts",
        "summary",
    }
    assert queue["items"][0]["status"] == "suggested"
    assert queue["items"][0]["latest_human_decision"] is None
    assert queue["visible_count"] == 1
    assert queue["total_count"] == 1
    assert queue["active_review_item_count"] == 1
    assert queue["filter_scope_count"] == 1
    assert queue["current_filter"] == {"stage": "", "status": "", "record_origin": ""}
    assert queue["records_by_origin"]["imported_reference"] == 1
    assert queue["active_records_by_origin"]["imported_reference"] == 1
    assert queue["active_unique_records"] == 1
    assert queue["duplicate_records"] == 0
    assert queue["imported_reference_records"] == 1
    assert queue["pdf_only_records"] == 0
    assert queue["manual_records"] == 0
    assert queue["review_items_by_status"]["suggested"] == 1
    assert queue["ai_suggestion_count"] == 1
    assert queue["human_decision_count"] == 0

    suggested = client.get("/api/workspace/review/queue?status=suggested").get_json()
    assert suggested["visible_count"] == 1
    assert suggested["total_count"] == 1
    assert suggested["current_filter"]["status"] == "suggested"

    accepted = client.post(
        "/api/workspace/review/accept-ai",
        json={"review_item_id": item["item_id"], "rationale": "Accept AI"},
    )
    assert accepted.status_code == 200
    assert accepted.get_json()["item"]["status"] == "included"

    overridden = client.post(
        "/api/workspace/review/override",
        json={"review_item_id": item["item_id"], "decision": "maybe", "rationale": "Unclear"},
    )
    assert overridden.status_code == 200
    override_item = overridden.get_json()["item"]
    assert override_item["status"] == "maybe"
    assert override_item["latest_ai_suggestion"]["decision"] == "include"

    summary = client.get("/api/workspace/review/summary").get_json()["summary"]
    assert summary["by_status"]["maybe"] == 1
    assert summary["ai_suggestion_count"] == 1
    assert summary["human_decision_count"] == 2
    assert summary["default_reviewer_id"] == workspace_store.DEFAULT_REVIEWER_ID
    assert summary["exclusion_reasons"]

    dump = _db_dump(root)
    assert "sk-not-stored" not in dump
    assert "prompt not stored" not in dump


def test_workspace_review_full_text_exclude_requires_reason(isolated_webapp, tmp_path):
    client = isolated_webapp.app.test_client()
    root = tmp_path / "workspace"
    _create_workspace(client, root)

    pdf_upload = client.post(
        "/api/pdfs/upload",
        data={"files": (io.BytesIO(b"%PDF-1.4\n"), "FullText.pdf")},
        content_type="multipart/form-data",
    ).get_json()
    pdf_id = pdf_upload["files"][0]["pdf_id"]
    record_id = workspace_store.ensure_record_for_pdf(root, pdf_id)
    item = workspace_store.create_review_item(root, record_id, "full_text", pdf_id=pdf_id)

    pdf_only_queue = client.get("/api/workspace/review/queue?origin=pdf_only").get_json()
    assert pdf_only_queue["visible_count"] == 1
    assert pdf_only_queue["total_count"] == 1
    assert pdf_only_queue["active_review_item_count"] == 1
    assert pdf_only_queue["filter_scope_count"] == 1
    assert pdf_only_queue["current_filter"]["record_origin"] == "pdf_only"
    assert pdf_only_queue["records_by_origin"]["pdf_only"] == 1
    assert pdf_only_queue["active_records_by_origin"]["pdf_only"] == 1
    assert pdf_only_queue["pdf_only_records"] == 1
    assert pdf_only_queue["items"][0]["record_origin"] == "pdf_only"

    missing_reason = client.post(
        "/api/workspace/review/decision",
        json={"review_item_id": item["item_id"], "decision": "exclude", "rationale": "Wrong scope"},
    )
    assert missing_reason.status_code == 400

    with_reason = client.post(
        "/api/workspace/review/decision",
        json={
            "review_item_id": item["item_id"],
            "decision": "exclude",
            "rationale": "Wrong population",
            "exclusion_reason_id": workspace_store.DEFAULT_EXCLUSION_REASONS[0][0],
        },
    )
    assert with_reason.status_code == 200
    assert with_reason.get_json()["item"]["status"] == "excluded"


def test_screening_stop_reaches_active_screener_and_preserves_response_contract(
    isolated_webapp, monkeypatch
):
    client = isolated_webapp.app.test_client()
    provider_started = threading.Event()
    release_provider = threading.Event()
    provider_calls = []
    screeners = []

    class ControlledLLM:
        def chat_completion_with_tokens(self, messages, **kwargs):
            provider_calls.append(len(provider_calls) + 1)
            if len(provider_calls) == 1:
                provider_started.set()
                if not release_provider.wait(timeout=2):
                    raise RuntimeError("test provider was not released")
            return '{"decision":"Include","rationale":"Eligible","confidence":"High"}', 3

    class RecordingScreener(AbstractScreener):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            screeners.append(self)

    monkeypatch.setattr(isolated_webapp, "LLMManager", lambda *args, **kwargs: ControlledLLM())
    monkeypatch.setattr(isolated_webapp, "AbstractScreener", RecordingScreener)
    isolated_webapp.session["references"] = [
        {"record_id": f"rec-{index}", "title": f"Study {index}", "abstract": "Safe abstract"}
        for index in range(1, 4)
    ]

    started = client.post(
        "/api/screening/start",
        json={"provider": "Fake", "api_key": "DUMMY_SCREENING_KEY", "rate_delay": 0},
    )
    thread = _screening_runtime(isolated_webapp).thread
    try:
        assert started.status_code == 200
        assert started.get_json() == {"status": "started", "total": 3}
        assert provider_started.wait(timeout=1)

        stopped = client.post("/api/screening/stop")
        same_event = screeners[0]._stop is _screening_runtime(isolated_webapp).stop_event
    finally:
        release_provider.set()
        thread.join(timeout=2)

    assert stopped.status_code == 200
    assert stopped.get_json() == {"status": "stopping"}
    assert same_event
    assert _screening_runtime(isolated_webapp).stop_event.is_set()
    assert not thread.is_alive()
    assert provider_calls == [1]
    results = client.get("/api/screening/results").get_json()
    assert set(results) == {"results", "total"}
    assert results["total"] < 3
    assert "DUMMY_SCREENING_KEY" not in json.dumps({
        "results": results,
        "progress": _screening_runtime(isolated_webapp).progress,
    })


def test_abstract_screener_stop_uses_external_event_between_records():
    stop_event = threading.Event()
    first_callback_started = threading.Event()
    release_callback = threading.Event()
    provider_calls = []
    completed = []

    class ImmediateLLM:
        def chat_completion_with_tokens(self, messages, **kwargs):
            provider_calls.append(len(provider_calls) + 1)
            return '{"decision":"Include","rationale":"Eligible","confidence":"High"}', 2

    screener = AbstractScreener(
        ImmediateLLM(),
        rate_limit_delay=0.5,
        stop_event=stop_event,
    )

    def callback(result, index, total):
        first_callback_started.set()
        if not release_callback.wait(timeout=2):
            raise RuntimeError("test callback was not released")

    thread = threading.Thread(
        target=lambda: completed.extend(screener.screen_all(
            [
                {"record_id": "rec-1", "title": "First", "abstract": "Safe"},
                {"record_id": "rec-2", "title": "Second", "abstract": "Safe"},
            ],
            "Include eligible studies",
            callback=callback,
        )),
        daemon=True,
    )
    thread.start()
    try:
        assert first_callback_started.wait(timeout=1)
        screener.stop()
        assert stop_event.is_set()
    finally:
        release_callback.set()
        thread.join(timeout=2)

    assert screener._stop is stop_event
    assert not thread.is_alive()
    assert provider_calls == [1]
    assert [result.record_id for result in completed] == ["rec-1"]


def test_legacy_abstract_screening_normal_completion_and_export(isolated_webapp, monkeypatch):
    client = isolated_webapp.app.test_client()

    class ImmediateLLM:
        def chat_completion_with_tokens(self, messages, **kwargs):
            return '{"decision":"Include","rationale":"Eligible","confidence":"High"}', 4

    monkeypatch.setattr(isolated_webapp, "LLMManager", lambda *args, **kwargs: ImmediateLLM())
    isolated_webapp.session["references"] = [
        {"record_id": "legacy-1", "title": "Legacy Study", "abstract": "Safe abstract"}
    ]

    started = client.post(
        "/api/screening/start",
        json={"provider": "Fake", "api_key": "DUMMY_SCREENING_KEY", "rate_delay": 0},
    )
    thread = _screening_runtime(isolated_webapp).thread
    thread.join(timeout=2)

    assert started.status_code == 200
    assert started.get_json() == {"status": "started", "total": 1}
    assert not thread.is_alive()
    results = client.get("/api/screening/results").get_json()
    assert set(results) == {"results", "total"}
    assert results["total"] == 1
    assert set(results["results"][0]) == {
        "record_id", "title", "decision", "rationale", "confidence", "tokens", "proc_time"
    }
    assert results["results"][0]["decision"] == "Include"
    assert [event["type"] for event in _screening_runtime(isolated_webapp).progress] == [
        "screening_progress",
        "screening_done",
    ]

    exported = client.post("/api/screening/export", json={"format": "csv"})
    assert exported.status_code == 200
    assert b"Legacy Study" in exported.data
    assert b"Include" in exported.data


def test_workspace_abstract_screening_persists_ai_suggestion_only(isolated_webapp, tmp_path, monkeypatch):
    client = isolated_webapp.app.test_client()
    root = tmp_path / "workspace"
    _create_workspace(client, root)

    upload = client.post(
        "/api/references/upload",
        data={"file": (io.BytesIO(b"TY  - JOUR\nTI  - Screen Study\nAB  - Useful abstract\nER  -\n"), "refs.ris")},
        content_type="multipart/form-data",
    ).get_json()
    client.post("/api/references/parse", json={"path": upload["path"]})

    class FakeLLMManager:
        def __init__(self, *args, **kwargs):
            pass

    class FakeScreener:
        def __init__(self, llm, rate_limit_delay=0.5, *, stop_event=None):
            self.llm = llm
            self.rate_limit_delay = rate_limit_delay
            assert stop_event is _screening_runtime(isolated_webapp).stop_event

        def screen_all(self, records, criteria, callback=None):
            results = []
            for idx, record in enumerate(records, start=1):
                result = AbstractScreeningResult(
                    record_id=record["record_id"],
                    title=record["title"],
                    decision="Likely Include",
                    rationale="Meets criteria",
                    confidence="High",
                    tokens=7,
                    proc_time=0.01,
                )
                results.append(result)
                if callback:
                    callback(result, idx, len(records))
            return results

    monkeypatch.setattr(isolated_webapp, "LLMManager", FakeLLMManager)
    monkeypatch.setattr(isolated_webapp, "AbstractScreener", FakeScreener)

    started = client.post(
        "/api/screening/start",
        json={
            "provider": "Fake",
            "api_key": "sk-not-stored",
            "model": "fake-model",
            "criteria": "Include useful studies",
        },
    )
    assert started.status_code == 200
    _screening_runtime(isolated_webapp).thread.join(timeout=2)

    results = client.get("/api/screening/results").get_json()
    queue = client.get("/api/workspace/review/queue").get_json()

    assert results["total"] == 1
    assert results["results"][0]["decision"] == "Likely Include"
    assert queue["items"][0]["status"] == "suggested"
    assert queue["items"][0]["latest_ai_suggestion"]["decision"] == "include"
    assert queue["items"][0]["latest_human_decision"] is None
    assert "sk-not-stored" not in _db_dump(root)


def test_workspace_full_text_processing_results_persist_ai_suggestion(isolated_webapp, tmp_path):
    client = isolated_webapp.app.test_client()
    root = tmp_path / "workspace"
    _create_workspace(client, root)

    upload = client.post(
        "/api/pdfs/upload",
        data={"files": (io.BytesIO(b"%PDF-1.4\n"), "FullTextResult.pdf")},
        content_type="multipart/form-data",
    ).get_json()
    server_filename = upload["files"][0]["filename"]

    audit_path = tmp_path / "audit.jsonl"
    audit_path.write_text(
        json.dumps({
            "kind": "screening",
            "filename": server_filename,
            "stage": "Full-text",
            "provider_profile": {"provider": "FakeProvider"},
            "model": "fake-model",
            "prompt_hash": "prompt-hash",
            "text_hash": "text-hash",
            "cache_key": "cache-key",
            "cache_hit": False,
        }) + "\n",
        encoding="utf-8",
    )
    fake_auto = SimpleNamespace(
        screening_results=[
            ScreeningResult(
                filename=server_filename,
                decision="Likely Exclude",
                reasoning="Wrong population",
                notes="",
                stage="Full-text",
                processing_time=0.2,
                text_length=1200,
                api_tokens_used=17,
            )
        ],
        audit_ledger=str(audit_path),
        get_paper_text_metadata=lambda filename: {"text_hash": "text-hash"},
    )

    processing_service.persist_workspace_processing_suggestions(
        isolated_webapp.session["workspace"],
        fake_auto,
        display_names=isolated_webapp.session.get("pdf_display_names", {}),
    )
    queue = client.get("/api/workspace/review/queue").get_json()["items"]

    assert len(queue) == 1
    assert queue[0]["stage"] == "full_text"
    assert queue[0]["status"] == "suggested"
    assert queue[0]["latest_ai_suggestion"]["decision"] == "exclude"
    assert queue[0]["latest_ai_suggestion"]["provider"] == "FakeProvider"
    assert queue[0]["latest_ai_suggestion"]["prompt_hash"] == "prompt-hash"
    assert queue[0]["latest_human_decision"] is None


def test_workspace_processing_paths_are_scoped_and_api_paths_are_relative(isolated_webapp, tmp_path, monkeypatch):
    client = isolated_webapp.app.test_client()
    instances = []

    class WorkspaceScopedAutomation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            instances.append(self)
            output_dir = Path(kwargs["output_folder"])
            pdfs = sorted(Path(kwargs["pdf_folder"]).glob("*.pdf"))
            self.filename = pdfs[0].name
            self.stats = {
                "total_files": 1,
                "processed_files": 0,
                "likely_include": 0,
                "likely_exclude": 0,
                "flag_for_review": 0,
                "flag_for_human_review": 0,
                "failed_files": 0,
                "total_api_tokens": 0,
                "total_processing_time": 0.1,
                "current_file": "",
            }
            self.screening_results = []
            self.extraction_results = []
            self.screening_csv = output_dir / "screening.csv"
            self.screening_excel = output_dir / "screening.xlsx"
            self.extraction_csv = output_dir / "extraction.csv"
            self.extraction_excel = output_dir / "extraction.xlsx"
            self.summary_report = output_dir / "summary.txt"
            self.audit_ledger = Path(kwargs["audit_ledger"])
            self.text_cache_path = Path(kwargs["text_cache_folder"]) / "paper.txt"

        def process_pdfs(self):
            Path(self.kwargs["cache_folder"]).mkdir(parents=True, exist_ok=True)
            Path(self.kwargs["cache_folder"], "screening_cache.json").write_text("{}", encoding="utf-8")
            self.text_cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.text_cache_path.write_text("cached text", encoding="utf-8")
            self.screening_results = [
                ScreeningResult(
                    filename=self.filename,
                    decision="Likely Include",
                    reasoning="Meets criteria",
                    notes="",
                    stage="Full-text",
                    processing_time=0.1,
                    text_length=42,
                    api_tokens_used=3,
                )
            ]
            self.audit_ledger.write_text(
                json.dumps({
                    "kind": "screening",
                    "filename": self.filename,
                    "stage": "Full-text",
                    "provider_profile": {"provider": "FakeProvider"},
                    "model": "fake-model",
                    "prompt_hash": "prompt-hash",
                    "text_hash": "text-hash",
                    "cache_key": "cache-key",
                }) + "\n",
                encoding="utf-8",
            )
            for path in (self.screening_csv, self.screening_excel, self.summary_report):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fake report", encoding="utf-8")
            self.stats["processed_files"] = 1
            self.stats["likely_include"] = 1
            return {
                "screening_csv": str(self.screening_csv),
                "screening_excel": str(self.screening_excel),
                "summary_report": str(self.summary_report),
                "audit_ledger": str(self.audit_ledger),
                "screened_count": 1,
            }

        def get_paper_text_metadata(self, filename):
            return {
                "text_hash": "text-hash",
                "text_cache_path": str(self.text_cache_path),
                "extraction_method": "fake",
                "extraction_status": "ok",
                "extracted_char_count": 42,
            }

    monkeypatch.setattr(isolated_webapp, "SystematicReviewAutomation", WorkspaceScopedAutomation)

    roots = [tmp_path / "workspace-a", tmp_path / "workspace-b"]
    responses = []
    for index, root in enumerate(roots, start=1):
        _create_workspace(client, root, name=f"Workspace {index}")
        upload = client.post(
            "/api/pdfs/upload",
            data={"files": (io.BytesIO(b"%PDF-1.4\n"), f"Paper {index}.pdf")},
            content_type="multipart/form-data",
        )
        assert upload.status_code == 200
        start = client.post("/api/processing/start", json={"provider": "Fake", "api_key": "sk-not-stored"})
        assert start.status_code == 200
        start_payload = start.get_json()
        assert set(start_payload) == PROCESSING_START_KEYS
        assert start_payload == {"status": "started", "total": 1}
        _processing_runtime(isolated_webapp).thread.join(timeout=2)
        status_payload = client.get("/api/processing/status").get_json()
        _assert_processing_status_shape(status_payload)
        responses.append(client.get("/api/processing/results").get_json())
        client.post("/api/workspaces/close")

    assert len(instances) == 2
    for root, instance, response in zip(roots, instances, responses):
        _assert_processing_results_shape(response)
        Path(instance.kwargs["output_folder"]).resolve().relative_to((root / "exports").resolve())
        Path(instance.kwargs["cache_folder"]).resolve().relative_to((root / "cache").resolve())
        Path(instance.kwargs["text_cache_folder"]).resolve().relative_to((root / "cache").resolve())
        Path(instance.kwargs["audit_ledger"]).resolve().relative_to((root / "audit").resolve())
        assert (root / "exports").is_dir()
        assert (root / "cache").is_dir()
        assert (root / "audit").is_dir()
        response_text = json.dumps(response)
        assert str(root) not in response_text
        assert str(isolated_webapp.OUTPUT_DIR) not in response_text
        assert response["reports"]["screening_excel"]["path"].startswith("exports/")
        assert not Path(response["reports"]["screening_excel"]["path"]).is_absolute()
        assert response["reports"]["audit_ledger"]["path"].startswith("audit/")
        assert response["screening"][0]["text_cache_path"].startswith("cache/")
        assert not Path(response["screening"][0]["text_cache_path"]).is_absolute()
        with workspace_store.workspace_connection(root) as conn:
            run = conn.execute("SELECT metadata_json FROM automation_runs").fetchone()
            decision = conn.execute("SELECT automation_run_id FROM decisions").fetchone()
        assert run is not None
        assert str(root) not in run["metadata_json"]
        assert "exports/" in run["metadata_json"]
        assert decision["automation_run_id"]

    assert Path(instances[0].kwargs["output_folder"]) != Path(instances[1].kwargs["output_folder"])
    assert not any(isolated_webapp.OUTPUT_DIR.iterdir())


def test_processing_summary_copy_does_not_label_ai_counts_as_prisma():
    template = Path("WebApp/templates/index.html").read_text(encoding="utf-8")
    script = Path("WebApp/static/js/app.js").read_text(encoding="utf-8")

    assert "PRISMA Summary" not in template
    assert "PRISMA summary" not in template
    assert "PRISMA compliant" not in template
    assert "automatic PRISMA compliance" not in template
    assert "full PRISMA workflow coverage" not in template
    assert "PRISMA summary" not in script
    assert "PRISMA compliant" not in script
    assert "automatic PRISMA compliance" not in script
    assert "full PRISMA workflow coverage" not in script
    assert "updatePrismaSummary" not in script
    assert "Accept AI" not in script
    assert "AI processing run summary" in template
    assert "These counts describe the current AI-assisted processing run." in template
    assert "They are not PRISMA-ready human-final counts." in template
    assert "No workspace is open. Create or open a workspace to save your review progress." in template
    assert "Create or Open a Workspace" in template
    assert "Continue Without Workspace" in template
    assert "Workspace Mode - saved locally" in script
    assert "Legacy Mode - one-off run" in script
    assert "Finalize from suggestion" in script
    assert "active review items because" in script
    assert "duplicate records are stored for audit but hidden from active screening" in script
    assert "Full-text exclusions should include a reason." in template
    assert "PRISMA-ready counts are derived from workspace data and should be checked before reporting." in template
    assert "AI-only suggestions are not final decisions." in template
    assert "This record was created from a PDF without imported reference metadata." in script
    assert "Current PRISMA-ready count snapshot" in script


def test_legacy_webapp_behavior_still_works_without_workspace(isolated_webapp):
    client = isolated_webapp.app.test_client()

    current = client.get("/api/workspaces/current").get_json()
    assert current == {"is_open": False, "workspace": None}
    assert client.get("/api/workspace/review/summary").status_code == 400

    ref_upload = client.post(
        "/api/references/upload",
        data={"file": (io.BytesIO(b"TY  - JOUR\nTI  - Legacy Study\nER  -\n"), "legacy.ris")},
        content_type="multipart/form-data",
    )
    assert ref_upload.status_code == 200
    ref_data = ref_upload.get_json()
    Path(ref_data["path"]).resolve().relative_to(isolated_webapp.REFERENCE_UPLOAD_DIR.resolve())

    parsed = client.post("/api/references/parse", json={"path": ref_data["path"]})
    assert parsed.status_code == 200
    assert parsed.get_json()["count"] == 1

    pdf_upload = client.post(
        "/api/pdfs/upload",
        data={"files": (io.BytesIO(b"%PDF-1.4\n"), "Legacy.pdf")},
        content_type="multipart/form-data",
    )
    assert pdf_upload.status_code == 200
    pdf_data = pdf_upload.get_json()
    Path(pdf_data["folder"]).resolve().relative_to(isolated_webapp.PDF_UPLOAD_ROOT.resolve())
    Path(pdf_data["files"][0]["path"]).resolve().relative_to(isolated_webapp.PDF_UPLOAD_ROOT.resolve())


def test_legacy_processing_status_results_and_export_contract(isolated_webapp, monkeypatch):
    client = isolated_webapp.app.test_client()
    monkeypatch.setattr(isolated_webapp, "SystematicReviewAutomation", ContractAutomation)

    upload = client.post(
        "/api/pdfs/upload",
        data={"files": (io.BytesIO(b"%PDF-1.4\n"), "Legacy Processing.pdf")},
        content_type="multipart/form-data",
    )
    assert upload.status_code == 200

    start = client.post(
        "/api/processing/start",
        json={
            "provider": "Fake",
            "api_key": "sk-not-returned",
            "screening_prompt": "full prompt should not be returned",
            "extraction_prompt": "extraction prompt should not be returned",
        },
    )
    assert start.status_code == 200
    assert set(start.get_json()) == PROCESSING_START_KEYS
    assert start.get_json()["total"] == 1
    _processing_runtime(isolated_webapp).thread.join(timeout=2)
    assert not _processing_runtime(isolated_webapp).thread.is_alive()

    status = client.get("/api/processing/status").get_json()
    results = client.get("/api/processing/results").get_json()
    _assert_processing_status_shape(status)
    _assert_processing_results_shape(results)

    response_text = json.dumps({"status": status, "results": results})
    assert "sk-not-returned" not in response_text
    assert "full prompt should not be returned" not in response_text
    assert "extraction prompt should not be returned" not in response_text
    assert "full paper text should not be returned" not in response_text
    assert Path(results["reports"]["screening_excel"]["path"]).is_absolute()

    export = client.post("/api/processing/export", json={"which": "screening"})
    assert export.status_code == 200
    assert "attachment" in export.headers.get("Content-Disposition", "")


def test_processing_export_endpoint_reports_missing_results_in_legacy_mode(isolated_webapp):
    client = isolated_webapp.app.test_client()

    response = client.post("/api/processing/export", json={"which": "screening"})

    assert response.status_code == 400
    assert response.get_json() == {"error": "No processing results"}


def test_extracted_workspace_services_preserve_response_shape_and_path_safety(tmp_path):
    root = tmp_path / "workspace"
    handle = workspace_store.create_workspace(root)
    inside = root / "exports" / "run-1" / "screening.xlsx"
    outside = tmp_path / "outside.xlsx"
    inside.parent.mkdir(parents=True, exist_ok=True)
    inside.write_text("report", encoding="utf-8")
    outside.write_text("outside", encoding="utf-8")

    workspace_response = response_builders.workspace_response(handle)
    assert set(workspace_response) == {"is_open", "workspace"}
    assert "path" not in workspace_response["workspace"]
    assert workspace_service.workspace_relative_api_path(handle, inside) == "exports/run-1/screening.xlsx"
    assert workspace_service.workspace_relative_api_path(handle, outside) == ""
    assert workspace_service.workspace_safe_summary(
        {"screening_excel": str(inside), "nested": {"audit_ledger": str(outside)}},
        handle,
    ) == {"screening_excel": "exports/run-1/screening.xlsx", "nested": {"audit_ledger": ""}}

    export_folder = export_service.export_run_folder(root)
    export_folder.relative_to((root / "exports").resolve())
    assert not export_folder.exists()
    manifest = export_service.empty_manifest(export_folder)
    assert manifest.run_id == export_folder.name
    assert manifest.folder == f"exports/{export_folder.name}"
    assert manifest.files == []


def _seed_workspace_export_data(root: Path, tmp_path: Path):
    import_file = tmp_path / "export_refs.ris"
    import_file.write_text("TY  - JOUR\nTI  - Export Study\nER  -\n", encoding="utf-8")
    workspace_store.persist_reference_import(
        root,
        import_file,
        [
            {
                "record_id": "rec-include",
                "title": "Export Study",
                "authors": "Doe J",
                "year": "2026",
                "journal": "Journal",
                "doi": "10.1000/export",
            },
            {
                "record_id": "rec-duplicate",
                "title": "Duplicate Export Study",
                "authors": "Doe J",
                "year": "2026",
                "journal": "Journal",
                "doi": "10.1000/EXPORT",
            },
        ],
        original_filename="export_refs.ris",
    )
    workspace_store.apply_reference_deduplication(root, fuzzy_threshold=90)

    title_item = next(
        item for item in workspace_store.get_review_queue(root)
        if item["record_id"] == "rec-include" and item["stage"] == workspace_store.REVIEW_STAGE_TITLE_ABSTRACT
    )
    workspace_store.add_ai_suggestion(
        root,
        record_id="rec-include",
        stage=workspace_store.REVIEW_STAGE_TITLE_ABSTRACT,
        decision="Likely Exclude",
        rationale="AI was conservative",
        provider="FakeProvider",
        model="fake-model",
        prompt_hash="prompt-hash",
        text_hash="text-hash",
        cache_key="cache-key",
        metadata={
            "api_key": "sk-export-secret",
            "full_prompt": "full prompt should not be exported",
            "full_text": "full paper text should not be exported",
        },
    )
    workspace_store.add_human_decision(
        root,
        review_item_id=title_item["item_id"],
        reviewer_id=workspace_store.DEFAULT_REVIEWER_ID,
        decision="include",
        rationale="Human final include",
    )

    full_text_item = workspace_store.create_review_item(
        root,
        "rec-include",
        workspace_store.REVIEW_STAGE_FULL_TEXT,
    )
    workspace_store.add_ai_suggestion(
        root,
        record_id="rec-include",
        stage=workspace_store.REVIEW_STAGE_FULL_TEXT,
        decision="Likely Include",
        rationale="AI full text suggestion",
        provider="FakeProvider",
        model="fake-model",
    )
    workspace_store.add_human_decision(
        root,
        review_item_id=full_text_item["item_id"],
        reviewer_id=workspace_store.DEFAULT_REVIEWER_ID,
        decision="exclude",
        rationale="Wrong population",
        exclusion_reason_id=workspace_store.DEFAULT_EXCLUSION_REASONS[0][0],
    )

    pdf_name = workspace_store.unique_stored_filename("Pdf Only.pdf")
    (root / "pdfs" / pdf_name).write_bytes(b"%PDF-1.4\n")
    pdf = workspace_store.register_pdf(root, f"pdfs/{pdf_name}", original_filename="Pdf Only.pdf")
    pdf_record_id = workspace_store.ensure_record_for_pdf(root, pdf["pdf_id"])
    workspace_store.create_review_item(
        root,
        pdf_record_id,
        workspace_store.REVIEW_STAGE_FULL_TEXT,
        pdf_id=pdf["pdf_id"],
    )
    workspace_store.add_ai_suggestion(
        root,
        record_id=pdf_record_id,
        pdf_id=pdf["pdf_id"],
        stage=workspace_store.REVIEW_STAGE_FULL_TEXT,
        decision="Likely Exclude",
        rationale="AI-only PDF suggestion",
        provider="FakeProvider",
        model="fake-model",
    )

    now = workspace_store.utc_now()
    with workspace_store.workspace_connection(root) as conn:
        conn.execute(
            """
            INSERT INTO records(
                record_id, title, abstract, authors, year, journal, doi,
                keywords, source_file, record_origin, created_at, updated_at,
                metadata_json
            )
            VALUES (?, ?, '', '', '', '', '', '', '', ?, ?, ?, '{}')
            """,
            ("manual-1", "Manual Record", workspace_store.RECORD_ORIGIN_MANUAL, now, now),
        )
    workspace_store.create_review_item(root, "manual-1", workspace_store.REVIEW_STAGE_TITLE_ABSTRACT)


def _read_csv(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_workspace_exports_generate_files_are_path_safe_and_downloadable(isolated_webapp, tmp_path):
    client = isolated_webapp.app.test_client()
    root = tmp_path / "workspace"
    _create_workspace(client, root)
    _seed_workspace_export_data(root, tmp_path)

    summary = client.get("/api/workspace/exports/summary")
    assert summary.status_code == 200
    summary_payload = summary.get_json()
    assert summary_payload["label"] == "Workspace reporting data"
    assert summary_payload["latest_export"] is None
    assert summary_payload["counts"]["label"] == "PRISMA-ready counts"

    generated = client.post("/api/workspace/exports/generate", json={})
    assert generated.status_code == 200
    payload = generated.get_json()
    response_text = json.dumps(payload)
    assert str(root) not in response_text
    assert "sk-export-secret" not in response_text
    assert "full prompt should not be exported" not in response_text
    assert "full paper text should not be exported" not in response_text

    export = payload["export"]
    export_id = export["export_id"]
    filenames = {item["filename"] for item in export["files"]}
    assert filenames == {
        "workspace_screening_decisions.csv",
        "workspace_screening_decisions.xlsx",
        "workspace_review_items.csv",
        "workspace_ai_suggestions.csv",
        "workspace_human_decisions.csv",
        "workspace_full_text_exclusions.csv",
        "prisma_ready_counts.json",
        "prisma_ready_counts.csv",
        "methods_disclosure.md",
        "export_manifest.json",
    }
    assert all(item["path"].startswith(f"exports/{export_id}/") for item in export["files"])
    assert all(not Path(item["path"]).is_absolute() for item in export["files"])
    export_dir = root / "exports" / export_id
    export_dir.resolve().relative_to((root / "exports").resolve())
    assert all((export_dir / name).is_file() for name in filenames)

    listed = client.get("/api/workspace/exports/list").get_json()
    assert listed["total"] == 1
    assert listed["exports"][0]["export_id"] == export_id
    assert str(root) not in json.dumps(listed)

    download = client.get(f"/api/workspace/exports/download/{export_id}/workspace_screening_decisions.csv")
    assert download.status_code == 200
    assert "attachment" in download.headers.get("Content-Disposition", "")

    traversal = client.get(f"/api/workspace/exports/download/{export_id}/..%2Fworkspace_screening_decisions.csv")
    assert traversal.status_code == 400


def test_workspace_exports_preserve_decision_dedup_origin_and_count_semantics(isolated_webapp, tmp_path):
    client = isolated_webapp.app.test_client()
    root = tmp_path / "workspace"
    _create_workspace(client, root)
    _seed_workspace_export_data(root, tmp_path)

    export = client.post("/api/workspace/exports/generate", json={}).get_json()["export"]
    export_dir = root / "exports" / export["export_id"]
    screening_rows = _read_csv(export_dir / "workspace_screening_decisions.csv")

    title_row = next(
        row for row in screening_rows
        if row["record_id"] == "rec-include" and row["stage"] == workspace_store.REVIEW_STAGE_TITLE_ABSTRACT
    )
    assert title_row["ai_suggestion"] == "exclude"
    assert title_row["ai_is_final"] == "no"
    assert title_row["human_final_decision"] == "include"
    assert title_row["human_rationale"] == "Human final include"
    assert title_row["final_decision_source"] == "human"

    duplicate_row = next(row for row in screening_rows if row["record_id"] == "rec-duplicate")
    assert duplicate_row["is_active_for_screening"] == "0"
    assert duplicate_row["duplicate_status"] == workspace_store.DEDUP_STATUS_DUPLICATE
    assert duplicate_row["duplicate_of_record_id"] == "rec-include"

    pdf_row = next(row for row in screening_rows if row["record_origin"] == workspace_store.RECORD_ORIGIN_PDF_ONLY)
    assert pdf_row["pdf_display_name"] == "Pdf Only.pdf"
    assert pdf_row["human_final_decision"] == ""
    assert pdf_row["final_decision_source"] == "ai_suggestion_not_final"

    full_text_exclusions = _read_csv(export_dir / "workspace_full_text_exclusions.csv")
    assert len(full_text_exclusions) == 1
    assert full_text_exclusions[0]["record_id"] == "rec-include"
    assert full_text_exclusions[0]["exclusion_reason"] == "Wrong population"

    counts = json.loads((export_dir / "prisma_ready_counts.json").read_text(encoding="utf-8"))
    count_values = counts["counts"]
    assert count_values["raw_imported_reference_rows"]["value"] == 2
    assert count_values["imported_reference_records"]["value"] == 2
    assert count_values["active_unique_imported_references"]["value"] == 1
    assert count_values["duplicate_records_hidden_from_active_screening"]["value"] == 1
    assert count_values["pdf_only_records"]["value"] == 1
    assert count_values["manual_records"]["value"] == 1
    assert count_values["title_abstract_human_included"]["value"] == 1
    assert count_values["full_text_human_excluded"]["value"] == 1
    assert count_values["full_text_exclusions_by_reason"]["value"] == {"Wrong population": 1}
    assert count_values["ai_only_unfinalized_suggestions"]["value"] == 1
    assert count_values["full_text_reports_available"]["value"] is None
    assert count_values["full_text_reports_available"]["status"] == "not_available"


def test_workspace_methods_disclosure_is_conservative_and_secret_free(isolated_webapp, tmp_path):
    client = isolated_webapp.app.test_client()
    root = tmp_path / "workspace"
    _create_workspace(client, root)
    _seed_workspace_export_data(root, tmp_path)

    export = client.post("/api/workspace/exports/generate", json={}).get_json()["export"]
    export_dir = root / "exports" / export["export_id"]
    methods = (export_dir / "methods_disclosure.md").read_text(encoding="utf-8")
    text_exports = "\n".join(
        path.read_text(encoding="utf-8")
        for path in export_dir.iterdir()
        if path.suffix.lower() in {".csv", ".json", ".md"}
    )

    assert "local-first AI-assisted workflow tool" in methods
    assert "AI-generated outputs were treated as suggestions only" in methods
    assert "Final include/exclude/maybe decisions were recorded as human decisions" in methods
    assert "Human decisions take precedence over AI suggestions" in methods
    assert "PRISMA compliance" not in methods
    assert "automatic PRISMA compliance" not in methods
    assert "full PRISMA workflow coverage" not in methods
    assert "sk-export-secret" not in text_exports
    assert "full prompt should not be exported" not in text_exports
    assert "full paper text should not be exported" not in text_exports


def test_workspace_export_endpoints_reject_when_no_workspace(isolated_webapp):
    client = isolated_webapp.app.test_client()

    assert client.get("/api/workspace/exports/summary").status_code == 400
    assert client.post("/api/workspace/exports/generate", json={}).status_code == 400
    assert client.get("/api/workspace/exports/list").status_code == 400
    assert client.get("/api/workspace/exports/download/export_1/prisma_ready_counts.json").status_code == 400
