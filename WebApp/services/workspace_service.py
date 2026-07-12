"""Workspace session, path, and summary helpers for the WebApp."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

import workspace_store
from WebApp.services import runtime_state
from workspace_store import WORKSPACE_PDF_TOKEN, UnsafeWorkspacePath, WorkspaceError


def current_workspace(session: dict):
    return session.get("workspace")


def workspace_pdf_api_name(relative_path: str) -> str:
    pure = Path(relative_path)
    if pure.parts and pure.parts[0] == "pdfs":
        return pure.relative_to("pdfs").as_posix()
    return pure.as_posix()


def workspace_pdf_relative_path(api_name: str) -> str:
    if not api_name:
        raise UnsafeWorkspacePath("Missing filename")
    name = str(api_name).replace("\\", "/")
    return f"pdfs/{name}"


def load_workspace_session_state(session: dict, handle) -> None:
    session["references"] = workspace_store.load_records(handle.root)
    session["dedup_stats"] = None
    session["pdf_folder"] = WORKSPACE_PDF_TOKEN
    display_names = {}
    for row in workspace_store.list_pdf_metadata(handle.root):
        api_name = workspace_pdf_api_name(row["relative_path"])
        display_names[api_name] = row["display_name"]
        display_names[Path(api_name).name] = row["display_name"]
    session["pdf_display_names"] = display_names
    runtime_state.screening(session).clear()
    runtime_state.processing(session).clear()
    session["event_stream_job"] = None


def clear_workspace_session_state(session: dict) -> None:
    session["workspace"] = None
    session["references"] = []
    session["dedup_stats"] = None
    session["pdf_folder"] = ""
    session["pdf_display_names"] = {}
    runtime_state.screening(session).clear()
    runtime_state.processing(session).clear()
    session["event_stream_job"] = None
    session["reference_uploads"] = {}


def public_recent_workspaces(load_settings: Callable[[], dict]) -> list[dict]:
    recent = load_settings().get("recent_workspaces", [])
    public = []
    for item in recent:
        if not isinstance(item, dict):
            continue
        # Never expose absolute filesystem paths through the API. The stored
        # "path" is local-only state used to reopen a workspace without asking
        # the researcher to re-enter it.
        public.append({
            "workspace_id": item.get("workspace_id", ""),
            "name": item.get("name", ""),
            "review_title": item.get("review_title", ""),
            "review_type": item.get("review_type", ""),
            "last_opened_at": item.get("last_opened_at", ""),
        })
    return [item for item in public if item["workspace_id"] and item["name"]]


def remember_recent_workspace(
    handle,
    load_settings: Callable[[], dict],
    write_settings: Callable[[dict], None],
) -> None:
    settings = load_settings()
    recent = settings.get("recent_workspaces", [])
    if not isinstance(recent, list):
        recent = []
    now = workspace_store.utc_now()
    record = {
        "workspace_id": handle.workspace_id,
        "name": handle.name,
        "path": str(handle.root),
        "review_title": getattr(handle, "review_title", "") or "",
        "review_type": getattr(handle, "review_type", "") or "",
        "last_opened_at": now,
    }
    deduped = [
        item for item in recent
        if isinstance(item, dict)
        and item.get("workspace_id") != handle.workspace_id
        and item.get("path") != str(handle.root)
    ]
    settings["recent_workspaces"] = [record] + deduped[:9]
    write_settings(settings)


def workspace_path_from_recent(workspace_id: str, load_settings: Callable[[], dict]) -> str:
    for item in load_settings().get("recent_workspaces", []):
        if isinstance(item, dict) and item.get("workspace_id") == workspace_id:
            return item.get("path", "")
    return ""


def set_current_workspace(
    session: dict,
    handle,
    load_settings: Callable[[], dict],
    write_settings: Callable[[dict], None],
) -> None:
    # Workspace lifecycle admission guarantees that no live WebApp job owns a
    # run while create/open is assigning the current workspace.
    workspace_store.reconcile_stale_automation_runs(handle.root)
    session["workspace"] = handle
    load_workspace_session_state(session, handle)
    remember_recent_workspace(handle, load_settings, write_settings)


def require_workspace(session: dict):
    handle = current_workspace(session)
    if not handle:
        raise WorkspaceError("No workspace open")
    return handle


def stage_for_workspace(stage: str) -> str:
    raw = (stage or "").strip().lower()
    if "full" in raw or "pdf" in raw:
        return workspace_store.REVIEW_STAGE_FULL_TEXT
    return workspace_store.REVIEW_STAGE_TITLE_ABSTRACT


def workspace_run_name() -> str:
    return f"processing_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def workspace_processing_paths(handle, run_name: str) -> dict[str, Path]:
    paths = {
        "output_folder": handle.root / "exports" / run_name,
        "cache_folder": handle.root / "cache" / run_name,
        "text_cache_folder": handle.root / "cache" / "text_cache" / run_name,
        "audit_ledger": handle.root / "audit" / f"{run_name}.jsonl",
    }
    for key, path in paths.items():
        if key == "audit_ledger":
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
    return paths


def workspace_relative_api_path(
    handle,
    path_value,
    *,
    allowed_roots: tuple[str, ...] = ("exports", "cache", "audit"),
) -> str:
    if not path_value:
        return ""
    try:
        target = Path(path_value).resolve()
        relative = target.relative_to(handle.root.resolve()).as_posix()
    except (OSError, ValueError):
        return ""
    first = Path(relative).parts[0] if Path(relative).parts else ""
    return relative if first in allowed_roots else ""


def workspace_safe_summary(summary, handle):
    if not isinstance(summary, dict) or not handle:
        return summary
    safe = {}
    path_keys = {
        "screening_csv",
        "extraction_csv",
        "screening_excel",
        "extraction_excel",
        "summary_report",
        "audit_ledger",
        "text_cache_path",
    }
    for key, value in summary.items():
        if key in path_keys:
            safe[key] = workspace_relative_api_path(handle, value)
        elif isinstance(value, dict):
            safe[key] = workspace_safe_summary(value, handle)
        elif isinstance(value, list):
            safe[key] = [
                workspace_safe_summary(item, handle) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            safe[key] = value
    return safe


def workspace_safe_error(message: str, handle) -> str:
    if not handle:
        return message
    return (message or "").replace(str(handle.root), "[workspace]")
