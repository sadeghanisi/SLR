# SLR Assistant Roadmap

This roadmap translates the current product and academic audit into a staged plan. It is intentionally conservative: SLR Assistant should remain clear about what it does today, what is planned, and what it is not designed to guarantee.

## 1. Current Positioning

SLR Assistant is a local-first, AI-assisted workflow tool for individual researchers conducting systematic and scoping review workflows on their own computer.

It is not yet a full collaborative systematic review management platform. The current architecture is best understood as a privacy-conscious desktop/local WebApp assistant for repetitive review tasks, with human researchers responsible for final methodological decisions, verification, and reporting.

## 2. Current Strengths

- Reference ingestion from common export formats.
- Deduplication using DOI and fuzzy title matching.
- Title/abstract screening support.
- Full-text PDF screening support.
- Structured extraction into review-ready tables.
- Multiple provider profiles for cloud, router, custom, and local endpoints.
- Local model support through Ollama and compatible local endpoints.
- JSON cache to avoid repeated LLM calls for the same configuration.
- Audit ledger for non-secret run metadata and reproducibility evidence.
- WebApp Workspace mode for local project folders, persistent references, persistent PDF metadata, AI suggestions, human decisions, and workspace audit events.
- Workspace exports with decision CSV/XLSX files, PRISMA-ready counts for checking, and a conservative methods disclosure draft.
- Desktop GUI and local WebApp interfaces.
- Human verification is required for screening decisions, extracted data, PRISMA reporting, and final research use.

## 3. Known Product Gaps

- WebApp is currently single-user and local-only.
- Workspace mode has a persistent single-reviewer queue, but no dual-reviewer workflow, conflict UI, or adjudication workflow yet.
- Structured extraction is not yet persisted as a workspace review workflow.
- Outputs are primarily files rather than a full review dashboard.
- Limited cost controls beyond token reporting and provider guidance.
- Possible Desktop/WebApp drift as both interfaces evolve.
- Limited integrations with external research tools and bibliographic systems.

## 4. Known Methodology Gaps

- PRISMA support is currently partial and count-oriented. Workspace exports provide PRISMA-ready counts for checking, not automatic PRISMA compliance.
- No structured protocol, search strategy, or provenance system yet.
- No dual independent screening workflow yet.
- No conflict resolution or kappa workflow yet.
- No risk-of-bias or quality appraisal module yet.
- No formal LLM validation benchmark yet.
- No page-level quote traceability yet.
- No OCR workflow for scanned or image-only PDFs yet.

## 5. Near-Term Roadmap: v3.4.x

- Completed in v3.4.x beta: provider profile catalog and OpenAI-compatible provider profiles.
- Completed in v3.4.x beta: cache correctness improvements and audit JSONL ledger.
- Completed in v3.4.x beta: WebApp PDF result/report visibility fix.
- Completed in v3.4.x beta: provider-level rate limiting so parallel jobs respect provider/profile constraints.
- Completed in v3.4.x beta: benchmark suite and mocked benchmark report covering synthetic datasets, prompts, metrics, cache behavior, rate limiting, PDF discovery, and limitations.
- Completed in v3.4.x beta: PDF subfolder behavior resolved with supported recursive PDF discovery and collision-safe relative display names.
- Completed in v3.5.1-beta: Workspace Mode UX/navigation redesign, recent workspace cards, default workspace location, persistent references/PDF metadata, review queue, AI suggestions as non-final, human decisions as final, workspace dedup persistence, reference-list search/pagination, workspace-scoped exports/cache/audit, Workspace Exports, PRISMA-ready reporting data, and Methods Disclosure.
- Remaining near-term release task: tag v3.5.1-beta after final metadata review.
- Remaining near-term archive task: create a Zenodo archive after the release/tag is ready.
- Remaining near-term publication task: finalize paper draft.
- Optional near-term validation task: add a real-world benchmark using an open-access corpus with redistribution-compatible inputs.

## 6. Product Roadmap: v3.5

- Continue hardening Workspace mode after the v3.5.1-beta foundation.
- Add richer workspace protocol metadata, including inclusion/exclusion criteria, extraction fields, and methods notes.
- Improve workspace dashboard views for review progress, human final decisions, and export readiness.
- Extend workspace exports as needed for PRISMA 2020 flow diagram preparation while keeping counts auditable and human-checked.

## 7. Methodology Roadmap: v3.6

- Support dual reviewer import/export comparison for independent screening runs.
- Add a conflict resolution workflow for disagreements between reviewers or between AI and human decisions.
- Calculate Cohen's kappa and related inter-rater agreement summaries.
- Add pilot calibration using known include/exclude papers before large runs.
- Produce a confusion matrix for calibration sets.
- Warn about false exclusion risk when calibration results suggest the model or criteria may be unsafe for automated first-pass exclusion.

## 8. Advanced Roadmap: v3.7+

- Add OCR support for scanned or image-only PDFs.
- Add page-level quote tracing for extracted evidence.
- Add integrations with Zotero, Rayyan, Covidence, OpenAlex, and PubMed where feasible.
- Support custom quality appraisal templates.
- Offer optional RoB-, CASP-, JBI-, and GRADE-style appraisal templates while avoiding claims of automatic methodological compliance.

## 9. Non-Goals

- Not a public multi-user SaaS in the current architecture.
- Not a replacement for human reviewers.
- Not a guarantee of PRISMA compliance.
- Not a clinical or policy decision system.

## 10. Contribution Opportunities

Contributors can help most in areas that improve transparency, validation, and research workflow fit:

- PRISMA exports and reporting helpers.
- Benchmark datasets, benchmark scripts, and reproducible benchmark reports.
- UI testing across the desktop GUI and local WebApp.
- Integrations with bibliographic and review-management tools.
- Documentation, tutorials, and methods-disclosure examples.
- Sample datasets suitable for testing screening and extraction behavior.
- Quality appraisal templates for different review types and disciplines.
