"""
LLM Interface - provider catalog plus a small set of adapters.

The app keeps a chat-style abstraction for local-first SLR workflows. Native
providers are used only when the API shape is genuinely different. Hosted and
local OpenAI-compatible services are represented as catalog profiles.
"""

import copy
import json
import logging
import os
import random
import re
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from version import VERSION as __version__

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared rate limiting and retry helpers
# ---------------------------------------------------------------------------

RETRYABLE_ERROR_CATEGORIES = {
    "rate_limit",
    "timeout",
    "server_error",
    "connection_error",
    "temporary_network",
    "unknown",
}


class LLMCallError(RuntimeError):
    """Clear final error for provider calls after retry classification."""

    def __init__(
        self,
        message: str,
        *,
        category: str,
        retry_count: int,
        original_error: Exception,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.category = category
        self.retry_count = retry_count
        self.original_error = original_error
        self.metadata = metadata or {}


class ProviderRateLimiter:
    """Thread-safe provider/profile limiter with request spacing and concurrency."""

    def __init__(
        self,
        min_interval: float = 0.75,
        max_concurrency: int = 1,
        *,
        clock=None,
        sleeper=None,
    ):
        self.min_interval = max(0.0, float(min_interval or 0.0))
        self.max_concurrency = max(1, int(max_concurrency or 1))
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or time.sleep
        self._condition = threading.Condition()
        self._active = 0
        self._last_start = 0.0

    def configure(self, *, min_interval: Optional[float] = None, max_concurrency: Optional[int] = None) -> None:
        with self._condition:
            if min_interval is not None:
                self.min_interval = max(0.0, float(min_interval))
            if max_concurrency is not None:
                self.max_concurrency = max(1, int(max_concurrency))
            self._condition.notify_all()

    def _enter(self) -> float:
        total_wait = 0.0
        while True:
            with self._condition:
                while self._active >= self.max_concurrency:
                    self._condition.wait()

                now = self._clock()
                wait_seconds = max(0.0, (self._last_start + self.min_interval) - now)
                if wait_seconds <= 0:
                    self._active += 1
                    self._last_start = now
                    return total_wait

            self._sleeper(wait_seconds)
            total_wait += wait_seconds

    def _exit(self) -> None:
        with self._condition:
            self._active = max(0, self._active - 1)
            self._condition.notify_all()

    def run(self, operation):
        wait_seconds = self._enter()
        try:
            return operation(), wait_seconds
        except Exception as exc:
            try:
                setattr(exc, "rate_limit_wait_seconds", wait_seconds)
            except Exception:
                pass
            raise
        finally:
            self._exit()


_RATE_LIMITERS: Dict[str, ProviderRateLimiter] = {}
_RATE_LIMITERS_LOCK = threading.Lock()


def reset_rate_limiters_for_tests() -> None:
    """Reset shared limiter state for deterministic tests."""
    with _RATE_LIMITERS_LOCK:
        _RATE_LIMITERS.clear()


def get_provider_rate_limiter(
    key: str,
    *,
    min_interval: float,
    max_concurrency: int,
) -> ProviderRateLimiter:
    with _RATE_LIMITERS_LOCK:
        limiter = _RATE_LIMITERS.get(key)
        if limiter is None:
            limiter = ProviderRateLimiter(
                min_interval=min_interval,
                max_concurrency=max_concurrency,
            )
            _RATE_LIMITERS[key] = limiter
        else:
            limiter.configure(min_interval=min_interval, max_concurrency=max_concurrency)
        return limiter


# ---------------------------------------------------------------------------
# Provider catalog
# ---------------------------------------------------------------------------

PRIVACY_LEVELS = {
    "local_only": "Local only",
    "direct_cloud": "Direct cloud provider",
    "router_third_party": "Router / third party",
    "custom_endpoint": "Custom endpoint",
}

FREE_TIER_BY_PROVIDER = {
    "OpenAI": False,
    "Anthropic (Claude)": False,
    "Google Gemini": True,
    "OpenRouter": "Varies",
    "DeepSeek": True,
    "Mistral": True,
    "Kimi (Moonshot)": True,
    "Grok (xAI)": False,
    "Ollama (Local)": True,
    "LM Studio": True,
    "vLLM": "Varies",
    "LocalAI": "Varies",
    "Custom OpenAI-Compatible": "Varies",
}


PROVIDER_CATALOG: Dict[str, Dict[str, Any]] = {
    "OpenAI": {
        "id": "openai",
        "display_name": "OpenAI",
        "adapter": "native_openai",
        "base_url": None,
        "show_base_url": False,
        "requires_api_key": True,
        "privacy_level": "direct_cloud",
        "website": "https://platform.openai.com",
        "default_model": "gpt-5.5",
        "recommended_models": [
            {"id": "gpt-5.5", "tier": "quality", "stability": "stable"},
            {"id": "gpt-5.4-mini", "tier": "balanced", "stability": "stable"},
            {"id": "gpt-5.4-nano", "tier": "low_cost", "stability": "stable"},
            {"id": "gpt-4o", "tier": "legacy_quality", "stability": "stable"},
            {"id": "gpt-4o-mini", "tier": "legacy_balanced", "stability": "stable"},
        ],
    },
    "Anthropic (Claude)": {
        "id": "anthropic",
        "display_name": "Anthropic Claude",
        "adapter": "native_anthropic",
        "base_url": None,
        "show_base_url": False,
        "requires_api_key": True,
        "privacy_level": "direct_cloud",
        "website": "https://console.anthropic.com",
        "default_model": "claude-sonnet-4-20250514",
        "recommended_models": [
            {"id": "claude-sonnet-4-20250514", "tier": "balanced", "stability": "stable"},
            {"id": "claude-opus-4-20250514", "tier": "quality", "stability": "stable"},
            {"id": "claude-3-7-sonnet-20250219", "tier": "legacy_quality", "stability": "stable"},
            {"id": "claude-3-5-haiku-20241022", "tier": "low_cost", "stability": "stable"},
        ],
        "model_discovery": {
            "type": "anthropic_models",
            "endpoint": "https://api.anthropic.com/v1/models",
        },
    },
    "Google Gemini": {
        "id": "google_gemini",
        "display_name": "Google Gemini",
        "adapter": "native_gemini",
        "base_url": None,
        "show_base_url": False,
        "requires_api_key": True,
        "privacy_level": "direct_cloud",
        "website": "https://aistudio.google.com",
        "default_model": "gemini-2.5-flash",
        "recommended_models": [
            {"id": "gemini-2.5-flash", "tier": "balanced", "stability": "stable"},
            {"id": "gemini-2.5-pro", "tier": "quality", "stability": "stable"},
            {"id": "gemini-2.0-flash", "tier": "fast", "stability": "stable"},
            {"id": "gemini-2.0-flash-lite", "tier": "low_cost", "stability": "stable"},
        ],
        "model_id_guidance": {
            "latest_alias_warning": "Latest aliases are convenient but reduce reproducibility.",
            "stability_detection": ["stable", "preview", "latest", "experimental"],
        },
        "model_discovery": {
            "type": "gemini_models",
            "endpoint": "https://generativelanguage.googleapis.com/v1beta/models",
        },
    },
    "OpenRouter": {
        "id": "openrouter",
        "display_name": "OpenRouter",
        "adapter": "openai_compatible",
        "base_url": "https://openrouter.ai/api/v1",
        "show_base_url": False,
        "requires_api_key": True,
        "privacy_level": "router_third_party",
        "website": "https://openrouter.ai",
        "default_model": "openai/gpt-5.5",
        "recommended_models": [
            {"id": "openai/gpt-5.5", "tier": "quality", "stability": "stable"},
            {"id": "openai/gpt-5.4-mini", "tier": "balanced", "stability": "stable"},
            {"id": "anthropic/claude-sonnet-4", "tier": "alternate_quality", "stability": "latest"},
        ],
        "model_discovery": {"type": "openrouter_models", "endpoint": "/models"},
        "privacy_note": "Paper text is sent through OpenRouter before reaching the selected model provider.",
    },
    "DeepSeek": {
        "id": "deepseek",
        "display_name": "DeepSeek",
        "adapter": "openai_compatible",
        "base_url": "https://api.deepseek.com/v1",
        "show_base_url": False,
        "requires_api_key": True,
        "privacy_level": "direct_cloud",
        "website": "https://platform.deepseek.com",
        "default_model": "deepseek-chat",
        "recommended_models": [
            {"id": "deepseek-chat", "tier": "balanced", "stability": "stable"},
            {"id": "deepseek-reasoner", "tier": "reasoning", "stability": "stable"},
            {"id": "deepseek-coder", "tier": "code", "stability": "stable"},
        ],
        "model_discovery": {"type": "openai_compatible_models", "endpoint": "/models"},
    },
    "Mistral": {
        "id": "mistral",
        "display_name": "Mistral",
        "adapter": "openai_compatible",
        "base_url": "https://api.mistral.ai/v1",
        "show_base_url": False,
        "requires_api_key": True,
        "privacy_level": "direct_cloud",
        "website": "https://console.mistral.ai",
        "default_model": "mistral-large-latest",
        "recommended_models": [
            {"id": "mistral-large-latest", "tier": "quality", "stability": "latest"},
            {"id": "mistral-small-latest", "tier": "balanced", "stability": "latest"},
            {"id": "open-mistral-nemo", "tier": "open", "stability": "stable"},
            {"id": "codestral-latest", "tier": "code", "stability": "latest"},
        ],
        "model_discovery": {"type": "openai_compatible_models", "endpoint": "/models"},
    },
    "Kimi (Moonshot)": {
        "id": "kimi_moonshot",
        "display_name": "Kimi / Moonshot",
        "adapter": "openai_compatible",
        "base_url": "https://api.moonshot.cn/v1",
        "show_base_url": False,
        "requires_api_key": True,
        "privacy_level": "direct_cloud",
        "website": "https://platform.moonshot.cn",
        "default_model": "moonshot-v1-auto",
        "recommended_models": [
            {"id": "moonshot-v1-auto", "tier": "balanced", "stability": "latest"},
            {"id": "moonshot-v1-8k", "tier": "small_context", "stability": "stable"},
            {"id": "moonshot-v1-32k", "tier": "medium_context", "stability": "stable"},
            {"id": "moonshot-v1-128k", "tier": "large_context", "stability": "stable"},
            {"id": "kimi-latest", "tier": "latest", "stability": "latest"},
        ],
        "model_discovery": {"type": "openai_compatible_models", "endpoint": "/models"},
    },
    "Grok (xAI)": {
        "id": "xai_grok",
        "display_name": "Grok (xAI)",
        "adapter": "openai_compatible",
        "base_url": "https://api.x.ai/v1",
        "show_base_url": False,
        "requires_api_key": True,
        "privacy_level": "direct_cloud",
        "website": "https://console.x.ai",
        "default_model": "grok-3-mini-fast",
        "recommended_models": [
            {"id": "grok-3", "tier": "quality", "stability": "stable"},
            {"id": "grok-3-fast", "tier": "quality_fast", "stability": "stable"},
            {"id": "grok-3-mini", "tier": "balanced", "stability": "stable"},
            {"id": "grok-3-mini-fast", "tier": "fast", "stability": "stable"},
        ],
        "model_discovery": {"type": "openai_compatible_models", "endpoint": "/models"},
    },
    "Ollama (Local)": {
        "id": "ollama",
        "display_name": "Ollama / Local",
        "adapter": "native_ollama",
        "base_url": "http://localhost:11434",
        "show_base_url": True,
        "requires_api_key": False,
        "privacy_level": "local_only",
        "website": "https://ollama.com",
        "default_model": "llama3.2",
        "recommended_models": [
            {"id": "llama3.2", "tier": "balanced", "stability": "local"},
            {"id": "llama3.1", "tier": "legacy_balanced", "stability": "local"},
            {"id": "mistral", "tier": "small", "stability": "local"},
            {"id": "gemma2", "tier": "small", "stability": "local"},
            {"id": "qwen2", "tier": "small", "stability": "local"},
        ],
        "model_discovery": {"type": "ollama_tags", "endpoint": "/api/tags"},
    },
    "LM Studio": {
        "id": "lm_studio",
        "display_name": "LM Studio",
        "adapter": "openai_compatible",
        "base_url": "http://localhost:1234/v1",
        "show_base_url": True,
        "requires_api_key": "Varies",
        "privacy_level": "local_only",
        "website": "https://lmstudio.ai",
        "default_model": "local-model",
        "recommended_models": [{"id": "local-model", "tier": "custom", "stability": "local"}],
        "model_discovery": {"type": "openai_compatible_models", "endpoint": "/models"},
    },
    "vLLM": {
        "id": "vllm",
        "display_name": "vLLM",
        "adapter": "openai_compatible",
        "base_url": "http://localhost:8000/v1",
        "show_base_url": True,
        "requires_api_key": "Varies",
        "privacy_level": "custom_endpoint",
        "website": "https://docs.vllm.ai",
        "default_model": "local-model",
        "recommended_models": [{"id": "local-model", "tier": "custom", "stability": "custom"}],
        "model_discovery": {"type": "openai_compatible_models", "endpoint": "/models"},
    },
    "LocalAI": {
        "id": "localai",
        "display_name": "LocalAI",
        "adapter": "openai_compatible",
        "base_url": "http://localhost:8080/v1",
        "show_base_url": True,
        "requires_api_key": "Varies",
        "privacy_level": "custom_endpoint",
        "website": "https://localai.io",
        "default_model": "local-model",
        "recommended_models": [{"id": "local-model", "tier": "custom", "stability": "custom"}],
        "model_discovery": {"type": "openai_compatible_models", "endpoint": "/models"},
    },
    "Custom OpenAI-Compatible": {
        "id": "custom_openai_compatible",
        "display_name": "Custom OpenAI-Compatible",
        "adapter": "openai_compatible",
        "base_url": None,
        "show_base_url": True,
        "requires_api_key": "Varies",
        "privacy_level": "custom_endpoint",
        "website": "Custom",
        "default_model": "gpt-5.5",
        "recommended_models": [
            {"id": "gpt-5.5", "tier": "quality", "stability": "custom"},
            {"id": "local-model", "tier": "local", "stability": "custom"},
        ],
        "model_discovery": {"type": "openai_compatible_models", "endpoint": "/models"},
    },
}


def _copy_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    return copy.deepcopy(profile)


def _model_ids(recommended_models: List[Any]) -> List[str]:
    ids: List[str] = []
    for item in recommended_models:
        model_id = item.get("id") if isinstance(item, dict) else item
        if model_id and model_id not in ids:
            ids.append(str(model_id))
    return ids


def _join_url(base_url: str, endpoint: str) -> str:
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        return endpoint
    return f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"


def _normalize_proxy_env_urls() -> None:
    """Google's SDK expects proxy env vars to include a URI scheme."""
    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        value = (os.environ.get(key) or "").strip()
        if not value:
            continue
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value):
            continue
        os.environ[key] = f"http://{value}"


