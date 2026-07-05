# SLR Assistant v3.4.0-rc.1 Release Notes

## What Changed

- Added provider profiles, including OpenAI-compatible provider profiles.
- Added provider privacy labels so users can distinguish local, direct cloud, router, and custom endpoint behavior.
- Hardened local-first privacy behavior and API key handling.
- Added configuration-aware JSON cache keys and a JSONL audit ledger.
- Added provider-level rate limiting.
- Fixed WebApp PDF screening counters, results, and report visibility.
- Fixed recursive PDF discovery and same-basename PDF handling in subfolders.
- Added a reproducible synthetic mocked benchmark suite and benchmark report.
- Updated release metadata and documentation for conservative AI-assisted, PRISMA-aligned wording.

## Why It Matters

This release candidate focuses on reproducibility, privacy, and operational clarity. It improves how runs are cached and audited, makes provider behavior easier to reason about, and fixes PDF workflow issues that could obscure results in the local WebApp.

## Upgrade Notes

- API keys are not saved to plaintext settings files. Re-enter keys when needed or use supported environment/credential mechanisms.
- Runtime cache loading is JSON-only. Legacy pickle cache files are not loaded automatically.
- Review cache and audit outputs before using generated results in research outputs.
- The WebApp remains local-only and should stay bound to `127.0.0.1`.

## Known Limitations

- SLR Assistant is not a full collaborative review management platform.
- There is no Project/Workspace model yet.
- Dual-reviewer workflows and conflict adjudication are not implemented yet.
- PRISMA support is partial and does not guarantee PRISMA compliance.
- There is no formal real-world LLM validation benchmark yet.
- Page-level quote tracing is not implemented yet.

## Validation

- `python -m py_compile llm_interface.py slr_gui.py housing_enhanced.py WebApp/app.py benchmarks/run_benchmarks.py` -> passed.
- `python -m pytest -q` -> 82 passed.
- `python benchmarks/run_benchmarks.py --quick` -> passed in 33.324 seconds.
- Tests and benchmarks used mocked/fake providers only and made no external LLM API calls.

## Benchmark Scope

The benchmark suite uses deterministic synthetic data and fake provider responses. It is suitable for smoke/performance documentation of engineering behavior, but it does not measure real-world LLM accuracy, latency, cost, token usage, or provider availability.
