# SLR Assistant Benchmark Report

## Environment

- Date: 2026-07-05T20:39:19
- Software version: 3.4.0-rc.1
- Python version: 3.11.9
- OS: Windows 10 (Windows-10-10.0.26200-SP0)
- Hardware: 12 logical CPUs; Intel64 Family 6 Model 165 Stepping 2, GenuineIntel; 15.8 GiB RAM
- Mode: quick
- Synthetic seed: 20260705
- External API calls: none; mocked/fake providers only

## Methodology

Benchmarks use deterministic synthetic records, fabricated PDF-like text, and local stub PDF files. LLM screening uses a deterministic in-process fake manager that returns JSON and never contacts hosted providers. PDF discovery benchmarks file discovery and display-name behavior only; they do not extract text from PDFs. Timings are wall-clock measurements from a single local run and include Python and filesystem overhead.

Mocked LLM benchmarks do not represent real provider latency, throughput, availability, rate limits, token usage, or cost.

Mocked LLM cache-hit runs may not be faster than cache-miss runs in these tables because the fake provider returns immediately and the cache-hit path still performs local file reads, metadata validation, and audit ledger writes. With real cloud LLM providers, cache hits avoid external network latency, provider queueing, token billing, and request-rate consumption.

## Reference Ingestion And Deduplication

| records | generation_wall_ms | dedup_wall_ms | dedup_records_per_sec | memory_peak_kib | duplicates_total | doi_duplicates | fuzzy_title_duplicates | total_after | expected_doi_duplicates | expected_fuzzy_duplicates | fuzzy_available |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 4.03 | 1.331 | 7511.45 | 13.35 | 2 | 1 | 1 | 8 | 1 | 1 | True |
| 100 | 39.992 | 95.857 | 1043.22 | 132.93 | 20 | 10 | 10 | 80 | 10 | 10 | True |
| 1000 | 363.337 | 6576.782 | 152.05 | 1267.7 | 200 | 100 | 100 | 800 | 100 | 100 | True |

Fuzzy title matching was available for this run.

## Cache-Key Generation

| kind | iterations | wall_ms | avg_us_per_key | distinct_keys | memory_peak_kib |
| --- | --- | --- | --- | --- | --- |
| screening | 1200 | 739.634 | 616.362 | 55 | 155.62 |
| extraction | 1200 | 837.833 | 698.195 | 44 | 153.9 |

## Mocked LLM Title/Abstract Screening

| records | cache_miss_wall_ms | cache_hit_wall_ms | miss_records_per_sec | hit_records_per_sec | cache_hit_rate_hit_run_pct | fake_llm_calls_miss | fake_llm_calls_hit_increment | audit_events_created | memory_peak_kib |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 57.058 | 131.429 | 175.26 | 76.09 | 100.0 | 10 | 0 | 20 | not measured |
| 100 | 400.036 | 1297.475 | 249.98 | 77.07 | 100.0 | 100 | 0 | 200 | not measured |
| 1000 | 4959.562 | 16175.459 | 201.63 | 61.82 | 100.0 | 1000 | 0 | 2000 | not measured |

## Mocked PDF-Like Text Screening

| text_size | chars_per_text | documents | cache_miss_wall_ms | cache_hit_wall_ms | miss_docs_per_sec | hit_docs_per_sec | cache_hit_rate_hit_run_pct | fake_llm_calls_miss | fake_llm_calls_hit_increment | audit_events_created | memory_peak_kib |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| small | 2000 | 3 | 22.046 | 88.167 | 136.08 | 34.03 | 100.0 | 3 | 0 | 6 | not measured |
| medium | 20000 | 3 | 30.415 | 43.315 | 98.63 | 69.26 | 100.0 | 3 | 0 | 6 | not measured |
| large | 80000 | 3 | 59.843 | 82.152 | 50.13 | 36.52 | 100.0 | 3 | 0 | 6 | not measured |

## PDF Discovery

| scenario | files_found | display_names | collision_names_distinct | wall_ms | memory_peak_kib | method |
| --- | --- | --- | --- | --- | --- | --- |
| direct_folder | 2 | a.pdf, b.pdf | n/a | 4.817 | 6.76 | synthetic stub PDFs; discovery only |
| recursive_subfolders | 4 | alpha/paper.pdf, beta/paper.pdf, nested/zeta.pdf, root.pdf | True | 174.178 | 14.07 | synthetic stub PDFs; discovery only |

## Rate Limiter Behavior

| max_concurrency_configured | max_concurrency_observed | same_profile_shares_limiter | different_profile_isolated | retry_calls | retry_count_recorded | retry_error_category | cache_hits_skip_limiter | wall_ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2 | 2 | True | True | 2 | 1 | rate_limit | True | 53.624 |

## Summary

- Median title/abstract cache-miss wall time across record-count scenarios: 400.036 ms.
- Benchmark duration: 33.324 seconds.
- Cache-hit runs should show 100% hit rate and zero fake LLM calls after the miss run.
- Mocked cache-hit wall time is an implementation-overhead check, not a real-provider speedup estimate.
- Audit ledger creation is represented by audit_events_created in the mocked LLM tables.

## Limitations

- Synthetic references and fabricated text do not represent a real systematic review corpus.
- Fake LLM JSON responses do not measure real model quality, latency, tokenization, rate-limit behavior, or cost.
- Stub PDFs benchmark discovery and collision-safe naming only, not real PDF parsing quality.
- Single-run wall-clock measurements can vary by machine load, filesystem, and Python environment.
- The optional 5000-record deduplication scenario is disabled unless `--include-large` is passed.

## TODO

- Add a future real-world benchmark using an open-access corpus with redistribution-compatible metadata and PDFs.
- Repeat each scenario across multiple runs and report confidence intervals.
- Add provider-latency and cost benchmarks only behind explicit opt-in flags and documented API-key handling.

## README Or Paper Suitability

These results are suitable for README-level smoke/performance documentation when clearly labeled as local synthetic mocked benchmarks. They are not suitable as paper evidence for real-world LLM latency, screening accuracy, provider cost, or PDF extraction quality without an open-access corpus and a repeated-run methodology.