def default_rate_limit_for_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Conservative provider/profile defaults; callers may override them."""
    privacy_level = profile.get("privacy_level")
    if privacy_level == "local_only":
        return {"min_interval": 0.1, "max_concurrency": 4}
    if privacy_level == "router_third_party":
        return {"min_interval": 1.0, "max_concurrency": 1}
    if privacy_level == "custom_endpoint":
        return {"min_interval": 0.75, "max_concurrency": 2}
    return {"min_interval": 0.75, "max_concurrency": 1}


def _status_code_from_error(error: Exception) -> Optional[int]:
    for attr in ("status_code", "status"):
        value = getattr(error, attr, None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass

    response = getattr(error, "response", None)
    value = getattr(response, "status_code", None)
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    return None


def categorize_llm_error(error: Exception) -> str:
    if isinstance(error, NotImplementedError):
        return "unsupported_feature"

    status_code = _status_code_from_error(error)
    message = str(error).lower()

    if status_code == 429 or "429" in message or "rate limit" in message or "too many requests" in message:
        return "rate_limit"
    if isinstance(error, (TimeoutError, requests.exceptions.Timeout)) or "timeout" in message or "timed out" in message:
        return "timeout"
    if isinstance(error, requests.exceptions.ConnectionError):
        return "connection_error"
    if status_code in {500, 502, 503, 504}:
        return "server_error"
    if any(term in message for term in ("connection reset", "temporarily unavailable", "temporary failure")):
        return "temporary_network"
    if status_code in {401, 403} or any(
        term in message
        for term in ("invalid api key", "unauthorized", "authentication", "permission denied", "forbidden")
    ):
        return "auth_error"
    if status_code == 404 or any(
        term in message
        for term in ("unsupported model", "model not found", "model_not_found", "unknown model")
    ):
        return "unsupported_model"
    if status_code == 400 or any(term in message for term in ("bad request", "invalid request", "malformed")):
        return "malformed_request"
    return "unknown"


def is_retryable_llm_error(error: Exception) -> bool:
    return categorize_llm_error(error) in RETRYABLE_ERROR_CATEGORIES


def classify_model_stability(model_id: str) -> str:
    """Classify model IDs for reproducibility warnings, especially Gemini."""
    value = (model_id or "").lower()
    if "experimental" in value or "-exp" in value or value.startswith("exp-"):
        return "experimental"
    if "preview" in value:
        return "preview"
    if "latest" in value:
        return "latest"
    return "stable"


def model_reproducibility_warning(model_id: str) -> str:
    stability = classify_model_stability(model_id)
    if stability in {"preview", "latest", "experimental"}:
        return (
            f"{model_id} is a {stability} model or alias; use a stable, dated "
            "model ID for reproducible research when available."
        )
    return ""


# ---------------------------------------------------------------------------
# User-defined custom models persistence
# ---------------------------------------------------------------------------

_CUSTOM_MODELS_FILE = Path(__file__).parent / "custom_models.json"


def load_custom_models() -> Dict[str, List[str]]:
    """Load user-added models per provider from disk."""
    if _CUSTOM_MODELS_FILE.exists():
        try:
            with open(_CUSTOM_MODELS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def save_custom_models(custom: Dict[str, List[str]]) -> None:
    """Persist user-added model IDs. This file does not contain API keys."""
    with open(_CUSTOM_MODELS_FILE, "w", encoding="utf-8") as f:
        json.dump(custom, f, indent=2)


def add_custom_model(provider: str, model_name: str) -> None:
    """Add a single user-defined model for a provider."""
    custom = load_custom_models()
    if provider not in custom:
        custom[provider] = []
    if model_name not in custom[provider]:
        custom[provider].append(model_name)
        save_custom_models(custom)


def remove_custom_model(provider: str, model_name: str) -> None:
    """Remove a user-defined model for a provider."""
    custom = load_custom_models()
    if provider in custom and model_name in custom[provider]:
        custom[provider].remove(model_name)
        if not custom[provider]:
            del custom[provider]
        save_custom_models(custom)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class LLMProvider(ABC):
    def __init__(self, api_key: str, model: str, **kwargs):
        self.api_key = api_key
        self.model = model
        self.config = kwargs

    @abstractmethod
    def chat_completion_with_tokens(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.05,
        max_tokens: int = 4000,
        **kwargs,
    ) -> Tuple[str, int]:
        """Return (response_text, total_tokens_used)."""
        pass

    def chat_completion(self, messages, temperature=0.05, max_tokens=4000, **kwargs) -> str:
        """Legacy shim kept for existing code."""
        text, _ = self.chat_completion_with_tokens(messages, temperature, max_tokens, **kwargs)
        return text

    @abstractmethod
    def get_available_models(self) -> List[str]:
        pass


# ---------------------------------------------------------------------------
# Native providers
# ---------------------------------------------------------------------------

class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-5.5", **kwargs):
        super().__init__(api_key, model, **kwargs)
        try:
            import openai
            self.client = openai.OpenAI(api_key=api_key)
        except ImportError:
            raise ImportError("Run: pip install openai")

    def chat_completion_with_tokens(self, messages, temperature=0.05, max_tokens=4000, **kwargs):
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            tokens = resp.usage.total_tokens if resp.usage else 0
            return resp.choices[0].message.content, tokens
        except Exception as e:
            logger.error(f"OpenAI error: {e}")
            raise

    def get_available_models(self) -> List[str]:
        return _model_ids(PROVIDER_CATALOG["OpenAI"]["recommended_models"])


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514", **kwargs):
        super().__init__(api_key, model, **kwargs)
        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            raise ImportError("Run: pip install anthropic")

    def chat_completion_with_tokens(self, messages, temperature=0.05, max_tokens=4000, **kwargs):
        try:
            system_msg = ""
            user_msgs = []
            for m in messages:
                if m["role"] == "system":
                    system_msg = m["content"]
                else:
                    user_msgs.append(m)

            resp = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_msg,
                messages=user_msgs,
            )
            tokens = (resp.usage.input_tokens + resp.usage.output_tokens) if resp.usage else 0
            return resp.content[0].text, tokens
        except Exception as e:
            logger.error(f"Anthropic error: {e}")
            raise

    def get_available_models(self) -> List[str]:
        return _model_ids(PROVIDER_CATALOG["Anthropic (Claude)"]["recommended_models"])


class GeminiProvider(LLMProvider):
    FINISH_REASON_LABELS = {
        0: "FINISH_REASON_UNSPECIFIED",
        1: "STOP",
        2: "MAX_TOKENS",
        3: "SAFETY",
        4: "RECITATION",
        5: "OTHER",
        6: "BLOCKLIST",
        7: "PROHIBITED_CONTENT",
        8: "SPII",
        9: "MALFORMED_FUNCTION_CALL",
        10: "IMAGE_SAFETY",
    }

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", **kwargs):
        super().__init__(api_key, model, **kwargs)
        _normalize_proxy_env_urls()
        try:
            from google import genai
            from google.genai import types as genai_types

            self.genai = genai
            self.genai_types = genai_types
            self._client = genai.Client(api_key=api_key)
            self._sdk = "google-genai"
        except ImportError:
            try:
                import google.generativeai as genai

                genai.configure(api_key=api_key)
                self.genai = genai
                self.genai_types = None
                self._client = genai.GenerativeModel(model)
                self._sdk = "google-generativeai"
            except ImportError as exc:
                raise ImportError("Run: pip install google-genai") from exc

    @staticmethod
    def _attr(obj: Any, name: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    @classmethod
    def _finish_reason(cls, candidate: Any) -> str:
        reason = cls._attr(candidate, "finish_reason")
        if reason is None:
            reason = cls._attr(candidate, "finishReason")
        if reason is None:
            return "unknown"
        if hasattr(reason, "name"):
            return str(reason.name)
        try:
            numeric = int(reason)
            label = cls.FINISH_REASON_LABELS.get(numeric)
            return f"{label} ({numeric})" if label else str(numeric)
        except (TypeError, ValueError):
            return str(reason)

    @classmethod
    def _usage_tokens(cls, response: Any) -> int:
        usage = cls._attr(response, "usage_metadata") or cls._attr(response, "usageMetadata")
        if not usage:
            return 0
        for name in ("total_token_count", "totalTokenCount"):
            value = cls._attr(usage, name)
            if value is not None:
                return int(value)
        input_tokens = cls._attr(usage, "prompt_token_count", cls._attr(usage, "promptTokenCount", 0)) or 0
        output_tokens = cls._attr(usage, "candidates_token_count", cls._attr(usage, "candidatesTokenCount", 0)) or 0
        return int(input_tokens) + int(output_tokens)

    @classmethod
    def _response_text(cls, response: Any) -> str:
        pieces: List[str] = []
        candidates = cls._attr(response, "candidates", []) or []
        finish_reasons = []

        for candidate in candidates:
            finish_reasons.append(cls._finish_reason(candidate))
            content = cls._attr(candidate, "content")
            parts = cls._attr(content, "parts", []) if content is not None else []
            for part in parts or []:
                text = cls._attr(part, "text")
                if text:
                    pieces.append(str(text))

        if pieces:
            return "\n".join(pieces)

        text_error = ""
        try:
            quick_text = cls._attr(response, "text")
            if quick_text:
                return str(quick_text)
        except Exception as exc:
            text_error = str(exc)

        reason = ", ".join(r for r in finish_reasons if r) or "unknown"
        guidance = "Gemini returned no text parts"
        if "MAX_TOKENS" in reason:
            guidance += "; increase Gemini max output tokens or use a model/configuration with less internal reasoning"
        elif "SAFETY" in reason or "PROHIBITED" in reason:
            guidance += "; review the prompt and Gemini safety response"
        detail = f"finish_reason={reason}"
        if text_error:
            detail += f"; text_accessor_error={text_error}"
        raise RuntimeError(f"{guidance} ({detail}).")

    def chat_completion_with_tokens(self, messages, temperature=0.05, max_tokens=4000, **kwargs):
        try:
            parts = []
            for m in messages:
                role = m["role"].upper()
                content = m["content"]
                if role == "SYSTEM":
                    parts.append(f"[SYSTEM]: {content}")
                elif role == "USER":
                    parts.append(content)
                else:
                    parts.append(f"[ASSISTANT]: {content}")
            prompt = "\n\n".join(parts)

            # Gemini 2.5 models may spend part of the output budget internally.
            # Tiny budgets, such as connection-test prompts, can otherwise
            # finish with MAX_TOKENS before any visible text part is returned.
            effective_max_tokens = max(int(max_tokens or 0), 1024)
            if self._sdk == "google-genai":
                cfg = self.genai_types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=effective_max_tokens,
                )
                resp = self._client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=cfg,
                )
            else:
                cfg = self.genai.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=effective_max_tokens,
                )
                resp = self._client.generate_content(prompt, generation_config=cfg)
            return self._response_text(resp), self._usage_tokens(resp)
        except Exception as e:
            logger.error(f"Gemini error: {e}")
            raise

    def get_available_models(self) -> List[str]:
        return _model_ids(PROVIDER_CATALOG["Google Gemini"]["recommended_models"])


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        api_key: str = "",
        model: str = "llama3.2",
        base_url: str = "http://localhost:11434",
        **kwargs,
    ):
        super().__init__(api_key, model, **kwargs)
        self.base_url = (base_url or "http://localhost:11434").rstrip("/")
        self.timeout = kwargs.get("timeout", 180)

    def chat_completion_with_tokens(self, messages, temperature=0.05, max_tokens=4000, **kwargs):
        """Use Ollama's local /api/chat endpoint."""
        try:
            data = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            }
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json=data,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            body = resp.json()
            text = body.get("message", {}).get("content", "")
            tokens = body.get("eval_count", 0) + body.get("prompt_eval_count", 0)
            return text, tokens
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            raise

    def get_available_models(self) -> List[str]:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=10)
            resp.raise_for_status()
            discovered = LLMManager.parse_discovered_models("ollama_tags", resp.json())
            return discovered or _model_ids(PROVIDER_CATALOG["Ollama (Local)"]["recommended_models"])
        except Exception:
            return _model_ids(PROVIDER_CATALOG["Ollama (Local)"]["recommended_models"])


