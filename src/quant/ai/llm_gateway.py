"""LLM Gateway — unified interface for local and remote LLMs.

Supports:
  - Ollama (local: DeepSeek-R1, Llama 3.1)
  - OpenAI-compatible APIs
  - Fallback to rule-based when LLM unavailable

All agents use this gateway for LLM calls, ensuring consistent
error handling, retry logic, and prompt management.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

import requests

from quant.core.config import config
from quant.core.rate_limiter import get_limiter

logger = logging.getLogger(__name__)

_llm_limiter = get_limiter("llm", base_rate=0.5, burst=2, timeout=60)


@dataclass
class LLMResponse:
    """Response from LLM."""
    text: str
    model: str
    latency_ms: float
    success: bool
    error: str | None = None
    parsed: Any = None


class LLMGateway:
    """Unified LLM gateway for multi-agent system.

    Usage:
        gw = LLMGateway()
        resp = gw.complete(
            system="You are a quant factor researcher.",
            user="Suggest a momentum factor for IDX stocks.",
            temperature=0.3,
        )
        if resp.success:
            print(resp.text)
    """

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: int = 60,
    ):
        self.provider = provider or config.llm_provider
        self.model = model or config.llm_model
        self.base_url = base_url or config.llm_base_url
        self.timeout = timeout

    def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Send a completion request to the LLM.

        Args:
            system: System prompt
            user: User prompt
            temperature: Sampling temperature (0=deterministic, 1=creative)
            max_tokens: Maximum response tokens
            json_mode: Request JSON-formatted response

        Returns:
            LLMResponse with text and metadata
        """
        if self.provider == "ollama":
            return self._complete_ollama(system, user, temperature, max_tokens, json_mode)
        elif self.provider == "openai":
            return self._complete_openai(system, user, temperature, max_tokens, json_mode)
        else:
            return LLMResponse(
                text="", model=self.model, latency_ms=0,
                success=False, error=f"Unknown provider: {self.provider}",
            )

    def _complete_ollama(
        self,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> LLMResponse:
        """Call Ollama API."""
        import time

        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if json_mode:
            payload["format"] = "json"

        start = time.time()
        try:
            _llm_limiter.acquire_sync()
            _llm_limiter.sleep_backoff_sync()
            resp = requests.post(url, json=payload, timeout=self.timeout)
            latency = (time.time() - start) * 1000

            if resp.status_code == 429:
                _llm_limiter._async._total_429 += 1
                _llm_limiter._async._apply_backoff()
                _llm_limiter._async._decrease_rate(0.5)
                return LLMResponse(
                    text="", model=self.model, latency_ms=latency,
                    success=False, error="HTTP 429: Rate limited by LLM provider",
                )
            if resp.status_code != 200:
                _llm_limiter._async._total_errors += 1
                _llm_limiter._async._apply_backoff()
                return LLMResponse(
                    text="", model=self.model, latency_ms=latency,
                    success=False, error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                )
            _llm_limiter._async._reset_backoff()
            _llm_limiter._async._update_latency(latency)

            data = resp.json()
            msg = data.get("message", {})
            text = msg.get("content", "")
            # DeepSeek-R1 puts reasoning in "thinking" field; use as fallback
            if not text and msg.get("thinking"):
                text = msg["thinking"]

            parsed = None
            if json_mode:
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    pass

            return LLMResponse(
                text=text, model=self.model, latency_ms=latency,
                success=True, parsed=parsed,
            )
        except requests.exceptions.ConnectionError:
            return LLMResponse(
                text="", model=self.model, latency_ms=0,
                success=False, error="Ollama not running. Start with: ollama serve",
            )
        except Exception as e:
            return LLMResponse(
                text="", model=self.model, latency_ms=0,
                success=False, error=str(e),
            )

    def _complete_openai(
        self,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> LLMResponse:
        """Call OpenAI-compatible API."""
        import time

        api_key = getattr(config, "llm_api_key", None)
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        start = time.time()
        try:
            resp = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload, headers=headers, timeout=self.timeout,
            )
            latency = (time.time() - start) * 1000

            if resp.status_code != 200:
                return LLMResponse(
                    text="", model=self.model, latency_ms=latency,
                    success=False, error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                )

            data = resp.json()
            text = data["choices"][0]["message"]["content"]

            parsed = None
            if json_mode:
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    pass

            return LLMResponse(
                text=text, model=self.model, latency_ms=latency,
                success=True, parsed=parsed,
            )
        except Exception as e:
            return LLMResponse(
                text="", model=self.model, latency_ms=0,
                success=False, error=str(e),
            )

    def is_available(self) -> bool:
        """Check if LLM is available."""
        resp = self.complete(
            system="You are a test.",
            user="Reply with: OK",
            max_tokens=10,
        )
        return resp.success
