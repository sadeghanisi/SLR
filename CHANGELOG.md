# Changelog

All notable changes to SLR Assistant are documented in this file.

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
- No Project/Workspace yet.
- No dual-reviewer workflow yet.
- PRISMA support is partial.
- No formal real-world LLM validation benchmark yet.
- No page-level quote tracing yet.
