#!/usr/bin/env python
"""Lightweight local benchmarks for SLR Assistant.

The suite is intentionally synthetic and local-only:
- no real API keys
- no external LLM provider calls
- no copyrighted PDFs or private data
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
import statistics
import sys
import threading
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import llm_interface
from housing_enhanced import SystematicReviewAutomation, __version__
from ingestion import deduplicate
from llm_interface import (
    LLMManager,
    ProviderRateLimiter,
    get_provider_rate_limiter,
    reset_rate_limiters_for_tests,
)


RESULTS_DIR = Path(__file__).resolve().parent / "results"
REPORT_PATH = Path(__file__).resolve().parent / "BENCHMARK_REPORT.md"
SYNTHETIC_SEED = 20260705


class DeterministicFakeLLMManager:
    """Deterministic in-process LLM stand-in used by benchmark automation."""

    def __init__(self, provider: str, model: str):
        self.provider = provider
        self.model = model
        self.call_count = 0
        self.external_api_calls = 0
        self.fail_on_call = False
        self.last_call_metadata: Dict[str, Any] = {}

    def chat_completion_with_tokens(self, messages, **kwargs) -> Tuple[str, int]:
        if self.fail_on_call:
            raise AssertionError("cache hit should not enter the fake LLM path")

        self.call_count += 1
        prompt = "\n".join(str(message.get("content", "")) for message in messages)
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        decisions = ["Likely Include", "Likely Exclude", "Flag for Review"]
        decision = decisions[int(digest[:2], 16) % len(decisions)]
        token_estimate = max(1, len(prompt.split())) + 24
        self.last_call_metadata = {
            "provider": self.provider,
            "provider_profile": "benchmark_fake",
            "model": self.model,
            "rate_limit_key": "benchmark_fake|local",
            "rate_limit_wait_seconds": 0.0,
            "backoff_wait_seconds": 0.0,
            "retry_count": 0,
            "attempt_count": 1,
            "final_status": "success",
            "error_category": None,
        }
        return (
            json.dumps(
                {
                    "decision": decision,
                    "reasoning": f"deterministic fake decision {digest[:12]}",
                    "notes": "mocked provider; no external API call",
                },
                sort_keys=True,
            ),
            token_estimate,
        )

    def chat_completion_structured(self, messages, response_model, **kwargs):
        raise ImportError("structured fake is not used by the benchmark")

    def get_last_call_metadata(self) -> Dict[str, Any]:
        return dict(self.last_call_metadata)


class BenchmarkAutomation(SystematicReviewAutomation):
    """SystematicReviewAutomation wired to the deterministic fake LLM."""

    def _init_llm(self):
        return DeterministicFakeLLMManager(self.llm_provider, self.llm_model)


class LLMManagerBackedAutomation(SystematicReviewAutomation):
    """Automation variant used only to verify real limiter skip on cache hits."""

    def _init_llm(self):
        return LLMManager(
            provider_name="OpenAI",
            api_key="benchmark-fake-key",
            model=self.llm_model,
            rate_limit_config={"min_interval": 0, "max_concurrency": 10},
        )


def generate_synthetic_records(count: int) -> List[Dict[str, str]]:
    """Generate deterministic, non-sensitive reference-like records."""

    records: List[Dict[str, str]] = []
    for index in range(count):
        block = index // 10
        position = index % 10
        base_title = f"Community housing outcome {_unique_synthetic_title(block)}"

        if position == 0:
            title = base_title
            doi = f"10.5555/slr.{block:04d}"
        elif position == 1:
            title = f"Alternate database record for housing study {block:04d}"
            doi = f"10.5555/slr.{block:04d}"
        elif position == 2:
            title = f"{base_title}!"
            doi = ""
        else:
            title = _unique_synthetic_title(index)
            doi = f"10.5555/slr.{block:04d}.{position}"

        year = str(2000 + (index % 25))
        records.append(
            {
                "id": f"REC-{index:05d}",
                "title": title,
                "doi": doi,
                "year": year,
                "authors": f"Author {block % 17}; Collaborator {position}",
                "abstract": (
                    f"Synthetic abstract {index}. This record contains public, "
                    f"fabricated benchmark text about local services, housing, "
                    f"screening criteria, outcomes, and reproducibility."
                ),
            }
        )
    return records


def _unique_synthetic_title(index: int) -> str:
    digest = hashlib.sha256(f"{SYNTHETIC_SEED}:{index}".encode("utf-8")).hexdigest()
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    tokens = []
    for offset in range(0, 48, 8):
        value = int(digest[offset:offset + 8], 16)
        letters = []
        for _ in range(7):
            value, remainder = divmod(value, len(alphabet))
            letters.append(alphabet[remainder])
        tokens.append("".join(letters))
    return " ".join(tokens)


def expected_duplicate_counts(count: int) -> Dict[str, int]:
    full_blocks, remainder = divmod(count, 10)
    doi_duplicates = full_blocks + (1 if remainder > 1 else 0)
    fuzzy_duplicates = full_blocks + (1 if remainder > 2 else 0)
    return {
        "expected_doi_duplicates": doi_duplicates,
        "expected_fuzzy_duplicates": fuzzy_duplicates,
        "expected_total_after": count - doi_duplicates - fuzzy_duplicates,
    }


def synthetic_pdf_like_text(label: str, target_chars: int) -> str:
    sections = [
        f"Title: Synthetic PDF-like benchmark document {label}.",
        "Abstract: This fabricated text is used only for local benchmarking.",
        "Methods: Records describe deterministic procedures and no private data.",
        "Results: Outcomes are repeated to reach the requested character count.",
        "Conclusion: Mocked screening does not represent provider latency or cost.",
    ]
    unit = "\n\n".join(sections) + "\n\n"
    repeats = (target_chars // len(unit)) + 1
    return (unit * repeats)[:target_chars]


def make_automation(
    work_dir: Path,
    name: str,
    *,
    cache_enabled: bool = True,
    include_subfolders: bool = False,
    llm_provider: str = "Benchmark Fake",
    llm_model: str = "fake-screen-v1",
    screening_prompt: str = "screen this synthetic record: {text}",
    extraction_fields: Optional[List[str]] = None,
    advanced_config: Optional[Dict[str, Any]] = None,
    **llm_kwargs,
) -> BenchmarkAutomation:
    pdf_dir = work_dir / name / "pdfs"
    output_dir = work_dir / name / "out"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "max_text_chars": 100000,
        "max_retries": 1,
        "retry_delay": 0,
        "retry_jitter": 0,
        "rate_limit_min_interval": 0,
        "rate_limit_max_concurrency": 10,
        "include_subfolders": include_subfolders,
    }
    if advanced_config:
        config.update(advanced_config)
    return BenchmarkAutomation(
        api_key="benchmark-fake-key",
        pdf_folder=str(pdf_dir),
        output_folder=str(output_dir),
        cache_enabled=cache_enabled,
        parallel_processing=False,
        rate_limit_delay=0,
        screening_prompt=screening_prompt,
        extraction_fields=extraction_fields or ["title", "year", "main_findings"],
        llm_provider=llm_provider,
        llm_model=llm_model,
        advanced_config=config,
        include_subfolders=include_subfolders,
        **llm_kwargs,
    )


def measured(operation: Callable[[], Any]) -> Tuple[Any, float, int]:
    tracemalloc.start()
    start = time.perf_counter()
    result = operation()
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, elapsed, peak


def timed(operation: Callable[[], Any]) -> Tuple[Any, float]:
    start = time.perf_counter()
    result = operation()
    return result, time.perf_counter() - start


def rows_per_second(count: int, seconds: float) -> float:
    if seconds <= 0:
        return 0.0
    return count / seconds


def benchmark_reference_dedup(sizes: Iterable[int]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        import thefuzz  # noqa: F401

        fuzzy_available = True
    except ImportError:
        fuzzy_available = False

    deduplicate(generate_synthetic_records(3))
    for size in sizes:
        generated, generation_seconds, generation_peak = measured(
            lambda size=size: generate_synthetic_records(size)
        )
        (deduped, stats), dedup_seconds, dedup_peak = measured(
            lambda generated=generated: deduplicate(copy.deepcopy(generated))
        )
        expected = expected_duplicate_counts(size)
        rows.append(
            {
                "records": size,
                "generation_wall_ms": round(generation_seconds * 1000, 3),
                "dedup_wall_ms": round(dedup_seconds * 1000, 3),
                "dedup_records_per_sec": round(rows_per_second(size, dedup_seconds), 2),
                "memory_peak_kib": round((generation_peak + dedup_peak) / 1024, 2),
                "duplicates_total": stats.removed_doi + stats.removed_fuzzy,
                "doi_duplicates": stats.removed_doi,
                "fuzzy_title_duplicates": stats.removed_fuzzy,
                "total_after": len(deduped),
                "expected_doi_duplicates": expected["expected_doi_duplicates"],
                "expected_fuzzy_duplicates": expected["expected_fuzzy_duplicates"],
                "fuzzy_available": fuzzy_available,
            }
        )
    return rows


def benchmark_cache_keys(work_dir: Path, *, quick: bool) -> List[Dict[str, Any]]:
    iterations = 1200 if quick else 8000
    automations = [
        make_automation(
            work_dir,
            "cache_keys_a",
            llm_provider="Benchmark Fake",
            llm_model="fake-screen-v1",
            screening_prompt="screen variant a: {text}",
        ),
        make_automation(
            work_dir,
            "cache_keys_b",
            llm_provider="Benchmark Fake Router",
            llm_model="fake-screen-v1",
            screening_prompt="screen variant a: {text}",
            base_url="https://benchmark.invalid/v1",
        ),
        make_automation(
            work_dir,
            "cache_keys_c",
            llm_provider="Benchmark Fake",
            llm_model="fake-screen-v2",
            screening_prompt="screen variant a: {text}",
        ),
        make_automation(
            work_dir,
            "cache_keys_d",
            llm_provider="Benchmark Fake",
            llm_model="fake-screen-v1",
            screening_prompt="screen variant b: {text}",
        ),
        make_automation(
            work_dir,
            "cache_keys_e",
            llm_provider="Benchmark Fake",
            llm_model="fake-screen-v1",
            advanced_config={"max_text_chars": 25000},
        ),
    ]
    texts = [synthetic_pdf_like_text(f"cache-{index}", 800 + index * 37) for index in range(11)]
    rows: List[Dict[str, Any]] = []

    def run_kind(kind: str) -> List[str]:
        keys: List[str] = []
        for index in range(iterations):
            auto = automations[index % len(automations)]
            text = texts[index % len(texts)]
            if kind == "screening":
                context = auto._cache_key_context(
                    kind="screening",
                    text=text,
                    prompt={"screening_prompt": auto.screening_prompt, "stage": "Title/Abstract"},
                    stage="Title/Abstract",
                )
            else:
                context = auto._cache_key_context(
                    kind="extraction",
                    text=text,
                    prompt=auto._extraction_prompt_fingerprint_source(),
                )
            keys.append(context["cache_key"])
        return keys

    for kind in ("screening", "extraction"):
        keys, seconds, peak = measured(lambda kind=kind: run_kind(kind))
        rows.append(
            {
                "kind": kind,
                "iterations": iterations,
                "wall_ms": round(seconds * 1000, 3),
                "avg_us_per_key": round((seconds / iterations) * 1_000_000, 3),
                "distinct_keys": len(set(keys)),
                "memory_peak_kib": round(peak / 1024, 2),
            }
        )
    return rows


def audit_counts(path: Path, start_line: int = 0) -> Dict[str, int]:
    if not path.exists():
        return {"events": 0, "hits": 0, "misses": 0}
    lines = path.read_text(encoding="utf-8").splitlines()[start_line:]
    hits = 0
    misses = 0
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("cache_hit"):
            hits += 1
        else:
            misses += 1
    return {"events": len(lines), "hits": hits, "misses": misses}


def line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def benchmark_title_abstract_pipeline(work_dir: Path, sizes: Iterable[int]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for size in sizes:
        auto = make_automation(work_dir, f"llm_title_abstract_{size}")
        records = generate_synthetic_records(size)

        def run_batch() -> None:
            for record in records:
                text = f"{record['title']}\n\n{record['abstract']}"
                auto.screen_article(text, f"{record['id']}.txt", stage="Title/Abstract")

        before = line_count(auto.audit_ledger)
        _, miss_seconds = timed(run_batch)
        after_miss = line_count(auto.audit_ledger)
        calls_after_miss = auto.llm_manager.call_count
        _, hit_seconds = timed(run_batch)
        after_hit = line_count(auto.audit_ledger)
        hit_audit = audit_counts(auto.audit_ledger, start_line=after_miss)

        rows.append(
            {
                "records": size,
                "cache_miss_wall_ms": round(miss_seconds * 1000, 3),
                "cache_hit_wall_ms": round(hit_seconds * 1000, 3),
                "miss_records_per_sec": round(rows_per_second(size, miss_seconds), 2),
                "hit_records_per_sec": round(rows_per_second(size, hit_seconds), 2),
                "cache_hit_rate_hit_run_pct": round((hit_audit["hits"] / max(1, size)) * 100, 2),
                "fake_llm_calls_miss": calls_after_miss,
                "fake_llm_calls_hit_increment": auto.llm_manager.call_count - calls_after_miss,
                "audit_events_created": after_hit - before,
                "memory_peak_kib": "not measured",
            }
        )
    return rows


def benchmark_pdf_text_pipeline(work_dir: Path, *, quick: bool) -> List[Dict[str, Any]]:
    repeats = 3 if quick else 10
    text_sizes = [
        ("small", 2_000),
        ("medium", 20_000),
        ("large", 80_000),
    ]
    rows: List[Dict[str, Any]] = []
    for label, chars in text_sizes:
        auto = make_automation(work_dir, f"llm_pdf_text_{label}")
        texts = [synthetic_pdf_like_text(f"{label}-{index}", chars) for index in range(repeats)]

        def run_batch() -> None:
            for index, text in enumerate(texts):
                auto.screen_article(text, f"{label}_{index}.pdf", stage="Full-text")

        before = line_count(auto.audit_ledger)
        _, miss_seconds = timed(run_batch)
        after_miss = line_count(auto.audit_ledger)
        calls_after_miss = auto.llm_manager.call_count
        _, hit_seconds = timed(run_batch)
        after_hit = line_count(auto.audit_ledger)
        hit_audit = audit_counts(auto.audit_ledger, start_line=after_miss)
        rows.append(
            {
                "text_size": label,
                "chars_per_text": chars,
                "documents": repeats,
                "cache_miss_wall_ms": round(miss_seconds * 1000, 3),
                "cache_hit_wall_ms": round(hit_seconds * 1000, 3),
                "miss_docs_per_sec": round(rows_per_second(repeats, miss_seconds), 2),
                "hit_docs_per_sec": round(rows_per_second(repeats, hit_seconds), 2),
                "cache_hit_rate_hit_run_pct": round((hit_audit["hits"] / max(1, repeats)) * 100, 2),
                "fake_llm_calls_miss": calls_after_miss,
                "fake_llm_calls_hit_increment": auto.llm_manager.call_count - calls_after_miss,
                "audit_events_created": after_hit - before,
                "memory_peak_kib": "not measured",
            }
        )
    return rows


def write_stub_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n% synthetic benchmark stub\n")


def benchmark_pdf_discovery(work_dir: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    direct = make_automation(work_dir, "pdf_direct", cache_enabled=False, include_subfolders=False)
    write_stub_pdf(direct.pdf_folder / "b.pdf")
    write_stub_pdf(direct.pdf_folder / "a.pdf")
    write_stub_pdf(direct.pdf_folder / "nested" / "ignored.pdf")
    found, seconds, peak = measured(direct._discover_pdf_files)
    rows.append(
        {
            "scenario": "direct_folder",
            "files_found": len(found),
            "display_names": ", ".join(direct._pdf_display_name(path) for path in found),
            "collision_names_distinct": "n/a",
            "wall_ms": round(seconds * 1000, 3),
            "memory_peak_kib": round(peak / 1024, 2),
            "method": "synthetic stub PDFs; discovery only",
        }
    )

    recursive = make_automation(work_dir, "pdf_recursive", cache_enabled=False, include_subfolders=True)
    write_stub_pdf(recursive.pdf_folder / "root.pdf")
    write_stub_pdf(recursive.pdf_folder / "alpha" / "paper.pdf")
    write_stub_pdf(recursive.pdf_folder / "beta" / "paper.pdf")
    write_stub_pdf(recursive.pdf_folder / "nested" / "zeta.pdf")
    found, seconds, peak = measured(recursive._discover_pdf_files)
    display_names = [recursive._pdf_display_name(path) for path in found]
    collision_names = [name for name in display_names if name.endswith("paper.pdf")]
    rows.append(
        {
            "scenario": "recursive_subfolders",
            "files_found": len(found),
            "display_names": ", ".join(display_names),
            "collision_names_distinct": len(collision_names) == len(set(collision_names)) == 2,
            "wall_ms": round(seconds * 1000, 3),
            "memory_peak_kib": round(peak / 1024, 2),
            "method": "synthetic stub PDFs; discovery only",
        }
    )
    return rows


def benchmark_rate_limiter(work_dir: Path) -> Dict[str, Any]:
    reset_rate_limiters_for_tests()

    limiter = ProviderRateLimiter(min_interval=0, max_concurrency=2)
    active = 0
    max_active = 0
    active_lock = threading.Lock()

    def limited_operation():
        nonlocal active, max_active
        with active_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.005)
        with active_lock:
            active -= 1
        return "ok"

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=6) as executor:
        outcomes = list(executor.map(lambda _: limiter.run(limited_operation)[0], range(12)))
    concurrency_seconds = time.perf_counter() - start

    same_profile_a = get_provider_rate_limiter("provider-a|profile", min_interval=0, max_concurrency=1)
    same_profile_b = get_provider_rate_limiter("provider-a|profile", min_interval=0, max_concurrency=1)
    other_profile = get_provider_rate_limiter("provider-b|profile", min_interval=0, max_concurrency=1)

    class FlakyProvider:
        calls = 0

        def __init__(self, api_key, model, **kwargs):
            self.api_key = api_key
            self.model = model

        def chat_completion_with_tokens(self, messages, **kwargs):
            type(self).calls += 1
            if type(self).calls == 1:
                raise RuntimeError("429 rate limit")
            return "ok", 5

        def get_available_models(self):
            return [self.model]

    class CountingProvider:
        calls = 0

        def __init__(self, api_key, model, **kwargs):
            self.api_key = api_key
            self.model = model

        def chat_completion_with_tokens(self, messages, **kwargs):
            type(self).calls += 1
            return '{"decision":"Likely Include","reasoning":"fresh","notes":""}', 7

        def get_available_models(self):
            return [self.model]

    original_openai_provider = llm_interface.OpenAIProvider
    try:
        llm_interface.OpenAIProvider = FlakyProvider
        reset_rate_limiters_for_tests()
        retry_manager = LLMManager(
            "OpenAI",
            "benchmark-fake-key",
            "fake-retry-model",
            rate_limit_config={"min_interval": 0, "max_concurrency": 10},
        )
        retry_manager.chat_completion_with_tokens(
            [{"role": "user", "content": "retry benchmark"}],
            retry_max_attempts=2,
            retry_delay=0,
            retry_jitter=0,
        )
        retry_metadata = retry_manager.get_last_call_metadata()

        llm_interface.OpenAIProvider = CountingProvider
        reset_rate_limiters_for_tests()
        cache_auto = LLMManagerBackedAutomation(
            api_key="benchmark-fake-key",
            pdf_folder=str(work_dir / "rate_limiter_cache" / "pdfs"),
            output_folder=str(work_dir / "rate_limiter_cache" / "out"),
            cache_enabled=True,
            parallel_processing=False,
            rate_limit_delay=0,
            screening_prompt="screen {text}",
            llm_provider="OpenAI",
            llm_model="fake-cache-model",
            advanced_config={
                "max_retries": 1,
                "retry_delay": 0,
                "retry_jitter": 0,
                "rate_limit_min_interval": 0,
                "rate_limit_max_concurrency": 10,
            },
        )
        cache_auto.screen_article("cache hit limiter benchmark text", "cache.pdf")

        def fail_if_limiter_called(operation):
            raise AssertionError("cache hit should not acquire the rate limiter")

        cache_auto.llm_manager.rate_limiter.run = fail_if_limiter_called
        cache_auto.screen_article("cache hit limiter benchmark text", "cache.pdf")
        cache_hits_skip_limiter = CountingProvider.calls == 1
    finally:
        llm_interface.OpenAIProvider = original_openai_provider
        reset_rate_limiters_for_tests()

    return {
        "max_concurrency_configured": 2,
        "max_concurrency_observed": max_active,
        "all_limited_operations_ok": all(outcome == "ok" for outcome in outcomes),
        "concurrency_wall_ms": round(concurrency_seconds * 1000, 3),
        "same_profile_shares_limiter": same_profile_a is same_profile_b,
        "different_profile_isolated": same_profile_a is not other_profile,
        "retry_calls": FlakyProvider.calls,
        "retry_count_recorded": retry_metadata.get("retry_count"),
        "retry_error_category": retry_metadata.get("error_category"),
        "retry_final_status": retry_metadata.get("final_status"),
        "cache_hits_skip_limiter": cache_hits_skip_limiter,
    }


def hardware_summary() -> str:
    parts = [f"{os.cpu_count() or 'unknown'} logical CPUs"]
    machine = platform.processor() or platform.machine()
    if machine:
        parts.append(machine)
    try:
        import psutil

        total_gib = psutil.virtual_memory().total / (1024**3)
        parts.append(f"{total_gib:.1f} GiB RAM")
    except Exception:
        parts.append("RAM unavailable")
    return "; ".join(parts)


def benchmark_sizes(*, quick: bool, include_large: bool) -> List[int]:
    sizes = [10, 100, 1000]
    if include_large:
        sizes.append(5000)
    return sizes


def run_benchmark_suite(
    *,
    quick: bool = False,
    output_dir: Optional[Path] = None,
    report_path: Optional[Path] = None,
    include_large: bool = False,
    record_sizes: Optional[List[int]] = None,
) -> Dict[str, Any]:
    output_dir = Path(output_dir or RESULTS_DIR)
    report_path = Path(report_path or REPORT_PATH)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    work_dir = output_dir / f"work_{run_id}"
    work_dir.mkdir(parents=True, exist_ok=True)

    sizes = record_sizes or benchmark_sizes(quick=quick, include_large=include_large)
    started = datetime.now()
    results = {
        "metadata": {
            "date": started.isoformat(timespec="seconds"),
            "mode": "quick" if quick else "standard",
            "synthetic_seed": SYNTHETIC_SEED,
            "software_version": __version__,
            "python_version": platform.python_version(),
            "os": f"{platform.system()} {platform.release()} ({platform.platform()})",
            "hardware": hardware_summary(),
            "work_dir": str(work_dir),
            "no_external_api_calls": True,
        },
        "reference_deduplication": benchmark_reference_dedup(sizes),
        "cache_keys": benchmark_cache_keys(work_dir, quick=quick),
        "mocked_llm_title_abstract": benchmark_title_abstract_pipeline(work_dir, sizes),
        "mocked_llm_pdf_text": benchmark_pdf_text_pipeline(work_dir, quick=quick),
        "pdf_discovery": benchmark_pdf_discovery(work_dir),
        "rate_limiter": benchmark_rate_limiter(work_dir),
    }
    results["metadata"]["duration_seconds"] = round((datetime.now() - started).total_seconds(), 3)

    write_report(results, report_path)
    latest_json = output_dir / ("quick_latest.json" if quick else "latest.json")
    timestamped_json = output_dir / f"benchmark_{run_id}.json"
    latest_json.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    timestamped_json.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    results["metadata"]["report_path"] = str(report_path)
    results["metadata"]["latest_json"] = str(latest_json)
    return results


def markdown_table(rows: List[Dict[str, Any]], columns: List[str]) -> str:
    if not rows:
        return "_No rows._"
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows:
        values = [str(row.get(column, "")) for column in columns]
        body.append("| " + " | ".join(value.replace("\n", " ") for value in values) + " |")
    return "\n".join([header, separator, *body])


def write_report(results: Dict[str, Any], report_path: Path) -> None:
    metadata = results["metadata"]
    rate = results["rate_limiter"]
    durations = [
        row["cache_miss_wall_ms"] for row in results["mocked_llm_title_abstract"]
    ]
    median_title_abs_miss = round(statistics.median(durations), 3) if durations else "n/a"
    fuzzy_available = all(row.get("fuzzy_available") for row in results["reference_deduplication"])
    fuzzy_note = (
        "Fuzzy title matching was available for this run."
        if fuzzy_available
        else (
            "Fuzzy title matching was not available in this Python environment, "
            "so the current application code skipped fuzzy title deduplication. "
            "Expected fuzzy duplicate counts are shown for reference."
        )
    )

    lines = [
        "# SLR Assistant Benchmark Report",
        "",
        "## Environment",
        "",
        f"- Date: {metadata['date']}",
        f"- Software version: {metadata['software_version']}",
        f"- Python version: {metadata['python_version']}",
        f"- OS: {metadata['os']}",
        f"- Hardware: {metadata['hardware']}",
        f"- Mode: {metadata['mode']}",
        f"- Synthetic seed: {metadata['synthetic_seed']}",
        f"- External API calls: none; mocked/fake providers only",
        "",
        "## Methodology",
        "",
        "Benchmarks use deterministic synthetic records, fabricated PDF-like text, "
        "and local stub PDF files. LLM screening uses a deterministic in-process "
        "fake manager that returns JSON and never contacts hosted providers. "
        "PDF discovery benchmarks file discovery and display-name behavior only; "
        "they do not extract text from PDFs. Timings are wall-clock measurements "
        "from a single local run and include Python and filesystem overhead.",
        "",
        "Mocked LLM benchmarks do not represent real provider latency, throughput, "
        "availability, rate limits, token usage, or cost.",
        "",
        "Mocked LLM cache-hit runs may not be faster than cache-miss runs in these "
        "tables because the fake provider returns immediately and the cache-hit path "
        "still performs local file reads, metadata validation, and audit ledger writes. "
        "With real cloud LLM providers, cache hits avoid external network latency, "
        "provider queueing, token billing, and request-rate consumption.",
        "",
        "## Reference Ingestion And Deduplication",
        "",
        markdown_table(
            results["reference_deduplication"],
            [
                "records",
                "generation_wall_ms",
                "dedup_wall_ms",
                "dedup_records_per_sec",
                "memory_peak_kib",
                "duplicates_total",
                "doi_duplicates",
                "fuzzy_title_duplicates",
                "total_after",
                "expected_doi_duplicates",
                "expected_fuzzy_duplicates",
                "fuzzy_available",
            ],
        ),
        "",
        fuzzy_note,
        "",
        "## Cache-Key Generation",
        "",
        markdown_table(
            results["cache_keys"],
            ["kind", "iterations", "wall_ms", "avg_us_per_key", "distinct_keys", "memory_peak_kib"],
        ),
        "",
        "## Mocked LLM Title/Abstract Screening",
        "",
        markdown_table(
            results["mocked_llm_title_abstract"],
            [
                "records",
                "cache_miss_wall_ms",
                "cache_hit_wall_ms",
                "miss_records_per_sec",
                "hit_records_per_sec",
                "cache_hit_rate_hit_run_pct",
                "fake_llm_calls_miss",
                "fake_llm_calls_hit_increment",
                "audit_events_created",
                "memory_peak_kib",
            ],
        ),
        "",
        "## Mocked PDF-Like Text Screening",
        "",
        markdown_table(
            results["mocked_llm_pdf_text"],
            [
                "text_size",
                "chars_per_text",
                "documents",
                "cache_miss_wall_ms",
                "cache_hit_wall_ms",
                "miss_docs_per_sec",
                "hit_docs_per_sec",
                "cache_hit_rate_hit_run_pct",
                "fake_llm_calls_miss",
                "fake_llm_calls_hit_increment",
                "audit_events_created",
                "memory_peak_kib",
            ],
        ),
        "",
        "## PDF Discovery",
        "",
        markdown_table(
            results["pdf_discovery"],
            [
                "scenario",
                "files_found",
                "display_names",
                "collision_names_distinct",
                "wall_ms",
                "memory_peak_kib",
                "method",
            ],
        ),
        "",
        "## Rate Limiter Behavior",
        "",
        markdown_table(
            [
                {
                    "max_concurrency_configured": rate["max_concurrency_configured"],
                    "max_concurrency_observed": rate["max_concurrency_observed"],
                    "same_profile_shares_limiter": rate["same_profile_shares_limiter"],
                    "different_profile_isolated": rate["different_profile_isolated"],
                    "retry_calls": rate["retry_calls"],
                    "retry_count_recorded": rate["retry_count_recorded"],
                    "retry_error_category": rate["retry_error_category"],
                    "cache_hits_skip_limiter": rate["cache_hits_skip_limiter"],
                    "wall_ms": rate["concurrency_wall_ms"],
                }
            ],
            [
                "max_concurrency_configured",
                "max_concurrency_observed",
                "same_profile_shares_limiter",
                "different_profile_isolated",
                "retry_calls",
                "retry_count_recorded",
                "retry_error_category",
                "cache_hits_skip_limiter",
                "wall_ms",
            ],
        ),
        "",
        "## Summary",
        "",
        f"- Median title/abstract cache-miss wall time across record-count scenarios: {median_title_abs_miss} ms.",
        f"- Benchmark duration: {metadata['duration_seconds']} seconds.",
        "- Cache-hit runs should show 100% hit rate and zero fake LLM calls after the miss run.",
        "- Mocked cache-hit wall time is an implementation-overhead check, not a real-provider speedup estimate.",
        "- Audit ledger creation is represented by audit_events_created in the mocked LLM tables.",
        "",
        "## Limitations",
        "",
        "- Synthetic references and fabricated text do not represent a real systematic review corpus.",
        "- Fake LLM JSON responses do not measure real model quality, latency, tokenization, rate-limit behavior, or cost.",
        "- Stub PDFs benchmark discovery and collision-safe naming only, not real PDF parsing quality.",
        "- Single-run wall-clock measurements can vary by machine load, filesystem, and Python environment.",
        "- The optional 5000-record deduplication scenario is disabled unless `--include-large` is passed.",
        "",
        "## TODO",
        "",
        "- Add a future real-world benchmark using an open-access corpus with redistribution-compatible metadata and PDFs.",
        "- Repeat each scenario across multiple runs and report confidence intervals.",
        "- Add provider-latency and cost benchmarks only behind explicit opt-in flags and documented API-key handling.",
        "",
        "## README Or Paper Suitability",
        "",
        "These results are suitable for README-level smoke/performance documentation "
        "when clearly labeled as local synthetic mocked benchmarks. They are not "
        "suitable as paper evidence for real-world LLM latency, screening accuracy, "
        "provider cost, or PDF extraction quality without an open-access corpus and "
        "a repeated-run methodology.",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local SLR Assistant benchmarks.")
    parser.add_argument("--quick", action="store_true", help="Run the quick benchmark profile.")
    parser.add_argument(
        "--include-large",
        action="store_true",
        help="Include optional 5000-record reference deduplication and LLM scenarios.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=RESULTS_DIR,
        help="Directory for gitignored JSON results and working files.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=REPORT_PATH,
        help="Markdown report path.",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress console summary.")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    results = run_benchmark_suite(
        quick=args.quick,
        output_dir=args.output_dir,
        report_path=args.report,
        include_large=args.include_large,
    )
    if not args.quiet:
        metadata = results["metadata"]
        print(f"Benchmark report: {metadata['report_path']}")
        print(f"JSON results: {metadata['latest_json']}")
        print(f"Duration: {metadata['duration_seconds']} seconds")
        print("External API calls: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
