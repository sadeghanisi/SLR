"""Workspace export and reporting boundary for the WebApp.

This module owns workspace export file generation and path validation. Route
handlers should call these helpers rather than writing export files directly.
"""

from __future__ import annotations

import csv
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from version import VERSION, VERSION_TAG


EXPORT_FILENAMES = (
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
)

SCREENING_DECISION_FIELDS = (
    "record_id",
    "stable_record_id",
    "title",
    "authors",
    "year",
    "journal",
    "doi",
    "record_origin",
    "is_active_for_screening",
    "duplicate_status",
    "duplicate_of_record_id",
    "dedup_method",
    "dedup_score",
    "stage",
    "current_status",
    "ai_suggestion",
    "ai_rationale",
    "ai_is_final",
    "human_final_decision",
    "human_rationale",
    "final_decision_source",
    "exclusion_reason",
    "reviewer",
    "decision_timestamp",
    "pdf_display_name",
    "source_filenames",
    "source_count",
)

DECISION_FIELDS = (
    "decision_id",
    "review_item_id",
    "actor_type",
    "reviewer_id",
    "decision",
    "rationale",
    "confidence",
    "exclusion_reason_id",
    "exclusion_reason",
    "provider",
    "model",
    "prompt_hash",
    "text_hash",
    "cache_key",
    "automation_run_id",
    "created_at",
    "record_id",
    "pdf_id",
    "stage",
    "current_status",
    "title",
    "authors",
    "year",
    "journal",
    "doi",
    "record_origin",
    "is_active_for_screening",
    "duplicate_of_record_id",
    "dedup_method",
    "dedup_score",
    "pdf_display_name",
)

FULL_TEXT_EXCLUSION_FIELDS = (
    "decision_id",
    "review_item_id",
    "reviewer_id",
    "decision",
    "rationale",
    "exclusion_reason_id",
    "exclusion_reason",
    "decision_timestamp",
    "record_id",
    "pdf_id",
    "stage",
    "current_status",
    "title",
    "authors",
    "year",
    "journal",
    "doi",
    "record_origin",
    "pdf_display_name",
)

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,160}$")


@dataclass(frozen=True)
class ExportManifest:
    run_id: str
    folder: str
    files: list[dict] = field(default_factory=list)


def export_run_folder(workspace_root: Path, prefix: str = "export") -> Path:
    run_id = f"{prefix}_{_timestamp_compact()}_{uuid.uuid4().hex[:8]}"
    root = (workspace_root / "exports" / run_id).resolve()
    root.relative_to((workspace_root / "exports").resolve())
    return root


def empty_manifest(export_folder: Path) -> ExportManifest:
    return ExportManifest(run_id=export_folder.name, folder=f"exports/{export_folder.name}", files=[])


def generate_workspace_exports(store, workspace_root: str | Path, options: dict | None = None) -> dict:
    """Generate workspace export files and return a safe manifest."""
    del options  # reserved for future filters without changing route shape
    root = store.validate_workspace_root(workspace_root)
    export_folder = export_run_folder(root)
    export_folder.mkdir(parents=True, exist_ok=False)

    screening_rows = store.get_exportable_screening_rows(root)
    ai_rows = store.get_decision_export_rows(root, actor_type=store.ACTOR_AI)
    human_rows = store.get_decision_export_rows(root, actor_type=store.ACTOR_HUMAN)
    full_text_exclusions = store.get_full_text_exclusion_rows(root)
    counts = store.get_prisma_ready_counts(root)
    metadata = store.get_export_metadata(root)

    files = []
    files.append(_write_csv(export_folder, "workspace_screening_decisions.csv", screening_rows, SCREENING_DECISION_FIELDS))
    files.append(_write_xlsx(export_folder, "workspace_screening_decisions.xlsx", "Screening decisions", screening_rows, SCREENING_DECISION_FIELDS))
    review_item_rows = [
        {key: row.get(key, "") for key in SCREENING_DECISION_FIELDS}
        for row in screening_rows
        if row.get("stage")
    ]
    files.append(_write_csv(export_folder, "workspace_review_items.csv", review_item_rows, SCREENING_DECISION_FIELDS))
    files.append(_write_csv(export_folder, "workspace_ai_suggestions.csv", ai_rows, DECISION_FIELDS))
    files.append(_write_csv(export_folder, "workspace_human_decisions.csv", human_rows, DECISION_FIELDS))
    files.append(_write_csv(export_folder, "workspace_full_text_exclusions.csv", full_text_exclusions, FULL_TEXT_EXCLUSION_FIELDS))
    files.append(_write_json(export_folder, "prisma_ready_counts.json", counts))
    files.append(_write_counts_csv(export_folder, "prisma_ready_counts.csv", counts))
    files.append(_write_text(export_folder, "methods_disclosure.md", _methods_disclosure_text(metadata, counts)))

    manifest = {
        "export_id": export_folder.name,
        "created_at": _utc_now(),
        "label": "Workspace reporting data",
        "folder": f"exports/{export_folder.name}",
        "warnings": [
            "PRISMA-ready counts are derived from workspace data and should be checked before reporting.",
            "AI-only suggestions are not final decisions.",
        ],
        "files": files,
    }
    manifest_file = _write_json(export_folder, "export_manifest.json", manifest)
    manifest["files"].append(manifest_file)
    _write_json(export_folder, "export_manifest.json", manifest)

    store.write_audit_event(
        root,
        event_type="workspace_exports_generated",
        entity_type="export",
        entity_id=export_folder.name,
        summary="Generated workspace reporting data exports",
        metadata={
            "export_id": export_folder.name,
            "folder": manifest["folder"],
            "files": [item["filename"] for item in manifest["files"]],
        },
    )
    return manifest


