import hashlib
import json

from housing_enhanced import CACHE_SCHEMA_VERSION, SystematicReviewAutomation


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


def test_cache_key_includes_provider_model_prompt_fields_config_and_schema(monkeypatch, tmp_path):
    base = _automation(
        monkeypatch,
        tmp_path,
        llm_provider="OpenAI",
        llm_model="gpt-5.5",
        screening_prompt="screen {text}",
        extraction_fields=["title"],
        advanced_config={"max_text_chars": 1000},
        output_name="base",
    )
    text = "paper text"
    base_key = base._cache_key_context(
        kind="screening",
        text=text,
        prompt={"screening_prompt": base.screening_prompt, "stage": "Full-text"},
        stage="Full-text",
    )["cache_key"]

    variants = [
        _automation(monkeypatch, tmp_path, llm_provider="OpenRouter", llm_model="gpt-5.5", output_name="provider"),
        _automation(monkeypatch, tmp_path, llm_provider="OpenAI", llm_model="gpt-5.4-mini", output_name="model"),
        _automation(monkeypatch, tmp_path, screening_prompt="different {text}", output_name="prompt"),
        _automation(monkeypatch, tmp_path, extraction_fields=["title", "sample_size"], output_name="fields"),
        _automation(monkeypatch, tmp_path, advanced_config={"max_text_chars": 2000}, output_name="config"),
    ]

    variant_keys = {
        automation._cache_key_context(
            kind="screening",
            text=text,
            prompt={"screening_prompt": automation.screening_prompt, "stage": "Full-text"},
            stage="Full-text",
        )["cache_key"]
        for automation in variants
    }

    assert base_key not in variant_keys
    assert len(variant_keys) == len(variants)
    assert base._cache_key_context(
        kind="screening",
        text=text,
        prompt={"screening_prompt": base.screening_prompt, "stage": "Full-text"},
        stage="Full-text",
    )["cache_schema_version"] == CACHE_SCHEMA_VERSION


def test_legacy_text_only_cache_file_is_not_used(monkeypatch, tmp_path):
    auto = _automation(monkeypatch, tmp_path, screening_prompt="screen {text}")
    legacy_key = hashlib.md5("paper textFull-text".encode()).hexdigest()
    legacy_file = auto.cache_folder / f"screening_{legacy_key}.json"
    legacy_file.write_text(
        json.dumps({"decision": "Likely Exclude", "reasoning": "legacy", "notes": ""}),
        encoding="utf-8",
    )
    calls = {"count": 0}

    def fake_llm_call(messages, **kwargs):
        calls["count"] += 1
        return '{"decision":"Likely Include","reasoning":"fresh","notes":""}', 17

    monkeypatch.setattr(auto, "_llm_call", fake_llm_call)

    result = auto.screen_article("paper text", "paper.pdf")

    assert result.decision == "Likely Include"
    assert result.reasoning == "fresh"
    assert calls["count"] == 1


def test_audit_ledger_records_screening_miss_and_hit_without_secrets(monkeypatch, tmp_path):
    auto = _automation(monkeypatch, tmp_path, screening_prompt="screen {text}", llm_model="manual-model")
    calls = {"count": 0}

    def fake_llm_call(messages, **kwargs):
        calls["count"] += 1
        return '{"decision":"Likely Include","reasoning":"ok","notes":""}', 11

    monkeypatch.setattr(auto, "_llm_call", fake_llm_call)

    first = auto.screen_article("paper text", "paper.pdf")
    second = auto.screen_article("paper text", "paper.pdf")

    assert first.decision == "Likely Include"
    assert second.decision == "Likely Include"
    assert calls["count"] == 1

    events = [
        json.loads(line)
        for line in auto.audit_ledger.read_text(encoding="utf-8").splitlines()
    ]

    assert [event["cache_hit"] for event in events] == [False, True]
    assert events[0]["kind"] == "screening"
    assert events[0]["model"] == "manual-model"
    assert events[0]["prompt_hash"]
    assert events[0]["text_hash"]
    assert events[0]["advanced_config_hash"]
    assert events[0]["extraction_fields_hash"]
    assert events[0]["api_tokens_used"] == 11
    assert events[1]["api_tokens_used"] == 0
    assert "secret-test-key" not in auto.audit_ledger.read_text(encoding="utf-8")


def test_audit_ledger_records_extraction_cache_status(monkeypatch, tmp_path):
    auto = _automation(monkeypatch, tmp_path, extraction_fields=["title"])
    monkeypatch.setattr(auto, "_generate_dynamic_schema", lambda: None)
    calls = {"count": 0}

    def fake_llm_call(messages, **kwargs):
        calls["count"] += 1
        return '{"title":"A study","title_quote":"A study"}', 23

    monkeypatch.setattr(auto, "_llm_call", fake_llm_call)

    first = auto.extract_data("paper text", "paper.pdf")
    second = auto.extract_data("paper text", "paper.pdf")

    assert first.fields["title"] == "A study"
    assert second.fields["title"] == "A study"
    assert calls["count"] == 1

    events = [
        json.loads(line)
        for line in auto.audit_ledger.read_text(encoding="utf-8").splitlines()
    ]

    assert [event["kind"] for event in events] == ["extraction", "extraction"]
    assert [event["cache_hit"] for event in events] == [False, True]
    assert events[0]["api_tokens_used"] == 23
    assert events[1]["api_tokens_used"] == 0
