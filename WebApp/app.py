"""
SLR Web Application — Flask Backend
Wraps the existing systematic review automation engine for browser-based access.
"""

import os
import sys
import json
import time
import uuid
import shutil
import threading
import hashlib
from pathlib import Path
from datetime import datetime
from dataclasses import asdict

from flask import (
    Flask, render_template, request, jsonify, send_file, Response, stream_with_context
)

# Parent directory contains the core modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm_interface import LLMManager, test_provider_connection
from ingestion import (
    parse_references, deduplicate, AbstractScreener,
    export_records_to_csv, export_records_to_excel,
)
from housing_enhanced import SystematicReviewAutomation
from version import VERSION, VERSION_TAG
import workspace_store
from workspace_store import (
    WORKSPACE_PDF_TOKEN,
    UnsafeWorkspacePath,
    WorkspaceError,
    WorkspaceNotFound,
)
from WebApp.services import (
    export_service,
    job_guard,
    processing_service,
    response_builders,
    runtime_state,
    upload_service,
    workspace_service,
)

# Local-only browser UI: this Flask app is intended to run on the researcher's
# own computer at 127.0.0.1. It is not designed for public hosting or multi-user
# deployment.
app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
REFERENCE_UPLOAD_DIR = UPLOAD_DIR / "references"
PDF_UPLOAD_ROOT = UPLOAD_DIR / "pdfs"
OUTPUT_DIR = BASE_DIR / "output"
SETTINGS_FILE = BASE_DIR / "webapp_settings.json"

ALLOWED_REFERENCE_EXTENSIONS = {".ris", ".bib", ".csv", ".txt"}
ALLOWED_PDF_EXTENSIONS = {".pdf"}
MAX_REFERENCE_UPLOAD_SIZE = 25 * 1024 * 1024
MAX_PDF_UPLOAD_SIZE = 100 * 1024 * 1024
MAX_PDF_UPLOAD_COUNT = 200
WEBAPP_DEBUG = os.environ.get("SLR_WEBAPP_DEBUG") == "1"
SETTINGS_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "credential",
)

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
REFERENCE_UPLOAD_DIR.mkdir(exist_ok=True)
PDF_UPLOAD_ROOT.mkdir(exist_ok=True)

app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB

# ---------------------------------------------------------------------------
# In-memory session (single-user web app)
# ---------------------------------------------------------------------------
session = {
    "references": [],
    "dedup_stats": None,
    "pdf_folder": "",
    "pdf_display_names": {},
    "workspace": None,
    "reference_uploads": {},
}
runtime_state.initialize(session)


def _push_runtime(state, event_type: str, data: dict):
    with state.progress_lock:
        state.progress.append({
            "type": event_type,
            "data": data,
            "ts": time.time(),
        })


def _push_screening(event_type: str, data: dict):
    _push_runtime(runtime_state.screening(session), event_type, data)


def _push_processing(event_type: str, data: dict):
    _push_runtime(runtime_state.processing(session), event_type, data)


def _is_relative_to(path: Path, root: Path) -> bool:
    return upload_service.is_relative_to(path, root)


def _resolve_existing_inside(path_value: str, root: Path, require_dir: bool = False) -> Path:
    return upload_service.resolve_existing_inside(path_value, root, require_dir=require_dir)


def _truthy(value) -> bool:
    return upload_service.truthy(value)


def _pdf_relative_name(path: Path, folder: Path) -> str:
    return upload_service.pdf_relative_name(path, folder)


def _discover_pdf_files(folder: Path, include_subfolders: bool = False) -> list[Path]:
    return upload_service.discover_pdf_files(folder, include_subfolders)


def _resolve_pdf_file(folder: Path, filename: str) -> Path:
    return upload_service.resolve_pdf_file(folder, filename)


def _validate_upload_filename(filename: str, allowed_exts: set[str]) -> tuple[str, str]:
    return upload_service.validate_upload_filename(filename, allowed_exts)


def _save_uploaded_file(file_storage, folder: Path, allowed_exts: set[str], max_size: int) -> dict:
    return upload_service.save_uploaded_file(file_storage, folder, allowed_exts, max_size)


def _load_webapp_settings() -> dict:
    if not SETTINGS_FILE.exists():
        return {}
    data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    safe = _sanitize_settings(data)
    if safe != data:
        SETTINGS_FILE.write_text(json.dumps(safe, indent=2), encoding="utf-8")
    return safe


def _write_webapp_settings(data: dict) -> None:
    safe = _sanitize_settings(data)
    SETTINGS_FILE.write_text(json.dumps(safe, indent=2), encoding="utf-8")


