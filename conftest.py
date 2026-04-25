"""pytest config — auto-exclude Ollama-dependent integration tests."""
import pytest

collect_ignore = [
    "tests/test_tool_calling.py",  # Requires Ollama server + model installed
]


@pytest.fixture(autouse=True)
def _reset_local_runtime_caches():
    """Clear local_runtime module-level TTL caches between tests.

    Prevents monkeypatched probes in one test from bleeding into the next
    via the TTL cache.
    """
    import hermit_agent.local_runtime as _lr
    _lr._ollama_models_cache = None
    _lr._ollama_models_cache_time = 0.0
    _lr._runtime_cache = None
    _lr._runtime_cache_time = 0.0
    yield
    _lr._ollama_models_cache = None
    _lr._ollama_models_cache_time = 0.0
    _lr._runtime_cache = None
    _lr._runtime_cache_time = 0.0


@pytest.fixture(autouse=True)
def _reset_log_retention_dir_cache():
    import hermit_agent.log_retention as _log_ret
    _log_ret._created_dirs.clear()
    yield
    _log_ret._created_dirs.clear()
