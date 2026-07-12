# Changelog

All notable changes to SLR Assistant are documented in this file.

## Unreleased

_No unreleased changes yet._

## [3.5.2] - 2026-07-13

This release consolidates the v3.5.x Workspace UX/navigation redesign, persistent
workspace references and PDF metadata, the Human Review Queue, AI suggestions as
non-final, human decisions as final, workspace dedup persistence, and
workspace-scoped exports/cache/audit. It is the first release to ship Workspace
Exports, PRISMA-ready reporting data, and Methods Disclosure via the workspace
database.

### Added

- **Workspace Mode UX/navigation redesign.** Clear start screen separating
  `+ New Workspace`, `Open Existing Workspace`, `Recent Workspaces`, and
  `Continue Without Workspace`. Workspace Mode and Legacy Mode are labeled
  explicitly in the WebApp header.
- **Guided workspace creation.** A researcher can create a workspace using only
  a review title; no manual absolute path entry is required. The workspace lands
  under a safe default location (`~/SLR Assistant Workspaces`) with
  collision-safe folder names. Manual path entry remains available as an
  advanced option.
- **Recent workspace cards.** Recent workspaces reopen from a card list via
  `workspace_id` without exposing absolute filesystem paths through the API.
- **Persistent workspace references, source provenance, and PDF metadata.**
  Imports, parsed records, record-to-source links, and PDF metadata persist in
  `workspace.sqlite3` and reload correctly on reopen, not just as counts.
- **Workspace-type review metadata.** Optional `review_title`, `review_type`,
  `review_question`, and `reviewer_name` are stored on the workspace for
  display only; they do not alter screening, deduplication, or count
  definitions.
- **Human Review Queue foundation.** Persistent `review_items` and `decisions`
  workflow using the existing SQLite workspace database.
- Workspace review endpoints:
  - `GET /api/workspace/review/queue`
  - `POST /api/workspace/review/decision`
  - `POST /api/workspace/review/accept-ai`
  - `POST /api/workspace/review/override`
  - `GET /api/workspace/review/summary`
- Compact WebApp review queue card with status filter, AI suggestion, human
  final decision, rationale field, exclusion reason dropdown, and Include /
  Exclude / Maybe / Accept AI actions.
- **AI suggestions are treated as non-final.** AI include/exclude/maybe output
  is stored as `actor_type = ai` and never counts as a final eligibility
  decision. A human Include / Exclude / Maybe decision is required for final
  status.
- **Human decisions as final.** Human Include / Exclude / Maybe decisions
  override AI suggestions and become the final eligibility decision in
  workspace summaries and exports.
- **Workspace dedup persistence.** DOI and fuzzy-title deduplication marks
  records inactive while retaining them for audit; active unique and duplicate
  counts persist across reopen.
- **First-class `record_origin`.** Records carry `record_origin` of
  `imported_reference`, `pdf_only`, or `manual`, so exports and PRISMA-ready
  counts distinguish database/reference imports from PDFs added without
  reference metadata. PDF-only records are usable in the review queue and
  counted separately from imported reference records.
- **Workspace-scoped exports/cache/audit.** Processing runs write output,
  cache, and audit artifacts under workspace `exports/`, `cache/`, and
  `audit/` as workspace-relative paths.
- **Workspace Exports.** Workspace reporting data generated from the local
  workspace database:
  - New Workspace export endpoints:
    - `GET /api/workspace/exports/summary`
    - `POST /api/workspace/exports/generate`
    - `GET /api/workspace/exports/list`
    - `GET /api/workspace/exports/download/<export_id>/<filename>`
  - Workspace export files under `workspace/exports/<export_id>/`:
    - `workspace_screening_decisions.csv`
    - `workspace_screening_decisions.xlsx`
    - `workspace_review_items.csv`
    - `workspace_ai_suggestions.csv`
    - `workspace_human_decisions.csv`
    - `workspace_full_text_exclusions.csv`
    - `prisma_ready_counts.json`
    - `prisma_ready_counts.csv`
    - `methods_disclosure.md`
    - `export_manifest.json`
- **PRISMA-ready reporting data.** PRISMA-ready counts derived from workspace
  SQLite data, including active unique imported references, duplicate records
  hidden from active screening, PDF-only records, manual records, AI-only
  unfinalized suggestions, human final decisions by stage, failed items, and
  full-text exclusions by reason. Counts marked `not_available` are not
  fabricated.
- **Methods Disclosure.** Conservative `methods_disclosure.md` draft explaining
  local-first mode, AI suggestions, human-final decisions, deduplication,
  record origins, AI provider/model metadata where available, full-text
  exclusion handling, and limitations. It does not claim PRISMA compliance.
- **Reference-list search and pagination.** The in-workspace reference list is
  bounded and scrollable, with `Showing X of Y records` copy, search across
  title/authors/year/journal/doi/record_id, and `page`/`per_page` pagination
  metadata.
- Workspace progress panel showing local database counts for imported
  reference records, PDF-only records, manual records, sources, PDFs, review
  items, AI suggestions, human decisions, and pending/final statuses.
- Review queue filter context showing current stage/status/origin filters,
  visible item count, total review item count, imported-reference count, and
  PDF-only count. The WebApp explains when a queue view is a filtered subset of
  a much larger imported reference set.
- Compact Workspace Exports panel in the WebApp Results stage.
- Default local reviewer and default exclusion reasons.
- Workspace audit events for AI suggestions, human decision actions, PDF
  uploads/deletes, and reference imports/deduplication.
