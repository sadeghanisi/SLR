"""JSON response builders for WebApp route handlers."""

from __future__ import annotations

import workspace_store


def workspace_response(handle=None) -> dict:
    if not handle:
        return {"is_open": False, "workspace": None}
    return {"is_open": True, "workspace": handle.public_summary()}


def review_queue_filter_payload(stage: str | None, status: str | None, origin: str | None) -> dict:
    return {
        "stage": stage or "",
        "status": status or "",
        "record_origin": origin or "",
    }


def workspace_review_response(handle=None) -> dict:
    if not handle:
        return {"is_open": False, "summary": None}
    return {
        "is_open": True,
        "summary": workspace_store.get_review_summary(handle.root),
    }


def workspace_review_queue_response(
    handle,
    *,
    stage: str | None = None,
    status: str | None = None,
    origin: str | None = None,
) -> dict:
    queue = workspace_store.get_review_queue(
        handle.root,
        stage=stage,
        status=status,
        record_origin=origin,
    )
    unfiltered_for_status = workspace_store.get_review_queue(
        handle.root,
        stage=stage,
        record_origin=origin,
    )
    unfiltered_active_queue = workspace_store.get_review_queue(handle.root)
    workspace_summary = workspace_store.get_workspace_summary(handle.root)
    review_summary = workspace_store.get_review_summary(handle.root)
    counts = workspace_summary.get("counts", {})
    active_origins = counts.get("active_records_by_origin", counts.get("records_by_origin", {}))
    return {
        "items": queue,
        "total": len(queue),
        "visible_count": len(queue),
        "total_count": len(unfiltered_for_status),
        "active_review_item_count": len(unfiltered_active_queue),
        "filter_scope_count": len(unfiltered_for_status),
        "current_filter": review_queue_filter_payload(stage, status, origin),
        "records_by_origin": active_origins,
        "active_records_by_origin": active_origins,
        "active_unique_records": counts.get("active_unique_records", 0),
        "duplicate_records": counts.get("duplicate_records", 0),
        "raw_imported_records": counts.get("raw_imported_records", 0),
        "imported_reference_records": active_origins.get(
            workspace_store.RECORD_ORIGIN_IMPORTED_REFERENCE,
            0,
        ),
        "pdf_only_records": active_origins.get(workspace_store.RECORD_ORIGIN_PDF_ONLY, 0),
        "manual_records": active_origins.get(workspace_store.RECORD_ORIGIN_MANUAL, 0),
        "review_items_by_status": review_summary.get("by_status", {}),
        "ai_suggestion_count": review_summary.get("ai_suggestion_count", 0),
        "human_decision_count": review_summary.get("human_decision_count", 0),
        "workspace_counts": counts,
        "summary": review_summary,
    }