def get_workspace_exports_summary(store, workspace_root: str | Path) -> dict:
    counts = store.get_prisma_ready_counts(workspace_root)
    exports = list_workspace_exports(store, workspace_root)
    latest = exports[0] if exports else None
    return {
        "is_available": True,
        "label": "Workspace reporting data",
        "counts": counts,
        "latest_export": latest,
        "export_count": len(exports),
        "warnings": [
            "PRISMA-ready counts are derived from workspace data and should be checked before reporting.",
            "AI-only suggestions are not final decisions.",
        ],
    }


def list_workspace_exports(store, workspace_root: str | Path) -> list[dict]:
    root = store.validate_workspace_root(workspace_root)
    exports_root = (root / "exports").resolve()
    exports_root.mkdir(parents=True, exist_ok=True)
    manifests = []
    for manifest_path in sorted(exports_root.glob("*/export_manifest.json"), reverse=True):
        try:
            manifest_path.resolve().relative_to(exports_root)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            export_id = _safe_export_id(manifest.get("export_id") or manifest_path.parent.name)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        manifests.append(_public_manifest_summary(manifest | {"export_id": export_id}))
    return manifests


def get_export_manifest(store, workspace_root: str | Path, export_id: str) -> dict:
    folder = _resolve_export_folder(store, workspace_root, export_id)
    manifest_path = folder / "export_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("Export manifest not found")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["export_id"] = _safe_export_id(manifest.get("export_id") or folder.name)
    return _public_manifest_summary(manifest, include_files=True)


def resolve_export_download(store, workspace_root: str | Path, export_id: str, filename: str) -> Path:
    folder = _resolve_export_folder(store, workspace_root, export_id)
    safe_filename = _safe_filename(filename)
    manifest = get_export_manifest(store, workspace_root, export_id)
    allowed = {item["filename"] for item in manifest.get("files", [])}
    if safe_filename not in allowed:
        raise FileNotFoundError("Export file not found")
    target = (folder / safe_filename).resolve()
    target.relative_to(folder.resolve())
    if not target.is_file():
        raise FileNotFoundError("Export file not found")
    return target


def _resolve_export_folder(store, workspace_root: str | Path, export_id: str) -> Path:
    root = store.validate_workspace_root(workspace_root)
    safe_export_id = _safe_export_id(export_id)
    exports_root = (root / "exports").resolve()
    folder = (exports_root / safe_export_id).resolve()
    folder.relative_to(exports_root)
    if not folder.is_dir():
        raise FileNotFoundError("Export not found")
    return folder


def _write_csv(folder: Path, filename: str, rows: list[dict], fieldnames: tuple[str, ...]) -> dict:
    path = folder / filename
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _cell_value(row.get(key)) for key in fieldnames})
    return _file_entry(folder, path, "text/csv")


