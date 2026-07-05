import hashlib
import json

from housing_enhanced import CACHE_SCHEMA_VERSION, __version__, SystematicReviewAutomation


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


def _fake_screening_call(decision, reasoning, calls):
    def fake_llm_call(messages, **kwargs):
        calls["count"] += 1
        return json.dumps({"decision": decision, "reasoning": reasoning, "notes": ""}), 7

    return fake_llm_call


def _fake_extraction_call(fields, calls):
    def fake_llm_call(messages, **kwargs):
        calls["count"] += 1
        return json.dumps(fields), 13

    return fake_llm_call


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
    assert base._cache_key_context(
        kind="screening",
        text=text,
        prompt={"screening_prompt": base.screening_prompt, "stage": "Full-text"},
        stage="Full-text",
    )["app_version"] == __version__


def test_normalized_text_hash_is_stable_for_line_endings_and_spaces(monkeypatch, tmp_path):
    auto = _automation(monkeypatch, tmp_path, screening_prompt="screen {text}")
    prompt = {"screening_prompt": auto.screening_prompt, "stage": "Full-text"}
    first = auto._cache_key_context(
        kind="screening",
        text="  A   paper\r\n\r\n\r\nwith text  ",
        prompt=prompt,
        stage="Full-text",
    )
    second = auto._cache_key_context(
        kind="screening",
        text="A paper\n\nwith text",
        prompt=prompt,
        stage="Full-text",
    )

    assert first["text_hash"] == second["text_hash"]
    assert first["cache_key"] == second["cache_key"]


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


