import sys
import types

import pytest

import llm_interface
from llm_interface import LLMManager, OpenAICompatibleProvider, classify_model_stability


def test_manual_model_id_is_accepted_for_openai(monkeypatch):
    class FakeOpenAIClient:
        def __init__(self, api_key=None, **kwargs):
            self.api_key = api_key

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAIClient))

    manager = LLMManager("OpenAI", "test-key", "future-openai-model")

    assert manager.provider.model == "future-openai-model"


def test_manual_model_id_is_accepted_for_openai_compatible_profile():
    manager = LLMManager("DeepSeek", "test-key", "future-compatible-model")

    assert isinstance(manager.provider, OpenAICompatibleProvider)
    assert manager.provider.model == "future-compatible-model"
    assert manager.provider.base_url == "https://api.deepseek.com/v1"


def test_openrouter_uses_openai_compatible_adapter_and_router_privacy():
    manager = LLMManager("OpenRouter", "test-key", "openai/custom-model")
    info = LLMManager.get_provider_info()["OpenRouter"]

    assert isinstance(manager.provider, OpenAICompatibleProvider)
    assert manager.provider.base_url == "https://openrouter.ai/api/v1"
    assert info["privacy_level"] == "router_third_party"


def test_provider_privacy_levels_are_present():
    info = LLMManager.get_provider_info()

    assert info["Ollama (Local)"]["privacy_level"] == "local_only"
    assert info["OpenAI"]["privacy_level"] == "direct_cloud"
    assert info["Anthropic (Claude)"]["privacy_level"] == "direct_cloud"
    assert info["Google Gemini"]["privacy_level"] == "direct_cloud"
    assert info["Custom OpenAI-Compatible"]["privacy_level"] == "custom_endpoint"


def test_mistral_profile_resolves_to_openai_compatible_base_url():
    manager = LLMManager("Mistral", "test-key", "mistral-manual-model")

    assert isinstance(manager.provider, OpenAICompatibleProvider)
    assert manager.provider.base_url == "https://api.mistral.ai/v1"


def test_provider_metadata_contains_required_fields():
    required = {
        "id",
        "display_name",
        "adapter",
        "base_url",
        "requires_api_key",
        "privacy_level",
        "website",
        "default_model",
        "recommended_models",
    }

    for profile in LLMManager.get_provider_catalog().values():
        assert required.issubset(profile)
        assert profile["privacy_level"] in {
            "local_only",
            "direct_cloud",
            "router_third_party",
            "custom_endpoint",
        }


def test_model_catalog_recommends_without_validating_unknown_models():
    recommended = LLMManager.get_models_for_provider("OpenAI")

    assert recommended[:3] == ["gpt-5.5", "gpt-5.4-mini", "gpt-5.4-nano"]
    assert "not-yet-listed-model" not in recommended
    manager = LLMManager("OpenRouter", "test-key", "not-yet-listed-model")
    assert manager.provider.model == "not-yet-listed-model"


def test_openrouter_model_discovery_is_mocked(monkeypatch):
    calls = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "openai/gpt-5.5"}, {"id": "anthropic/claude-sonnet-4"}]}

    def fake_get(url, **kwargs):
        calls["url"] = url
        calls["kwargs"] = kwargs
        return FakeResponse()

    monkeypatch.setattr(llm_interface.requests, "get", fake_get)

    models = LLMManager.discover_models("OpenRouter", api_key="test-key")

    assert calls["url"] == "https://openrouter.ai/api/v1/models"
    assert calls["kwargs"]["headers"]["Authorization"] == "Bearer test-key"
    assert models == ["openai/gpt-5.5", "anthropic/claude-sonnet-4"]


def test_ollama_tags_discovery_parser_works():
    payload = {"models": [{"name": "llama3.2:latest"}, {"name": "qwen2:7b"}]}

    assert LLMManager.parse_discovered_models("ollama_tags", payload) == [
        "llama3.2:latest",
        "qwen2:7b",
    ]


def test_anthropic_models_discovery_parser_works():
    payload = {"data": [{"id": "claude-sonnet-4-20250514"}, {"id": "claude-opus-4-20250514"}]}

    assert LLMManager.parse_discovered_models("anthropic_models", payload) == [
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
    ]


def test_gemini_model_stability_classification_supports_reproducibility_warnings():
    assert classify_model_stability("gemini-2.5-flash") == "stable"
    assert classify_model_stability("gemini-2.5-flash-preview") == "preview"
    assert classify_model_stability("gemini-2.5-flash-latest") == "latest"
    assert classify_model_stability("gemini-exp-1206") == "experimental"


def test_unsupported_provider_raises_clear_error():
    with pytest.raises(ValueError) as exc:
        LLMManager("Unknown Provider", "key", "model")

    msg = str(exc.value)
    assert "Unknown provider" in msg
    assert "Supported providers" in msg
    assert "Custom OpenAI-Compatible" in msg