# ---------------------------------------------------------------------------
# Shared OpenAI-compatible adapter
# ---------------------------------------------------------------------------

class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: Optional[str] = None,
        profile: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):
        profile = profile or {}
        super().__init__(api_key, model, **kwargs)
        self.profile = profile
        self.display_name = profile.get("display_name", "OpenAI-compatible endpoint")
        resolved_base_url = base_url or profile.get("base_url")
        if not resolved_base_url:
            raise ValueError(f"Base URL is required for {self.display_name}.")
        self.base_url = resolved_base_url.rstrip("/")
        self.timeout = kwargs.get("timeout", profile.get("timeout", 90))
        self.extra_headers = dict(profile.get("extra_headers", {}))
        self.extra_headers.update(kwargs.get("extra_headers", {}) or {})

    def chat_completion_with_tokens(self, messages, temperature=0.05, max_tokens=4000, **kwargs):
        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            headers.update(self.extra_headers)

            data = dict(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            data.update(kwargs)
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=data,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            body = resp.json()
            tokens = body.get("usage", {}).get("total_tokens", 0)
            return body["choices"][0]["message"]["content"], tokens
        except Exception as e:
            logger.error(f"{self.display_name} error: {e}")
            raise

    def get_available_models(self) -> List[str]:
        return _model_ids(self.profile.get("recommended_models", [])) or [self.model]


# Compatibility aliases for external imports. The duplicated REST
# implementations were removed; these names now use the shared adapter.
GenericOpenAIProvider = OpenAICompatibleProvider


def _profile_provider(profile_name: str):
    profile = PROVIDER_CATALOG[profile_name]

    def factory(api_key: str, model: Optional[str] = None, **kwargs) -> OpenAICompatibleProvider:
        selected_model = model or profile["default_model"]
        base_url = kwargs.pop("base_url", None) or profile.get("base_url")
        return OpenAICompatibleProvider(
            api_key,
            selected_model,
            base_url=base_url,
            profile=_copy_profile(profile),
            **kwargs,
        )

    return factory


DeepSeekProvider = _profile_provider("DeepSeek")
MistralProvider = _profile_provider("Mistral")
KimiProvider = _profile_provider("Kimi (Moonshot)")
GrokProvider = _profile_provider("Grok (xAI)")


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class LLMManager:
    PROVIDERS: Dict[str, Any] = {
        "OpenAI": OpenAIProvider,
        "Anthropic (Claude)": AnthropicProvider,
        "Google Gemini": GeminiProvider,
        "OpenRouter": _profile_provider("OpenRouter"),
        "DeepSeek": DeepSeekProvider,
        "Mistral": MistralProvider,
        "Kimi (Moonshot)": KimiProvider,
        "Grok (xAI)": GrokProvider,
        "Ollama (Local)": OllamaProvider,
        "LM Studio": _profile_provider("LM Studio"),
        "vLLM": _profile_provider("vLLM"),
        "LocalAI": _profile_provider("LocalAI"),
        "Custom OpenAI-Compatible": GenericOpenAIProvider,
    }

    def __init__(self, provider_name: str, api_key: str, model: str, **kwargs):
        rate_limit_config = kwargs.pop("rate_limit_config", {}) or {}
        if provider_name not in PROVIDER_CATALOG:
            supported = ", ".join(PROVIDER_CATALOG)
            raise ValueError(
                f"Unknown provider: {provider_name}. Supported providers: {supported}. "
                "If your service is OpenAI-compatible, choose Custom OpenAI-Compatible "
                "and enter its Base URL."
            )

        self.provider_name = provider_name
        self.profile = self.get_provider_profile(provider_name)
        selected_model = model or self.profile["default_model"]
        adapter = self.profile["adapter"]

        if adapter == "native_openai":
            self.provider = OpenAIProvider(api_key, selected_model, **kwargs)
        elif adapter == "native_anthropic":
            self.provider = AnthropicProvider(api_key, selected_model, **kwargs)
        elif adapter == "native_gemini":
            self.provider = GeminiProvider(api_key, selected_model, **kwargs)
        elif adapter == "native_ollama":
            base_url = kwargs.pop("base_url", None) or self.profile.get("base_url")
            self.provider = OllamaProvider(api_key, selected_model, base_url=base_url, **kwargs)
        elif adapter == "openai_compatible":
            base_url = kwargs.pop("base_url", None) or self.profile.get("base_url")
            self.provider = OpenAICompatibleProvider(
                api_key,
                selected_model,
                base_url=base_url,
                profile=self.profile,
                **kwargs,
            )
        else:
            raise ValueError(f"Unsupported adapter type for {provider_name}: {adapter}")

        defaults = default_rate_limit_for_profile(self.profile)
        defaults.update({k: v for k, v in rate_limit_config.items() if v is not None})
        self.rate_limit_min_interval = float(defaults.get("min_interval", 0.75))
        self.rate_limit_max_concurrency = int(defaults.get("max_concurrency", 1))
        self.rate_limit_key = self._build_rate_limit_key()
        self.rate_limiter = get_provider_rate_limiter(
            self.rate_limit_key,
            min_interval=self.rate_limit_min_interval,
            max_concurrency=self.rate_limit_max_concurrency,
        )
        self.last_call_metadata: Dict[str, Any] = {}
        self._thread_local = threading.local()

    def _build_rate_limit_key(self) -> str:
        profile_id = self.profile.get("id") or self.provider_name.lower().replace(" ", "_")
        base_url = getattr(self.provider, "base_url", None) or self.profile.get("base_url") or ""
        return f"{profile_id}|{base_url}".lower()

    @staticmethod
    def _pop_retry_options(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "max_attempts": max(1, int(kwargs.pop("retry_max_attempts", 3) or 1)),
            "retry_delay": max(0.0, float(kwargs.pop("retry_delay", 0.5) or 0.0)),
            "retry_jitter": max(0.0, float(kwargs.pop("retry_jitter", 0.1) or 0.0)),
        }

    @staticmethod
    def _backoff_delay(category: str, retry_delay: float, retry_jitter: float, retry_count: int) -> float:
        base = retry_delay
        delay = base * (2 ** max(0, retry_count - 1))
        if delay > 0 and retry_jitter > 0:
            delay += random.uniform(0.0, delay * retry_jitter)
        return delay

    def _set_last_call_metadata(self, metadata: Dict[str, Any]) -> None:
        self.last_call_metadata = dict(metadata)
        self._thread_local.last_call_metadata = dict(metadata)

    def _execute_with_retry(
        self,
        operation,
        *,
        max_attempts: int,
        retry_delay: float,
        retry_jitter: float,
    ):
        total_rate_limit_wait = 0.0
        total_backoff_wait = 0.0
        retry_count = 0
        last_category = None

        for attempt_index in range(max_attempts):
            try:
                result, wait_seconds = self.rate_limiter.run(operation)
                total_rate_limit_wait += wait_seconds
                metadata = {
                    "provider": self.provider_name,
                    "provider_profile": self.profile.get("id"),
                    "model": self.provider.model,
                    "rate_limit_key": self.rate_limit_key,
                    "rate_limit_wait_seconds": round(total_rate_limit_wait, 6),
                    "backoff_wait_seconds": round(total_backoff_wait, 6),
                    "retry_count": retry_count,
                    "attempt_count": attempt_index + 1,
                    "final_status": "success",
                    "error_category": last_category,
                }
                self._set_last_call_metadata(metadata)
                return result
            except Exception as exc:
                metadata = getattr(exc, "metadata", None)
                if isinstance(metadata, dict):
                    total_rate_limit_wait += float(metadata.get("rate_limit_wait_seconds", 0.0) or 0.0)
                elif hasattr(exc, "rate_limit_wait_seconds"):
                    total_rate_limit_wait += float(getattr(exc, "rate_limit_wait_seconds", 0.0) or 0.0)

                category = categorize_llm_error(exc)
                last_category = category
                should_retry = category in RETRYABLE_ERROR_CATEGORIES and attempt_index < max_attempts - 1
                if not should_retry:
                    final_status = "failed_retry_exhausted" if category in RETRYABLE_ERROR_CATEGORIES else "failed_permanent"
                    metadata = {
                        "provider": self.provider_name,
                        "provider_profile": self.profile.get("id"),
                        "model": self.provider.model,
                        "rate_limit_key": self.rate_limit_key,
                        "rate_limit_wait_seconds": round(total_rate_limit_wait, 6),
                        "backoff_wait_seconds": round(total_backoff_wait, 6),
                        "retry_count": retry_count,
                        "attempt_count": attempt_index + 1,
                        "final_status": final_status,
                        "error_category": category,
                    }
                    self._set_last_call_metadata(metadata)
                    if final_status == "failed_retry_exhausted":
                        message = (
                            f"LLM call failed after {attempt_index + 1} attempts "
                            f"({category}): {exc}"
                        )
                    else:
                        message = f"LLM call failed without retry ({category}): {exc}"
                    raise LLMCallError(
                        message,
                        category=category,
                        retry_count=retry_count,
                        original_error=exc,
                        metadata=self.get_last_call_metadata(),
                    ) from exc

                retry_count += 1
                delay = self._backoff_delay(category, retry_delay, retry_jitter, retry_count)
                total_backoff_wait += delay
                if delay > 0:
                    time.sleep(delay)

        raise RuntimeError("LLM retry loop exited unexpectedly")

    def get_last_call_metadata(self) -> Dict[str, Any]:
        local_metadata = getattr(self._thread_local, "last_call_metadata", None)
        return dict(local_metadata or self.last_call_metadata)

    def chat_completion_with_tokens(self, messages, **kwargs) -> Tuple[str, int]:
        retry_options = self._pop_retry_options(kwargs)
        return self._execute_with_retry(
            lambda: self.provider.chat_completion_with_tokens(messages, **kwargs),
            **retry_options,
        )

    def chat_completion(self, messages, **kwargs) -> str:
        text, _ = self.chat_completion_with_tokens(messages, **kwargs)
        return text

    def chat_completion_structured(
        self,
        messages: list,
        response_model: type,
        temperature: float = 0.05,
        max_tokens: int = 4000,
        **kwargs,
    ) -> Tuple[Any, int]:
        """
        Best-effort schema-enforced output via instructor.

        Structured calls may return token count 0 when the wrapped provider
        client does not expose usage in the parsed response.
        """
        try:
            import instructor
        except ImportError:
            raise ImportError(
                "Run: pip install instructor>=1.2.0 "
                "(required for structured output / anti-hallucination mode)"
            )

        pname = self.provider_name
        adapter = self.profile["adapter"]

        retry_options = self._pop_retry_options(kwargs)

        def operation():
            if adapter in ("native_openai", "openai_compatible", "native_ollama"):
                import openai
                raw_client = openai.OpenAI(
                    api_key=self.provider.api_key or "ollama",
                    base_url=getattr(self.provider, "base_url", None),
                )
                client = instructor.from_openai(raw_client)
                resp = client.chat.completions.create(
                    model=self.provider.model,
                    messages=messages,
                    response_model=response_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    max_retries=1,
                )
                return resp, 0

            if adapter == "native_anthropic":
                import anthropic
                raw_client = anthropic.Anthropic(api_key=self.provider.api_key)
                client = instructor.from_anthropic(raw_client)
                system_content = next(
                    (m["content"] for m in messages if m["role"] == "system"), ""
                )
                user_msgs = [m for m in messages if m["role"] != "system"]
                resp = client.messages.create(
                    model=self.provider.model,
                    max_tokens=max_tokens,
                    system=system_content,
                    messages=user_msgs,
                    response_model=response_model,
                    max_retries=1,
                )
                return resp, 0

            raise NotImplementedError(
                f"Structured output not natively supported for {pname}. "
                "Falling back to JSON parse."
            )

        try:
            return self._execute_with_retry(operation, **retry_options)
        except instructor.exceptions.InstructorRetryException as exc:
            raise RuntimeError(f"instructor structured output failed: {exc}") from exc

    @classmethod
    def get_supported_providers(cls) -> List[str]:
        return list(PROVIDER_CATALOG.keys())

    @classmethod
    def get_provider_profile(cls, provider_name: str) -> Dict[str, Any]:
        if provider_name not in PROVIDER_CATALOG:
            supported = ", ".join(PROVIDER_CATALOG)
            raise ValueError(f"Unknown provider: {provider_name}. Supported providers: {supported}.")
        return _copy_profile(PROVIDER_CATALOG[provider_name])

    @classmethod
    def get_provider_catalog(cls) -> Dict[str, Dict[str, Any]]:
        return {name: _copy_profile(profile) for name, profile in PROVIDER_CATALOG.items()}

    @classmethod
    def get_default_models(cls) -> Dict[str, str]:
        return {name: profile["default_model"] for name, profile in PROVIDER_CATALOG.items()}

    @classmethod
    def get_provider_info(cls) -> Dict[str, Dict[str, Any]]:
        info: Dict[str, Dict[str, Any]] = {}
        for name, profile in PROVIDER_CATALOG.items():
            item = _copy_profile(profile)
            item["privacy_label"] = PRIVACY_LEVELS[item["privacy_level"]]
            item["free_tier"] = item.get("free_tier", FREE_TIER_BY_PROVIDER.get(name, False))
            item["recommended_model_ids"] = _model_ids(item.get("recommended_models", []))
            info[name] = item
        return info

    @classmethod
    def needs_base_url(cls, provider_name: str) -> bool:
        profile = PROVIDER_CATALOG.get(provider_name, {})
        return bool(profile.get("show_base_url"))

    @classmethod
    def get_models_for_provider(cls, provider_name: str) -> List[str]:
        """Return recommended + user-added model IDs. This is not validation."""
        profile = PROVIDER_CATALOG.get(provider_name)
        recommended = _model_ids(profile.get("recommended_models", [])) if profile else []
        custom = load_custom_models().get(provider_name, [])
        combined = list(recommended)
        for model in custom:
            if model not in combined:
                combined.append(model)
        return combined

    @staticmethod
    def parse_discovered_models(discovery_type: str, payload: Any) -> List[str]:
        if not payload:
            return []

        if isinstance(payload, list):
            items = payload
        elif discovery_type == "ollama_tags":
            items = payload.get("models", [])
        elif discovery_type == "gemini_models":
            items = payload.get("models", [])
        else:
            items = payload.get("data", payload.get("models", []))

        models: List[str] = []
        for item in items:
            model_id = item if isinstance(item, str) else item.get("id") or item.get("name")
            if not model_id:
                continue
            model_id = str(model_id)
            if discovery_type == "gemini_models":
                methods = item.get("supportedGenerationMethods", []) if isinstance(item, dict) else []
                if methods and "generateContent" not in methods:
                    continue
                if model_id.startswith("models/"):
                    model_id = model_id.split("/", 1)[1]
            if model_id not in models:
                models.append(model_id)
        return models

    @classmethod
    def discover_models(
        cls,
        provider_name: str,
        api_key: str = "",
        base_url: Optional[str] = None,
        timeout: int = 10,
    ) -> List[str]:
        """
        Explicit model discovery. This is never called during startup; UIs should
        call it only from an explicit refresh action.
        """
        profile = cls.get_provider_profile(provider_name)
        discovery = profile.get("model_discovery")
        if not discovery:
            return cls.get_models_for_provider(provider_name)

        discovery_type = discovery["type"]
        endpoint = discovery["endpoint"]
        headers: Dict[str, str] = {}
        params: Dict[str, str] = {}

        if discovery_type == "ollama_tags":
            resolved_base = base_url or profile.get("base_url") or "http://localhost:11434"
            url = _join_url(resolved_base, endpoint)
        elif discovery_type == "anthropic_models":
            url = endpoint
            if api_key:
                headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
        elif discovery_type == "gemini_models":
            url = endpoint
            if api_key:
                params["key"] = api_key
        else:
            resolved_base = base_url or profile.get("base_url")
            if not resolved_base:
                raise ValueError(f"Base URL is required to discover models for {provider_name}.")
            url = _join_url(resolved_base, endpoint)
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

        request_kwargs: Dict[str, Any] = {"timeout": timeout}
        if headers:
            request_kwargs["headers"] = headers
        if params:
            request_kwargs["params"] = params
        resp = requests.get(url, **request_kwargs)
        resp.raise_for_status()
        return cls.parse_discovered_models(discovery_type, resp.json())


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def test_provider_connection(provider_name: str, api_key: str, model: str, **kwargs) -> Tuple[bool, str]:
    """Returns (success, message)."""
    try:
        mgr = LLMManager(provider_name, api_key, model, **kwargs)
        msgs = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Reply with exactly: Connection OK"},
        ]
        text, tokens = mgr.chat_completion_with_tokens(msgs, max_tokens=20)
        ok = bool(text and len(text.strip()) > 0)
        return ok, f"Tokens used: {tokens}" if ok else "Empty response"
    except Exception as e:
        return False, str(e)


def get_install_instructions() -> Dict[str, str]:
    return {
        "OpenAI": "pip install openai",
        "Anthropic (Claude)": "pip install anthropic",
        "Google Gemini": "pip install google-genai",
        "OpenRouter": "Uses the OpenAI-compatible adapter; no extra package",
        "DeepSeek": "Uses the OpenAI-compatible adapter; no extra package",
        "Mistral": "Uses the OpenAI-compatible adapter; no extra package",
        "Kimi (Moonshot)": "Uses the OpenAI-compatible adapter; no extra package",
        "Grok (xAI)": "Uses the OpenAI-compatible adapter; no extra package",
        "Ollama (Local)": "Install from https://ollama.com then run: ollama serve",
        "LM Studio": "Run LM Studio's local OpenAI-compatible server",
        "vLLM": "Run vLLM with its OpenAI-compatible server enabled",
        "LocalAI": "Run LocalAI with its OpenAI-compatible server enabled",
        "Custom OpenAI-Compatible": "No extra package; enter the endpoint Base URL",
    }


if __name__ == "__main__":
    for name, info in LLMManager.get_provider_info().items():
        print(
            f"{name}: API key required={info['requires_api_key']} "
            f"Privacy={info['privacy_label']} {info['website']}"
        )