def _sanitize_settings(value):
    if isinstance(value, dict):
        clean = {}
        for key, nested in value.items():
            key_text = str(key)
            if any(part in key_text.lower() for part in SETTINGS_SECRET_KEY_PARTS):
                continue
            clean[key_text] = _sanitize_settings(nested)
        return clean
    if isinstance(value, list):
        return [_sanitize_settings(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_settings(item) for item in value]
    return value


def _current_workspace():
    return workspace_service.current_workspace(session)


def _workspace_response(handle=None) -> dict:
    return response_builders.workspace_response(handle or _current_workspace())


def _workspace_pdf_api_name(relative_path: str) -> str:
    return workspace_service.workspace_pdf_api_name(relative_path)


def _workspace_pdf_relative_path(api_name: str) -> str:
    return workspace_service.workspace_pdf_relative_path(api_name)


def _load_workspace_session_state(handle) -> None:
    workspace_service.load_workspace_session_state(session, handle)


def _clear_workspace_session_state() -> None:
    workspace_service.clear_workspace_session_state(session)


def _public_recent_workspaces() -> list[dict]:
    return workspace_service.public_recent_workspaces(_load_webapp_settings)


def _remember_recent_workspace(handle) -> None:
    workspace_service.remember_recent_workspace(handle, _load_webapp_settings, _write_webapp_settings)


def _workspace_path_from_recent(workspace_id: str) -> str:
    return workspace_service.workspace_path_from_recent(workspace_id, _load_webapp_settings)


def _set_current_workspace(handle) -> None:
    workspace_service.set_current_workspace(session, handle, _load_webapp_settings, _write_webapp_settings)


def _resolve_workspace_reference_input(path_value: str) -> tuple[Path, dict]:
    handle = _current_workspace()
    if not handle:
        return _resolve_existing_inside(path_value, REFERENCE_UPLOAD_DIR), {}

    if path_value.startswith("workspace-upload:"):
        upload_id = path_value.split(":", 1)[1]
        meta = session.setdefault("reference_uploads", {}).get(upload_id)
        if not meta:
            raise FileNotFoundError("Upload not found")
        ref_path = _resolve_existing_inside(meta.get("path", ""), REFERENCE_UPLOAD_DIR)
        return ref_path, meta

    ref_path = workspace_store.resolve_workspace_relative_path(
        handle.root,
        path_value,
        subdir="imports",
        must_exist=True,
        require_file=True,
    )
    return ref_path, {"original_filename": ref_path.name}


def _hash_text(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _workspace_relative_api_path(handle, path_value, *, allowed_roots: tuple[str, ...] = ("exports", "cache", "audit")) -> str:
    return workspace_service.workspace_relative_api_path(handle, path_value, allowed_roots=allowed_roots)


def _require_workspace():
    return workspace_service.require_workspace(session)


def _stage_for_workspace(stage: str) -> str:
    return workspace_service.stage_for_workspace(stage)


def _workspace_review_response(handle=None) -> dict:
    return response_builders.workspace_review_response(handle or _current_workspace())


def _review_queue_filter_payload(stage: str | None, status: str | None, origin: str | None) -> dict:
    return response_builders.review_queue_filter_payload(stage, status, origin)


def _persist_workspace_abstract_suggestion(handle, result, *, criteria: str, provider: str, model: str) -> None:
    record = next(
        (item for item in session.get("references", []) if item.get("record_id") == result.record_id),
        {},
    )
    text_fingerprint = "\n".join([
        record.get("title", "") or result.title or "",
        record.get("abstract", "") or "",
    ])
    workspace_store.add_ai_suggestion(
        handle.root,
        record_id=result.record_id,
        stage=workspace_store.REVIEW_STAGE_TITLE_ABSTRACT,
        decision=result.decision,
        rationale=result.rationale,
        confidence=result.confidence,
        provider=provider,
        model=model,
        prompt_hash=_hash_text(criteria),
        text_hash=_hash_text(text_fingerprint),
        metadata={
            "tokens": result.tokens,
            "proc_time": result.proc_time,
        },
    )


# ═══════════════════════════════════════════════════════════════════════════
# Pages
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html", version=VERSION, version_tag=VERSION_TAG)


# ═══════════════════════════════════════════════════════════════════════════
# Provider API
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/providers", methods=["GET"])
def get_providers():
    providers = LLMManager.get_supported_providers()
    return jsonify({
        "providers": providers,
        "defaults": LLMManager.get_default_models(),
        "info": LLMManager.get_provider_info(),
        "models": {p: LLMManager.get_models_for_provider(p) for p in providers},
    })



# ─── Enhance prompts/criteria via user's own LLM ────────────────────────────

_ENHANCE_SYSTEM_PROMPTS = {
    "screening_criteria": """\
You are an expert systematic literature review (SLR) methodologist. A researcher has written \
abstract-screening criteria and needs you to improve them. Return ONLY the improved criteria \
text — no preamble, no commentary, no markdown fences.

IMPROVEMENT RULES
1. Separate the output into clearly labelled "INCLUSION CRITERIA:" and "EXCLUSION CRITERIA:" \
   sections if they are not already distinct.
2. Use a bullet point (•) for each criterion.
3. Organise inclusion criteria under standard PICO/PICOS sub-headings where applicable: \
   Study Type, Population, Intervention/Exposure, Comparator, Outcome, Publication Year, \
   Language, Publication Type. Only include sub-headings that are relevant.
4. Use specific, unambiguous, research-standard language. Replace vague terms \
   (e.g. "good studies", "relevant papers") with precise ones \
   (e.g. "peer-reviewed randomised controlled trials").
5. Remove redundant or duplicate criteria; merge near-duplicates.
6. If the input is very sparse (fewer than 3 bullets), expand it into a complete, \
   PRISMA-aligned template based on the topic implied by the text. State reasonable \
   assumptions in parentheses where you had to guess.
7. Do NOT add criteria that are not implied by the user's input unless the input is so \
   sparse that a reasonable template is required.

OUTPUT FORMAT — return only:
INCLUSION CRITERIA:
• [Sub-heading (optional)]: [Criterion]
...

EXCLUSION CRITERIA:
• [Criterion]
...\
""",

    "screening_prompt": """\
You are an expert systematic literature review (SLR) methodologist. A researcher has written \
screening instructions that will be given to an AI assistant reading full-text papers. \
Return ONLY the improved screening prompt — no preamble, no commentary, no markdown fences.

IMPROVEMENT RULES
1. Frame every criterion as a clear instruction to an AI evaluator, not just a bullet list.
2. Begin with a one-sentence context statement: \
   "You are screening a research paper for inclusion in a systematic review about [topic]."
3. Present INCLUSION and EXCLUSION criteria in clearly labelled sections using bullet points (•).
4. Add an explicit decision rule at the end:
   - "Likely Include" — paper clearly meets all key inclusion criteria.
   - "Likely Exclude" — paper clearly fails one or more inclusion criteria.
   - "Flag for Review" — paper is ambiguous, partially meets criteria, or the full text \
     cannot be reliably assessed; a human must decide.
5. Include a note: when in doubt, flag for review rather than exclude.
6. Use specific, unambiguous language. Remove vague phrasing.
7. If the input is very sparse, expand it into a complete, well-structured full-text \
   screening prompt based on the topic implied by the text.

OUTPUT FORMAT — return only the ready-to-use screening prompt.\
""",

    "extraction_fields": """\
You are an expert systematic literature review (SLR) data-extraction specialist. A researcher \
has listed the fields they want an AI to extract from research papers. Return ONLY the improved \
field list — one field name per line, no bullets, no numbers, no commentary, no markdown fences.

IMPROVEMENT RULES
1. Use snake_case for all field names (e.g. sample_size, study_design, primary_outcome).
2. Keep names concise but self-explanatory (2–4 words maximum per name).
3. Preserve every field the researcher specified. Do not remove any.
4. Remove exact duplicates; merge near-duplicates into the most descriptive version.
5. Add standard SLR extraction fields that are clearly missing but implied by the \
   existing fields or by PRISMA best practice. Do not add fields unrelated to the \
   apparent review topic.
6. Order fields logically:
   a. Identification: title, authors, publication_year, journal, doi
   b. Study characteristics: study_design, country, sample_size, age_range, follow_up
   c. Intervention / Exposure: intervention, comparison / control
   d. Outcomes: primary_outcome, secondary_outcomes, measurement_tool
   e. Results: key_findings, effect_size, statistical_significance
   f. Quality / Context: limitations, funding, conflict_of_interest, risk_of_bias

OUTPUT FORMAT — return only the field names, one per line.\
""",
}


@app.route("/api/enhance", methods=["POST"])
def api_enhance():
    d = request.json or {}
    content   = (d.get("content") or "").strip()
    ftype     = d.get("type", "screening_criteria")
    provider  = d.get("provider", "")
    api_key   = d.get("api_key", "")
    model     = d.get("model", "")
    base_url  = d.get("base_url", "") or None

    if not content:
        return jsonify({"error": "Nothing to enhance — the field is empty."}), 400
    if not provider or not api_key:
        return jsonify({"error": "Configure your AI provider in Stage 1 first."}), 400
    if ftype not in _ENHANCE_SYSTEM_PROMPTS:
        return jsonify({"error": f"Unknown field type: {ftype}"}), 400

    system_prompt = _ENHANCE_SYSTEM_PROMPTS[ftype]

    try:
        kwargs = {}
        if base_url:
            kwargs["base_url"] = base_url
        llm = LLMManager(provider, api_key, model, **kwargs)
        messages = [
            {"role": "system",  "content": system_prompt},
            {"role": "user",    "content": content},
        ]
        enhanced, _ = llm.chat_completion_with_tokens(
            messages, temperature=0.35, max_tokens=2048
        )
        return jsonify({"enhanced": enhanced.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/provider/test", methods=["POST"])
def api_test_connection():
    d = request.json or {}
    kwargs = {}
    if d.get("base_url"):
        kwargs["base_url"] = d["base_url"]
    ok, msg = test_provider_connection(
        d.get("provider", ""), d.get("api_key", ""), d.get("model", ""), **kwargs
    )
    return jsonify({"success": ok, "message": msg})


# ═══════════════════════════════════════════════════════════════════════════
# Workspace API
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/workspaces/current", methods=["GET"])
def api_workspace_current():
    return jsonify(_workspace_response())


@app.route("/api/workspaces/recent", methods=["GET"])
def api_workspace_recent():
    return jsonify({"recent": _public_recent_workspaces()})


@app.route("/api/workspaces/create", methods=["POST"])
def api_workspace_create():
    reservation = job_guard.try_reserve("workspace_lifecycle")
    if reservation is None:
        return jsonify({"error": job_guard.WORKSPACE_CONFLICT_ERROR}), 409
    try:
        d = request.json or {}
        path = (d.get("path") or "").strip()
        name = (d.get("name") or "").strip() or None
        review_title = (d.get("review_title") or "").strip() or None
        review_type = (d.get("review_type") or "").strip() or None
        review_question = (d.get("review_question") or "").strip() or None
        reviewer_name = (d.get("reviewer_name") or "").strip() or None
        if review_type and review_type not in workspace_store.REVIEW_TYPES:
            return jsonify({"error": "Unknown review type"}), 400
        if not path and not review_title and not name:
            return jsonify({
                "error": "Enter a review title to create a workspace, or open the advanced location to choose a folder path."
            }), 400
        try:
            handle = workspace_store.create_workspace(
                path or None,
                name=name,
                review_title=review_title,
                review_type=review_type,
                review_question=review_question,
                reviewer_name=reviewer_name,
            )
            _set_current_workspace(handle)
            return jsonify(_workspace_response(handle))
        except WorkspaceError as e:
            return jsonify({"error": str(e)}), 400
        except OSError as e:
            return jsonify({"error": str(e)}), 400
    finally:
        job_guard.release(reservation)


@app.route("/api/workspaces/open", methods=["POST"])
def api_workspace_open():
    reservation = job_guard.try_reserve("workspace_lifecycle")
    if reservation is None:
        return jsonify({"error": job_guard.WORKSPACE_CONFLICT_ERROR}), 409
    try:
        d = request.json or {}
        path = (d.get("path") or "").strip()
        workspace_id = (d.get("workspace_id") or "").strip()
        if not path and workspace_id:
            path = _workspace_path_from_recent(workspace_id)
        if not path:
            return jsonify({"error": "Workspace path is required"}), 400
        try:
            handle = workspace_store.open_workspace(path)
            _set_current_workspace(handle)
            return jsonify(_workspace_response(handle))
        except WorkspaceNotFound as e:
            return jsonify({"error": str(e)}), 404
        except WorkspaceError as e:
            return jsonify({"error": str(e)}), 400
        except OSError as e:
            return jsonify({"error": str(e)}), 400
    finally:
        job_guard.release(reservation)


@app.route("/api/workspaces/close", methods=["POST"])
def api_workspace_close():
    reservation = job_guard.try_reserve("workspace_lifecycle")
    if reservation is None:
        return jsonify({"error": job_guard.WORKSPACE_CONFLICT_ERROR}), 409
    try:
        _clear_workspace_session_state()
        return jsonify(_workspace_response())
    finally:
        job_guard.release(reservation)


@app.route("/api/workspace/review/queue", methods=["GET"])
def api_workspace_review_queue():
    try:
        handle = _require_workspace()
        stage = request.args.get("stage") or None
        status = request.args.get("status") or None
        origin = request.args.get("origin") or request.args.get("record_origin") or None
        return jsonify(response_builders.workspace_review_queue_response(
            handle,
            stage=stage,
            status=status,
            origin=origin,
        ))
    except WorkspaceError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/workspace/review/decision", methods=["POST"])
def api_workspace_review_decision():
    d = request.json or {}
    try:
        handle = _require_workspace()
        item = workspace_store.add_human_decision(
            handle.root,
            review_item_id=d.get("review_item_id") or d.get("item_id") or "",
            reviewer_id=d.get("reviewer_id") or workspace_store.DEFAULT_REVIEWER_ID,
            decision=d.get("decision") or "",
            rationale=d.get("rationale") or "",
            exclusion_reason_id=d.get("exclusion_reason_id") or None,
        )
        return jsonify({"item": item, "summary": workspace_store.get_review_summary(handle.root)})
    except WorkspaceError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/workspace/review/accept-ai", methods=["POST"])
def api_workspace_review_accept_ai():
    d = request.json or {}
    try:
        handle = _require_workspace()
        item = workspace_store.accept_ai_suggestion(
            handle.root,
            review_item_id=d.get("review_item_id") or d.get("item_id") or "",
            reviewer_id=d.get("reviewer_id") or workspace_store.DEFAULT_REVIEWER_ID,
            rationale=d.get("rationale") or "",
            exclusion_reason_id=d.get("exclusion_reason_id") or None,
        )
        return jsonify({"item": item, "summary": workspace_store.get_review_summary(handle.root)})
    except WorkspaceError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/workspace/review/override", methods=["POST"])
def api_workspace_review_override():
    d = request.json or {}
    try:
        handle = _require_workspace()
        item = workspace_store.override_decision(
            handle.root,
            review_item_id=d.get("review_item_id") or d.get("item_id") or "",
            reviewer_id=d.get("reviewer_id") or workspace_store.DEFAULT_REVIEWER_ID,
            decision=d.get("decision") or "",
            rationale=d.get("rationale") or "",
            exclusion_reason_id=d.get("exclusion_reason_id") or None,
        )
        return jsonify({"item": item, "summary": workspace_store.get_review_summary(handle.root)})
    except WorkspaceError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/workspace/review/summary", methods=["GET"])
def api_workspace_review_summary():
    try:
        handle = _require_workspace()
        return jsonify(_workspace_review_response(handle))
    except WorkspaceError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/workspace/exports/summary", methods=["GET"])
def api_workspace_exports_summary():
    try:
        handle = _require_workspace()
        return jsonify(export_service.get_workspace_exports_summary(workspace_store, handle.root))
    except WorkspaceError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/workspace/exports/generate", methods=["POST"])
def api_workspace_exports_generate():
    try:
        handle = _require_workspace()
        manifest = export_service.generate_workspace_exports(
            workspace_store,
            handle.root,
            options=request.json or {},
        )
        return jsonify({"export": manifest})
    except WorkspaceError as e:
        return jsonify({"error": str(e)}), 400
    except OSError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/workspace/exports/list", methods=["GET"])
def api_workspace_exports_list():
    try:
        handle = _require_workspace()
        exports = export_service.list_workspace_exports(workspace_store, handle.root)
        return jsonify({"exports": exports, "total": len(exports)})
    except WorkspaceError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/workspace/exports/download/<export_id>/<path:filename>", methods=["GET"])
def api_workspace_exports_download(export_id, filename):
    try:
        handle = _require_workspace()
        target = export_service.resolve_export_download(
            workspace_store,
            handle.root,
            export_id,
            filename,
        )
        return send_file(str(target), as_attachment=True, download_name=target.name)
    except FileNotFoundError:
        return jsonify({"error": "Export file not found"}), 404
    except (WorkspaceError, ValueError):
        return jsonify({"error": "Invalid export path"}), 400


# ═══════════════════════════════════════════════════════════════════════════
# Reference ingestion
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/references/upload", methods=["POST"])
def upload_references():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    try:
        saved = _save_uploaded_file(
            f,
            REFERENCE_UPLOAD_DIR,
            ALLOWED_REFERENCE_EXTENSIONS,
            MAX_REFERENCE_UPLOAD_SIZE,
        )
        if _current_workspace():
            upload_id = uuid.uuid4().hex
            session.setdefault("reference_uploads", {})[upload_id] = saved
            public = {
                "path": f"workspace-upload:{upload_id}",
                "filename": saved["filename"],
                "original_filename": saved["original_filename"],
                "size": saved["size"],
            }
            return jsonify(public)
        return jsonify(saved)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/references/parse", methods=["POST"])
def api_parse_references():
    d = request.json or {}
    path = d.get("path", "")
    try:
        ref_path, upload_meta = _resolve_workspace_reference_input(path)
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404
    except (ValueError, UnsafeWorkspacePath) as e:
        return jsonify({"error": str(e)}), 400
    if ref_path.suffix.lower() not in ALLOWED_REFERENCE_EXTENSIONS:
        return jsonify({"error": "Unsupported reference file format"}), 400
    try:
        records = parse_references(str(ref_path))
        session["references"] = records
        payload = {
            "count": len(records),
            "sample": records[:5],
        }
        handle = _current_workspace()
        if handle:
            persisted = workspace_store.persist_reference_import(
                handle.root,
                ref_path,
                records,
                original_filename=upload_meta.get("original_filename") or ref_path.name,
            )
            payload["workspace"] = {
                "source_id": persisted["source_id"],
                "record_count": persisted["record_count"],
                "summary": handle.public_summary(),
            }
            session["references"] = workspace_store.load_records(handle.root)
        return jsonify(payload)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/references/deduplicate", methods=["POST"])
def api_deduplicate():
    if not session["references"]:
        return jsonify({"error": "No references loaded"}), 400
    d = request.json or {}
    threshold = d.get("threshold", 90)
    handle = _current_workspace()
    if handle:
        result = workspace_store.apply_reference_deduplication(
            handle.root,
            fuzzy_threshold=threshold,
        )
        session["references"] = workspace_store.load_records(handle.root)
        session["dedup_stats"] = result["stats"]
        return jsonify({
            "stats": result["stats"],
            "remaining": len(session["references"]),
            "workspace": {
                "summary": handle.public_summary(),
                "duplicates": result["duplicates"],
            },
        })

    unique, stats = deduplicate(session["references"], fuzzy_threshold=threshold)
    session["references"] = unique
    session["dedup_stats"] = asdict(stats)
    return jsonify({"stats": asdict(stats), "remaining": len(unique)})


@app.route("/api/references/list", methods=["GET"])
def api_list_references():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    query = (request.args.get("q") or "").strip()
    refs = session["references"]
    filtered = refs
    if query:
        needle = query.lower()
        filtered = [
            ref for ref in refs
            if any(
                needle in (str(ref.get(field) or "").lower())
                for field in ("title", "authors", "year", "journal", "doi")
            )
            or needle in (str(ref.get("record_id") or "").lower())
        ]
    start = (page - 1) * per_page
    end = start + per_page
    page_records = filtered[start:end]
    return jsonify({
        "total": len(refs),
        "filtered_total": len(filtered),
        "visible_count": len(page_records),
        "showing": len(page_records),
        "page": page,
        "per_page": per_page,
        "query": query,
        "showing_copy": f"Showing {len(page_records)} of {len(filtered)} records{(' matching filter') if query else ''}",
        "has_filter": bool(query),
        "records": page_records,
    })


# ═══════════════════════════════════════════════════════════════════════════
# Abstract screening
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/screening/start", methods=["POST"])
def api_start_screening():
    d = request.json or {}
    provider = d.get("provider", "")
    api_key = d.get("api_key", "")
    model = d.get("model", "")
    criteria = d.get("criteria", "")
    kwargs = {}
    if d.get("base_url"):
        kwargs["base_url"] = d["base_url"]

    reservation = job_guard.try_reserve("screening")
    if reservation is None:
        return jsonify({"error": job_guard.CONFLICT_ERROR}), 409

    worker_started = False
    screening = runtime_state.screening(session)
    try:
        if not session["references"]:
            return jsonify({"error": "No references loaded"}), 400

        try:
            llm = LLMManager(provider, api_key, model, **kwargs)
        except Exception as e:
            return jsonify({"error": f"LLM init failed: {e}"}), 500

        screening.reset_for_start()

        screener = AbstractScreener(
            llm,
            rate_limit_delay=float(d.get("rate_delay", 0.5)),
            stop_event=screening.stop_event,
        )
        workspace_handle = _current_workspace()

        def _run():
            try:
                def _cb(result, idx, total):
                    screening.results.append(asdict(result))
                    if workspace_handle:
                        try:
                            _persist_workspace_abstract_suggestion(
                                workspace_handle,
                                result,
                                criteria=criteria,
                                provider=provider,
                                model=model,
                            )
                        except Exception as exc:
                            _push_screening("screening_warning", {"warning": f"Workspace suggestion not persisted: {exc}"})
                    _push_screening("screening_progress", {
                        "index": idx,
                        "total": total,
                        "decision": result.decision,
                        "title": result.title[:120],
                    })

                screener.screen_all(session["references"], criteria, callback=_cb)
                _push_screening("screening_done", {"total": len(screening.results)})
            except Exception:
                screening.error = "Screening failed"
                raise
            finally:
                job_guard.release(reservation)

        t = threading.Thread(target=_run, daemon=True)
        previous_thread = screening.thread
        previous_stream_job = session["event_stream_job"]
        screening.thread = t
        session["event_stream_job"] = "screening"
        try:
            t.start()
        except Exception:
            screening.thread = previous_thread
            session["event_stream_job"] = previous_stream_job
            raise
        worker_started = True
        return jsonify({"status": "started", "total": len(session["references"])})
    finally:
        if not worker_started:
            job_guard.release(reservation)


@app.route("/api/screening/stop", methods=["POST"])
def api_stop_screening():
    runtime_state.screening(session).stop_event.set()
    return jsonify({"status": "stopping"})


@app.route("/api/screening/results", methods=["GET"])
def api_screening_results():
    results = runtime_state.screening(session).results
    return jsonify({
        "results": results,
        "total": len(results),
    })


@app.route("/api/screening/export", methods=["POST"])
def api_export_screening():
    d = request.json or {}
    fmt = d.get("format", "xlsx")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    from ingestion import AbstractScreeningResult
    results_objs = []
    for r in runtime_state.screening(session).results:
        results_objs.append(AbstractScreeningResult(
            record_id=r.get("record_id", ""),
            title=r.get("title", ""),
            decision=r.get("decision", ""),
            rationale=r.get("rationale", ""),
            confidence=r.get("confidence", ""),
            tokens=r.get("tokens", 0),
            proc_time=r.get("proc_time", 0),
        ))

    if fmt == "csv":
        path = OUTPUT_DIR / f"abstract_screening_{ts}.csv"
        export_records_to_csv(session["references"], results_objs, str(path))
    else:
        path = OUTPUT_DIR / f"abstract_screening_{ts}.xlsx"
        stats_obj = None
        if session["dedup_stats"]:
            from ingestion import DeduplicationStats
            stats_obj = DeduplicationStats(**session["dedup_stats"])
        export_records_to_excel(session["references"], results_objs, str(path), stats=stats_obj)

    return send_file(str(path), as_attachment=True)


# ═══════════════════════════════════════════════════════════════════════════
# PDF upload & processing
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/pdfs/upload", methods=["POST"])
def upload_pdfs():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files provided"}), 400
    if len(files) > MAX_PDF_UPLOAD_COUNT:
        return jsonify({"error": f"Too many files; limit is {MAX_PDF_UPLOAD_COUNT} PDFs"}), 400
    try:
        for f in files:
            _validate_upload_filename(f.filename, ALLOWED_PDF_EXTENSIONS)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    handle = _current_workspace()
    if handle:
        pdf_dir = handle.root / "pdfs"
        saved = []
        display_names = session.setdefault("pdf_display_names", {})
        for f in files:
            try:
                item = _save_uploaded_file(f, pdf_dir, ALLOWED_PDF_EXTENSIONS, MAX_PDF_UPLOAD_SIZE)
                relative_path = Path(item["path"]).resolve().relative_to(handle.root.resolve()).as_posix()
                pdf_meta = workspace_store.register_pdf(
                    handle.root,
                    relative_path,
                    original_filename=item["original_filename"],
                    display_name=item["original_filename"],
                )
            except (ValueError, WorkspaceError, FileNotFoundError) as e:
                return jsonify({"error": str(e)}), 400
            api_name = _workspace_pdf_api_name(pdf_meta["relative_path"])
            display_names[api_name] = pdf_meta["display_name"]
            display_names[Path(api_name).name] = pdf_meta["display_name"]
            saved.append({
                "path": api_name,
                "filename": api_name,
                "relative_path": pdf_meta["relative_path"],
                "original_filename": pdf_meta["original_filename"],
                "display_name": pdf_meta["display_name"],
                "size": pdf_meta["size"],
                "sha256": pdf_meta["sha256"],
                "pdf_id": pdf_meta["pdf_id"],
            })

        session["pdf_folder"] = WORKSPACE_PDF_TOKEN
        return jsonify({
            "count": len(saved),
            "files": saved,
            "folder": WORKSPACE_PDF_TOKEN,
            "workspace": True,
        })

    # Reuse the existing session folder so users can add files incrementally
    existing = session.get("pdf_folder", "")
    try:
        pdf_dir = _resolve_existing_inside(existing, PDF_UPLOAD_ROOT, require_dir=True) if existing else None
    except (FileNotFoundError, ValueError):
        pdf_dir = None
    if pdf_dir is None:
        pdf_dir = PDF_UPLOAD_ROOT / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        pdf_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    display_names = session.setdefault("pdf_display_names", {})
    for f in files:
        try:
            item = _save_uploaded_file(f, pdf_dir, ALLOWED_PDF_EXTENSIONS, MAX_PDF_UPLOAD_SIZE)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        saved.append(item)
        display_names[item["filename"]] = item["original_filename"]

    session["pdf_folder"] = str(pdf_dir)
    return jsonify({"count": len(saved), "files": saved, "folder": str(pdf_dir)})


@app.route("/api/pdfs/list", methods=["GET"])
def list_pdfs():
    handle = _current_workspace()
    if handle:
        include_subfolders = _truthy(request.args.get("include_subfolders"))
        files = []
        for row in workspace_store.list_pdf_metadata(handle.root):
            api_name = _workspace_pdf_api_name(row["relative_path"])
            if not include_subfolders and "/" in api_name:
                continue
            try:
                target = workspace_store.resolve_workspace_relative_path(
                    handle.root,
                    row["relative_path"],
                    subdir="pdfs",
                    must_exist=True,
                    require_file=True,
                )
            except (FileNotFoundError, WorkspaceError):
                continue
            files.append({
                "name": api_name,
                "display_name": row["display_name"],
                "size": row["file_size"],
                "path": api_name,
                "sha256": row["sha256"],
                "pdf_id": row["pdf_id"],
            })
        return jsonify({
            "files": files,
            "folder": WORKSPACE_PDF_TOKEN,
            "include_subfolders": include_subfolders,
            "workspace": True,
        })

    pdf_folder = session.get("pdf_folder", "")
    include_subfolders = _truthy(request.args.get("include_subfolders"))
    try:
        folder = _resolve_existing_inside(pdf_folder, PDF_UPLOAD_ROOT, require_dir=True)
    except (FileNotFoundError, ValueError):
        return jsonify({"files": []})
    files = []
    display_names = session.get("pdf_display_names", {})
    for p in _discover_pdf_files(folder, include_subfolders):
        relative_name = _pdf_relative_name(p, folder)
        files.append({
            "name": relative_name,
            "display_name": display_names.get(relative_name, relative_name),
            "size": p.stat().st_size,
            "path": str(p),
        })
    return jsonify({"files": files, "folder": str(folder), "include_subfolders": include_subfolders})


@app.route("/api/pdfs/delete", methods=["POST"])
def delete_pdf():
    d = request.json or {}
    filename = d.get("filename", "")
    include_subfolders = _truthy(d.get("include_subfolders"))
    handle = _current_workspace()
    if handle:
        if not filename:
            return jsonify({"error": "Missing filename"}), 400
        try:
            relative_path = _workspace_pdf_relative_path(filename)
            remaining = workspace_store.delete_pdf(handle.root, relative_path)
        except FileNotFoundError:
            return jsonify({"error": "File not found"}), 404
        except WorkspaceError:
            return jsonify({"error": "Invalid filename"}), 400
        display_names = session.setdefault("pdf_display_names", {})
        display_names.pop(filename, None)
        display_names.pop(Path(filename).name, None)
        session["pdf_count"] = remaining
        session["pdf_folder"] = WORKSPACE_PDF_TOKEN
        return jsonify({"ok": True, "remaining": remaining})

    pdf_folder = session.get("pdf_folder", "")
    if not pdf_folder or not filename:
        return jsonify({"error": "Missing folder or filename"}), 400
    try:
        folder = _resolve_existing_inside(pdf_folder, PDF_UPLOAD_ROOT, require_dir=True)
        target = _resolve_pdf_file(folder, filename)
    except (FileNotFoundError, ValueError):
        return jsonify({"error": "Invalid filename"}), 400
    if not target.exists():
        return jsonify({"error": "File not found"}), 404
    relative_name = _pdf_relative_name(target, folder)
    target.unlink()
    display_names = session.setdefault("pdf_display_names", {})
    display_names.pop(relative_name, None)
    remaining = len(_discover_pdf_files(folder, include_subfolders))
    session["pdf_count"] = remaining
    if remaining == 0:
        session["pdf_folder"] = ""
    return jsonify({"ok": True, "remaining": remaining})


@app.route("/api/pdfs/clear", methods=["POST"])
def clear_pdfs():
    handle = _current_workspace()
    if handle:
        workspace_store.clear_pdfs(handle.root)
        session["pdf_folder"] = WORKSPACE_PDF_TOKEN
        session["pdf_display_names"] = {}
        return jsonify({"ok": True})

    pdf_folder = session.get("pdf_folder", "")
    try:
        folder = _resolve_existing_inside(pdf_folder, PDF_UPLOAD_ROOT, require_dir=True)
    except (FileNotFoundError, ValueError):
        folder = None
    if folder and folder != PDF_UPLOAD_ROOT.resolve():
        shutil.rmtree(folder, ignore_errors=True)
    session["pdf_folder"] = ""
    session["pdf_display_names"] = {}
    return jsonify({"ok": True})


@app.route("/api/pdfs/file/<path:filename>", methods=["GET"])
def serve_pdf(filename):
    handle = _current_workspace()
    if handle:
        try:
            target = workspace_store.resolve_workspace_relative_path(
                handle.root,
                _workspace_pdf_relative_path(filename),
                subdir="pdfs",
                must_exist=True,
                require_file=True,
            )
        except FileNotFoundError:
            return jsonify({"error": "File not found"}), 404
        except WorkspaceError:
            return jsonify({"error": "Invalid path"}), 400
        return send_file(str(target), mimetype="application/pdf")

    pdf_folder = session.get("pdf_folder", "")
    if not pdf_folder:
        return jsonify({"error": "No PDF folder"}), 404
    try:
        folder = _resolve_existing_inside(pdf_folder, PDF_UPLOAD_ROOT, require_dir=True)
        target = _resolve_pdf_file(folder, filename)
    except (FileNotFoundError, ValueError):
        return jsonify({"error": "Invalid path"}), 400
    if not target.exists():
        return jsonify({"error": "File not found"}), 404
    return send_file(str(target), mimetype="application/pdf")


@app.route("/api/processing/start", methods=["POST"])
def api_start_processing():
    d = request.json or {}
    result = processing_service.start_processing(
        d,
        session=session,
        workspace_handle=_current_workspace(),
        pdf_upload_root=PDF_UPLOAD_ROOT,
        output_dir=OUTPUT_DIR,
        automation_cls=SystematicReviewAutomation,
        push_event=_push_processing,
    )
    if result.status_code == 200:
        return jsonify(result.payload)
    return jsonify(result.payload), result.status_code


@app.route("/api/processing/stop", methods=["POST"])
def api_stop_processing():
    return jsonify(processing_service.stop_processing(session))


@app.route("/api/processing/status", methods=["GET"])
def api_processing_status():
    return jsonify(processing_service.processing_status_payload(session, _current_workspace()))


@app.route("/api/progress", methods=["GET"])
def api_progress():
    return api_processing_status()


@app.route("/api/processing/results", methods=["GET"])
def api_processing_results():
    return jsonify(processing_service.processing_results_payload(session, _current_workspace()))


@app.route("/api/processing/export", methods=["POST"])
def api_export_processing():
    d = request.json or {}
    result = processing_service.processing_export_response(
        session,
        d.get("which", "screening"),
        _current_workspace(),
    )
    if result.path:
        return send_file(str(result.path), as_attachment=True)
    return jsonify(result.payload), result.status_code


# ═══════════════════════════════════════════════════════════════════════════
# SSE progress stream
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/events")
def sse_events():
    def generate():
        last_idx = 0
        while True:
            state = runtime_state.event_stream(session, job_guard.active_job())
            with state.progress_lock:
                events = state.progress[last_idx:]
                last_idx = len(state.progress)

            for ev in events:
                yield f"data: {json.dumps(ev)}\n\n"

            # Also stream processing stats if active
            stats_event = processing_service.processing_stats_event_payload(session, _current_workspace())
            if stats_event:
                yield f"data: {json.dumps(stats_event)}\n\n"

            time.sleep(1)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ═══════════════════════════════════════════════════════════════════════════
# Settings
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    data = _load_webapp_settings()
    data.pop("recent_workspaces", None)
    return jsonify(data)


@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    d = request.json or {}
    # Strip API key before persisting
    existing = _load_webapp_settings()
    safe = {k: v for k, v in d.items() if k != "api_key"}
    if "recent_workspaces" in existing and "recent_workspaces" not in safe:
        safe["recent_workspaces"] = existing["recent_workspaces"]
    _write_webapp_settings(safe)
    return jsonify({"status": "saved"})


# ═══════════════════════════════════════════════════════════════════════════
# Run
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app.run(debug=WEBAPP_DEBUG, host="127.0.0.1", port=5000, threaded=True)
