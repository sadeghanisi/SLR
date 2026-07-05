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
- Desktop GUI and local WebApp interfaces.
- Human verification is required for screening decisions, extracted data, PRISMA reporting, and final research use.

## 3. Known Product Gaps

- No first-class Project/Workspace concept yet.
- WebApp is currently single-user and local-only.
- Limited persistent manual review workflow for human decisions, overrides, and adjudication.
- Outputs are primarily files rather than a full review dashboard.
- Limited cost controls beyond token reporting and provider guidance.
- Possible Desktop/WebApp drift as both interfaces evolve.
- Limited integrations with external research tools and bibliographic systems.

## 4. Known Methodology Gaps

- PRISMA support is currently partial and count-oriented.
- No structured protocol, search strategy, or provenance system yet.
- No dual independent screening workflow yet.
- No conflict resolution or kappa workflow yet.
- No risk-of-bias or quality appraisal module yet.
- No formal LLM validation benchmark yet.
- No page-level quote traceability yet.

## 5. Near-Term Roadmap: v3.4.x

- Completed in v3.4.x beta: provider profile catalog and OpenAI-compatible provider profiles.
- Completed in v3.4.x beta: cache correctness improvements and audit JSONL ledger.
- Completed in v3.4.x beta: WebApp PDF result/report visibility fix.
- Completed in v3.4.x beta: provider-level rate limiting so parallel jobs respect provider/profile constraints.
- Completed in v3.4.x beta: benchmark suite and mocked benchmark report covering synthetic datasets, prompts, metrics, cache behavior, rate limiting, PDF discovery, and limitations.
- Completed in v3.4.x beta: PDF subfolder behavior resolved with supported recursive PDF discovery and collision-safe relative display names.
- Remaining near-term release task: publish v3.4.0-rc.1 release artifacts after final review.
- Remaining near-term archive task: create a Zenodo archive after the release/tag is ready.
- Remaining near-term publication task: finalize paper draft.
- Optional near-term validation task: add a real-world benchmark using an open-access corpus with redistribution-compatible inputs.

## 6. Product Roadmap: v3.5

- Introduce a Project Workspace model for review-specific state.
- Define a persistent project folder structure for protocol, settings, inputs, outputs, cache metadata, audit logs, and review decisions.
- Add open, save, and recent-project flows.
- Store project-level protocol metadata, including review title, question, inclusion/exclusion criteria, extraction fields, and methods notes.
- Add a manual review queue for flagged items, included/excluded samples, and failed records.
- Persist human overrides and exclusion reasons with timestamps and reviewer metadata.
- Export PRISMA 2020 data fields needed for flow diagrams and reporting.

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
