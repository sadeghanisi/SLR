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
from pathlib import Path
from datetime import datetime
from dataclasses import asdict

from flask import (
    Flask, render_template, request, jsonify, send_file, Response, stream_with_context
)
from flask_cors import CORS

# Parent directory contains the core modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm_interface import LLMManager, test_provider_connection
from ingestion import (
    parse_references, deduplicate, AbstractScreener,
    export_records_to_csv, export_records_to_excel,
)
from housing_enhanced import SystematicReviewAutomation

app = Flask(__name__)
CORS(app)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
SETTINGS_FILE = BASE_DIR / "webapp_settings.json"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
(UPLOAD_DIR / "references").mkdir(exist_ok=True)
(UPLOAD_DIR / "pdfs").mkdir(exist_ok=True)

app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB

# ---------------------------------------------------------------------------
# In-memory session (single-user web app)
# ---------------------------------------------------------------------------
session = {
    "references": [],
    "dedup_stats": None,
    "screening_results": [],
    "pdf_folder": "",
    "automation": None,
    "stop_event": threading.Event(),
    "processing_thread": None,
    "progress": [],
    "progress_lock": threading.Lock(),
}


def _push(event_type: str, data: dict):
    with session["progress_lock"]:
        session["progress"].append({
            "type": event_type,
            "data": data,
            "ts": time.time(),
        })


# ═══════════════════════════════════════════════════════════════════════════
# Pages
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


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
# Reference ingestion
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/references/upload", methods=["POST"])
def upload_references():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    ext = Path(f.filename).suffix.lower()
    if ext not in (".ris", ".bib", ".csv", ".txt"):
        return jsonify({"error": f"Unsupported format: {ext}"}), 400

    dest = UPLOAD_DIR / "references" / f.filename
    f.save(str(dest))
    return jsonify({"path": str(dest), "filename": f.filename, "size": dest.stat().st_size})


