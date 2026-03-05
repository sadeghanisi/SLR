"""
LLM Interface — Universal AI Provider Support
Supports OpenAI, Anthropic Claude, DeepSeek, Mistral, Google Gemini,
Kimi (Moonshot), Grok (xAI), Ollama (local), and any OpenAI-compatible endpoint.

All providers implement chat_completion_with_tokens() which returns
(response_text: str, tokens_used: int) so cost tracking works everywhere.
"""

__version__ = "3.3.0"

import json
import time
import requests
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Tuple
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# User-defined custom models persistence
# ─────────────────────────────────────────────────────────────────────────────

_CUSTOM_MODELS_FILE = Path(__file__).parent / "custom_models.json"

def load_custom_models() -> Dict[str, List[str]]:
    """Load user-added models per provider from disk.
    Returns dict like {"OpenAI": ["my-fine-tune"], "Kimi (Moonshot)": ["moonshot-v1-128k"]}.
    """
    if _CUSTOM_MODELS_FILE.exists():
        try:
            with open(_CUSTOM_MODELS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def save_custom_models(custom: Dict[str, List[str]]) -> None:
    """Persist user-added models to disk."""
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


# ─────────────────────────────────────────────────────────────────────────────
# Abstract base
# ─────────────────────────────────────────────────────────────────────────────

class LLMProvider(ABC):

    def __init__(self, api_key: str, model: str, **kwargs):
        self.api_key = api_key
        self.model   = model
        self.config  = kwargs

    @abstractmethod
    def chat_completion_with_tokens(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.05,
        max_tokens:  int   = 4000,
        **kwargs,
    ) -> Tuple[str, int]:
        """Return (response_text, total_tokens_used)."""
        pass

    # Legacy shim — kept so any existing code calling chat_completion() still works
    def chat_completion(self, messages, temperature=0.05, max_tokens=4000, **kwargs) -> str:
        text, _ = self.chat_completion_with_tokens(messages, temperature, max_tokens, **kwargs)
        return text

    @abstractmethod
    def get_available_models(self) -> List[str]:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI
# ─────────────────────────────────────────────────────────────────────────────

class OpenAIProvider(LLMProvider):

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", **kwargs):
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
        return [
            # GPT-4o family
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4o-2024-11-20",
            "gpt-4o-audio-preview",
            "gpt-4o-mini-audio-preview",
            # GPT-4.1 family
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            # o-series reasoning
            "o3",
            "o3-mini",
            "o4-mini",
            "o1",
            "o1-pro",
            "o1-mini",
            "o1-preview",
            # Legacy
            "gpt-4-turbo",
            "gpt-4",
            "gpt-3.5-turbo",
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Anthropic Claude
# ─────────────────────────────────────────────────────────────────────────────

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
            user_msgs  = []
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
        return [
            # Claude 4 family
            "claude-sonnet-4-20250514",
            "claude-opus-4-20250514",
            # Claude 3.7
            "claude-3-7-sonnet-20250219",
            # Claude 3.5 family
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            # Claude 3 family
            "claude-3-opus-20240229",
            "claude-3-haiku-20240307",
        ]


# ─────────────────────────────────────────────────────────────────────────────
# DeepSeek
# ─────────────────────────────────────────────────────────────────────────────

class DeepSeekProvider(LLMProvider):

    def __init__(self, api_key: str, model: str = "deepseek-chat", **kwargs):
        super().__init__(api_key, model, **kwargs)
        self.base_url = kwargs.get("base_url", "https://api.deepseek.com/v1")

    def chat_completion_with_tokens(self, messages, temperature=0.05, max_tokens=4000, **kwargs):
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type":  "application/json",
            }
            data = dict(model=self.model, messages=messages,
                        temperature=temperature, max_tokens=max_tokens)
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=data, timeout=90,
            )
            resp.raise_for_status()
            body   = resp.json()
            tokens = body.get("usage", {}).get("total_tokens", 0)
            return body["choices"][0]["message"]["content"], tokens
        except Exception as e:
            logger.error(f"DeepSeek error: {e}")
            raise

    def get_available_models(self) -> List[str]:
        return [
            "deepseek-chat",
            "deepseek-reasoner",
            "deepseek-coder",
            "deepseek-prover-v2-671b",
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Mistral
# ─────────────────────────────────────────────────────────────────────────────

class MistralProvider(LLMProvider):

    def __init__(self, api_key: str, model: str = "mistral-large-latest", **kwargs):
        super().__init__(api_key, model, **kwargs)
        try:
            from mistralai import Mistral
            self.client = Mistral(api_key=api_key)
        except ImportError:
            raise ImportError("Run: pip install mistralai")

    def chat_completion_with_tokens(self, messages, temperature=0.05, max_tokens=4000, **kwargs):
        try:
            resp = self.client.chat.complete(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            tokens = resp.usage.total_tokens if resp.usage else 0
            return resp.choices[0].message.content, tokens
        except Exception as e:
            logger.error(f"Mistral error: {e}")
            raise

    def get_available_models(self) -> List[str]:
        return [
            "mistral-large-latest",
            "mistral-medium-latest",
            "mistral-small-latest",
            "mistral-saba-latest",
            "open-mistral-nemo",
            "open-mistral-7b",
            "open-mixtral-8x7b",
            "open-mixtral-8x22b",
            "codestral-latest",
            "pixtral-large-latest",
            "pixtral-12b-2409",
            "ministral-8b-latest",
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Google Gemini
# ─────────────────────────────────────────────────────────────────────────────

class GeminiProvider(LLMProvider):

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash", **kwargs):
        super().__init__(api_key, model, **kwargs)
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self.genai   = genai
            self._client = genai.GenerativeModel(model)
        except ImportError:
            raise ImportError("Run: pip install google-generativeai")

    def chat_completion_with_tokens(self, messages, temperature=0.05, max_tokens=4000, **kwargs):
        try:
            # Build a single prompt string from the message list
            parts = []
            for m in messages:
                role    = m["role"].upper()
                content = m["content"]
                if role == "SYSTEM":
                    parts.append(f"[SYSTEM]: {content}")
                elif role == "USER":
                    parts.append(content)
                else:
                    parts.append(f"[ASSISTANT]: {content}")
            prompt = "\n\n".join(parts)

            cfg  = self.genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
            resp = self._client.generate_content(prompt, generation_config=cfg)
            tokens = resp.usage_metadata.total_token_count if resp.usage_metadata else 0
            return resp.text, tokens
        except Exception as e:
            logger.error(f"Gemini error: {e}")
            raise

    def get_available_models(self) -> List[str]:
        return [
            # Gemini 2.5
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            # Gemini 2.0
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            # Gemini 1.5
            "gemini-1.5-pro",
            "gemini-1.5-flash",
            "gemini-1.5-flash-8b",
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Kimi / Moonshot AI
# ─────────────────────────────────────────────────────────────────────────────

class KimiProvider(LLMProvider):
    """Moonshot AI (Kimi) — uses OpenAI-compatible REST API."""

    def __init__(self, api_key: str, model: str = "moonshot-v1-auto", **kwargs):
        super().__init__(api_key, model, **kwargs)
        self.base_url = kwargs.get("base_url", "https://api.moonshot.cn/v1")

    def chat_completion_with_tokens(self, messages, temperature=0.05, max_tokens=4000, **kwargs):
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type":  "application/json",
            }
            data = dict(model=self.model, messages=messages,
                        temperature=temperature, max_tokens=max_tokens)
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=data, timeout=120,
            )
            resp.raise_for_status()
            body   = resp.json()
            tokens = body.get("usage", {}).get("total_tokens", 0)
            return body["choices"][0]["message"]["content"], tokens
        except Exception as e:
            logger.error(f"Kimi/Moonshot error: {e}")
            raise

    def get_available_models(self) -> List[str]:
        return [
            "moonshot-v1-auto",
            "moonshot-v1-8k",
            "moonshot-v1-32k",
            "moonshot-v1-128k",
            "kimi-latest",
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Grok / xAI
# ─────────────────────────────────────────────────────────────────────────────

class GrokProvider(LLMProvider):
    """xAI Grok — uses OpenAI-compatible REST API."""

    def __init__(self, api_key: str, model: str = "grok-3", **kwargs):
        super().__init__(api_key, model, **kwargs)
        self.base_url = kwargs.get("base_url", "https://api.x.ai/v1")

    def chat_completion_with_tokens(self, messages, temperature=0.05, max_tokens=4000, **kwargs):
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type":  "application/json",
            }
            data = dict(model=self.model, messages=messages,
                        temperature=temperature, max_tokens=max_tokens)
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=data, timeout=90,
            )
            resp.raise_for_status()
            body   = resp.json()
            tokens = body.get("usage", {}).get("total_tokens", 0)
            return body["choices"][0]["message"]["content"], tokens
        except Exception as e:
            logger.error(f"Grok/xAI error: {e}")
            raise

    def get_available_models(self) -> List[str]:
        return [
            "grok-3",
            "grok-3-fast",
            "grok-3-mini",
            "grok-3-mini-fast",
            "grok-2",
            "grok-2-mini",
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Ollama (local)
# ─────────────────────────────────────────────────────────────────────────────

class OllamaProvider(LLMProvider):

    def __init__(self, api_key: str = "", model: str = "llama3.2",
                 base_url: str = "http://localhost:11434", **kwargs):
        super().__init__(api_key, model, **kwargs)
        self.base_url = base_url.rstrip('/')

    def chat_completion_with_tokens(self, messages, temperature=0.05, max_tokens=4000, **kwargs):
        """Uses Ollama's /api/chat endpoint (proper chat, not flat-prompt)."""
        try:
            data = {
                "model":    self.model,
                "messages": messages,
                "stream":   False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            }
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json=data, timeout=180,
            )
            resp.raise_for_status()
            body   = resp.json()
            text   = body.get("message", {}).get("content", "")
            tokens = body.get("eval_count", 0) + body.get("prompt_eval_count", 0)
            return text, tokens
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            raise

    def get_available_models(self) -> List[str]:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=10)
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            return [
                "llama3.2", "llama3.1", "llama3",
                "llama2", "mistral", "gemma2",
                "phi3", "qwen2", "codellama",
            ]


