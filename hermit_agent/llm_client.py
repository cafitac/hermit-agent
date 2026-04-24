"""OpenAI-compatible LLM client.

Class hierarchy:
  LLMClientBase          — common interface (HTTP, retry, streaming, model routing)
  ├── LocalLLMClient     — local backend (MLX, llama.cpp, Ollama)
  │   └── OllamaClient   — thin subclass for qwen3 reasoning_effort support
  └── OpenAICompatClient — standard OpenAI-compatible external API
      └── ZAIClient      — z.ai/GLM (glm-5.1/glm-4.7 model routing)

Factory:   create_llm_client(base_url, model, api_key) → auto-detect provider
"""

from __future__ import annotations

import json
import threading
import time as _time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Generator, Literal

import httpx


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict | None = None  # {"prompt_tokens": N, "completion_tokens": N}

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class StreamChunk:
    """Streaming chunk."""
    type: Literal["text", "reasoning", "tool_call_start", "tool_call_done", "done", "usage"]
    text: str = ""
    tool_call: ToolCall | None = None
    usage: dict | None = None  # only populated in type="usage" chunks


class LLMCallTimeout(TimeoutError):
    """LLM call exceeds CALL_TIMEOUT or user cancels (§32 G30-C)."""


_FLAT_RETRY_DELAY = 2.0
_OVERLOAD_RETRY_DELAY = 5.0


