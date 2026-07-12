"""Tests for the redesigned WebApp workspace navigation and list UX.

These tests cover the start-screen copy, the guided default-location new
workspace flow, recent-workspace privacy, the manual-path advanced mode, the
bounded/scrollable reference list with pagination metadata and "Showing X of Y"
copy, and assertions that no "PRISMA compliant" wording is introduced. They do
not change Phase 3 export logic, PRISMA-ready count definitions, workspace
database schema, or Desktop GUI behavior.
"""

from pathlib import Path

import pytest

import WebApp.app as webapp
import workspace_store


TEMPLATE_PATH = Path("WebApp/templates/index.html")
SCRIPT_PATH = Path("WebApp/static/js/app.js")
CSS_PATH = Path("WebApp/static/css/style.css")


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

    # Redirect the guided default-location root away from the real home folder.
    default_root = tmp_path / "SLR Assistant Workspaces"
    monkeypatch.setattr(workspace_store, "default_workspaces_root", lambda: default_root)

    webapp.app.config.update(TESTING=True)
    return webapp


def _create_default(client, **fields):
    return client.post("/api/workspaces/create", json=fields).get_json()


def test_start_screen_copy_exists_in_template():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "Start a Review Project" in template
    assert "+ New Workspace" in template
    assert "Open Existing Workspace" in template
    assert "Continue Without Workspace" in template
    assert "Use this for a quick one-off run. It is not a persistent review project." in template
    assert (
        "Workspaces save your references, PDFs, AI suggestions, human decisions, exports, "
        "and audit history locally on this computer."
    ) in template
    assert "Choose the folder that contains" in template


def test_legacy_mode_copy_and_mode_explanation_present():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "No workspace is open. Create or open a workspace to save your review progress." in template
    assert "Workspace Mode - saved locally" in script
    assert "Legacy Mode - one-off run" in script
    assert "Workspace Mode" in template  # mode explanation block present


def test_manual_path_entry_moved_to_advanced_mode():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    # Path entry is now nested inside an "Advanced location" disclosure, not the
    # main header, and the normal flow needs only a review title.
    assert "Advanced location (manual folder path)" in template
    assert "Advanced: choose a folder manually" in template
    assert 'id="workspacePathInput"' in template
    assert 'id="openWorkspacePathInput"' in template
    assert 'id="reviewTitleInput"' in template
    assert 'id="reviewTypeSelect"' in template


def test_no_prisma_compliant_wording_introduced():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "PRISMA compliant" not in template
    assert "PRISMA compliant" not in script
    assert "automatic PRISMA compliance" not in template
    assert "automatic PRISMA compliance" not in script


def test_recent_workspaces_do_not_expose_unsafe_absolute_paths(isolated_webapp):
    client = isolated_webapp.app.test_client()
    created = _create_default(
        client,
        review_title="Cardiology Screening Review",
        review_type="systematic_review",
        reviewer_name="Jane Doe",
    )
    assert created["is_open"] is True
    workspace_id = created["workspace"]["workspace_id"]
    assert created["workspace"]["review_title"] == "Cardiology Screening Review"
    assert created["workspace"]["review_type"] == "systematic_review"
    assert "path" not in created["workspace"]

    client.post("/api/workspaces/close")
    recent = client.get("/api/workspaces/recent").get_json()["recent"]
    assert recent
    first = recent[0]
    assert first["workspace_id"] == workspace_id
    assert first["review_title"] == "Cardiology Screening Review"
    assert first["review_type"] == "systematic_review"
    assert "path" not in first
    assert "abs" not in str(first).lower()
    # The stored settings path is local-only state and must never appear in API
    # responses. Sanity check that no drive-rooted absolute path leaks out.
    settings_text = isolated_webapp.SETTINGS_FILE.read_text(encoding="utf-8")
    assert "\\Users\\" not in str(recent)
    assert "C:" not in str(recent)


def test_default_location_create_does_not_require_a_manual_path(isolated_webapp):
    client = isolated_webapp.app.test_client()

    # Default flow: the researcher only enters a review title.
    created = _create_default(
        client,
        review_title="Mental Health Outcomes",
        review_type="scoping_review",
        review_question="What outcomes are reported?",
        reviewer_name="A. Reviewer",
    )
    assert created["is_open"] is True
    workspace = created["workspace"]
    assert workspace["review_title"] == "Mental Health Outcomes"
    assert workspace["review_type"] == "scoping_review"
    assert workspace["review_question"] == "What outcomes are reported?"
    assert workspace["reviewer_name"] == "A. Reviewer"
    assert "path" not in workspace

    # The workspace folder must live under the safe default location, not the
    # home directory itself and not a drive root.
    stored_path = isolated_webapp.SETTINGS_FILE.read_text(encoding="utf-8")
    import json as _json
    recent = _json.loads(stored_path).get("recent_workspaces", [])
    assert recent
    on_disk = Path(recent[0]["path"])
    assert on_disk.is_dir()
    assert on_disk.name != "SLR Assistant Workspaces"
    assert on_disk.parent.name == "SLR Assistant Workspaces"
    assert on_disk.resolve() != Path.cwd().anchor and on_disk.resolve() != Path.home()


