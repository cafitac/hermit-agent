from __future__ import annotations

import time as _time

import httpx

from .types import LLMCallTimeout

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