def _with_retry(func, max_retries: int = 3, base_delay: float = _FLAT_RETRY_DELAY):
    """Flat-delay based retry.

    Exponential backoff was too long relative to external API rate-limit recovery and looked like a hang.
    If a Retry-After header is present, its value takes priority.
    """
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except LLMCallTimeout:
            # §32 G30-C: cancellation/timeout propagates immediately without retry.
            raise
        except httpx.HTTPStatusError as e:
            last_error = e
            if attempt >= max_retries:
                break
            code = e.response.status_code
            if code == 429:
                retry_after = e.response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else base_delay
            elif code == 529:
                delay = _OVERLOAD_RETRY_DELAY
            else:
                delay = base_delay
            print(f"\033[33m[Retry {attempt + 1}/{max_retries}: HTTP {code}. Waiting {delay:.1f}s]\033[0m")
            _time.sleep(delay)
        except Exception as e:
            last_error = e
            if attempt >= max_retries:
                break
            print(f"\033[33m[Retry {attempt + 1}/{max_retries}: {e}. Waiting {base_delay:.1f}s]\033[0m")
            _time.sleep(base_delay)

    raise last_error  # type: ignore


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class LLMClientBase(ABC):
    """Common interface for OpenAI-compatible LLM clients.

    Subclasses implement _provider_extra_params() to add or remove
    provider-specific non-standard parameters.
    """

    MAX_RETRIES = 3
    SLOW_CALL_THRESHOLD = 60.0   # emit [LLM_CALL_SLOW] warning if exceeded
    CALL_TIMEOUT = 120.0         # httpx read timeout

    # session logger (injected from bridge)
    session_logger = None

    # model routing by task type (override in subclasses)
    MODEL_ROUTING: dict[str, str] = {}

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.fallback_model: str | None = None
        self._consecutive_failures = 0
        self._MAX_FAILURES_BEFORE_FALLBACK = 3
        self._original_model = model
        self._auto_routing = True
        self.reasoning = False
        self._cancel_event = None

    # ------------------------------------------------------------------
    # Provider hook: implemented in subclasses
    # ------------------------------------------------------------------

    @abstractmethod
    def _provider_extra_params(self, stream: bool) -> dict:
        """Return provider-specific parameters to add to the payload.

        Parameters not in the standard OpenAI spec (e.g. reasoning_effort) are
        returned here only when the provider supports them.
        """

    # ------------------------------------------------------------------
    # Common helpers
    # ------------------------------------------------------------------

    def _auth_headers(self) -> dict:
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    def _log_session(self, tag: str, content: str) -> None:
        logger = getattr(self, "session_logger", None)
        if logger is not None:
            try:
                logger.log(tag, content)
            except Exception:
                pass

    def _start_cancel_watcher(self, client: httpx.Client) -> threading.Thread:
        """Close the httpx client immediately upon cancel_event to abort inference instantly."""
        def _watch() -> None:
            cancel = self._cancel_event
            if cancel:
                cancel.wait()
                try:
                    client.close()
                except Exception:
                    pass

        t = threading.Thread(target=_watch, daemon=True, name="llm-cancel-watcher")
        t.start()
        return t

    def _build_payload(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        temperature: float,
        stream: bool,
    ) -> dict:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        payload.update(self._provider_extra_params(stream=stream))
        if tools:
            payload["tools"] = tools
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    # ------------------------------------------------------------------
    # Model routing
    # ------------------------------------------------------------------

    def enable_reasoning(self) -> None:
        self.reasoning = True

    def disable_reasoning(self) -> None:
        self.reasoning = False

    def is_reasoning_enabled(self) -> bool:
        return self.reasoning

    def use_tier(self, tier: str) -> str:
        """Switch to the model appropriate for the given task tier. Returns the previous model."""
        prev = self.model
        if self._auto_routing and tier in self.MODEL_ROUTING:
            self.model = self.MODEL_ROUTING[tier]
        return prev

    def restore_model(self, model: str) -> None:
        self.model = model

    # ------------------------------------------------------------------
    # HTTP request — chat (non-streaming)
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        if system:
            messages = [{"role": "system", "content": system}, *messages]

        payload = self._build_payload(messages, tools, temperature, stream=False)
        url = f"{self.base_url}/chat/completions"
        timeout = httpx.Timeout(connect=10.0, read=self.CALL_TIMEOUT, write=60.0, pool=5.0)

        def _do_request() -> dict:
            start = _time.monotonic()
            with httpx.Client(timeout=timeout) as client:
                self._start_cancel_watcher(client)
                try:
                    resp = client.post(url, json=payload, headers=self._auth_headers())
                    resp.raise_for_status()
                except httpx.ReadTimeout as e:
                    # ReadTimeout is a subclass of TransportError — catch the more specific
                    # type first to avoid it being swallowed by the generic TransportError handler.
                    elapsed = _time.monotonic() - start
                    self._log_session(
                        "LLM_CALL_TIMEOUT",
                        f"LLM call timed out after {elapsed:.1f}s (model={self.model})",
                    )
                    raise LLMCallTimeout(f"LLM call exceeded {self.CALL_TIMEOUT:.1f}s (model={self.model})") from e
                except (httpx.RemoteProtocolError, httpx.LocalProtocolError, httpx.TransportError) as e:
                    if self._cancel_event and self._cancel_event.is_set():
                        raise LLMCallTimeout(f"LLM call cancelled by user (model={self.model})") from e
                    raise

                elapsed = _time.monotonic() - start
                if elapsed >= self.SLOW_CALL_THRESHOLD:
                    self._log_session(
                        "LLM_CALL_SLOW",
                        f"LLM call completed in {elapsed:.1f}s (model={self.model})",
                    )
                return resp.json()

        try:
            result = _with_retry(_do_request, max_retries=self.MAX_RETRIES)
            self._consecutive_failures = 0
        except LLMCallTimeout:
            raise
        except Exception as primary_error:
            self._consecutive_failures += 1
            if (
                self.fallback_model is not None
                and self.model != self.fallback_model
                and self._consecutive_failures >= self._MAX_FAILURES_BEFORE_FALLBACK
            ):
                print(f"\033[33m[Switching to fallback model: {self.fallback_model}]\033[0m")
                self.model = self.fallback_model
                payload["model"] = self.model
                try:
                    result = _with_retry(_do_request, max_retries=self.MAX_RETRIES)
                    self._consecutive_failures = 0
                except Exception:
                    raise primary_error
            else:
                raise

        message = result["choices"][0]["message"]
        tool_calls: list[ToolCall] = []

        for tc in message.get("tool_calls") or []:
            args = tc["function"]["arguments"]
            if isinstance(args, str):
                args = json.loads(args)
            tool_calls.append(ToolCall(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments=args,
            ))

        return LLMResponse(
            content=message.get("content"),
            tool_calls=tool_calls,
            usage=result.get("usage"),
        )

    # ------------------------------------------------------------------
    # HTTP request — chat_stream (streaming)
    # ------------------------------------------------------------------

    def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        temperature: float = 0.0,
        abort_event=None,
    ) -> Generator[StreamChunk, None, LLMResponse]:
        """Streaming mode. Yields text chunks and returns a final LLMResponse."""
        if system:
            messages = [{"role": "system", "content": system}, *messages]

        payload = self._build_payload(messages, tools, temperature, stream=True)
        url = f"{self.base_url}/chat/completions"
        timeout = httpx.Timeout(connect=10.0, read=300.0, write=60.0, pool=5.0)

        full_content = ""
        tool_calls_acc: dict[int, dict] = {}
        usage_acc: dict | None = None

        with httpx.Client(timeout=timeout) as client:
            self._start_cancel_watcher(client)
            if abort_event is not None:
                def _abort_watch() -> None:
                    abort_event.wait()
                    try:
                        client.close()
                    except Exception:
                        pass
                threading.Thread(target=_abort_watch, daemon=True, name="llm-abort-watcher").start()

            try:
                with client.stream("POST", url, json=payload, headers=self._auth_headers()) as resp:
                    resp.raise_for_status()
                    for raw_line in resp.iter_lines():
                        if abort_event is not None and abort_event.is_set():
                            raise InterruptedError("LLM stream aborted by user")
                        if self._cancel_event and self._cancel_event.is_set():
                            raise InterruptedError("LLM stream cancelled by user")

                        line = raw_line.strip()
                        if not line.startswith("data: "):
                            continue
                        line = line[6:]
                        if line == "[DONE]":
                            break

                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        # capture usage regardless of whether choices is present
                        # (OpenAI: choices=[] + usage, z.ai etc.: choices present + usage)
                        if chunk.get("usage"):
                            usage_acc = chunk["usage"]
                            yield StreamChunk(type="usage", usage=chunk["usage"])
                            if not chunk.get("choices"):
                                continue

                        delta = chunk.get("choices", [{}])[0].get("delta", {}) if chunk.get("choices") else {}

                        # reasoning tokens (gemma4: delta.reasoning field)
                        if delta.get("reasoning"):
                            yield StreamChunk(type="reasoning", text=delta["reasoning"])

                        if "content" in delta and delta["content"]:
                            text = delta["content"]
                            full_content += text
                            yield StreamChunk(type="text", text=text)

                        for tc_delta in delta.get("tool_calls") or []:
                            idx = tc_delta.get("index", 0)
                            if idx not in tool_calls_acc:
                                tool_calls_acc[idx] = {
                                    "id": tc_delta.get("id", f"call_{idx}"),
                                    "name": "",
                                    "arguments_str": "",
                                }
                            acc = tool_calls_acc[idx]
                            func = tc_delta.get("function", {})
                            if "name" in func:
                                acc["name"] = func["name"]
                            if "arguments" in func:
                                acc["arguments_str"] += func["arguments"]

            except (httpx.RemoteProtocolError, httpx.LocalProtocolError, httpx.TransportError) as e:
                if (abort_event is not None and abort_event.is_set()) or \
                   (self._cancel_event and self._cancel_event.is_set()):
                    raise InterruptedError("LLM stream aborted by user") from e
                raise

        tool_calls: list[ToolCall] = []
        for idx in sorted(tool_calls_acc.keys()):
            acc = tool_calls_acc[idx]
            try:
                args = json.loads(acc["arguments_str"]) if acc["arguments_str"] else {}
            except json.JSONDecodeError:
                args = {}
            tc = ToolCall(id=acc["id"], name=acc["name"], arguments=args)
            tool_calls.append(tc)
            yield StreamChunk(type="tool_call_done", tool_call=tc)

        yield StreamChunk(type="done")

        return LLMResponse(
            content=full_content or None,
            tool_calls=tool_calls,
            usage=usage_acc,
        )