- Tests for AI suggestions, human decisions, full-text exclusion reasons,
  accept/override behavior, queue persistence, restart/reopen behavior,
  workspace summary/filter metadata, origin counts, reference-list pagination,
  recent-workspace privacy, and privacy scrubbing.
- Co-author citation metadata for Farahnaz Yazdanpanah Faragheh, including
  ORCID, affiliation, and LinkedIn profile references in public project
  documentation.

### Changed

- Review status transitions are centralized in `workspace_store.py`.
- Workspace exports use human final decisions as final eligibility decisions.
  AI-only suggestions are explicitly labeled as not final
  (`final_decision_source = ai_suggestion_not_final`).
- Duplicate and inactive records are retained in audit/export rows but
  excluded from active screening counts.
- Full-text human exclude decisions require an exclusion reason.
- Workspace summaries now include review item and decision counts.
- Export manifests and APIs return workspace-relative paths only.

### Security

- Decision and audit metadata continue to scrub API keys, raw secrets, full
  prompts, raw provider request bodies, and full paper text. AI metadata
  persisted in workspace decisions is limited to sanitized fields such as
  provider, model, prompt hash, text hash, cache key, confidence, and
  rationale.
- Workspace export metadata avoids absolute workspace paths in API responses.
- Export downloads validate that the requested file remains inside the
  selected workspace export folder.
- Workspace paths reject traversal and unsafe roots (filesystem root, drive
  root, home directory), and registered PDFs confined to workspace `pdfs/`.

### Known Limitations

- Workspace review queue is a single-reviewer foundation only. There is **no
  dual reviewer workflow** and **no kappa** calculation.
- There is **no conflict UI** or adjudication workflow for disagreeing
  reviewers.
- There is **no extraction workflow persistence or extraction review** in the
  workspace database yet; structured extraction remains run-based.
- There is **no OCR** step for scanned PDFs.
- There is **no risk-of-bias or quality appraisal** tooling.
- There is **no SaaS, login, or multi-user behavior**; the Web App remains
  local-first on the researcher's own computer.
- There is **no automatic PRISMA compliance**. PRISMA-ready counts are derived
  from workspace data and must be checked against the protocol, search logs,
  and final human decisions before reporting.
- **Full-text report availability** remains `not_available` unless tracked
  separately; full-text reports are not yet represented as a distinct
  availability count in the workspace schema.
- Legacy run-based exports remain unchanged; use Workspace Exports for
  workspace-decision-aware reporting data.

## [3.5.0] - 2026-07-08

### Added

- Local Workspace folder model for project-based review state.
- Standard-library SQLite workspace database via `workspace_store.py`.
- Workspace create/open/close/recent workflow in the local WebApp.
- Workspace structure:
  - `workspace.sqlite3`
  - `workspace.json`
  - `imports/`
  - `pdfs/`
  - `exports/`
  - `cache/`
  - `audit/`
- Persistent reference import metadata, parsed records, and record-source provenance in workspace mode.
- Persistent PDF metadata in workspace mode, including original filename, display name, relative path, size, and SHA-256 where practical.
- Default local reviewer and default exclusion reasons.
- Workspace-level audit events.
- Compact workspace bar in the WebApp.
- Tests for workspace creation/opening, migrations, path safety, reference persistence, PDF persistence, duplicate PDF basenames, recent workspace sanitization, close/open persistence, and legacy no-workspace compatibility.

### Changed

- WebApp workspace mode stores imported references under workspace `imports/` and uploaded PDFs under workspace `pdfs/`.
- Legacy run-based WebApp behavior remains available when no workspace is open.
- Desktop GUI behavior remains unchanged.

### Security

- Workspace paths reject traversal and unsafe roots.
- Workspace API responses avoid exposing arbitrary filesystem paths.
- Workspace DB does not store API keys, full prompts, or full paper text.

## [3.4.0-rc.1] - 2026-07-05

### Added

- Provider profile catalog and OpenAI-compatible profiles.
- Explicit privacy labels for providers.
- Audit JSONL ledger for non-secret run metadata.
- Configuration-aware cache keys.
- Provider-level rate limiter.
- Recursive PDF discovery and subfolder behavior.
- Benchmark suite and benchmark report.
- GitHub Pages SEO, robots, sitemap, and llms metadata where present in the repository.

### Changed

- Local-first privacy hardening.
- API key handling: no plaintext settings persistence.
- WebApp debug, CORS, upload, and path safety.
- JSON-only runtime cache.
- Documentation wording: AI-assisted, PRISMA-aligned, human verification required.

### Fixed

- WebApp PDF screening counters, results, and report visibility issue.
- Same-basename PDF handling in subfolders.
- Rate limiter timing issue.
- Legacy pytest warnings where applicable.

### Security

- Removed automatic pickle loading at runtime.
- Hardened WebApp upload and path traversal behavior.
- API keys are no longer saved in plaintext settings files.

### Benchmarks

- Added a synthetic mocked benchmark suite covering reference deduplication, cache-key generation, mocked LLM pipeline behavior, PDF discovery, and rate limiter behavior.
- Benchmarks use deterministic synthetic data and fake providers only.
- Limitations: no real LLM latency, cost, quality, provider availability, or token usage is measured.

### Known Limitations

- Not a full collaborative review management platform.
- Workspace mode is single-user and local-first; it is not a collaborative review management platform.
- No dual-reviewer workflow yet.
- PRISMA support is partial.
- No formal real-world LLM validation benchmark yet.
- No page-level quote tracing yet.
