import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import llm_interface
from housing_enhanced import SystematicReviewAutomation
from llm_interface import (
    LLMCallError,
    LLMManager,
    ProviderRateLimiter,
    get_provider_rate_limiter,
    reset_rate_limiters_for_tests,
)


def _install_fake_openai_provider(monkeypatch, provider_cls):
    monkeypatch.setattr(llm_interface, "OpenAIProvider", provider_cls)
    reset_rate_limiters_for_tests()


def _automation(tmp_path, **kwargs):
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    return SystematicReviewAutomation(
        api_key="test-key",
        pdf_folder=str(pdf_dir),
        output_folder=str(tmp_path / kwargs.pop("output_name", "out")),
        cache_enabled=True,
        parallel_processing=False,
        rate_limit_delay=0,
        screening_prompt="screen {text}",
        advanced_config={
            "max_retries": kwargs.pop("max_retries", 2),
            "retry_delay": 0,
            "retry_jitter": 0,
            "rate_limit_min_interval": 0,
            "rate_limit_max_concurrency": 10,
        },
        **kwargs,
    )


def test_limiter_enforces_provider_level_spacing_across_threads():
    limiter = ProviderRateLimiter(min_interval=0.03, max_concurrency=3)
    starts = []

    def operation():
        starts.append(time.monotonic())
        return "ok"

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(limiter.run, operation) for _ in range(3)]
        assert [future.result()[0] for future in futures] == ["ok", "ok", "ok"]

    ordered = sorted(starts)
    gaps = [ordered[i + 1] - ordered[i] for i in range(len(ordered) - 1)]
    assert min(gaps) >= 0.02


def test_limiter_enforces_max_concurrency():
    limiter = ProviderRateLimiter(min_interval=0, max_concurrency=1)
    active = 0
    max_seen = 0

    def operation():
        nonlocal active, max_seen
        active += 1
        max_seen = max(max_seen, active)
        time.sleep(0.02)
        active -= 1
        return "ok"

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(limiter.run, operation) for _ in range(3)]
        assert [future.result()[0] for future in futures] == ["ok", "ok", "ok"]

    assert max_seen == 1


def test_limiter_registry_is_keyed_by_provider_profile():
    reset_rate_limiters_for_tests()
    openai_a = get_provider_rate_limiter("openai|", min_interval=0, max_concurrency=1)
    openai_b = get_provider_rate_limiter("openai|", min_interval=0, max_concurrency=1)
    openrouter = get_provider_rate_limiter("openrouter|https://openrouter.ai/api/v1", min_interval=0, max_concurrency=1)

    assert openai_a is openai_b
    assert openai_a is not openrouter


def test_openai_and_openrouter_do_not_share_limiter_state(monkeypatch):
    class FakeOpenAIProvider:
        def __init__(self, api_key, model, **kwargs):
            self.api_key = api_key
            self.model = model

        def chat_completion_with_tokens(self, messages, **kwargs):
            return "ok", 1

        def get_available_models(self):
            return [self.model]

    _install_fake_openai_provider(monkeypatch, FakeOpenAIProvider)

    openai = LLMManager(
        "OpenAI",
        "test-key",
        "gpt-manual",
        rate_limit_config={"min_interval": 0, "max_concurrency": 10},
    )
    openrouter = LLMManager(
        "OpenRouter",
        "test-key",
        "openai/gpt-manual",
        rate_limit_config={"min_interval": 0, "max_concurrency": 10},
    )

    assert openai.rate_limiter is not openrouter.rate_limiter
    assert openai.rate_limit_key.startswith("openai|")
    assert openrouter.rate_limit_key.startswith("openrouter|")


def test_same_provider_profile_managers_share_limiter(monkeypatch):
    class FakeOpenAIProvider:
        def __init__(self, api_key, model, **kwargs):
            self.api_key = api_key
            self.model = model

        def chat_completion_with_tokens(self, messages, **kwargs):
            return "ok", 1

        def get_available_models(self):
            return [self.model]

    _install_fake_openai_provider(monkeypatch, FakeOpenAIProvider)

    first = LLMManager(
        "OpenAI",
        "test-key",
        "gpt-manual",
        rate_limit_config={"min_interval": 0, "max_concurrency": 10},
    )
    second = LLMManager(
        "OpenAI",
        "another-test-key",
        "gpt-other",
        rate_limit_config={"min_interval": 0, "max_concurrency": 10},
    )

    assert first.rate_limit_key == second.rate_limit_key
    assert first.rate_limiter is second.rate_limiter