@app.route("/api/references/parse", methods=["POST"])
def api_parse_references():
    d = request.json or {}
    path = d.get("path", "")
    if not path or not Path(path).exists():
        return jsonify({"error": "File not found"}), 404
    try:
        records = parse_references(path)
        session["references"] = records
        return jsonify({
            "count": len(records),
            "sample": records[:5],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/references/deduplicate", methods=["POST"])
def api_deduplicate():
    if not session["references"]:
        return jsonify({"error": "No references loaded"}), 400
    d = request.json or {}
    threshold = d.get("threshold", 90)
    unique, stats = deduplicate(session["references"], fuzzy_threshold=threshold)
    session["references"] = unique
    session["dedup_stats"] = asdict(stats)
    return jsonify({"stats": asdict(stats), "remaining": len(unique)})


@app.route("/api/references/list", methods=["GET"])
def api_list_references():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    refs = session["references"]
    start = (page - 1) * per_page
    end = start + per_page
    return jsonify({
        "total": len(refs),
        "page": page,
        "per_page": per_page,
        "records": refs[start:end],
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

    if not session["references"]:
        return jsonify({"error": "No references loaded"}), 400

    try:
        llm = LLMManager(provider, api_key, model, **kwargs)
    except Exception as e:
        return jsonify({"error": f"LLM init failed: {e}"}), 500

    session["screening_results"] = []
    session["stop_event"].clear()
    session["progress"] = []

    screener = AbstractScreener(llm, rate_limit_delay=float(d.get("rate_delay", 0.5)))

    def _run():
        def _cb(result, idx, total):
            session["screening_results"].append(asdict(result))
            _push("screening_progress", {
                "index": idx,
                "total": total,
                "decision": result.decision,
                "title": result.title[:120],
            })

        screener.screen_all(session["references"], criteria, callback=_cb)
        _push("screening_done", {"total": len(session["screening_results"])})

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    session["processing_thread"] = t
    return jsonify({"status": "started", "total": len(session["references"])})


@app.route("/api/screening/stop", methods=["POST"])
def api_stop_screening():
    session["stop_event"].set()
    return jsonify({"status": "stopping"})


@app.route("/api/screening/results", methods=["GET"])
def api_screening_results():
    return jsonify({
        "results": session["screening_results"],
        "total": len(session["screening_results"]),
    })


@app.route("/api/screening/export", methods=["POST"])
def api_export_screening():
    d = request.json or {}
    fmt = d.get("format", "xlsx")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    from ingestion import AbstractScreeningResult
    results_objs = []
    for r in session["screening_results"]:
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

    # Reuse the existing session folder so users can add files incrementally
    existing = session.get("pdf_folder", "")
    if existing and Path(existing).exists():
        pdf_dir = Path(existing)
    else:
        pdf_dir = UPLOAD_DIR / "pdfs" / datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for f in files:
        if f.filename and f.filename.lower().endswith(".pdf"):
            dest = pdf_dir / f.filename
            f.save(str(dest))
            saved.append(f.filename)

    session["pdf_folder"] = str(pdf_dir)
    return jsonify({"count": len(saved), "files": saved, "folder": str(pdf_dir)})


@app.route("/api/pdfs/list", methods=["GET"])
def list_pdfs():
    pdf_folder = session.get("pdf_folder", "")
    if not pdf_folder or not Path(pdf_folder).exists():
        return jsonify({"files": []})
    files = []
    for p in sorted(Path(pdf_folder).glob("*.pdf")):
        files.append({"name": p.name, "size": p.stat().st_size, "path": str(p)})
    return jsonify({"files": files, "folder": pdf_folder})


@app.route("/api/pdfs/delete", methods=["POST"])
def delete_pdf():
    d = request.json or {}
    filename = d.get("filename", "")
    pdf_folder = session.get("pdf_folder", "")
    if not pdf_folder or not filename:
        return jsonify({"error": "Missing folder or filename"}), 400
    target = Path(pdf_folder) / filename
    # Guard against path traversal
    if not target.resolve().parent == Path(pdf_folder).resolve():
        return jsonify({"error": "Invalid filename"}), 400
    if not target.exists():
        return jsonify({"error": "File not found"}), 404
    target.unlink()
    remaining = len(list(Path(pdf_folder).glob("*.pdf")))
    session["pdf_count"] = remaining
    if remaining == 0:
        session["pdf_folder"] = ""
    return jsonify({"ok": True, "remaining": remaining})


@app.route("/api/pdfs/clear", methods=["POST"])
def clear_pdfs():
    pdf_folder = session.get("pdf_folder", "")
    if pdf_folder and Path(pdf_folder).exists():
        shutil.rmtree(pdf_folder, ignore_errors=True)
    session["pdf_folder"] = ""
    return jsonify({"ok": True})


@app.route("/api/pdfs/file/<path:filename>", methods=["GET"])
def serve_pdf(filename):
    pdf_folder = session.get("pdf_folder", "")
    if not pdf_folder:
        return jsonify({"error": "No PDF folder"}), 404
    target = (Path(pdf_folder) / filename).resolve()
    if not str(target).startswith(str(Path(pdf_folder).resolve())):
        return jsonify({"error": "Invalid path"}), 400
    if not target.exists():
        return jsonify({"error": "File not found"}), 404
    return send_file(str(target), mimetype="application/pdf")


@app.route("/api/processing/start", methods=["POST"])
def api_start_processing():
    d = request.json or {}
    pdf_folder = d.get("pdf_folder") or session.get("pdf_folder", "")
    if not pdf_folder or not Path(pdf_folder).exists():
        return jsonify({"error": "No PDF folder selected"}), 400

    session["stop_event"].clear()
    session["progress"] = []

    config = {
        "api_key": d.get("api_key", ""),
        "pdf_folder": pdf_folder,
        "output_folder": str(OUTPUT_DIR),
        "cache_enabled": d.get("cache_enabled", True),
        "parallel_processing": d.get("parallel", True),
        "max_workers": d.get("max_workers", 3),
        "rate_limit_delay": d.get("rate_delay", 1.0),
        "llm_provider": d.get("provider", "OpenAI"),
        "llm_model": d.get("model", ""),
        "two_stage_screening": d.get("two_stage", False),
        "stop_event": session["stop_event"],
        "screening_prompt": d.get("screening_prompt"),
        "extraction_prompt": d.get("extraction_prompt"),
        "extraction_fields": d.get("extraction_fields"),
    }

    if d.get("base_url"):
        config["base_url"] = d["base_url"]

    adv = d.get("advanced", {})
    if adv:
        config["advanced_config"] = adv

    try:
        auto = SystematicReviewAutomation(**config)
        session["automation"] = auto
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    def _run():
        try:
            summary = auto.process_pdfs()
            _push("processing_done", summary)
        except Exception as e:
            _push("processing_error", {"error": str(e)})

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    session["processing_thread"] = t

    pdf_count = len(list(Path(pdf_folder).glob("*.pdf")))
    return jsonify({"status": "started", "total": pdf_count})


@app.route("/api/processing/stop", methods=["POST"])
def api_stop_processing():
    session["stop_event"].set()
    return jsonify({"status": "stopping"})


@app.route("/api/processing/status", methods=["GET"])
def api_processing_status():
    auto = session.get("automation")
    if not auto:
        return jsonify({"active": False})

    stats = dict(auto.stats)
    screening = [asdict(r) for r in auto.screening_results]
    extraction = []
    for r in auto.extraction_results:
        extraction.append({
            "filename": r.filename,
            "fields": r.fields,
            "processing_time": r.processing_time,
            "api_tokens_used": r.api_tokens_used,
        })

    running = session["processing_thread"] and session["processing_thread"].is_alive()
    return jsonify({
        "active": running,
        "stats": stats,
        "screening_count": len(screening),
        "extraction_count": len(extraction),
    })


@app.route("/api/processing/results", methods=["GET"])
def api_processing_results():
    auto = session.get("automation")
    if not auto:
        return jsonify({"screening": [], "extraction": []})

    screening = [asdict(r) for r in auto.screening_results]
    extraction = []
    for r in auto.extraction_results:
        extraction.append({
            "filename": r.filename,
            "fields": r.fields,
            "processing_time": round(r.processing_time, 2),
            "api_tokens_used": r.api_tokens_used,
        })

    return jsonify({"screening": screening, "extraction": extraction})


@app.route("/api/processing/export", methods=["POST"])
def api_export_processing():
    auto = session.get("automation")
    if not auto:
        return jsonify({"error": "No processing results"}), 400

    d = request.json or {}
    which = d.get("which", "screening")

    if which == "extraction" and auto.extraction_excel and Path(auto.extraction_excel).exists():
        return send_file(str(auto.extraction_excel), as_attachment=True)
    elif auto.screening_excel and Path(auto.screening_excel).exists():
        return send_file(str(auto.screening_excel), as_attachment=True)
    else:
        return jsonify({"error": "Export file not found"}), 404


# ═══════════════════════════════════════════════════════════════════════════
# SSE progress stream
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/events")
def sse_events():
    def generate():
        last_idx = 0
        while True:
            with session["progress_lock"]:
                events = session["progress"][last_idx:]
                last_idx = len(session["progress"])

            for ev in events:
                yield f"data: {json.dumps(ev)}\n\n"

            # Also stream processing stats if active
            auto = session.get("automation")
            if auto:
                stats = dict(auto.stats)
                yield f"data: {json.dumps({'type': 'stats', 'data': stats})}\n\n"

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
    if SETTINGS_FILE.exists():
        return jsonify(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    return jsonify({})


@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    d = request.json or {}
    # Strip API key before persisting
    safe = {k: v for k, v in d.items() if k != "api_key"}
    SETTINGS_FILE.write_text(json.dumps(safe, indent=2), encoding="utf-8")
    return jsonify({"status": "saved"})


# ═══════════════════════════════════════════════════════════════════════════
# Run
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000, threaded=True)