def test_default_location_collides_without_clobbering_existing_folder(isolated_webapp):
    client = isolated_webapp.app.test_client()
    first = _create_default(client, review_title="Duplicate Name Project")
    assert first["is_open"] is True
    first_root = _json_load_settings_path(isolated_webapp)

    client.post("/api/workspaces/close")
    # Create again with the same review title — must pick a new sibling folder.
    second = _create_default(client, review_title="Duplicate Name Project")
    assert second["is_open"] is True
    second_root = _json_load_settings_path(isolated_webapp)
    assert first_root != second_root
    assert first_root.exists()
    assert second_root.exists()


def _json_load_settings(isolated_webapp):
    import json as _json
    return _json.loads(isolated_webapp.SETTINGS_FILE.read_text(encoding="utf-8"))


def _json_load_settings_path(isolated_webapp):
    return Path(_json_load_settings(isolated_webapp)["recent_workspaces"][0]["path"])


def test_invalid_review_type_is_rejected(isolated_webapp):
    client = isolated_webapp.app.test_client()
    resp = client.post(
        "/api/workspaces/create",
        json={"review_title": "Bad Type", "review_type": "meta_review"},
    )
    assert resp.status_code == 400


def test_missing_title_and_path_returns_clear_error(isolated_webapp):
    client = isolated_webapp.app.test_client()
    resp = client.post("/api/workspaces/create", json={})
    assert resp.status_code == 400
    assert "review title" in resp.get_json()["error"].lower()


def test_existing_workspace_endpoints_still_pass_after_navigation_redesign(isolated_webapp, tmp_path):
    client = isolated_webapp.app.test_client()

    # Current/close/open/recent still behave as before with an explicit path.
    root = tmp_path / "workspace"
    created = client.post(
        "/api/workspaces/create",
        json={"path": str(root), "name": "Explicit"}
    ).get_json()
    assert created["is_open"] is True
    assert set(created) == {"is_open", "workspace"}

    assert client.get("/api/workspaces/current").get_json()["is_open"] is True
    assert client.post("/api/workspaces/close").get_json()["is_open"] is False

    workspace_id = created["workspace"]["workspace_id"]
    reopened = client.post(
        "/api/workspaces/open", json={"workspace_id": workspace_id}
    ).get_json()
    assert reopened["is_open"] is True
    assert reopened["workspace"]["workspace_id"] == workspace_id

    summary = client.get("/api/workspace/review/summary").get_json()
    assert summary["is_open"] is True
    assert summary["summary"]["default_reviewer_id"] == workspace_store.DEFAULT_REVIEWER_ID

    queue = client.get("/api/workspace/review/queue").get_json()
    assert queue["visible_count"] == 0
    assert queue["active_unique_records"] == 0


def test_reference_list_uses_pagination_metadata_and_search(isolated_webapp):
    client = isolated_webapp.app.test_client()
    created = _create_default(client, review_title="Refs Review")
    assert created["is_open"]

    # Seed the in-memory session references list directly (no parse needed).
    isolated_webapp.session["references"] = [
        {"record_id": f"rec-{i}", "title": title, "authors": author, "year": str(2020 + i),
         "journal": "J", "doi": "", "decision": "", "rationale": ""}
        for i, (title, author) in enumerate(
            [
                ("Deep learning review", "Doe J"),
                ("Screening records study", "Roe A"),
                ("Other paper", "Smith B"),
            ]
        )
    ]

    payload = client.get("/api/references/list?per_page=2&page=1").get_json()
    assert payload["total"] == 3
    assert payload["filtered_total"] == 3
    assert payload["per_page"] == 2
    assert payload["page"] == 1
    assert payload["visible_count"] == len(payload["records"]) == 2
    assert "showing" in payload
    assert "Showing" in payload["showing_copy"]

    page2 = client.get("/api/references/list?per_page=2&page=2").get_json()
    assert len(page2["records"]) == 1

    filtered = client.get("/api/references/list?q=screening").get_json()
    assert filtered["total"] == 3
    assert filtered["filtered_total"] == 1
    assert filtered["query"] == "screening"
    assert filtered["has_filter"] is True
    assert filtered["records"][0]["title"] == "Screening records study"


def test_reference_list_empty_state_metadata(isolated_webapp):
    client = isolated_webapp.app.test_client()
    _create_default(client, review_title="Empty Review")
    payload = client.get("/api/references/list").get_json()
    assert payload["total"] == 0
    assert payload["filtered_total"] == 0
    assert payload["showing"] == 0
    assert payload["records"] == []


def test_bounded_reference_list_container_present():
    css = CSS_PATH.read_text(encoding="utf-8")
    assert ".ref-table-wrap" in css
    assert "max-height" in css


def test_showing_x_of_y_copy_exists_in_template_and_script():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'id="refShowing"' in template
    assert "Showing 0 of 0 records" in template
    assert 'id="reviewQueueShowing"' in template
    assert "Showing 0 of 0 review items" in template
    assert "Showing" in script and " of " in script


def test_existing_workspace_export_endpoint_still_responds(isolated_webapp):
    client = isolated_webapp.app.test_client()
    created = _create_default(client, review_title="Export Review")
    assert created["is_open"]

    summary = client.get("/api/workspace/exports/summary").get_json()
    assert summary["label"] == "Workspace reporting data"
    assert summary["latest_export"] is None

    exports_list = client.get("/api/workspace/exports/list").get_json()
    assert exports_list["total"] == 0

    generated = client.post("/api/workspace/exports/generate", json={})
    assert generated.status_code == 200
    export = generated.get_json()["export"]
    assert all(item["path"].startswith(f"exports/{export['export_id']}/") for item in export["files"])
    assert all(not Path(item["path"]).is_absolute() for item in export["files"])