def test_json_cache_with_missing_metadata_is_ignored(monkeypatch, tmp_path):
    auto = _automation(monkeypatch, tmp_path, screening_prompt="screen {text}")
    context = auto._cache_key_context(
        kind="screening",
        text="paper text",
        prompt={"screening_prompt": auto.screening_prompt, "stage": "Full-text"},
        stage="Full-text",
    )
    stale_file = auto.cache_folder / f"screening_{context['cache_key']}.json"
    stale_file.write_text(
        json.dumps({"decision": "Likely Exclude", "reasoning": "stale", "notes": ""}),
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


def test_changed_screening_prompt_does_not_reuse_old_screening_cache(monkeypatch, tmp_path):
    first = _automation(monkeypatch, tmp_path, screening_prompt="first prompt {text}")
    first_calls = {"count": 0}
    monkeypatch.setattr(
        first,
        "_llm_call",
        _fake_screening_call("Likely Exclude", "first prompt result", first_calls),
    )

    first_result = first.screen_article("paper text", "paper.pdf")

    second = _automation(monkeypatch, tmp_path, screening_prompt="second prompt {text}")
    second_calls = {"count": 0}
    monkeypatch.setattr(
        second,
        "_llm_call",
        _fake_screening_call("Likely Include", "second prompt result", second_calls),
    )

    second_result = second.screen_article("paper text", "paper.pdf")

    assert first_result.reasoning == "first prompt result"
    assert second_result.reasoning == "second prompt result"
    assert first_calls["count"] == 1
    assert second_calls["count"] == 1


def test_changed_provider_does_not_reuse_old_screening_cache(monkeypatch, tmp_path):
    first = _automation(monkeypatch, tmp_path, llm_provider="OpenAI", llm_model="same-model")
    first_calls = {"count": 0}
    monkeypatch.setattr(
        first,
        "_llm_call",
        _fake_screening_call("Likely Exclude", "openai result", first_calls),
    )

    first.screen_article("paper text", "paper.pdf")

    second = _automation(monkeypatch, tmp_path, llm_provider="OpenRouter", llm_model="same-model")
    second_calls = {"count": 0}
    monkeypatch.setattr(
        second,
        "_llm_call",
        _fake_screening_call("Likely Include", "openrouter result", second_calls),
    )

    result = second.screen_article("paper text", "paper.pdf")

    assert result.reasoning == "openrouter result"
    assert first_calls["count"] == 1
    assert second_calls["count"] == 1


def test_changed_model_does_not_reuse_old_screening_cache(monkeypatch, tmp_path):
    first = _automation(monkeypatch, tmp_path, llm_provider="OpenAI", llm_model="model-a")
    first_calls = {"count": 0}
    monkeypatch.setattr(
        first,
        "_llm_call",
        _fake_screening_call("Likely Exclude", "model-a result", first_calls),
    )

    first.screen_article("paper text", "paper.pdf")

    second = _automation(monkeypatch, tmp_path, llm_provider="OpenAI", llm_model="model-b")
    second_calls = {"count": 0}
    monkeypatch.setattr(
        second,
        "_llm_call",
        _fake_screening_call("Likely Include", "model-b result", second_calls),
    )

    result = second.screen_article("paper text", "paper.pdf")

    assert result.reasoning == "model-b result"
    assert first_calls["count"] == 1
    assert second_calls["count"] == 1


def test_title_abstract_and_full_text_screening_do_not_collide(monkeypatch, tmp_path):
    auto = _automation(monkeypatch, tmp_path, screening_prompt="screen {text}")
    calls = {"count": 0}
    responses = [
        {"decision": "Likely Exclude", "reasoning": "title abstract result", "notes": ""},
        {"decision": "Likely Include", "reasoning": "full text result", "notes": ""},
    ]

    def fake_llm_call(messages, **kwargs):
        response = responses[calls["count"]]
        calls["count"] += 1
        return json.dumps(response), 7

    monkeypatch.setattr(auto, "_llm_call", fake_llm_call)

    title_result = auto.screen_article("paper text", "paper.pdf", stage="Title/Abstract")
    full_result = auto.screen_article("paper text", "paper.pdf", stage="Full-text")

    assert title_result.reasoning == "title abstract result"
    assert full_result.reasoning == "full text result"
    assert calls["count"] == 2


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
    assert events[0]["provider"] == "OpenAI"
    assert events[0]["app_version"] == __version__
    assert events[0]["pipeline_version"] == __version__
    assert events[0]["prompt_hash"]
    assert events[0]["text_hash"]
    assert events[0]["advanced_config_hash"]
    assert events[0]["extraction_fields_hash"]
    assert events[0]["parse_status"] == "ok"
    assert events[0]["retry_count"] == 0
    assert events[0]["api_tokens_used"] == 11
    assert events[1]["api_tokens_used"] == 0
    assert "secret-test-key" not in auto.audit_ledger.read_text(encoding="utf-8")
    assert "paper text" not in auto.audit_ledger.read_text(encoding="utf-8")


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


def test_changed_extraction_prompt_does_not_reuse_old_extraction_cache(monkeypatch, tmp_path):
    first = _automation(monkeypatch, tmp_path, extraction_prompt="extract title from {text}")
    monkeypatch.setattr(first, "_generate_dynamic_schema", lambda: None)
    first_calls = {"count": 0}
    monkeypatch.setattr(
        first,
        "_llm_call",
        _fake_extraction_call({"title": "Old prompt", "title_quote": "Old prompt"}, first_calls),
    )

    first.extract_data("paper text", "paper.pdf")

    second = _automation(monkeypatch, tmp_path, extraction_prompt="extract verified title from {text}")
    monkeypatch.setattr(second, "_generate_dynamic_schema", lambda: None)
    second_calls = {"count": 0}
    monkeypatch.setattr(
        second,
        "_llm_call",
        _fake_extraction_call({"title": "New prompt", "title_quote": "New prompt"}, second_calls),
    )

    result = second.extract_data("paper text", "paper.pdf")

    assert result.fields["title"] == "New prompt"
    assert first_calls["count"] == 1
    assert second_calls["count"] == 1


def test_changed_extraction_fields_do_not_reuse_old_extraction_cache(monkeypatch, tmp_path):
    first = _automation(monkeypatch, tmp_path, extraction_fields=["title"])
    monkeypatch.setattr(first, "_generate_dynamic_schema", lambda: None)
    first_calls = {"count": 0}
    monkeypatch.setattr(
        first,
        "_llm_call",
        _fake_extraction_call({"title": "Title A", "title_quote": "Title A"}, first_calls),
    )

    first.extract_data("paper text", "paper.pdf")

    second = _automation(monkeypatch, tmp_path, extraction_fields=["title", "sample_size"])
    monkeypatch.setattr(second, "_generate_dynamic_schema", lambda: None)
    second_calls = {"count": 0}
    monkeypatch.setattr(
        second,
        "_llm_call",
        _fake_extraction_call(
            {
                "title": "Title B",
                "title_quote": "Title B",
                "sample_size": "42",
                "sample_size_quote": "42",
            },
            second_calls,
        ),
    )

    result = second.extract_data("paper text", "paper.pdf")

    assert result.fields["title"] == "Title B"
    assert result.fields["sample_size"] == "42"
    assert first_calls["count"] == 1
    assert second_calls["count"] == 1


def test_changed_advanced_config_does_not_reuse_old_extraction_cache(monkeypatch, tmp_path):
    first = _automation(monkeypatch, tmp_path, advanced_config={"max_text_chars": 1000})
    monkeypatch.setattr(first, "_generate_dynamic_schema", lambda: None)
    first_calls = {"count": 0}
    monkeypatch.setattr(
        first,
        "_llm_call",
        _fake_extraction_call({"title": "Config A", "title_quote": "Config A"}, first_calls),
    )

    first.extract_data("paper text", "paper.pdf")

    second = _automation(monkeypatch, tmp_path, advanced_config={"max_text_chars": 2000})
    monkeypatch.setattr(second, "_generate_dynamic_schema", lambda: None)
    second_calls = {"count": 0}
    monkeypatch.setattr(
        second,
        "_llm_call",
        _fake_extraction_call({"title": "Config B", "title_quote": "Config B"}, second_calls),
    )

    result = second.extract_data("paper text", "paper.pdf")

    assert result.fields["title"] == "Config B"
    assert first_calls["count"] == 1
    assert second_calls["count"] == 1
