import io
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import WebApp.app as webapp
import workspace_store


ZERO_COUNTERS = {
    "total_files": 0,
    "processed_files": 0,
    "included": 0,
    "excluded": 0,
    "flagged": 0,
    "failed": 0,
}

REPORT_KEYS = {
    "screening_csv",
    "screening_excel",
    "extraction_csv",
    "extraction_excel",
    "summary_report",
    "audit_ledger",
}

STATS_KEYS = {
    "total_files",
    "processed_files",
    "likely_include",
    "likely_exclude",
    "flag_for_review",
    "flag_for_human_review",
    "failed_files",
}

SENSITIVE_SENTINELS = (
    "DUMMY_TEST_KEY_NOT_SECRET",
    "DUMMY_TOKEN_VALUE_NOT_SECRET",
    "DUMMY_PASSWORD_VALUE_NOT_SECRET",
    "DUMMY_CREDENTIAL_VALUE_NOT_SECRET",
    "DUMMY_FULL_PROMPT_TEXT_DO_NOT_LEAK",
    "DUMMY_EXTRACTION_PROMPT_TEXT_DO_NOT_LEAK",
    "DUMMY_FULL_PAPER_TEXT_DO_NOT_LEAK",
)


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


def _base_stats(total_files: int = 0) -> dict:
    return {
        "total_files": total_files,
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


def _set_report_paths(auto, output_dir: Path, audit_ledger: Path | None = None) -> None:
    auto.screening_csv = output_dir / "screening.csv"
    auto.screening_excel = output_dir / "screening.xlsx"
    auto.extraction_csv = output_dir / "extraction.csv"
    auto.extraction_excel = output_dir / "extraction.xlsx"
    auto.summary_report = output_dir / "summary.txt"
    auto.audit_ledger = audit_ledger or output_dir / "audit.jsonl"


def _write_report_files(auto, *, include_extraction: bool = True) -> None:
    paths = [auto.screening_csv, auto.screening_excel, auto.summary_report, auto.audit_ledger]
    if include_extraction:
        paths.extend([auto.extraction_csv, auto.extraction_excel])
    for path in paths:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text("safe fake report", encoding="utf-8")


def _make_legacy_pdf_folder(app_module, names=("paper.pdf",)) -> Path:
    pdf_dir = app_module.PDF_UPLOAD_ROOT / "batch"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (pdf_dir / name).write_bytes(b"%PDF-1.4\n")
    app_module.session["pdf_folder"] = str(pdf_dir)
    app_module.session["pdf_display_names"] = {name: name for name in names}
    return pdf_dir


def _create_workspace(client, root: Path, name: str = "Review") -> dict:
    response = client.post("/api/workspaces/create", json={"path": str(root), "name": name})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["is_open"] is True
    assert "path" not in payload["workspace"]
    return payload


def _upload_workspace_pdf(client, name: str = "Paper.pdf") -> str:
    response = client.post(
        "/api/pdfs/upload",
        data={"files": (io.BytesIO(b"%PDF-1.4\n"), name)},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    return response.get_json()["files"][0]["filename"]


def _automation_run_rows(root: Path) -> list[dict]:
    with workspace_store.workspace_connection(root) as conn:
        rows = conn.execute(
            """
            SELECT run_id, status, input_count, output_count, metadata_json
            FROM automation_runs
            ORDER BY started_at ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _join_processing_thread(app_module) -> None:
    thread = app_module.runtime_state.processing(app_module.session).thread
    assert thread is not None
    thread.join(timeout=3)
    assert not thread.is_alive()


def _screening_runtime(app_module):
    return app_module.runtime_state.screening(app_module.session)


def _processing_runtime(app_module):
    return app_module.runtime_state.processing(app_module.session)


def _same_identity(before, after) -> bool:
    return all(left is right for left, right in zip(before, after))


def _runtime_snapshot(app_module) -> dict:
    screening = _screening_runtime(app_module)
    processing = _processing_runtime(app_module)
    return {
        "screening": {
            "state": screening,
            "thread": screening.thread,
            "stop_event": screening.stop_event,
            "progress": screening.progress,
            "progress_contents": list(screening.progress),
            "results": screening.results,
            "results_contents": list(screening.results),
            "error": screening.error,
        },
        "processing": {
            "state": processing,
            "thread": processing.thread,
            "stop_event": processing.stop_event,
            "progress": processing.progress,
            "progress_contents": list(processing.progress),
            "automation": processing.automation,
            "summary": processing.summary,
            "summary_contents": (
                dict(processing.summary)
                if isinstance(processing.summary, dict)
                else processing.summary
            ),
            "error": processing.error,
            "reports": processing.reports,
            "reports_contents": dict(processing.reports),
            "report_errors": processing.report_errors,
            "report_errors_contents": list(processing.report_errors),
        },
    }


def _assert_runtime_unchanged(app_module, before: dict) -> None:
    after = _runtime_snapshot(app_module)
    identity_fields = {
        "screening": ("state", "thread", "stop_event", "progress", "results"),
        "processing": (
            "state", "thread", "stop_event", "progress", "automation", "summary",
            "reports", "report_errors",
        ),
    }
    for kind, fields in identity_fields.items():
        for field in fields:
            assert after[kind][field] is before[kind][field]
    for kind in ("screening", "processing"):
        for field, value in before[kind].items():
            if field not in identity_fields[kind]:
                assert after[kind][field] == value


def _settings_text(app_module) -> str | None:
    return (
        app_module.SETTINGS_FILE.read_text(encoding="utf-8")
        if app_module.SETTINGS_FILE.exists()
        else None
    )


def _assert_no_sentinels(payload) -> None:
    if isinstance(payload, bytes):
        text = payload.decode("utf-8", errors="replace")
    elif isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, sort_keys=True, default=str)
    for sentinel in SENSITIVE_SENTINELS:
        assert sentinel not in text


def _parse_sse_chunk(chunk) -> dict:
    text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
    assert text.startswith("data: ")
    return json.loads(text.removeprefix("data: ").strip())


def _static_report_auto(output_dir: Path, *, audit_ledger: Path | None = None):
    output_dir.mkdir(parents=True, exist_ok=True)
    auto = SimpleNamespace(
        stats=_base_stats(),
        screening_results=[],
        extraction_results=[],
    )
    _set_report_paths(auto, output_dir, audit_ledger)
    _write_report_files(auto)
    return auto


def test_no_automation_status_progress_and_results_exact_current_shape(isolated_webapp):
    client = isolated_webapp.app.test_client()

    expected_status = {
        "active": False,
        "stats": {},
        "counters": ZERO_COUNTERS,
        "screening_count": 0,
        "extraction_count": 0,
        "reports": {},
        "report_errors": [],
        "error": "",
    }
    expected_results = {
        "screening": [],
        "extraction": [],
        "counters": ZERO_COUNTERS,
        "reports": {},
        "report_errors": [],
        "error": "",
    }

    status = client.get("/api/processing/status").get_json()
    progress = client.get("/api/progress").get_json()
    results = client.get("/api/processing/results").get_json()

    assert status == expected_status
    assert progress == expected_status
    assert results == expected_results
    assert "summary" not in status
    assert "summary" not in progress
    assert "summary" not in results


def test_processing_start_constructor_failure_preserves_existing_automation(
    isolated_webapp,
    monkeypatch,
):
    pdf_dir = _make_legacy_pdf_folder(isolated_webapp)
    previous_auto = object()
    _processing_runtime(isolated_webapp).automation = previous_auto
    screening = _screening_runtime(isolated_webapp)
    screening.progress.append({"type": "screening_sentinel"})
    screening.results.append({"record_id": "rec-sentinel"})
    screening_progress = screening.progress
    screening_results = screening.results
    captured_config = {}

    class FailingInitAutomation:
        def __init__(self, **kwargs):
            captured_config.update(kwargs)
            raise RuntimeError("constructor failed")

    monkeypatch.setattr(isolated_webapp, "SystematicReviewAutomation", FailingInitAutomation)
    client = isolated_webapp.app.test_client()

    response = client.post("/api/processing/start", json={"pdf_folder": str(pdf_dir)})

    assert response.status_code == 500
    assert response.get_json() == {"error": "constructor failed"}
    assert _processing_runtime(isolated_webapp).automation is previous_auto
    assert _processing_runtime(isolated_webapp).thread is None
    assert captured_config["pdf_folder"] == str(pdf_dir)
    assert screening.progress is screening_progress
    assert screening.results is screening_results


def test_workspace_processing_start_rejects_invalid_non_token_pdf_folder(
    isolated_webapp,
    tmp_path,
    monkeypatch,
):
    client = isolated_webapp.app.test_client()
    root = tmp_path / "workspace"
    _create_workspace(client, root)

    monkeypatch.setattr(
        isolated_webapp,
        "SystematicReviewAutomation",
        lambda **kwargs: pytest.fail("Automation should not be constructed"),
    )

    response = client.post("/api/processing/start", json={"pdf_folder": str(root / "pdfs")})

    assert response.status_code == 400
    assert response.get_json() == {"error": "Invalid workspace PDF folder"}
    assert _processing_runtime(isolated_webapp).automation is None
    assert _automation_run_rows(root) == []


def test_processing_stop_sets_same_stop_event_passed_to_automation_config(
    isolated_webapp,
    monkeypatch,
):
    pdf_dir = _make_legacy_pdf_folder(isolated_webapp)
    process_started = threading.Event()
    captured = {}

    class BlockingAutomation:
        def __init__(self, **kwargs):
            captured["stop_event"] = kwargs["stop_event"]
            output_dir = Path(kwargs["output_folder"])
            output_dir.mkdir(parents=True, exist_ok=True)
            self.stats = _base_stats(total_files=1)
            self.screening_results = []
            self.extraction_results = []
            _set_report_paths(self, output_dir)

        def process_pdfs(self):
            captured["was_set_before_wait"] = captured["stop_event"].is_set()
            process_started.set()
            captured["stop_event"].wait(timeout=2)
            return {"screened_count": 0}

    monkeypatch.setattr(isolated_webapp, "SystematicReviewAutomation", BlockingAutomation)
    client = isolated_webapp.app.test_client()

    start = client.post("/api/processing/start", json={"pdf_folder": str(pdf_dir)})
    assert start.status_code == 200
    assert process_started.wait(timeout=1)
    assert captured["stop_event"] is _processing_runtime(isolated_webapp).stop_event
    assert captured["was_set_before_wait"] is False

    stop = client.post("/api/processing/stop")

    assert stop.status_code == 200
    assert stop.get_json() == {"status": "stopping"}
    assert captured["stop_event"].is_set()
    _join_processing_thread(isolated_webapp)


def test_workspace_processing_failure_finishes_run_failed_with_sanitized_metadata(
    isolated_webapp,
    tmp_path,
    monkeypatch,
):
    client = isolated_webapp.app.test_client()
    root = tmp_path / "workspace"
    _create_workspace(client, root)
    _upload_workspace_pdf(client)

    class FailingProcessingAutomation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            output_dir = Path(kwargs["output_folder"])
            output_dir.mkdir(parents=True, exist_ok=True)
            self.stats = _base_stats(total_files=1)
            self.screening_results = []
            self.extraction_results = []
            _set_report_paths(self, output_dir, Path(kwargs["audit_ledger"]))

        def process_pdfs(self):
            pdf_folder = Path(self.kwargs["pdf_folder"]).resolve()
            raise RuntimeError(f"failed while reading {pdf_folder}")

    monkeypatch.setattr(isolated_webapp, "SystematicReviewAutomation", FailingProcessingAutomation)

    response = client.post(
        "/api/processing/start",
        json={
            "provider": "Fake",
            "model": "fake-model",
            "api_key": SENSITIVE_SENTINELS[0],
        },
    )
    assert response.status_code == 200
    _join_processing_thread(isolated_webapp)

    status = client.get("/api/processing/status").get_json()
    rows = _automation_run_rows(root)
    metadata = json.loads(rows[0]["metadata_json"])

    assert status["error"].startswith("failed while reading [workspace]")
    assert str(root) not in status["error"]
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert metadata == {"error": status["error"]}
    assert "[workspace]" in metadata["error"]
    assert str(root) not in rows[0]["metadata_json"]
    _assert_no_sentinels(status)
    _assert_no_sentinels(rows[0]["metadata_json"])


def test_events_stream_emits_queued_event_and_stats_shape(isolated_webapp):
    client = isolated_webapp.app.test_client()
    _processing_runtime(isolated_webapp).automation = SimpleNamespace(
        stats={
            **_base_stats(total_files=2),
            "processed_files": 1,
            "likely_include": 1,
            "total_api_tokens": 7,
        },
        screening_results=[
            {
                "filename": "paper.pdf",
                "decision": "Likely Include",
                "reasoning": "Meets criteria",
            }
        ],
        extraction_results=[],
    )
    queued_event = {
        "type": "processing_warning",
        "data": {"warnings": ["queued warning"]},
        "ts": 123.0,
    }
    _processing_runtime(isolated_webapp).progress.append(queued_event)

    response = client.get("/api/events", buffered=False)
    try:
        queued = _parse_sse_chunk(next(response.response))
        stats = _parse_sse_chunk(next(response.response))
    finally:
        response.close()

    assert queued == queued_event
    assert stats["type"] == "stats"
    assert STATS_KEYS.issubset(stats["data"])
    assert stats["data"]["total_files"] == 2
    assert stats["data"]["processed_files"] == 1
    assert stats["data"]["likely_include"] == 1


def test_processing_export_extraction_prefers_extraction_excel_then_falls_back_to_screening(
    isolated_webapp,
    tmp_path,
):
    client = isolated_webapp.app.test_client()
    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    screening_excel = output_dir / "screening.xlsx"
    extraction_excel = output_dir / "extraction.xlsx"
    screening_excel.write_bytes(b"screening fallback")
    extraction_excel.write_bytes(b"extraction preferred")
    _processing_runtime(isolated_webapp).automation = SimpleNamespace(
        screening_excel=screening_excel,
        extraction_excel=extraction_excel,
    )

    preferred = client.post("/api/processing/export", json={"which": "extraction"})
    preferred_body = preferred.get_data()
    preferred.close()
    extraction_excel.unlink()
    fallback = client.post("/api/processing/export", json={"which": "extraction"})
    fallback_body = fallback.get_data()
    fallback.close()

    assert preferred.status_code == 200
    assert preferred_body == b"extraction preferred"
    assert fallback.status_code == 200
    assert fallback_body == b"screening fallback"


def test_processing_report_paths_remain_legacy_absolute_and_workspace_relative(
    isolated_webapp,
    tmp_path,
):
    client = isolated_webapp.app.test_client()

    legacy_auto = _static_report_auto(isolated_webapp.OUTPUT_DIR / "legacy-run")
    _processing_runtime(isolated_webapp).automation = legacy_auto
    legacy = client.get("/api/processing/results").get_json()

    assert set(legacy["reports"]) == REPORT_KEYS
    for info in legacy["reports"].values():
        assert Path(info["path"]).is_absolute()

    root = tmp_path / "workspace"
    _create_workspace(client, root)
    workspace_auto = _static_report_auto(
        root / "exports" / "run-contract",
        audit_ledger=root / "audit" / "run-contract.jsonl",
    )
    _processing_runtime(isolated_webapp).automation = workspace_auto
    workspace = client.get("/api/processing/results").get_json()

    assert set(workspace["reports"]) == REPORT_KEYS
    assert workspace["reports"]["screening_excel"]["path"].startswith("exports/")
    assert workspace["reports"]["extraction_excel"]["path"].startswith("exports/")
    assert workspace["reports"]["summary_report"]["path"].startswith("exports/")
    assert workspace["reports"]["audit_ledger"]["path"].startswith("audit/")
    for info in workspace["reports"].values():
        assert not Path(info["path"]).is_absolute()
    assert str(root) not in json.dumps(workspace)


def test_processing_contract_outputs_do_not_leak_sensitive_inputs(
    isolated_webapp,
    tmp_path,
    monkeypatch,
):
    client = isolated_webapp.app.test_client()
    root = tmp_path / "workspace"
    _create_workspace(client, root)
    server_filename = _upload_workspace_pdf(client, "Private Paper.pdf")

    class PrivacyAutomation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            output_dir = Path(kwargs["output_folder"])
            output_dir.mkdir(parents=True, exist_ok=True)
            self.filename = server_filename
            self.stats = _base_stats(total_files=1)
            self.screening_results = []
            self.extraction_results = []
            self.text_cache_path = Path(kwargs["text_cache_folder"]) / "paper.txt"
            _set_report_paths(self, output_dir, Path(kwargs["audit_ledger"]))

        def process_pdfs(self):
            self.screening_results = [
                {
                    "filename": self.filename,
                    "decision": "Likely Include",
                    "reasoning": "Meets criteria",
                    "notes": "",
                    "stage": "Full-text",
                    "processing_time": 0.1,
                    "text_length": 64,
                    "api_tokens_used": 5,
                }
            ]
            self.stats.update({
                "processed_files": 1,
                "likely_include": 1,
                "total_api_tokens": 5,
                "total_processing_time": 0.1,
            })
            self.text_cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.text_cache_path.write_text(SENSITIVE_SENTINELS[-1], encoding="utf-8")
            self.audit_ledger.parent.mkdir(parents=True, exist_ok=True)
            self.audit_ledger.write_text(
                json.dumps({
                    "kind": "screening",
                    "filename": self.filename,
                    "stage": "Full-text",
                    "provider_profile": {"provider": "FakeProvider"},
                    "model": "fake-model",
                    "prompt_hash": "safe-prompt-hash",
                    "text_hash": "safe-text-hash",
                    "cache_key": "safe-cache-key",
                    "cache_hit": False,
                }) + "\n",
                encoding="utf-8",
            )
            _write_report_files(self, include_extraction=False)
            return {
                "screened_count": 1,
                "screening_excel": str(self.screening_excel),
                "summary_report": str(self.summary_report),
                "audit_ledger": str(self.audit_ledger),
                "text_cache_path": str(self.text_cache_path),
            }

        def get_paper_text_metadata(self, filename):
            return {
                "text_hash": "safe-text-hash",
                "text_cache_path": str(self.text_cache_path),
                "extraction_method": "fake",
                "extraction_status": "ok",
                "extracted_char_count": 64,
            }

    monkeypatch.setattr(isolated_webapp, "SystematicReviewAutomation", PrivacyAutomation)

    start = client.post(
        "/api/processing/start",
        json={
            "provider": "Fake",
            "model": "fake-model",
            "api_key": SENSITIVE_SENTINELS[0],
            "screening_prompt": SENSITIVE_SENTINELS[4],
            "extraction_prompt": SENSITIVE_SENTINELS[5],
            "advanced": {
                "token": SENSITIVE_SENTINELS[1],
                "password": SENSITIVE_SENTINELS[2],
                "credential": SENSITIVE_SENTINELS[3],
            },
        },
    )
    assert start.status_code == 200
    _join_processing_thread(isolated_webapp)

    status = client.get("/api/processing/status").get_json()
    progress = client.get("/api/progress").get_json()
    results = client.get("/api/processing/results").get_json()
    rows = _automation_run_rows(root)

    assert rows[0]["status"] == "completed"
    assert status["report_errors"] == []
    assert results["report_errors"] == []
    assert results["screening"][0]["text_cache_path"].startswith("cache/")
    assert progress["summary"]["text_cache_path"].startswith("cache/")
    assert str(root) not in json.dumps({"status": status, "results": results})

    _assert_no_sentinels(start.get_json())
    _assert_no_sentinels(status)
    _assert_no_sentinels(progress)
    _assert_no_sentinels(results)
    _assert_no_sentinels(_processing_runtime(isolated_webapp).progress)
    _assert_no_sentinels(rows[0]["metadata_json"])


def test_job_admission_is_atomic_for_simultaneous_attempts():
    from WebApp.services import job_guard

    barrier = threading.Barrier(3)
    reservations = []

    def reserve(kind):
        barrier.wait(timeout=2)
        reservations.append(job_guard.try_reserve(kind))

    threads = [
        threading.Thread(target=reserve, args=(kind,))
        for kind in ("screening", "processing")
    ]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=2)
    for thread in threads:
        thread.join(timeout=2)

    winner = next((token for token in reservations if token is not None), None)
    try:
        assert all(not thread.is_alive() for thread in threads)
        assert len([token for token in reservations if token is not None]) == 1
        assert job_guard.active_job() in {"screening", "processing"}
    finally:
        if winner is not None:
            job_guard.release(winner)

    assert job_guard.active_job() is None


def test_second_screening_start_conflicts_without_mutating_active_job(
    isolated_webapp,
    monkeypatch,
):
    provider_started = threading.Event()
    release_provider = threading.Event()
    llm_instances = []

    class BlockingLLM:
        def __init__(self):
            llm_instances.append(self)

        def chat_completion_with_tokens(self, messages, **kwargs):
            provider_started.set()
            if not release_provider.wait(timeout=2):
                raise RuntimeError("test provider was not released")
            return '{"decision":"Include","rationale":"Eligible","confidence":"High"}', 1

    monkeypatch.setattr(isolated_webapp, "LLMManager", lambda *args, **kwargs: BlockingLLM())
    isolated_webapp.session["references"] = [
        {"record_id": "rec-1", "title": "Study", "abstract": "Safe"}
    ]
    client = isolated_webapp.app.test_client()
    screening = _screening_runtime(isolated_webapp)
    processing = _processing_runtime(isolated_webapp)

    first = client.post("/api/screening/start", json={"provider": "Fake", "rate_delay": 0})
    first_thread = screening.thread
    assert first.status_code == 200
    assert provider_started.wait(timeout=1)

    stop_event = screening.stop_event
    progress = screening.progress
    progress.append({"type": "sentinel"})
    results = screening.results
    processing_snapshot = (
        processing.thread, processing.stop_event, processing.progress,
        processing.automation, processing.reports, processing.error,
    )
    second = client.post("/api/screening/start", json={"provider": "Fake", "rate_delay": 0})
    second_thread = screening.thread
    first_still_active = first_thread.is_alive()
    state_unchanged = (
        second_thread is first_thread
        and screening.stop_event is stop_event
        and screening.progress is progress
        and screening.results is results
        and _same_identity(processing_snapshot, (
            processing.thread, processing.stop_event, processing.progress,
            processing.automation, processing.reports, processing.error,
        ))
    )

    release_provider.set()
    first_thread.join(timeout=2)
    if second_thread is not first_thread:
        second_thread.join(timeout=2)

    assert second.status_code == 409
    assert second.get_json() == {"error": "Another job is already running"}
    assert first_still_active
    assert state_unchanged
    assert len(llm_instances) == 1

    third = client.post("/api/screening/start", json={"provider": "Fake", "rate_delay": 0})
    screening.thread.join(timeout=2)
    assert third.status_code == 200
    assert third.get_json() == {"status": "started", "total": 1}
    assert len(llm_instances) == 2


def test_second_processing_start_conflicts_and_stop_targets_first_job(
    isolated_webapp,
    monkeypatch,
):
    pdf_dir = _make_legacy_pdf_folder(isolated_webapp)
    process_started = threading.Event()
    instances = []

    class BlockingAutomation:
        def __init__(self, **kwargs):
            instances.append(self)
            self.stop_event = kwargs["stop_event"]
            output_dir = Path(kwargs["output_folder"])
            output_dir.mkdir(parents=True, exist_ok=True)
            self.stats = _base_stats(total_files=1)
            self.screening_results = []
            self.extraction_results = []
            _set_report_paths(self, output_dir)

        def process_pdfs(self):
            process_started.set()
            self.stop_event.wait(timeout=2)
            return {"screened_count": 0}

    monkeypatch.setattr(isolated_webapp, "SystematicReviewAutomation", BlockingAutomation)
    client = isolated_webapp.app.test_client()
    screening = _screening_runtime(isolated_webapp)
    processing = _processing_runtime(isolated_webapp)

    first = client.post("/api/processing/start", json={"pdf_folder": str(pdf_dir)})
    first_thread = processing.thread
    assert first.status_code == 200
    assert process_started.wait(timeout=1)

    stop_event = processing.stop_event
    progress = processing.progress
    progress.append({"type": "sentinel"})
    reports = processing.reports
    automation = processing.automation
    screening_snapshot = (
        screening.thread, screening.stop_event, screening.progress,
        screening.results, screening.error,
    )
    second = client.post("/api/processing/start", json={"pdf_folder": str(pdf_dir)})
    second_thread = processing.thread
    state_unchanged = (
        second_thread is first_thread
        and processing.stop_event is stop_event
        and processing.progress is progress
        and processing.reports is reports
        and processing.automation is automation
        and _same_identity(screening_snapshot, (
            screening.thread, screening.stop_event, screening.progress,
            screening.results, screening.error,
        ))
    )
    stopped = client.post("/api/processing/stop")
    first_thread.join(timeout=2)
    if second_thread is not first_thread:
        second_thread.join(timeout=2)

    assert second.status_code == 409
    assert second.get_json() == {"error": "Another job is already running"}
    assert state_unchanged
    assert len(instances) == 1
    assert stopped.status_code == 200
    assert stopped.get_json() == {"status": "stopping"}
    assert stop_event.is_set()
    assert not first_thread.is_alive()

    process_started.clear()
    third = client.post("/api/processing/start", json={"pdf_folder": str(pdf_dir)})
    assert third.status_code == 200
    assert process_started.wait(timeout=1)
    client.post("/api/processing/stop")
    _join_processing_thread(isolated_webapp)
    assert len(instances) == 2


def test_processing_start_conflicts_while_screening_is_active(
    isolated_webapp,
    monkeypatch,
):
    pdf_dir = _make_legacy_pdf_folder(isolated_webapp)
    provider_started = threading.Event()
    release_provider = threading.Event()
    automation_instances = []

    class BlockingLLM:
        def chat_completion_with_tokens(self, messages, **kwargs):
            provider_started.set()
            if not release_provider.wait(timeout=2):
                raise RuntimeError("test provider was not released")
            return '{"decision":"Include","rationale":"Eligible","confidence":"High"}', 1

    class UnexpectedAutomation:
        def __init__(self, **kwargs):
            automation_instances.append(self)

    monkeypatch.setattr(isolated_webapp, "LLMManager", lambda *args, **kwargs: BlockingLLM())
    monkeypatch.setattr(isolated_webapp, "SystematicReviewAutomation", UnexpectedAutomation)
    isolated_webapp.session["references"] = [
        {"record_id": "rec-1", "title": "Study", "abstract": "Safe"}
    ]
    client = isolated_webapp.app.test_client()
    screening = _screening_runtime(isolated_webapp)
    processing = _processing_runtime(isolated_webapp)

    client.post("/api/screening/start", json={"provider": "Fake", "rate_delay": 0})
    screening_thread = screening.thread
    assert provider_started.wait(timeout=1)
    stop_event = screening.stop_event
    progress = screening.progress
    progress.append({"type": "sentinel"})
    results = screening.results
    processing_snapshot = (
        processing.thread, processing.stop_event, processing.progress,
        processing.automation, processing.reports, processing.error,
    )

    response = client.post("/api/processing/start", json={"pdf_folder": str(pdf_dir)})
    second_thread = processing.thread
    state_unchanged = (
        second_thread is processing_snapshot[0]
        and screening.thread is screening_thread
        and screening.stop_event is stop_event
        and screening.progress is progress
        and screening.results is results
        and _same_identity(processing_snapshot, (
            processing.thread, processing.stop_event, processing.progress,
            processing.automation, processing.reports, processing.error,
        ))
    )
    release_provider.set()
    screening_thread.join(timeout=2)
    if second_thread is not None:
        second_thread.join(timeout=2)

    assert response.status_code == 409
    assert response.get_json() == {"error": "Another job is already running"}
    assert state_unchanged
    assert automation_instances == []


def test_screening_start_conflicts_while_processing_is_active(
    isolated_webapp,
    monkeypatch,
):
    pdf_dir = _make_legacy_pdf_folder(isolated_webapp)
    process_started = threading.Event()
    llm_instances = []

    class BlockingAutomation:
        def __init__(self, **kwargs):
            self.stop_event = kwargs["stop_event"]
            output_dir = Path(kwargs["output_folder"])
            output_dir.mkdir(parents=True, exist_ok=True)
            self.stats = _base_stats(total_files=1)
            self.screening_results = []
            self.extraction_results = []
            _set_report_paths(self, output_dir)

        def process_pdfs(self):
            process_started.set()
            self.stop_event.wait(timeout=2)
            return {"screened_count": 0}

    class UnexpectedLLM:
        def __init__(self):
            llm_instances.append(self)

    monkeypatch.setattr(isolated_webapp, "SystematicReviewAutomation", BlockingAutomation)
    monkeypatch.setattr(isolated_webapp, "LLMManager", lambda *args, **kwargs: UnexpectedLLM())
    client = isolated_webapp.app.test_client()
    screening = _screening_runtime(isolated_webapp)
    processing = _processing_runtime(isolated_webapp)

    client.post("/api/processing/start", json={"pdf_folder": str(pdf_dir)})
    processing_thread = processing.thread
    assert process_started.wait(timeout=1)
    stop_event = processing.stop_event
    progress = processing.progress
    progress.append({"type": "sentinel"})
    reports = processing.reports
    automation = processing.automation
    screening_snapshot = (
        screening.thread, screening.stop_event, screening.progress,
        screening.results, screening.error,
    )

    response = client.post("/api/screening/start", json={"provider": "Fake", "rate_delay": 0})
    second_thread = screening.thread
    state_unchanged = (
        second_thread is screening_snapshot[0]
        and processing.thread is processing_thread
        and processing.stop_event is stop_event
        and processing.progress is progress
        and processing.reports is reports
        and processing.automation is automation
        and _same_identity(screening_snapshot, (
            screening.thread, screening.stop_event, screening.progress,
            screening.results, screening.error,
        ))
        and not stop_event.is_set()
    )
    stopped = client.post("/api/processing/stop")
    processing_thread.join(timeout=2)
    if second_thread is not None:
        second_thread.join(timeout=2)

    assert response.status_code == 409
    assert response.get_json() == {"error": "Another job is already running"}
    assert state_unchanged
    assert llm_instances == []
    assert stopped.get_json() == {"status": "stopping"}


def test_processing_reservation_releases_after_worker_and_constructor_failures(
    isolated_webapp,
    monkeypatch,
):
    pdf_dir = _make_legacy_pdf_folder(isolated_webapp)
    attempts = []

    class FailThenCompleteAutomation:
        def __init__(self, **kwargs):
            attempts.append(self)
            if len(attempts) == 1:
                raise RuntimeError("constructor failed")
            output_dir = Path(kwargs["output_folder"])
            output_dir.mkdir(parents=True, exist_ok=True)
            self.stats = _base_stats(total_files=1)
            self.screening_results = []
            self.extraction_results = []
            _set_report_paths(self, output_dir)

        def process_pdfs(self):
            if len(attempts) == 2:
                raise RuntimeError("worker failed")
            return {"screened_count": 0}

    monkeypatch.setattr(isolated_webapp, "SystematicReviewAutomation", FailThenCompleteAutomation)
    client = isolated_webapp.app.test_client()

    construction_failure = client.post(
        "/api/processing/start", json={"pdf_folder": str(pdf_dir)}
    )
    worker_failure = client.post("/api/processing/start", json={"pdf_folder": str(pdf_dir)})
    _join_processing_thread(isolated_webapp)
    after_failure = client.post("/api/processing/start", json={"pdf_folder": str(pdf_dir)})
    _join_processing_thread(isolated_webapp)

    assert construction_failure.status_code == 500
    assert construction_failure.get_json() == {"error": "constructor failed"}
    assert worker_failure.status_code == 200
    assert after_failure.status_code == 200
    assert len(attempts) == 3


def test_screening_reservation_releases_after_llm_construction_failure(
    isolated_webapp,
    monkeypatch,
):
    attempts = []

    class ImmediateLLM:
        def chat_completion_with_tokens(self, messages, **kwargs):
            return '{"decision":"Include","rationale":"Eligible","confidence":"High"}', 1

    def build_llm(*args, **kwargs):
        attempts.append(object())
        if len(attempts) == 1:
            raise RuntimeError("constructor failed")
        return ImmediateLLM()

    monkeypatch.setattr(isolated_webapp, "LLMManager", build_llm)
    processing = _processing_runtime(isolated_webapp)
    processing.progress.append({"type": "processing_sentinel"})
    processing.reports["sentinel"] = "kept"
    processing_progress = processing.progress
    processing_reports = processing.reports
    isolated_webapp.session["references"] = [
        {"record_id": "rec-1", "title": "Study", "abstract": "Safe"}
    ]
    client = isolated_webapp.app.test_client()

    failed = client.post("/api/screening/start", json={"provider": "Fake"})
    started = client.post(
        "/api/screening/start", json={"provider": "Fake", "rate_delay": 0}
    )
    _screening_runtime(isolated_webapp).thread.join(timeout=2)

    assert failed.status_code == 500
    assert failed.get_json() == {"error": "LLM init failed: constructor failed"}
    assert started.status_code == 200
    assert started.get_json() == {"status": "started", "total": 1}
    assert len(attempts) == 2
    assert processing.progress is processing_progress
    assert processing.reports is processing_reports


def test_screening_worker_failure_isolated_and_releases_admission(
    isolated_webapp,
    monkeypatch,
):
    from WebApp.services import job_guard

    class FailingScreener:
        def __init__(self, llm, rate_limit_delay=0.5, *, stop_event=None):
            self.stop_event = stop_event

        def screen_all(self, records, criteria, callback=None):
            raise RuntimeError("screening worker failed")

    class CompleteScreener(FailingScreener):
        def screen_all(self, records, criteria, callback=None):
            return []

    monkeypatch.setattr(isolated_webapp, "LLMManager", lambda *args, **kwargs: object())
    monkeypatch.setattr(isolated_webapp, "AbstractScreener", FailingScreener)
    monkeypatch.setattr(isolated_webapp.threading, "excepthook", lambda args: None)
    isolated_webapp.session["references"] = [
        {"record_id": "rec-1", "title": "Study", "abstract": "Safe"}
    ]
    screening = _screening_runtime(isolated_webapp)
    processing = _processing_runtime(isolated_webapp)
    processing.progress.append({"type": "processing_sentinel"})
    processing.reports["sentinel"] = "kept"
    processing_progress = processing.progress
    processing_reports = processing.reports
    client = isolated_webapp.app.test_client()

    failed = client.post("/api/screening/start", json={"provider": "Fake"})
    screening.thread.join(timeout=2)

    assert failed.status_code == 200
    assert not screening.thread.is_alive()
    assert screening.error == "Screening failed"
    assert screening.results == []
    assert processing.progress is processing_progress
    assert processing.reports is processing_reports
    assert job_guard.active_job() is None

    monkeypatch.setattr(isolated_webapp, "AbstractScreener", CompleteScreener)
    restarted = client.post("/api/screening/start", json={"provider": "Fake"})
    screening.thread.join(timeout=2)
    assert restarted.status_code == 200


def test_screening_reservation_releases_when_thread_start_fails(
    isolated_webapp,
    monkeypatch,
):
    class ImmediateLLM:
        def chat_completion_with_tokens(self, messages, **kwargs):
            return '{"decision":"Include","rationale":"Eligible","confidence":"High"}', 1

    class FailingStartThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("thread start failed")

    real_thread = threading.Thread
    monkeypatch.setattr(isolated_webapp, "LLMManager", lambda *args, **kwargs: ImmediateLLM())
    monkeypatch.setattr(isolated_webapp.threading, "Thread", FailingStartThread)
    isolated_webapp.session["references"] = [
        {"record_id": "rec-1", "title": "Study", "abstract": "Safe"}
    ]
    client = isolated_webapp.app.test_client()

    with pytest.raises(RuntimeError, match="thread start failed"):
        client.post("/api/screening/start", json={"provider": "Fake"})

    assert _screening_runtime(isolated_webapp).thread is None
    monkeypatch.setattr(isolated_webapp.threading, "Thread", real_thread)
    started = client.post(
        "/api/screening/start", json={"provider": "Fake", "rate_delay": 0}
    )
    _screening_runtime(isolated_webapp).thread.join(timeout=2)

    assert started.status_code == 200
    assert started.get_json() == {"status": "started", "total": 1}


def test_screening_and_processing_runtime_states_have_distinct_ownership():
    from WebApp.services import runtime_state

    state = {}
    runtime_state.initialize(state)
    screening = runtime_state.screening(state)
    processing = runtime_state.processing(state)

    assert screening.thread is None
    assert processing.thread is None
    assert screening.stop_event is not processing.stop_event
    assert screening.progress is not processing.progress
    assert screening.progress_lock is not processing.progress_lock
    assert screening.results is not processing.report_errors
    screening.progress.append({"type": "screening"})
    screening.results.append({"record_id": "rec-1"})
    screening.error = "screening error"

    assert processing.progress == []
    assert processing.report_errors == []
    assert processing.error == ""
    assert processing.automation is None
    assert processing.reports == {}

    state["event_stream_job"] = "screening"
    assert runtime_state.event_stream(state, "workspace_lifecycle") is screening


def test_stop_endpoints_target_only_their_owned_runtime_state(isolated_webapp):
    from WebApp.services import runtime_state

    screening = runtime_state.screening(isolated_webapp.session)
    processing = runtime_state.processing(isolated_webapp.session)
    client = isolated_webapp.app.test_client()

    screening_stop = client.post("/api/screening/stop")
    assert screening_stop.status_code == 200
    assert screening_stop.get_json() == {"status": "stopping"}
    assert screening.stop_event.is_set()
    assert not processing.stop_event.is_set()

    screening.stop_event.clear()
    processing_stop = client.post("/api/processing/stop")
    assert processing_stop.status_code == 200
    assert processing_stop.get_json() == {"status": "stopping"}
    assert processing.stop_event.is_set()
    assert not screening.stop_event.is_set()


def test_sequential_screening_and_processing_preserve_each_others_state(
    isolated_webapp,
    monkeypatch,
):
    from WebApp.services import runtime_state

    pdf_dir = _make_legacy_pdf_folder(isolated_webapp)

    class ImmediateLLM:
        def chat_completion_with_tokens(self, messages, **kwargs):
            return '{"decision":"Include","rationale":"Eligible","confidence":"High"}', 1

    class ImmediateAutomation:
        def __init__(self, **kwargs):
            output_dir = Path(kwargs["output_folder"])
            output_dir.mkdir(parents=True, exist_ok=True)
            self.stats = _base_stats(total_files=1)
            self.screening_results = []
            self.extraction_results = []
            _set_report_paths(self, output_dir)

        def process_pdfs(self):
            return {"screened_count": 0}

        def write_screening_csv(self):
            self.screening_csv.write_text("safe", encoding="utf-8")

        def write_screening_excel(self):
            self.screening_excel.write_text("safe", encoding="utf-8")

        def _generate_summary(self):
            self.summary_report.write_text("safe", encoding="utf-8")

    monkeypatch.setattr(isolated_webapp, "LLMManager", lambda *args, **kwargs: ImmediateLLM())
    monkeypatch.setattr(isolated_webapp, "SystematicReviewAutomation", ImmediateAutomation)
    isolated_webapp.session["references"] = [
        {"record_id": "rec-1", "title": "Study", "abstract": "Safe"}
    ]
    screening = runtime_state.screening(isolated_webapp.session)
    processing = runtime_state.processing(isolated_webapp.session)
    client = isolated_webapp.app.test_client()

    screening_start = client.post(
        "/api/screening/start", json={"provider": "Fake", "rate_delay": 0}
    )
    screening.thread.join(timeout=2)
    screening_results = screening.results
    screening_progress = screening.progress
    screening_payload = client.get("/api/screening/results").get_json()

    assert processing.thread is None
    assert not processing.stop_event.is_set()
    assert processing.progress == []
    assert processing.automation is None
    assert processing.reports == {}
    assert processing.error == ""

    processing_start = client.post(
        "/api/processing/start", json={"pdf_folder": str(pdf_dir)}
    )
    processing.thread.join(timeout=2)
    processing_reports = processing.reports
    processing_error = processing.error
    processing_payload = client.get("/api/processing/results").get_json()

    assert screening_start.status_code == 200
    assert processing_start.status_code == 200
    assert screening_payload["total"] == 1
    assert set(processing_payload) == {
        "screening", "extraction", "counters", "reports", "report_errors", "error", "summary"
    }
    assert screening.results is screening_results
    assert screening.progress is screening_progress
    assert all(event["type"].startswith("screening_") for event in screening.progress)
    assert all(not event["type"].startswith("screening_") for event in processing.progress)

    second_screening = client.post(
        "/api/screening/start", json={"provider": "Fake", "rate_delay": 0}
    )
    screening.thread.join(timeout=2)

    assert second_screening.status_code == 200
    assert processing.reports is processing_reports
    assert processing.error == processing_error
    assert client.get("/api/processing/results").get_json() == processing_payload


def test_workspace_lifecycle_mutations_conflict_during_screening(
    isolated_webapp,
    monkeypatch,
    tmp_path,
):
    from WebApp.services import job_guard

    worker_started = threading.Event()

    class BlockingScreener:
        def __init__(self, llm, rate_limit_delay=0.5, *, stop_event=None):
            self.stop_event = stop_event

        def screen_all(self, records, criteria, callback=None):
            worker_started.set()
            self.stop_event.wait(timeout=2)
            return []

    monkeypatch.setattr(isolated_webapp, "LLMManager", lambda *args, **kwargs: object())
    monkeypatch.setattr(isolated_webapp, "AbstractScreener", BlockingScreener)
    client = isolated_webapp.app.test_client()
    current_root = tmp_path / "current"
    other_root = tmp_path / "other"
    blocked_root = tmp_path / "blocked"
    current = _create_workspace(client, current_root, "Current")
    current_id = current["workspace"]["workspace_id"]
    client.post("/api/workspaces/close")
    other = _create_workspace(client, other_root, "Other")
    other_id = other["workspace"]["workspace_id"]
    client.post("/api/workspaces/open", json={"workspace_id": current_id})
    isolated_webapp.session["references"] = [
        {"record_id": "rec-1", "title": "Study", "abstract": "Safe"}
    ]

    started = client.post("/api/screening/start", json={"provider": "Fake"})
    screening = _screening_runtime(isolated_webapp)
    worker = screening.thread
    assert started.status_code == 200
    assert worker_started.wait(timeout=1)
    screening.progress.append({"type": "sentinel"})
    screening.results.append({"record_id": "partial"})
    screening.error = "screening sentinel"
    before = _runtime_snapshot(isolated_webapp)
    settings_before = _settings_text(isolated_webapp)

    try:
        responses = [
            client.post(
                "/api/workspaces/create",
                json={"path": str(blocked_root), "name": "Blocked"},
            ),
            client.post("/api/workspaces/open", json={"path": str(other_root)}),
            client.post("/api/workspaces/open", json={"workspace_id": other_id}),
            client.post("/api/workspaces/close"),
        ]

        assert [response.status_code for response in responses] == [409, 409, 409, 409]
        assert all(
            response.get_json() == {"error": "Cannot change workspace while a job is running"}
            for response in responses
        )
        assert not blocked_root.exists()
        assert isolated_webapp.session["workspace"].workspace_id == current_id
        assert _settings_text(isolated_webapp) == settings_before
        _assert_runtime_unchanged(isolated_webapp, before)
        assert job_guard.active_job() == "screening"
        assert client.get("/api/workspaces/current").status_code == 200
        assert client.get("/api/workspaces/recent").status_code == 200
        assert client.get("/api/workspace/review/summary").status_code == 200
        assert client.get("/api/workspace/review/queue").status_code == 200
        assert client.get("/api/screening/results").get_json()["total"] == 1
    finally:
        client.post("/api/screening/stop")
        worker.join(timeout=2)

    assert not worker.is_alive()
    assert job_guard.active_job() is None
    assert client.post(
        "/api/workspaces/create",
        json={"path": str(blocked_root), "name": "Allowed"},
    ).status_code == 200


def test_workspace_lifecycle_mutations_conflict_during_processing(
    isolated_webapp,
    monkeypatch,
    tmp_path,
):
    from WebApp.services import job_guard

    worker_started = threading.Event()

    class BlockingAutomation:
        def __init__(self, **kwargs):
            self.stop_event = kwargs["stop_event"]
            output_dir = Path(kwargs["output_folder"])
            output_dir.mkdir(parents=True, exist_ok=True)
            self.stats = _base_stats(total_files=1)
            self.screening_results = []
            self.extraction_results = []
            _set_report_paths(self, output_dir, Path(kwargs["audit_ledger"]))

        def process_pdfs(self):
            worker_started.set()
            self.stop_event.wait(timeout=2)
            return {"screened_count": 0}

        def write_screening_csv(self):
            self.screening_csv.write_text("safe", encoding="utf-8")

        def write_screening_excel(self):
            self.screening_excel.write_text("safe", encoding="utf-8")

        def _generate_summary(self):
            self.summary_report.write_text("safe", encoding="utf-8")

    monkeypatch.setattr(isolated_webapp, "SystematicReviewAutomation", BlockingAutomation)
    client = isolated_webapp.app.test_client()
    current_root = tmp_path / "current"
    other_root = tmp_path / "other"
    blocked_root = tmp_path / "blocked"
    current = _create_workspace(client, current_root, "Current")
    current_id = current["workspace"]["workspace_id"]
    _upload_workspace_pdf(client)
    client.post("/api/workspaces/close")
    other = _create_workspace(client, other_root, "Other")
    other_id = other["workspace"]["workspace_id"]
    client.post("/api/workspaces/open", json={"workspace_id": current_id})

    started = client.post("/api/processing/start", json={"provider": "Fake"})
    processing = _processing_runtime(isolated_webapp)
    worker = processing.thread
    assert started.status_code == 200
    assert worker_started.wait(timeout=1)
    processing.progress.append({"type": "sentinel"})
    processing.reports["sentinel"] = "kept"
    processing.summary = {"sentinel": "kept"}
    processing.error = "processing sentinel"
    processing.report_errors.append("sentinel")
    before = _runtime_snapshot(isolated_webapp)
    settings_before = _settings_text(isolated_webapp)
    runs_before = _automation_run_rows(current_root)

    try:
        responses = [
            client.post(
                "/api/workspaces/create",
                json={"path": str(blocked_root), "name": "Blocked"},
            ),
            client.post("/api/workspaces/open", json={"path": str(other_root)}),
            client.post("/api/workspaces/open", json={"workspace_id": other_id}),
            client.post("/api/workspaces/close"),
        ]

        assert [response.status_code for response in responses] == [409, 409, 409, 409]
        assert all(
            response.get_json() == {"error": "Cannot change workspace while a job is running"}
            for response in responses
        )
        assert not blocked_root.exists()
        assert isolated_webapp.session["workspace"].workspace_id == current_id
        assert _settings_text(isolated_webapp) == settings_before
        assert _automation_run_rows(current_root) == runs_before
        _assert_runtime_unchanged(isolated_webapp, before)
        assert job_guard.active_job() == "processing"
        assert client.get("/api/workspaces/current").status_code == 200
        assert client.get("/api/workspaces/recent").status_code == 200
    finally:
        client.post("/api/processing/stop")
        worker.join(timeout=2)

    assert not worker.is_alive()
    assert job_guard.active_job() is None


def test_workspace_lifecycle_reservation_blocks_other_mutations_and_job_starts(
    isolated_webapp,
    monkeypatch,
    tmp_path,
):
    from WebApp.services import job_guard

    operation_entered = threading.Event()
    release_operation = threading.Event()
    create_calls = []
    llm_instances = []
    automation_instances = []
    original_create = workspace_store.create_workspace

    def blocking_create(*args, **kwargs):
        create_calls.append(args[0])
        operation_entered.set()
        if not release_operation.wait(timeout=2):
            raise RuntimeError("workspace operation was not released")
        return original_create(*args, **kwargs)

    monkeypatch.setattr(workspace_store, "create_workspace", blocking_create)
    monkeypatch.setattr(
        isolated_webapp,
        "LLMManager",
        lambda *args, **kwargs: llm_instances.append(object()),
    )
    monkeypatch.setattr(
        isolated_webapp,
        "SystematicReviewAutomation",
        lambda **kwargs: automation_instances.append(object()),
    )
    isolated_webapp.session["references"] = [
        {"record_id": "rec-1", "title": "Study", "abstract": "Safe"}
    ]
    before = _runtime_snapshot(isolated_webapp)
    first_result = {}

    def create_workspace_request():
        with isolated_webapp.app.test_client() as client:
            response = client.post(
                "/api/workspaces/create",
                json={"path": str(tmp_path / "first"), "name": "First"},
            )
            first_result["status"] = response.status_code

    thread = threading.Thread(target=create_workspace_request)
    thread.start()
    assert operation_entered.wait(timeout=1)

    try:
        with isolated_webapp.app.test_client() as client:
            second_workspace = client.post(
                "/api/workspaces/create",
                json={"path": str(tmp_path / "second"), "name": "Second"},
            )
            screening = client.post("/api/screening/start", json={"provider": "Fake"})
            processing = client.post("/api/processing/start", json={})

        assert second_workspace.status_code == 409
        assert second_workspace.get_json() == {
            "error": "Cannot change workspace while a job is running"
        }
        assert screening.status_code == 409
        assert processing.status_code == 409
        assert screening.get_json() == {"error": "Another job is already running"}
        assert processing.get_json() == {"error": "Another job is already running"}
        assert create_calls == [str(tmp_path / "first")]
        assert not (tmp_path / "second").exists()
        assert llm_instances == []
        assert automation_instances == []
        _assert_runtime_unchanged(isolated_webapp, before)
        assert job_guard.active_job() == "workspace_lifecycle"
    finally:
        release_operation.set()
        thread.join(timeout=2)

    assert not thread.is_alive()
    assert first_result == {"status": 200}
    assert job_guard.active_job() is None


def test_workspace_lifecycle_failure_releases_reservation(
    isolated_webapp,
    monkeypatch,
    tmp_path,
):
    from WebApp.services import job_guard

    original_create = workspace_store.create_workspace
    attempts = []

    def fail_once(*args, **kwargs):
        attempts.append(args[0])
        if len(attempts) == 1:
            raise OSError("workspace create failed")
        return original_create(*args, **kwargs)

    monkeypatch.setattr(workspace_store, "create_workspace", fail_once)
    client = isolated_webapp.app.test_client()

    failed = client.post(
        "/api/workspaces/create",
        json={"path": str(tmp_path / "failed"), "name": "Failed"},
    )
    assert failed.status_code == 400
    assert failed.get_json() == {"error": "workspace create failed"}
    assert job_guard.active_job() is None

    succeeded = client.post(
        "/api/workspaces/create",
        json={"path": str(tmp_path / "succeeded"), "name": "Succeeded"},
    )
    assert succeeded.status_code == 200
    assert succeeded.get_json()["is_open"] is True
    assert job_guard.active_job() is None
