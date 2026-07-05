import json

from housing_enhanced import ScreeningDecision, ScreeningResult, SystematicReviewAutomation


def _automation(monkeypatch, tmp_path, **kwargs):
    monkeypatch.setattr(SystematicReviewAutomation, "_init_llm", lambda self: object())
    return SystematicReviewAutomation(
        api_key="secret-test-key",
        pdf_folder=str(tmp_path / "pdfs"),
        output_folder=str(tmp_path / kwargs.pop("output_name", "out")),
        cache_enabled=True,
        parallel_processing=False,
        **kwargs,
    )


def test_process_one_writes_text_cache_and_retains_metadata_only(monkeypatch, tmp_path):
    auto = _automation(monkeypatch, tmp_path)
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF fake fixture")
    extracted_text = "Small extracted text fixture."

    def fake_extract(path):
        auto._record_text_extraction_metadata(
            path,
            method="fake",
            status="ok",
            text=extracted_text,
            page_count=2,
        )
        return extracted_text, True

    monkeypatch.setattr(auto, "extract_text_from_pdf", fake_extract)
    monkeypatch.setattr(
        auto,
        "screen_article",
        lambda text, filename, stage="Full-text": ScreeningResult(
            filename=filename,
            decision=ScreeningDecision.LIKELY_EXCLUDE.value,
            reasoning="fake",
            notes="",
            stage=stage,
            text_length=len(text),
        ),
    )

    screening, extraction = auto._process_one(pdf_path)
    metadata = auto.get_paper_text_metadata("paper.pdf")
    cache_path = auto.text_cache_folder / f"{metadata['text_hash']}.txt"
    metadata_path = auto.text_cache_folder / f"{metadata['text_hash']}.json"

    assert screening.decision == ScreeningDecision.LIKELY_EXCLUDE.value
    assert extraction is None
    assert cache_path.exists()
    assert metadata_path.exists()
    assert cache_path.read_text(encoding="utf-8") == extracted_text
    assert json.loads(metadata_path.read_text(encoding="utf-8"))["text_hash"] == metadata["text_hash"]
    assert metadata["text_cache_path"] == str(cache_path)
    assert metadata["extraction_method"] == "fake"
    assert metadata["extraction_status"] == "ok"
    assert metadata["extracted_char_count"] == len(extracted_text)
    assert metadata["page_count"] == 2
    assert auto._paper_texts == {}
    assert extracted_text not in json.dumps(metadata)


def test_lazy_loading_returns_expected_text(monkeypatch, tmp_path):
    auto = _automation(monkeypatch, tmp_path)
    text = "Lazy loaded text fixture."

    auto._store_paper_text_cache(
        "paper.pdf",
        text,
        {"extraction_method": "fake", "extraction_status": "ok"},
    )

    assert auto.get_paper_text("paper.pdf") == text
    assert auto._paper_texts == {}


def test_missing_text_cache_file_is_handled_gracefully(monkeypatch, tmp_path):
    auto = _automation(monkeypatch, tmp_path)
    metadata = auto._store_paper_text_cache(
        "paper.pdf",
        "Temporary text fixture.",
        {"extraction_method": "fake", "extraction_status": "ok"},
    )
    (auto.text_cache_folder / f"{metadata['text_hash']}.txt").unlink()

    assert auto.get_paper_text("paper.pdf") == (
        "(Paper text cache missing; rerun processing to rebuild it.)"
    )


def test_audit_records_text_cache_metadata_without_full_text(monkeypatch, tmp_path):
    auto = _automation(monkeypatch, tmp_path, screening_prompt="screen {text}")
    text = "UNIQUE_FULL_TEXT_SHOULD_NOT_APPEAR_IN_AUDIT"
    auto._store_paper_text_cache(
        "paper.pdf",
        text,
        {"extraction_method": "fake", "extraction_status": "ok", "page_count": 1},
    )

    def fake_llm_call(messages, **kwargs):
        return '{"decision":"Likely Include","reasoning":"ok","notes":""}', 5

    monkeypatch.setattr(auto, "_llm_call", fake_llm_call)

    auto.screen_article(text, "paper.pdf")

    audit_text = auto.audit_ledger.read_text(encoding="utf-8")
    event = json.loads(audit_text.splitlines()[0])

    assert event["text_hash"]
    assert event["text_cache"]["original_filename"] == "paper.pdf"
    assert event["text_cache"]["text_hash"]
    assert event["text_cache"]["text_cache_path"].endswith(".txt")
    assert event["text_cache"]["extraction_method"] == "fake"
    assert event["text_cache"]["extraction_status"] == "ok"
    assert event["text_cache"]["extracted_char_count"] == len(text)
    assert event["text_cache"]["page_count"] == 1
    assert "secret-test-key" not in audit_text
    assert text not in audit_text
