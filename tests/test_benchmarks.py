import subprocess
import sys

import requests

from benchmarks.run_benchmarks import (
    expected_duplicate_counts,
    generate_synthetic_records,
    run_benchmark_suite,
)
from ingestion import deduplicate


def test_synthetic_record_generation_is_deterministic():
    first = generate_synthetic_records(25)
    second = generate_synthetic_records(25)

    assert first == second
    assert first[0]["doi"] == "10.5555/slr.0000"
    assert first[1]["doi"] == first[0]["doi"]
    assert first[2]["doi"] == ""
    assert expected_duplicate_counts(25) == {
        "expected_doi_duplicates": 3,
        "expected_fuzzy_duplicates": 3,
        "expected_total_after": 19,
    }


def test_synthetic_records_have_deliberate_dedup_counts_when_fuzz_is_available():
    try:
        import thefuzz  # noqa: F401
    except ImportError:
        return

    records = generate_synthetic_records(100)
    deduped, stats = deduplicate(records)
    expected = expected_duplicate_counts(100)

    assert stats.removed_doi == expected["expected_doi_duplicates"]
    assert stats.removed_fuzzy == expected["expected_fuzzy_duplicates"]
    assert len(deduped) == expected["expected_total_after"]


def test_benchmark_suite_runs_with_external_http_blocked(monkeypatch, tmp_path):
    def fail_request(*args, **kwargs):
        raise AssertionError("benchmark suite must not perform external HTTP calls")

    monkeypatch.setattr(requests.sessions.Session, "request", fail_request)
    report_path = tmp_path / "BENCHMARK_REPORT.md"

    results = run_benchmark_suite(
        quick=True,
        output_dir=tmp_path / "results",
        report_path=report_path,
        record_sizes=[10],
    )

    assert results["metadata"]["no_external_api_calls"] is True
    assert report_path.exists()
    report = report_path.read_text(encoding="utf-8")
    assert "External API calls: none" in report
    assert "mocked/fake providers only" in report


def test_benchmark_script_quick_mode_generates_markdown(tmp_path):
    report_path = tmp_path / "BENCHMARK_REPORT.md"
    output_dir = tmp_path / "results"

    completed = subprocess.run(
        [
            sys.executable,
            "benchmarks/run_benchmarks.py",
            "--quick",
            "--quiet",
            "--output-dir",
            str(output_dir),
            "--report",
            str(report_path),
        ],
        cwd=".",
        check=False,
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    assert report_path.exists()
    report = report_path.read_text(encoding="utf-8")
    assert "SLR Assistant Benchmark Report" in report
    assert "Mocked LLM benchmarks do not represent real provider latency" in report
    assert (output_dir / "quick_latest.json").exists()