def _write_xlsx(folder: Path, filename: str, sheet_name: str, rows: list[dict], fieldnames: tuple[str, ...]) -> dict:
    from openpyxl import Workbook

    path = folder / filename
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet_name[:31]
    worksheet.append(list(fieldnames))
    for row in rows:
        worksheet.append([_cell_value(row.get(key)) for key in fieldnames])
    for cell in worksheet[1]:
        cell.style = "Headline 4"
    workbook.save(path)
    return _file_entry(folder, path, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _write_json(folder: Path, filename: str, payload: dict) -> dict:
    path = folder / filename
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
    return _file_entry(folder, path, "application/json")


def _write_counts_csv(folder: Path, filename: str, counts: dict) -> dict:
    rows = []
    for metric, payload in counts.get("counts", {}).items():
        value = payload.get("value") if isinstance(payload, dict) else payload
        rows.append({
            "metric": metric,
            "value": json.dumps(value, ensure_ascii=True, sort_keys=True) if isinstance(value, (dict, list)) else value,
            "status": payload.get("status", "available") if isinstance(payload, dict) else "available",
            "explanation": payload.get("explanation", "") if isinstance(payload, dict) else "",
        })
    return _write_csv(folder, filename, rows, ("metric", "value", "status", "explanation"))


def _write_text(folder: Path, filename: str, text: str) -> dict:
    path = folder / filename
    path.write_text(text, encoding="utf-8")
    return _file_entry(folder, path, "text/markdown")


def _file_entry(folder: Path, path: Path, content_type: str) -> dict:
    filename = _safe_filename(path.name)
    return {
        "filename": filename,
        "path": f"exports/{folder.name}/{filename}",
        "bytes": path.stat().st_size,
        "content_type": content_type,
    }


def _methods_disclosure_text(metadata: dict, counts: dict) -> str:
    summary = metadata.get("workspace_summary", {})
    count_values = counts.get("counts", {})
    sources = metadata.get("sources", [])
    review_summary = metadata.get("review_summary", {})
    ai_models = metadata.get("ai_models", [])
    dedup_methods = metadata.get("dedup_methods", {})
    origin_counts = summary.get("counts", {}).get("records_by_origin", {})

    ai_lines = [
        f"- {item.get('provider') or 'Unknown provider'} / {item.get('model') or 'unknown model'}: {item.get('suggestion_count', 0)} AI suggestions"
        for item in ai_models
    ] or ["- No AI provider/model metadata was available in the workspace export metadata."]
    dedup_lines = [
        f"- {method or 'unspecified'}: {count} duplicate records"
        for method, count in sorted(dedup_methods.items())
    ] or ["- No duplicate records were recorded in the workspace database."]

    def metric_value(name: str, default: Any = 0) -> Any:
        payload = count_values.get(name, {})
        if isinstance(payload, dict):
            return payload.get("value", default)
        return payload if payload is not None else default

    generated_at = counts.get("generated_at") or _utc_now()
    return "\n".join([
        "# Methods Disclosure",
        "",
        f"Generated at: {generated_at}",
        "",
        f"Software: SLR Assistant {VERSION_TAG or VERSION}",
        "",
        "SLR Assistant was used as a local-first AI-assisted workflow tool. AI-generated outputs were treated as suggestions only. Final include/exclude/maybe decisions were recorded as human decisions in the workspace database.",
        "",
        "## Workspace Summary",
        "",
        f"- Workspace name: {summary.get('name', '')}",
        f"- Imported sources: {len(sources)}",
        f"- Raw imported reference rows: {metric_value('raw_imported_reference_rows')}",
        f"- Active unique imported references: {metric_value('active_unique_imported_references')}",
        f"- Duplicate records hidden from active screening: {metric_value('duplicate_records_hidden_from_active_screening')}",
        f"- PDF-only records: {origin_counts.get('pdf_only', 0)}",
        f"- Manual records: {origin_counts.get('manual', 0)}",
        "",
        "## Deduplication",
        "",
        "Duplicate records were retained in the workspace database for auditability and excluded from active screening counts when marked inactive.",
        *dedup_lines,
        "",
        "## Record Origins",
        "",
        f"- imported_reference: {origin_counts.get('imported_reference', 0)}",
        f"- pdf_only: {origin_counts.get('pdf_only', 0)}",
        f"- manual: {origin_counts.get('manual', 0)}",
        "",
        "## AI Metadata",
        "",
        *ai_lines,
        "",
        "AI-only suggestions were not treated as final eligibility decisions.",
        "",
        "## Human Review",
        "",
        f"- Human decisions recorded: {review_summary.get('human_decision_count', 0)}",
        f"- AI-only unfinalized suggestions: {metric_value('ai_only_unfinalized_suggestions')}",
        "",
        "Human decisions take precedence over AI suggestions in exported decision fields.",
        "",
        "## Full-Text Exclusion Reasons",
        "",
        "Full-text exclusion decisions support structured exclusion reasons. Missing reasons should be checked before reporting.",
        f"- Full-text human exclusions: {metric_value('full_text_human_excluded')}",
        "",
        "## Limitations",
        "",
        "- PRISMA-ready counts are derived from the current workspace database and should be checked before reporting.",
        "- Counts marked not_available indicate data that is not yet represented accurately in the workspace schema.",
        "- This export does not include dual-reviewer agreement, conflict resolution, risk of bias, quality appraisal, OCR status, or extraction workflow data.",
        "- The software does not replace human methodological judgment.",
        "",
    ])


def _public_manifest_summary(manifest: dict, *, include_files: bool = True) -> dict:
    export_id = _safe_export_id(manifest.get("export_id", ""))
    files = [
        {
            "filename": _safe_filename(item.get("filename", "")),
            "path": f"exports/{export_id}/{_safe_filename(item.get('filename', ''))}",
            "bytes": int(item.get("bytes") or 0),
            "content_type": item.get("content_type", "application/octet-stream"),
        }
        for item in manifest.get("files", [])
        if item.get("filename")
    ]
    summary = {
        "export_id": export_id,
        "created_at": manifest.get("created_at", ""),
        "label": manifest.get("label", "Workspace reporting data"),
        "folder": f"exports/{export_id}",
        "file_count": len(files),
        "warnings": manifest.get("warnings", []),
    }
    if include_files:
        summary["files"] = files
    return summary


def _safe_export_id(value: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_NAME.fullmatch(text) or "/" in text or "\\" in text:
        raise ValueError("Invalid export id")
    return text


def _safe_filename(value: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_NAME.fullmatch(text) or "/" in text or "\\" in text or text not in EXPORT_FILENAMES:
        raise ValueError("Invalid export filename")
    return text


def _cell_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    return value


def _timestamp_compact() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