# ---------------------------------------------------------------------------
# Concrete implementations
# ---------------------------------------------------------------------------

class LocalLLMClient(LLMClientBase):
    """Local LLM client for any local backend (MLX, llama.cpp, Ollama).

    All local backends expose an OpenAI-compatible /v1 endpoint, so this
    single class handles them all via URL-based dispatch.
    """

    MODEL_ROUTING = {
        "quality": "qwen3-coder:30b",
        "speed": "qwen3-coder:30b",
        "fast": "qwen3-coder:30b",
    }

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        model: str = "qwen3-coder:30b",
        api_key: str | None = None,
    ):
        super().__init__(base_url, model, api_key)

    def _provider_extra_params(self, stream: bool) -> dict:
        return {}


class OllamaClient(LocalLLMClient):
    """Thin subclass adding qwen3 reasoning_effort support for Ollama.

    Use LocalLLMClient for non-ollama local backends (MLX, llama.cpp).
    """

    def _provider_extra_params(self, stream: bool) -> dict:
        """reasoning_effort: qwen3 thinking mode control parameter."""
        if not self.reasoning:
            return {"reasoning_effort": "none"}
        return {}


class OpenAICompatClient(LLMClientBase):
    """Standard OpenAI-compatible external API client.

    Used for z.ai/GLM, OpenAI, and other external services.
    Does not send non-standard parameters (e.g., reasoning_effort).
"""

    MODEL_ROUTING = {
        "quality": "gpt-4o",
        "speed": "gpt-4o-mini",
        "fast": "gpt-4o-mini",
    }

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
    ):
        super().__init__(base_url, model, api_key)

    def _provider_extra_params(self, stream: bool) -> dict:
        return {}