def test_retry_succeeds_after_simulated_transient_429(monkeypatch):
    calls = {"count": 0}

    class FlakyProvider:
        def __init__(self, api_key, model, **kwargs):
            self.api_key = api_key
            self.model = model

        def chat_completion_with_tokens(self, messages, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("429 rate limit")
            return "ok", 5

        def get_available_models(self):
            return [self.model]

    _install_fake_openai_provider(monkeypatch, FlakyProvider)
    manager = LLMManager(
        "OpenAI",
        "test-key",
        "gpt-manual",
        rate_limit_config={"min_interval": 0, "max_concurrency": 10},
    )

    text, tokens = manager.chat_completion_with_tokens(
        [{"role": "user", "content": "hi"}],
        retry_max_attempts=2,
        retry_delay=0,
        retry_jitter=0,
    )

    assert (text, tokens) == ("ok", 5)
    assert calls["count"] == 2
    assert manager.get_last_call_metadata()["retry_count"] == 1
    assert manager.get_last_call_metadata()["error_category"] == "rate_limit"


def test_retry_succeeds_after_simulated_timeout(monkeypatch):
    calls = {"count": 0}

    class TimeoutThenSuccessProvider:
        def __init__(self, api_key, model, **kwargs):
            self.api_key = api_key
            self.model = model

        def chat_completion_with_tokens(self, messages, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise TimeoutError("request timed out")
            return "ok", 3

        def get_available_models(self):
            return [self.model]

    _install_fake_openai_provider(monkeypatch, TimeoutThenSuccessProvider)
    manager = LLMManager(
        "OpenAI",
        "test-key",
        "gpt-manual",
        rate_limit_config={"min_interval": 0, "max_concurrency": 10},
    )

    assert manager.chat_completion_with_tokens([], retry_max_attempts=2, retry_delay=0, retry_jitter=0) == ("ok", 3)
    assert calls["count"] == 2
    assert manager.get_last_call_metadata()["error_category"] == "timeout"


def test_permanent_auth_error_is_not_retried(monkeypatch):
    calls = {"count": 0}

    class AuthErrorProvider:
        def __init__(self, api_key, model, **kwargs):
            self.api_key = api_key
            self.model = model

        def chat_completion_with_tokens(self, messages, **kwargs):
            calls["count"] += 1
            raise RuntimeError("401 invalid API key")

        def get_available_models(self):
            return [self.model]

    _install_fake_openai_provider(monkeypatch, AuthErrorProvider)
    manager = LLMManager(
        "OpenAI",
        "bad-key",
        "gpt-manual",
        rate_limit_config={"min_interval": 0, "max_concurrency": 10},
    )

    with pytest.raises(LLMCallError) as exc:
        manager.chat_completion_with_tokens([], retry_max_attempts=3, retry_delay=0, retry_jitter=0)

    assert calls["count"] == 1
    assert exc.value.category == "auth_error"
    assert manager.get_last_call_metadata()["final_status"] == "failed_permanent"


def test_unsupported_model_error_is_not_retried(monkeypatch):
    calls = {"count": 0}

    class UnsupportedModelProvider:
        def __init__(self, api_key, model, **kwargs):
            self.api_key = api_key
            self.model = model

        def chat_completion_with_tokens(self, messages, **kwargs):
            calls["count"] += 1
            raise RuntimeError("model not found")

        def get_available_models(self):
            return [self.model]

    _install_fake_openai_provider(monkeypatch, UnsupportedModelProvider)
    manager = LLMManager(
        "OpenAI",
        "test-key",
        "missing-model",
        rate_limit_config={"min_interval": 0, "max_concurrency": 10},
    )

    with pytest.raises(LLMCallError) as exc:
        manager.chat_completion_with_tokens([], retry_max_attempts=3, retry_delay=0, retry_jitter=0)

    assert calls["count"] == 1
    assert exc.value.category == "unsupported_model"
    metadata = manager.get_last_call_metadata()
    assert metadata["retry_count"] == 0
    assert metadata["attempt_count"] == 1
    assert metadata["final_status"] == "failed_permanent"
    assert metadata["error_category"] == "unsupported_model"


def test_exhausted_retries_produce_clear_error_metadata(monkeypatch):
    calls = {"count": 0}

    class AlwaysRateLimitedProvider:
        def __init__(self, api_key, model, **kwargs):
            self.api_key = api_key
            self.model = model

        def chat_completion_with_tokens(self, messages, **kwargs):
            calls["count"] += 1
            raise RuntimeError("429 rate limit")

        def get_available_models(self):
            return [self.model]

    _install_fake_openai_provider(monkeypatch, AlwaysRateLimitedProvider)
    manager = LLMManager(
        "OpenAI",
        "test-key",
        "gpt-manual",
        rate_limit_config={"min_interval": 0, "max_concurrency": 10},
    )

    with pytest.raises(LLMCallError) as exc:
        manager.chat_completion_with_tokens([], retry_max_attempts=2, retry_delay=0, retry_jitter=0)

    assert calls["count"] == 2
    assert "failed after 2 attempts" in str(exc.value)
    assert exc.value.category == "rate_limit"
    metadata = manager.get_last_call_metadata()
    assert metadata["retry_count"] == 1
    assert metadata["final_status"] == "failed_retry_exhausted"
    assert metadata["error_category"] == "rate_limit"


def test_audit_ledger_records_retry_count_and_error_category(monkeypatch, tmp_path):
    calls = {"count": 0}

    class FlakyProvider:
        def __init__(self, api_key, model, **kwargs):
            self.api_key = api_key
            self.model = model

        def chat_completion_with_tokens(self, messages, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("429 rate limit")
            return '{"decision":"Likely Include","reasoning":"ok","notes":""}', 11

        def get_available_models(self):
            return [self.model]

    _install_fake_openai_provider(monkeypatch, FlakyProvider)
    auto = _automation(tmp_path, llm_provider="OpenAI", llm_model="gpt-manual")

    result = auto.screen_article("paper text", "paper.pdf")
    events = [json.loads(line) for line in auto.audit_ledger.read_text(encoding="utf-8").splitlines()]

    assert result.decision == "Likely Include"
    assert calls["count"] == 2
    assert events[0]["retry_count"] == 1
    assert events[0]["final_status"] == "success"
    assert events[0]["error_category"] == "rate_limit"
    assert events[0]["rate_limit_wait_seconds"] >= 0
    assert "test-key" not in auto.audit_ledger.read_text(encoding="utf-8")


def test_audit_ledger_records_exhausted_retry_failure_metadata(monkeypatch, tmp_path):
    calls = {"count": 0}

    class AlwaysRateLimitedProvider:
        def __init__(self, api_key, model, **kwargs):
            self.api_key = api_key
            self.model = model

        def chat_completion_with_tokens(self, messages, **kwargs):
            calls["count"] += 1
            raise RuntimeError("429 rate limit")

        def get_available_models(self):
            return [self.model]

    _install_fake_openai_provider(monkeypatch, AlwaysRateLimitedProvider)
    auto = _automation(tmp_path, llm_provider="OpenAI", llm_model="gpt-manual")

    result = auto.screen_article("paper text", "paper.pdf")
    events = [json.loads(line) for line in auto.audit_ledger.read_text(encoding="utf-8").splitlines()]

    assert calls["count"] == 2
    assert result.decision == "Error"
    assert "failed after 2 attempts" in result.reasoning
    assert events[0]["status"] == "error"
    assert events[0]["final_status"] == "failed_retry_exhausted"
    assert events[0]["retry_count"] == 1
    assert events[0]["error_category"] == "rate_limit"


def test_cache_hit_does_not_call_limiter_or_llm(monkeypatch, tmp_path):
    calls = {"count": 0}

    class CountingProvider:
        def __init__(self, api_key, model, **kwargs):
            self.api_key = api_key
            self.model = model

        def chat_completion_with_tokens(self, messages, **kwargs):
            calls["count"] += 1
            return '{"decision":"Likely Include","reasoning":"fresh","notes":""}', 9

        def get_available_models(self):
            return [self.model]

    _install_fake_openai_provider(monkeypatch, CountingProvider)
    auto = _automation(tmp_path, llm_provider="OpenAI", llm_model="gpt-manual")

    first = auto.screen_article("paper text", "paper.pdf")

    def fail_if_called(operation):
        raise AssertionError("cache hit should not acquire limiter or call provider")

    auto.llm_manager.rate_limiter.run = fail_if_called
    second = auto.screen_article("paper text", "paper.pdf")

    assert first.reasoning == "fresh"
    assert second.reasoning == "fresh"
    assert calls["count"] == 1
