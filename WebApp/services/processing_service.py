"""Processing response and setup helpers for the WebApp."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import workspace_store
from WebApp.services import job_guard, runtime_state, upload_service, workspace_service
from workspace_store import WORKSPACE_PDF_TOKEN


@dataclass
class ProcessingStartResult:
    payload: dict
    status_code: int = 200


@dataclass
class ProcessingExportResult:
    path: Path | None = None
    payload: dict | None = None
    status_code: int = 200


@dataclass
class ProcessingInput:
    pdf_folder_path: Path
    include_subfolders: bool
    pdf_count: int
    workspace_run_name: str
    workspace_paths: dict
    output_folder: Path


def build_automation_config(
    payload: dict,
    *,
    pdf_folder_path: Path,
    output_folder: Path,
    include_subfolders: bool,
    stop_event,
    workspace_paths: dict | None = None,
) -> dict:
    config = {
        "api_key": payload.get("api_key", ""),
        "pdf_folder": str(pdf_folder_path),
        "output_folder": str(output_folder),
        "cache_enabled": payload.get("cache_enabled", True),
        "parallel_processing": payload.get("parallel", True),
        "max_workers": payload.get("max_workers", 3),
        "rate_limit_delay": payload.get("rate_delay", 1.0),
        "llm_provider": payload.get("provider", "OpenAI"),
        "llm_model": payload.get("model", ""),
        "two_stage_screening": payload.get("two_stage", False),
        "include_subfolders": include_subfolders,
        "stop_event": stop_event,
        "screening_prompt": payload.get("screening_prompt"),
        "extraction_prompt": payload.get("extraction_prompt"),
        "extraction_fields": payload.get("extraction_fields"),
    }
    if workspace_paths:
        config.update({
            "cache_folder": str(workspace_paths["cache_folder"]),
            "text_cache_folder": str(workspace_paths["text_cache_folder"]),
            "audit_ledger": str(workspace_paths["audit_ledger"]),
        })

    if payload.get("base_url"):
        config["base_url"] = payload["base_url"]

    advanced = payload.get("advanced", {})
    if advanced:
        config["advanced_config"] = advanced

    return config


def decision_bucket(decision: str) -> str:
    d = (decision or "").lower()
    if "error" in d or "fail" in d:
        return "failed"
    if "include" in d:
        return "included"
    if "exclude" in d:
        return "excluded"
    if "flag" in d or "human" in d or "review" in d:
        return "flagged"
    return "other"


def processing_counters(screening_results: list[dict], total_files: int = 0) -> dict:
    counters = {
        "total_files": total_files or len(screening_results),
        "processed_files": len(screening_results),
        "included": 0,
        "excluded": 0,
        "flagged": 0,
        "failed": 0,
    }
    for result in screening_results:
        bucket = decision_bucket(result.get("decision", ""))
        if bucket in counters:
            counters[bucket] += 1
    return counters


def screening_records(
    auto,
    *,
    display_names: dict,
    workspace_handle=None,
    workspace_relative_api_path: Callable | None = None,
) -> list[dict]:
    records = []
    for result in getattr(auto, "screening_results", []):
        record = asdict(result) if hasattr(result, "__dataclass_fields__") else dict(result)
        filename = record.get("filename", "")
        record["server_filename"] = filename
        record["display_filename"] = display_names.get(filename, filename)
        record.setdefault("title", "")
        record.setdefault("reasoning", "")
        record.setdefault("rationale", record.get("reasoning", ""))
        record.setdefault(
            "error",
            record.get("reasoning", "") if decision_bucket(record.get("decision", "")) == "failed" else "",
        )
        if hasattr(auto, "get_paper_text_metadata"):
            meta = auto.get_paper_text_metadata(filename)
            if meta:
                record["text_hash"] = meta.get("text_hash", "")
                if workspace_handle and workspace_relative_api_path:
                    record["text_cache_path"] = workspace_relative_api_path(
                        workspace_handle,
                        meta.get("text_cache_path", ""),
                        allowed_roots=("cache",),
                    )
                else:
                    record["text_cache_path"] = meta.get("text_cache_path", "")
                record["extraction_method"] = meta.get("extraction_method", "")
                record["extraction_status"] = meta.get("extraction_status", "")
                record["extracted_char_count"] = meta.get("extracted_char_count", 0)
        records.append(record)
    return records


def extraction_records(auto, *, display_names: dict) -> list[dict]:
    records = []
    for result in getattr(auto, "extraction_results", []):
        if hasattr(result, "__dataclass_fields__"):
            record = {
                "filename": result.filename,
                "fields": result.fields,
                "processing_time": round(result.processing_time, 2),
                "api_tokens_used": result.api_tokens_used,
            }
        else:
            record = dict(result)
            if "processing_time" in record:
                record["processing_time"] = round(record["processing_time"], 2)
        filename = record.get("filename", "")
        record["server_filename"] = filename
        record["display_filename"] = display_names.get(filename, filename)
        records.append(record)
    return records


def path_exists(path_value) -> bool:
    return bool(path_value) and Path(path_value).exists()


def processing_report_state(auto, workspace_handle=None, workspace_relative_api_path: Callable | None = None) -> dict:
    def report_path(path_value):
        if workspace_handle and workspace_relative_api_path:
            return workspace_relative_api_path(workspace_handle, path_value)
        return str(path_value or "")

    return {
        "screening_csv": {
            "path": report_path(getattr(auto, "screening_csv", "")),
            "exists": path_exists(getattr(auto, "screening_csv", "")),
        },
        "screening_excel": {
            "path": report_path(getattr(auto, "screening_excel", "")),
            "exists": path_exists(getattr(auto, "screening_excel", "")),
        },
        "extraction_csv": {
            "path": report_path(getattr(auto, "extraction_csv", "")),
            "exists": path_exists(getattr(auto, "extraction_csv", "")),
        },
        "extraction_excel": {
            "path": report_path(getattr(auto, "extraction_excel", "")),
            "exists": path_exists(getattr(auto, "extraction_excel", "")),
        },
        "summary_report": {
            "path": report_path(getattr(auto, "summary_report", "")),
            "exists": path_exists(getattr(auto, "summary_report", "")),
        },
        "audit_ledger": {
            "path": report_path(getattr(auto, "audit_ledger", "")),
            "exists": path_exists(getattr(auto, "audit_ledger", "")),
        },
    }


def ensure_processing_reports(
    auto,
    workspace_handle=None,
    workspace_relative_api_path: Callable | None = None,
) -> tuple[dict, list[str]]:
    errors = []

    if getattr(auto, "screening_results", []):
        for writer_name, path_name in (
            ("write_screening_csv", "screening_csv"),
            ("write_screening_excel", "screening_excel"),
        ):
            path_value = getattr(auto, path_name, "")
            if path_value and not Path(path_value).exists() and hasattr(auto, writer_name):
                try:
                    getattr(auto, writer_name)()
                except Exception as exc:
                    errors.append(f"{path_name}: {exc}")
            if path_value and not Path(path_value).exists():
                errors.append(f"{path_name} was not generated")

    if getattr(auto, "extraction_results", []):
        for writer_name, path_name in (
            ("write_extraction_csv", "extraction_csv"),
            ("write_extraction_excel", "extraction_excel"),
        ):
            path_value = getattr(auto, path_name, "")
            if path_value and not Path(path_value).exists() and hasattr(auto, writer_name):
                try:
                    getattr(auto, writer_name)()
                except Exception as exc:
                    errors.append(f"{path_name}: {exc}")
            if path_value and not Path(path_value).exists():
                errors.append(f"{path_name} was not generated")

    summary_path = getattr(auto, "summary_report", "")
    if summary_path and not Path(summary_path).exists() and hasattr(auto, "_generate_summary"):
        try:
            auto._generate_summary()
        except Exception as exc:
            errors.append(f"summary_report: {exc}")
        if not Path(summary_path).exists():
            errors.append("summary_report was not generated")

    return processing_report_state(auto, workspace_handle, workspace_relative_api_path), errors


def processing_payload(
    auto,
    active: bool,
    *,
    display_names: dict,
    processing_reports: dict | None = None,
    processing_report_errors: list | None = None,
    processing_error: str = "",
    processing_summary=None,
    workspace_handle=None,
    workspace_relative_api_path: Callable | None = None,
) -> dict:
    if not auto:
        return {
            "active": active,
            "stats": {},
            "counters": processing_counters([]),
            "screening_count": 0,
            "extraction_count": 0,
            "reports": {},
            "report_errors": processing_report_errors or [],
            "error": processing_error or "",
        }

    screening = screening_records(
        auto,
        display_names=display_names,
        workspace_handle=workspace_handle,
        workspace_relative_api_path=workspace_relative_api_path,
    )
    extraction = extraction_records(auto, display_names=display_names)
    stats = dict(getattr(auto, "stats", {}))
    counters = processing_counters(screening, stats.get("total_files", 0))
    stats.update({
        "total_files": counters["total_files"],
        "processed_files": counters["processed_files"],
        "likely_include": counters["included"],
        "likely_exclude": counters["excluded"],
        "flag_for_review": counters["flagged"],
        "flag_for_human_review": 0,
        "failed_files": counters["failed"],
    })
    reports = processing_reports or processing_report_state(
        auto,
        workspace_handle,
        workspace_relative_api_path,
    )
    return {
        "active": active,
        "stats": stats,
        "counters": counters,
        "screening_count": len(screening),
        "extraction_count": len(extraction),
        "reports": reports,
        "report_errors": processing_report_errors or [],
        "error": processing_error or "",
        "summary": processing_summary,
    }


def processing_export_path(auto, which: str, workspace_handle=None) -> Path | None:
    attrs = ("extraction_excel", "screening_excel") if which == "extraction" else ("screening_excel",)
    for attr in attrs:
        path_value = getattr(auto, attr, "")
        if not path_value:
            continue
        try:
            path = Path(path_value).resolve()
        except OSError:
            continue
        if workspace_handle:
            try:
                path.relative_to((workspace_handle.root / "exports").resolve())
            except ValueError:
                continue
        if path.exists() and path.is_file():
            return path
    return None


def workspace_pdf_row_for_result(handle, result: dict) -> dict | None:
    filename = result.get("server_filename") or result.get("filename") or ""
    display_filename = result.get("display_filename") or ""
    candidates = {filename, Path(filename).name, display_filename}
    for row in workspace_store.list_pdf_metadata(handle.root):
        api_name = workspace_service.workspace_pdf_api_name(row["relative_path"])
        row_candidates = {
            api_name,
            Path(api_name).name,
            row["relative_path"],
            row["display_name"],
            row["original_filename"],
        }
        if candidates & {item for item in row_candidates if item}:
            return row
    return None


def processing_audit_metadata(auto) -> dict[tuple[str, str], dict]:
    path_value = getattr(auto, "audit_ledger", "")
    if not path_value or not Path(path_value).exists():
        return {}
    by_result: dict[tuple[str, str], dict] = {}
    try:
        with Path(path_value).open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("kind") != "screening":
                    continue
                filename = event.get("filename", "")
                stage = workspace_service.stage_for_workspace(event.get("stage", ""))
                by_result[(filename, stage)] = event
    except OSError:
        return {}
    return by_result


def persist_workspace_processing_suggestions(
    handle,
    auto,
    *,
    display_names: dict,
    automation_run_id: str | None = None,
) -> None:
    audit_by_result = processing_audit_metadata(auto)
    for result in screening_records(auto, display_names=display_names):
        pdf_row = workspace_pdf_row_for_result(handle, result)
        if not pdf_row:
            continue
        record_id = pdf_row.get("record_id") or workspace_store.ensure_record_for_pdf(
            handle.root,
            pdf_row["pdf_id"],
        )
        stage = workspace_service.stage_for_workspace(result.get("stage", ""))
        audit = audit_by_result.get((result.get("server_filename") or result.get("filename") or "", stage), {})
        provider_profile = audit.get("provider_profile") or {}
        workspace_store.add_ai_suggestion(
            handle.root,
            record_id=record_id,
            pdf_id=pdf_row["pdf_id"],
            stage=stage,
            decision=result.get("decision", ""),
            rationale=result.get("reasoning") or result.get("rationale") or result.get("error") or "",
            confidence=None,
            provider=provider_profile.get("provider") or audit.get("provider") or "",
            model=audit.get("model") or "",
            prompt_hash=audit.get("prompt_hash") or "",
            text_hash=audit.get("text_hash") or result.get("text_hash") or "",
            cache_key=audit.get("cache_key") or "",
            automation_run_id=automation_run_id,
            metadata={
                "api_tokens_used": result.get("api_tokens_used"),
                "processing_time": result.get("processing_time"),
                "cache_hit": audit.get("cache_hit"),
            },
        )


def reset_processing_state(state: runtime_state.ProcessingRuntimeState) -> None:
    state.reset_for_start()


def resolve_processing_input(
    payload: dict,
    *,
    session: dict,
    workspace_handle,
    pdf_upload_root: Path,
    output_dir: Path,
) -> tuple[ProcessingInput | None, ProcessingStartResult | None]:
    pdf_folder = payload.get("pdf_folder") or session.get("pdf_folder", "")
    include_subfolders = upload_service.truthy(payload.get("include_subfolders"))

    if workspace_handle:
        if pdf_folder not in ("", WORKSPACE_PDF_TOKEN):
            return None, ProcessingStartResult({"error": "Invalid workspace PDF folder"}, 400)
        pdf_folder_path = workspace_handle.root / "pdfs"
        if not pdf_folder_path.exists():
            return None, ProcessingStartResult({"error": "No PDF folder selected"}, 400)
        workspace_run_name = workspace_service.workspace_run_name()
        workspace_paths = workspace_service.workspace_processing_paths(workspace_handle, workspace_run_name)
        output_folder = workspace_paths["output_folder"]
    else:
        workspace_run_name = ""
        workspace_paths = {}
        output_folder = output_dir
        try:
            pdf_folder_path = upload_service.resolve_existing_inside(
                pdf_folder,
                pdf_upload_root,
                require_dir=True,
            )
        except FileNotFoundError:
            return None, ProcessingStartResult({"error": "No PDF folder selected"}, 400)
        except ValueError as exc:
            return None, ProcessingStartResult({"error": str(exc)}, 400)

    pdf_count = len(upload_service.discover_pdf_files(pdf_folder_path, include_subfolders))
    return ProcessingInput(
        pdf_folder_path=pdf_folder_path,
        include_subfolders=include_subfolders,
        pdf_count=pdf_count,
        workspace_run_name=workspace_run_name,
        workspace_paths=workspace_paths,
        output_folder=output_folder,
    ), None


def create_workspace_processing_run(
    payload: dict,
    *,
    workspace_handle,
    run_name: str,
    paths: dict,
    output_folder: Path,
    pdf_count: int,
    auto,
) -> str | None:
    if not workspace_handle:
        return None
    return workspace_store.create_automation_run(
        workspace_handle.root,
        run_id=run_name,
        run_type="full_text_processing",
        provider=payload.get("provider", "OpenAI"),
        model=payload.get("model", ""),
        base_url=payload.get("base_url", ""),
        input_count=pdf_count,
        metadata={
            "output_folder": workspace_service.workspace_relative_api_path(workspace_handle, output_folder),
            "cache_folder": workspace_service.workspace_relative_api_path(
                workspace_handle,
                paths["cache_folder"],
                allowed_roots=("cache",),
            ),
            "text_cache_folder": workspace_service.workspace_relative_api_path(
                workspace_handle,
                paths["text_cache_folder"],
                allowed_roots=("cache",),
            ),
            "audit_ledger": workspace_service.workspace_relative_api_path(
                workspace_handle,
                paths["audit_ledger"],
                allowed_roots=("audit",),
            ),
            "reports": processing_report_state(
                auto,
                workspace_handle,
                workspace_service.workspace_relative_api_path,
            ),
        },
    )


def run_processing_background(
    *,
    session: dict,
    state: runtime_state.ProcessingRuntimeState,
    auto,
    workspace_handle,
    automation_run_id: str | None,
    push_event: Callable[[str, dict], None],
) -> None:
    try:
        summary = auto.process_pdfs()
        if workspace_handle:
            summary = workspace_service.workspace_safe_summary(summary, workspace_handle)
        if workspace_handle:
            try:
                persist_workspace_processing_suggestions(
                    workspace_handle,
                    auto,
                    display_names=session.get("pdf_display_names", {}),
                    automation_run_id=automation_run_id,
                )
            except Exception as exc:
                push_event("processing_warning", {
                    "warnings": [
                        "Workspace suggestions not persisted: "
                        f"{workspace_service.workspace_safe_error(str(exc), workspace_handle)}"
                    ]
                })
        reports, report_errors = ensure_processing_reports(
            auto,
            workspace_handle,
            workspace_service.workspace_relative_api_path,
        )
        state.reports = reports
        state.report_errors = report_errors
        state.summary = summary
        if workspace_handle:
            workspace_store.finish_automation_run(
                workspace_handle.root,
                automation_run_id or "",
                status="completed",
                output_count=len(getattr(auto, "screening_results", [])),
                metadata={
                    "reports": reports,
                    "summary": summary,
                    "report_errors": report_errors,
                },
            )
        if report_errors:
            summary = dict(summary)
            summary["report_errors"] = report_errors
            push_event("processing_warning", {"warnings": report_errors, "reports": reports})
        push_event("processing_done", summary)
    except Exception as exc:
        safe_error = workspace_service.workspace_safe_error(str(exc), workspace_handle)
        state.error = safe_error
        if workspace_handle:
            workspace_store.finish_automation_run(
                workspace_handle.root,
                automation_run_id or "",
                status="failed",
                output_count=len(getattr(auto, "screening_results", [])),
                metadata={"error": safe_error},
            )
        push_event("processing_error", {"error": safe_error})


def run_reserved_processing_background(*, reservation: object, **kwargs) -> None:
    try:
        run_processing_background(**kwargs)
    finally:
        job_guard.release(reservation)


def start_processing(
    payload: dict,
    *,
    session: dict,
    workspace_handle,
    pdf_upload_root: Path,
    output_dir: Path,
    automation_cls,
    push_event: Callable[[str, dict], None],
) -> ProcessingStartResult:
    reservation = job_guard.try_reserve("processing")
    if reservation is None:
        return ProcessingStartResult({"error": job_guard.CONFLICT_ERROR}, 409)

    worker_started = False
    state = runtime_state.processing(session)
    try:
        processing_input, error = resolve_processing_input(
            payload,
            session=session,
            workspace_handle=workspace_handle,
            pdf_upload_root=pdf_upload_root,
            output_dir=output_dir,
        )
        if error:
            return error

        reset_processing_state(state)
        config = build_automation_config(
            payload,
            pdf_folder_path=processing_input.pdf_folder_path,
            output_folder=processing_input.output_folder,
            include_subfolders=processing_input.include_subfolders,
            stop_event=state.stop_event,
            workspace_paths=processing_input.workspace_paths if workspace_handle else None,
        )

        try:
            auto = automation_cls(**config)
            state.automation = auto
        except Exception as exc:
            return ProcessingStartResult(
                {"error": workspace_service.workspace_safe_error(str(exc), workspace_handle)},
                500,
            )

        automation_run_id = create_workspace_processing_run(
            payload,
            workspace_handle=workspace_handle,
            run_name=processing_input.workspace_run_name,
            paths=processing_input.workspace_paths,
            output_folder=processing_input.output_folder,
            pdf_count=processing_input.pdf_count,
            auto=auto,
        )

        thread = threading.Thread(
            target=run_reserved_processing_background,
            kwargs={
                "reservation": reservation,
                "session": session,
                "state": state,
                "auto": auto,
                "workspace_handle": workspace_handle,
                "automation_run_id": automation_run_id,
                "push_event": push_event,
            },
            daemon=True,
        )
        previous_thread = state.thread
        previous_stream_job = session["event_stream_job"]
        state.thread = thread
        session["event_stream_job"] = "processing"
        try:
            thread.start()
        except Exception:
            state.thread = previous_thread
            session["event_stream_job"] = previous_stream_job
            raise
        worker_started = True

        return ProcessingStartResult({"status": "started", "total": processing_input.pdf_count})
    finally:
        if not worker_started:
            job_guard.release(reservation)


def stop_processing(session: dict) -> dict:
    runtime_state.processing(session).stop_event.set()
    return {"status": "stopping"}


def processing_status_payload(session: dict, workspace_handle=None) -> dict:
    state = runtime_state.processing(session)
    auto = state.automation
    if not auto:
        return processing_payload(
            None,
            False,
            display_names=session.get("pdf_display_names", {}),
            processing_reports=state.reports,
            processing_report_errors=state.report_errors,
            processing_error=state.error,
            processing_summary=state.summary,
            workspace_handle=workspace_handle,
            workspace_relative_api_path=workspace_service.workspace_relative_api_path,
        )

    running = state.thread and state.thread.is_alive()
    return processing_payload(
        auto,
        bool(running),
        display_names=session.get("pdf_display_names", {}),
        processing_reports=state.reports,
        processing_report_errors=state.report_errors,
        processing_error=state.error,
        processing_summary=state.summary,
        workspace_handle=workspace_handle,
        workspace_relative_api_path=workspace_service.workspace_relative_api_path,
    )


def processing_results_payload(session: dict, workspace_handle=None) -> dict:
    state = runtime_state.processing(session)
    auto = state.automation
    if not auto:
        return {
            "screening": [],
            "extraction": [],
            "counters": processing_counters([]),
            "reports": {},
            "report_errors": state.report_errors,
            "error": state.error,
        }

    screening = screening_records(
        auto,
        display_names=session.get("pdf_display_names", {}),
        workspace_handle=workspace_handle,
        workspace_relative_api_path=workspace_service.workspace_relative_api_path,
    )
    extraction = extraction_records(auto, display_names=session.get("pdf_display_names", {}))
    stats = dict(getattr(auto, "stats", {}))
    return {
        "screening": screening,
        "extraction": extraction,
        "counters": processing_counters(screening, stats.get("total_files", 0)),
        "reports": state.reports or processing_report_state(
            auto,
            workspace_handle,
            workspace_service.workspace_relative_api_path,
        ),
        "report_errors": state.report_errors,
        "error": state.error,
        "summary": state.summary,
    }


def processing_export_response(session: dict, which: str, workspace_handle=None) -> ProcessingExportResult:
    state = runtime_state.processing(session)
    auto = state.automation
    if not auto:
        return ProcessingExportResult(payload={"error": "No processing results"}, status_code=400)

    export_path = processing_export_path(auto, which, workspace_handle)
    if export_path:
        return ProcessingExportResult(path=export_path)

    report_errors = state.report_errors
    detail = "; ".join(report_errors) if report_errors else "Export file not found"
    return ProcessingExportResult(payload={"error": detail}, status_code=404)


def processing_stats_event_payload(session: dict, workspace_handle=None) -> dict | None:
    auto = runtime_state.processing(session).automation
    if not auto:
        return None
    return {
        "type": "stats",
        "data": processing_status_payload(session, workspace_handle)["stats"],
    }