# ─────────────────────────────────────────────────────────────────────────────
# Generic OpenAI-compatible
# ─────────────────────────────────────────────────────────────────────────────

class GenericOpenAIProvider(LLMProvider):

    def __init__(self, api_key: str, model: str, base_url: str, **kwargs):
        super().__init__(api_key, model, **kwargs)
        self.base_url = base_url.rstrip('/')

    def chat_completion_with_tokens(self, messages, temperature=0.05, max_tokens=4000, **kwargs):
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type":  "application/json",
            }
            data = dict(model=self.model, messages=messages,
                        temperature=temperature, max_tokens=max_tokens)
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=data, timeout=90,
            )
            resp.raise_for_status()
            body   = resp.json()
            tokens = body.get("usage", {}).get("total_tokens", 0)
            return body["choices"][0]["message"]["content"], tokens
        except Exception as e:
            logger.error(f"Generic provider error: {e}")
            raise

    def get_available_models(self) -> List[str]:
        return [self.model]


# ─────────────────────────────────────────────────────────────────────────────
# Manager
# ─────────────────────────────────────────────────────────────────────────────

class LLMManager:

    PROVIDERS: Dict[str, type] = {
        "OpenAI":                    OpenAIProvider,
        "Anthropic (Claude)":        AnthropicProvider,
        "Google Gemini":             GeminiProvider,
        "DeepSeek":                  DeepSeekProvider,
        "Mistral":                   MistralProvider,
        "Kimi (Moonshot)":           KimiProvider,
        "Grok (xAI)":               GrokProvider,
        "Ollama (Local)":            OllamaProvider,
        "Custom OpenAI-Compatible":  GenericOpenAIProvider,
    }

    def __init__(self, provider_name: str, api_key: str, model: str, **kwargs):
        if provider_name not in self.PROVIDERS:
            raise ValueError(f"Unknown provider: {provider_name}. "
                             f"Supported: {list(self.PROVIDERS)}")
        self.provider_name = provider_name
        cls = self.PROVIDERS[provider_name]
        self.provider: LLMProvider = cls(api_key, model, **kwargs)

    def chat_completion_with_tokens(self, messages, **kwargs) -> Tuple[str, int]:
        return self.provider.chat_completion_with_tokens(messages, **kwargs)

    def chat_completion(self, messages, **kwargs) -> str:
        text, _ = self.provider.chat_completion_with_tokens(messages, **kwargs)
        return text

    def chat_completion_structured(
        self,
        messages: list,
        response_model: type,
        temperature: float = 0.05,
        max_tokens: int = 4000,
    ) -> Tuple[Any, int]:
        """
        Force the LLM to return data matching a Pydantic response_model,
        using the `instructor` library for schema enforcement and auto-retry
        on malformed JSON (up to 3 attempts).

        Supported providers: OpenAI, Anthropic (Claude), Mistral,
        DeepSeek, Ollama (Local), Custom OpenAI-Compatible.
        Google Gemini falls back to plain structured parsing automatically.

        Returns (parsed_pydantic_instance, tokens_used).
        Raises ImportError if instructor is not installed.
        """
        try:
            import instructor
        except ImportError:
            raise ImportError(
                "Run: pip install instructor>=1.2.0  "
                "(required for structured output / anti-hallucination mode)"
            )

        pname = self.provider_name

        try:
            if pname in ("OpenAI", "Custom OpenAI-Compatible",
                         "DeepSeek", "Kimi (Moonshot)", "Grok (xAI)",
                         "Ollama (Local)"):
                import openai
                raw_client = openai.OpenAI(
                    api_key=self.provider.api_key or "ollama",
                    base_url=getattr(self.provider, 'base_url', None),
                )
                client = instructor.from_openai(raw_client)
                resp = client.chat.completions.create(
                    model=self.provider.model,
                    messages=messages,
                    response_model=response_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    max_retries=3,
                )
                return resp, 0  # instructor doesn't expose usage; token count via normal path

            elif pname == "Anthropic (Claude)":
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
                    max_retries=3,
                )
                return resp, 0

            elif pname == "Mistral":
                from mistralai import Mistral
                raw_client = Mistral(api_key=self.provider.api_key)
                client = instructor.from_mistral(raw_client)
                resp = client.chat.completions.create(
                    model=self.provider.model,
                    messages=messages,
                    response_model=response_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    max_retries=3,
                )
                return resp, 0

            else:
                raise NotImplementedError(
                    f"Structured output not natively supported for {pname}. "
                    "Falling back to JSON parse."
                )

        except instructor.exceptions.InstructorRetryException as exc:
            raise RuntimeError(f"instructor failed after 3 retries: {exc}") from exc

    @classmethod
    def get_supported_providers(cls) -> List[str]:
        return list(cls.PROVIDERS.keys())

    @classmethod
    def get_default_models(cls) -> Dict[str, str]:
        return {
            "OpenAI":                   "gpt-4o-mini",
            "Anthropic (Claude)":       "claude-sonnet-4-20250514",
            "Google Gemini":            "gemini-2.5-flash",
            "DeepSeek":                 "deepseek-chat",
            "Mistral":                  "mistral-large-latest",
            "Kimi (Moonshot)":           "moonshot-v1-auto",
            "Grok (xAI)":               "grok-3-mini-fast",
            "Ollama (Local)":           "llama3.2",
            "Custom OpenAI-Compatible": "gpt-3.5-turbo",
        }

    @classmethod
    def get_provider_info(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "OpenAI":                   {"requires_api_key": True,  "free_tier": False,   "website": "https://platform.openai.com"},
            "Anthropic (Claude)":       {"requires_api_key": True,  "free_tier": False,   "website": "https://console.anthropic.com"},
            "Google Gemini":            {"requires_api_key": True,  "free_tier": True,    "website": "https://aistudio.google.com"},
            "DeepSeek":                 {"requires_api_key": True,  "free_tier": True,    "website": "https://platform.deepseek.com"},
            "Mistral":                  {"requires_api_key": True,  "free_tier": True,    "website": "https://console.mistral.ai"},
            "Kimi (Moonshot)":           {"requires_api_key": True,  "free_tier": True,    "website": "https://platform.moonshot.cn"},
            "Grok (xAI)":               {"requires_api_key": True,  "free_tier": False,   "website": "https://console.x.ai"},
            "Ollama (Local)":           {"requires_api_key": False, "free_tier": True,    "website": "https://ollama.ai"},
            "Custom OpenAI-Compatible": {"requires_api_key": True,  "free_tier": "Varies","website": "Custom"},
        }

    @classmethod
    def needs_base_url(cls, provider_name: str) -> bool:
        return provider_name in ("Ollama (Local)", "Custom OpenAI-Compatible")

    @classmethod
    def get_models_for_provider(cls, provider_name: str) -> List[str]:
        """Return built-in + user-added custom models for the given provider."""
        # Get built-in models — use static list to avoid needing SDK installed
        builtin = cls._BUILTIN_MODELS.get(provider_name, [])
        if not builtin and provider_name in cls.PROVIDERS:
            # Fallback: try instantiation (works for providers w/o SDK deps)
            try:
                default_model = cls.get_default_models().get(provider_name, "")
                builtin = cls.PROVIDERS[provider_name](
                    "", default_model
                ).get_available_models()
            except Exception:
                builtin = []
        # Append user-added custom models
        custom = load_custom_models().get(provider_name, [])
        combined = list(builtin)
        for m in custom:
            if m not in combined:
                combined.append(m)
        return combined

    # Static model lists so we don't need to instantiate providers (avoids SDK import errors)
    _BUILTIN_MODELS: Dict[str, List[str]] = {
        "OpenAI": [
            "gpt-4o", "gpt-4o-mini", "gpt-4o-2024-11-20",
            "gpt-4o-audio-preview", "gpt-4o-mini-audio-preview",
            "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano",
            "o3", "o3-mini", "o4-mini",
            "o1", "o1-pro", "o1-mini", "o1-preview",
            "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo",
        ],
        "Anthropic (Claude)": [
            "claude-sonnet-4-20250514", "claude-opus-4-20250514",
            "claude-3-7-sonnet-20250219",
            "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229", "claude-3-haiku-20240307",
        ],
        "Google Gemini": [
            "gemini-2.5-pro", "gemini-2.5-flash",
            "gemini-2.0-flash", "gemini-2.0-flash-lite",
            "gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.5-flash-8b",
        ],
        "DeepSeek": [
            "deepseek-chat", "deepseek-reasoner",
            "deepseek-coder", "deepseek-prover-v2-671b",
        ],
        "Mistral": [
            "mistral-large-latest", "mistral-medium-latest", "mistral-small-latest",
            "mistral-saba-latest", "open-mistral-nemo",
            "open-mistral-7b", "open-mixtral-8x7b", "open-mixtral-8x22b",
            "codestral-latest", "pixtral-large-latest", "pixtral-12b-2409",
            "ministral-8b-latest",
        ],
        "Kimi (Moonshot)": [
            "moonshot-v1-auto", "moonshot-v1-8k",
            "moonshot-v1-32k", "moonshot-v1-128k",
            "kimi-latest",
        ],
        "Grok (xAI)": [
            "grok-3", "grok-3-fast",
            "grok-3-mini", "grok-3-mini-fast",
            "grok-2", "grok-2-mini",
        ],
        "Ollama (Local)": [
            "llama3.2", "llama3.1", "llama3",
            "llama2", "mistral", "gemma2",
            "phi3", "qwen2", "codellama",
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Utility functions
# ─────────────────────────────────────────────────────────────────────────────

def test_provider_connection(provider_name: str, api_key: str, model: str, **kwargs) -> Tuple[bool, str]:
    """Returns (success, message)."""
    try:
        mgr = LLMManager(provider_name, api_key, model, **kwargs)
        msgs = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user",   "content": "Reply with exactly: Connection OK"},
        ]
        text, tokens = mgr.chat_completion_with_tokens(msgs, max_tokens=20)
        ok = bool(text and len(text.strip()) > 0)
        return ok, f"Tokens used: {tokens}" if ok else "Empty response"
    except Exception as e:
        return False, str(e)


def get_install_instructions() -> Dict[str, str]:
    return {
        "OpenAI":                   "pip install openai",
        "Anthropic (Claude)":       "pip install anthropic",
        "Google Gemini":            "pip install google-generativeai",
        "DeepSeek":                 "No extra package (uses requests)",
        "Mistral":                  "pip install mistralai",
        "Kimi (Moonshot)":           "No extra package (uses requests)",
        "Grok (xAI)":               "No extra package (uses requests)",
        "Ollama (Local)":           "Install from https://ollama.ai then run: ollama serve",
        "Custom OpenAI-Compatible": "No extra package (uses requests)",
    }


if __name__ == "__main__":
    for name, info in LLMManager.get_provider_info().items():
        print(f"{name}: API key required={info['requires_api_key']}  "
              f"Free tier={info['free_tier']}  {info['website']}")