class ZAIClient(OpenAICompatClient):
    """z.ai/GLM API client.

    Environment variables:
      Z_AI_API_KEY   or   HERMIT_API_KEY
      HERMIT_MODEL  (default: glm-5.1)
"""

    DEFAULT_BASE_URL = "https://api.z.ai/api/coding/paas/v4"

    MODEL_ROUTING = {
        "quality": "glm-5.1",   # Code generation, review, complex reasoning
        "speed": "glm-4.7",     # Tasks requiring fast responses
        "fast": "glm-4.7",
    }

    def __init__(
        self,
        model: str = "glm-5.1",
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        import os
        resolved_key = api_key or os.environ.get("Z_AI_API_KEY") or os.environ.get("HERMIT_API_KEY")
        super().__init__(
            base_url=base_url or self.DEFAULT_BASE_URL,
            model=model,
            api_key=resolved_key,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1")


def create_llm_client(
    base_url: str = "http://localhost:11434/v1",
    model: str | None = None,
    api_key: str | None = None,
    local_backend: str | None = None,
) -> LLMClientBase:
    """Auto-detects the provider from base_url and returns the appropriate client.

    For local hosts, uses OllamaClient (qwen3 reasoning_effort) only when
    local_backend is "ollama".  All other local backends get LocalLLMClient.
    """
    url = base_url.lower()

    if "z.ai" in url:
        return ZAIClient(base_url=base_url, model=model or "glm-5.1", api_key=api_key)

    if any(h in url for h in _LOCAL_HOSTS):
        # Ollama gets the subclass with reasoning_effort support
        if local_backend == "ollama":
            return OllamaClient(base_url=base_url, model=model or "qwen3-coder:30b", api_key=api_key)
        # MLX, llama.cpp, or unspecified → generic local client
        return LocalLLMClient(base_url=base_url, model=model or "qwen3-coder:30b", api_key=api_key)

    # Unknown external server → handled as standard OpenAI-compat
    return OpenAICompatClient(base_url=base_url, model=model or "gpt-4o", api_key=api_key)


# ---------------------------------------------------------------------------
# Backward compatibility alias (deprecated) — removed
# ---------------------------------------------------------------------------
