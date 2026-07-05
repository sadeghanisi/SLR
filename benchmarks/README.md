# SLR Assistant Benchmarks

This directory contains lightweight, reproducible benchmarks for SLR Assistant.
They are designed for local validation and regression checks, not for measuring
real hosted LLM latency or cost.

## Guarantees

- Uses deterministic synthetic records only.
- Uses mocked/fake LLM providers only.
- Requires no real API keys.
- Does not call external LLM APIs.
- Does not use copyrighted PDFs or private data.
- Uses local stub PDF files for discovery benchmarks only.

## Run

Quick profile:

```powershell
python benchmarks/run_benchmarks.py --quick
```

Standard profile:

```powershell
python benchmarks/run_benchmarks.py
```

Optional large reference scenario:

```powershell
python benchmarks/run_benchmarks.py --include-large
```

## Outputs

- `benchmarks/BENCHMARK_REPORT.md` is the latest markdown report.
- `benchmarks/results/` contains gitignored JSON results and working files.

## Scenarios

- Reference generation and deduplication for 10, 100, and 1000 synthetic records.
- Optional 5000-record scenario with `--include-large`.
- Screening and extraction cache-key generation overhead.
- Mocked title/abstract screening with cache miss and cache hit runs.
- Mocked PDF-like text screening for small, medium, and large fabricated texts.
- PDF discovery for direct folders, recursive subfolders, and duplicate basenames.
- Provider/profile rate limiter behavior, retry metadata, and cache-hit limiter skip.

## Interpretation

The mocked LLM benchmarks validate SLR Assistant pipeline overhead, cache behavior,
audit ledger creation, and rate limiter logic. They do not represent real provider
latency, real token usage, real model quality, availability, or cost.
