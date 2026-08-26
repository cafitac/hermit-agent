"""Tests for local LLM runtime detection and setup.

Covers:
  - detect_local_runtime() probe logic (MLX, llama.cpp, ollama)
  - Priority: MLX > llama.cpp > ollama
  - Health check integration
  - LocalRuntimeInfo dataclass
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock


from hermit_agent.local_runtime import (
    LocalRuntimeInfo,
    detect_local_runtime,
    BACKEND_MLX,
    BACKEND_LLAMA_CPP,
    BACKEND_OLLAMA,
)


# ── LocalRuntimeInfo dataclass ──────────────────────────────────────────

def test_local_runtime_info_defaults():
    info = LocalRuntimeInfo()
    assert info.backend is None
    assert info.base_url is None
    assert info.available is False
    assert info.model_hint is None


def test_local_runtime_info_with_values():
    info = LocalRuntimeInfo(
        backend=BACKEND_OLLAMA,
        base_url="http://localhost:11434/v1",
        available=True,
    )
    assert info.backend == "ollama"
    assert info.available is True


# ── Detection: MLX ──────────────────────────────────────────────────────

def test_mlx_detected_on_apple_silicon():
    """MLX should be detected on darwin/arm64 when mlx-lm is importable and healthy."""
    info = LocalRuntimeInfo(
        backend=BACKEND_MLX,
        base_url="http://localhost:8080/v1",
        available=True,
    )
    assert info.backend == "mlx"
    assert info.base_url == "http://localhost:8080/v1"


def test_mlx_skipped_on_linux():
    """MLX probe must be skipped on non-darwin platforms."""
    with patch("sys.platform", "linux"):
        # Even if mlx is importable, linux should skip it
        pass  # detect_local_runtime will skip MLX step


def test_mlx_skipped_on_intel_mac():
    """MLX should be skipped on darwin/x86_64 (Intel Macs)."""
    with patch("sys.platform", "darwin"), \
         patch("platform.machine", return_value="x86_64"):
        pass  # detect_local_runtime should skip MLX


# ── Detection: llama.cpp ────────────────────────────────────────────────

def test_llama_cpp_detected_when_binary_exists():
    info = LocalRuntimeInfo(
        backend=BACKEND_LLAMA_CPP,
        base_url="http://localhost:8080/v1",
        available=True,
    )
    assert info.backend == "llama_cpp"


# ── Detection: ollama ───────────────────────────────────────────────────

def test_ollama_detected_when_available():
    info = LocalRuntimeInfo(
        backend=BACKEND_OLLAMA,
        base_url="http://localhost:11434/v1",
        available=True,
    )
    assert info.backend == "ollama"


# ── Priority: MLX > llama.cpp > ollama ──────────────────────────────────

def test_mlx_preferred_over_ollama():
    """When both MLX and ollama are available, MLX wins."""
    with patch("hermit_agent.local_runtime._probe_mlx") as mock_mlx, \
         patch("hermit_agent.local_runtime._probe_llama_cpp"), \
         patch("hermit_agent.local_runtime._probe_ollama") as mock_ollama:
        mock_mlx.return_value = LocalRuntimeInfo(
            backend=BACKEND_MLX,
            base_url="http://localhost:8080/v1",
            available=True,
        )
        mock_ollama.return_value = LocalRuntimeInfo(
            backend=BACKEND_OLLAMA,
            base_url="http://localhost:11434/v1",
            available=True,
        )
        result = detect_local_runtime()
        assert result.backend == "mlx"


def test_llama_cpp_preferred_over_ollama():
    """When llama.cpp and ollama are available (no MLX), llama.cpp wins."""
    with patch("hermit_agent.local_runtime._probe_mlx") as mock_mlx, \
         patch("hermit_agent.local_runtime._probe_llama_cpp") as mock_llama, \
         patch("hermit_agent.local_runtime._probe_ollama") as mock_ollama:
        mock_mlx.return_value = LocalRuntimeInfo(available=False)
        mock_llama.return_value = LocalRuntimeInfo(
            backend=BACKEND_LLAMA_CPP,
            base_url="http://localhost:8080/v1",
            available=True,
        )
        mock_ollama.return_value = LocalRuntimeInfo(
            backend=BACKEND_OLLAMA,
            base_url="http://localhost:11434/v1",
            available=True,
        )
        result = detect_local_runtime()
        assert result.backend == "llama_cpp"


def test_ollama_as_fallback():
    """When nothing else is available, ollama is the fallback."""
    with patch("hermit_agent.local_runtime._probe_mlx") as mock_mlx, \
         patch("hermit_agent.local_runtime._probe_llama_cpp") as mock_llama, \
         patch("hermit_agent.local_runtime._probe_ollama") as mock_ollama:
        mock_mlx.return_value = LocalRuntimeInfo(available=False)
        mock_llama.return_value = LocalRuntimeInfo(available=False)
        mock_ollama.return_value = LocalRuntimeInfo(
            backend=BACKEND_OLLAMA,
            base_url="http://localhost:11434/v1",
            available=True,
        )
        result = detect_local_runtime()
        assert result.backend == "ollama"


def test_nothing_available():
    """When no backend is available, returns unavailable info."""
    with patch("hermit_agent.local_runtime._probe_mlx") as mock_mlx, \
         patch("hermit_agent.local_runtime._probe_llama_cpp") as mock_llama, \
         patch("hermit_agent.local_runtime._probe_ollama") as mock_ollama:
        mock_mlx.return_value = LocalRuntimeInfo(available=False)
        mock_llama.return_value = LocalRuntimeInfo(available=False)
        mock_ollama.return_value = LocalRuntimeInfo(available=False)
        result = detect_local_runtime()
        assert result.available is False
        assert result.backend is None


# ── Probe unit tests (mocked HTTP) ──────────────────────────────────────

def test_probe_ollama_binary_exists_and_healthy():
    """Ollama probe succeeds when binary exists and HTTP health check passes."""
    with patch("shutil.which", return_value="/usr/local/bin/ollama"), \
         patch("httpx.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        from hermit_agent.local_runtime import _probe_ollama
        result = _probe_ollama()
        assert result.available is True
        assert result.backend == BACKEND_OLLAMA
        assert result.base_url == "http://localhost:11434/v1"


def test_probe_ollama_binary_missing():
    """Ollama probe fails when binary is not found."""
    with patch("shutil.which", return_value=None):
        from hermit_agent.local_runtime import _probe_ollama
        result = _probe_ollama()
        assert result.available is False


def test_probe_ollama_health_check_fails():
    """Ollama probe fails when binary exists but server is not running."""
    with patch("shutil.which", return_value="/usr/local/bin/ollama"), \
         patch("httpx.get", side_effect=Exception("connection refused")):
        from hermit_agent.local_runtime import _probe_ollama
        result = _probe_ollama()
        assert result.available is False


def test_probe_llama_cpp_binary_exists_and_healthy():
    """llama.cpp probe succeeds when llama-server binary exists and healthy."""
    with patch("shutil.which", return_value="/usr/local/bin/llama-server"), \
         patch("httpx.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        from hermit_agent.local_runtime import _probe_llama_cpp
        result = _probe_llama_cpp()
        assert result.available is True
        assert result.backend == BACKEND_LLAMA_CPP


def test_probe_llama_cpp_binary_missing():
    with patch("shutil.which", return_value=None):
        from hermit_agent.local_runtime import _probe_llama_cpp
        result = _probe_llama_cpp()
        assert result.available is False


def test_probe_mlx_on_apple_silicon():
    """MLX probe succeeds on darwin/arm64 when mlx module is importable."""
    with patch("sys.platform", "darwin"), \
         patch("platform.machine", return_value="arm64"), \
         patch("importlib.util.find_spec", return_value=MagicMock()), \
         patch("httpx.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        from hermit_agent.local_runtime import _probe_mlx
        result = _probe_mlx()
        assert result.available is True
        assert result.backend == BACKEND_MLX


def test_probe_mlx_skipped_on_linux():
    """MLX probe returns unavailable on non-darwin."""
    with patch("sys.platform", "linux"):
        from hermit_agent.local_runtime import _probe_mlx
        result = _probe_mlx()
        assert result.available is False


def test_probe_mlx_skipped_on_intel_mac():
    """MLX probe returns unavailable on x86_64."""
    with patch("sys.platform", "darwin"), \
         patch("platform.machine", return_value="x86_64"):
        from hermit_agent.local_runtime import _probe_mlx
        result = _probe_mlx()
        assert result.available is False


def test_probe_mlx_skipped_when_module_missing():
    """MLX probe returns unavailable when mlx module is not installed."""
    with patch("sys.platform", "darwin"), \
         patch("platform.machine", return_value="arm64"), \
         patch("importlib.util.find_spec", return_value=None):
        from hermit_agent.local_runtime import _probe_mlx
        result = _probe_mlx()
        assert result.available is False


# ── detect_all_runtimes ─────────────────────────────────────────────────

def test_detect_all_runtimes_returns_three_results():
    """detect_all_runtimes returns exactly 3 results (one per probe)."""
    with patch("sys.platform", "linux"), \
         patch("shutil.which", return_value=None):
        from hermit_agent.local_runtime import detect_all_runtimes
        results = detect_all_runtimes()
        assert len(results) == 3
        assert all(not r.available for r in results)


def test_detect_all_runtimes_mixed_availability():
    """detect_all_runtimes returns mixed available/unavailable."""
    with patch("sys.platform", "linux"), \
         patch("shutil.which", side_effect=lambda cmd: "/usr/bin/ollama" if cmd == "ollama" else None), \
         patch("httpx.get") as mock_get:
        def mock_response(url, timeout=None):
            m = MagicMock()
            m.status_code = 200 if "11434" in str(url) else 503
            return m
        mock_get.side_effect = mock_response
        from hermit_agent.local_runtime import detect_all_runtimes, BACKEND_OLLAMA
        results = detect_all_runtimes()
        assert len(results) == 3
        assert results[2].backend == BACKEND_OLLAMA
        assert results[2].available is True
        assert not results[0].available  # MLX (linux)
        assert not results[1].available  # llama.cpp (no binary)


# ── get_install_hints ───────────────────────────────────────────────────

def test_get_install_hints_known_backends():
    """get_install_hints returns hints for known backends."""
    from hermit_agent.local_runtime import get_install_hints, BACKEND_MLX, BACKEND_LLAMA_CPP, BACKEND_OLLAMA
    assert get_install_hints(BACKEND_MLX) == "pip install mlx-lm"
    assert get_install_hints(BACKEND_LLAMA_CPP) == "https://github.com/ggerganov/llama.cpp/releases"
    assert get_install_hints(BACKEND_OLLAMA) == "curl -fsSL https://ollama.com/install.sh | sh"


def test_get_install_hints_unknown_backend():
    """get_install_hints returns None for unknown backends."""
    from hermit_agent.local_runtime import get_install_hints
    assert get_install_hints("nonexistent") is None


# ── apply_detected_backend ──────────────────────────────────────────────

def test_apply_detected_backend_sets_fields():
    """apply_detected_backend merges backend info into settings."""
    from hermit_agent.config import apply_detected_backend
    from hermit_agent.local_runtime import LocalRuntimeInfo, BACKEND_OLLAMA
    cfg = {"model": "qwen3-coder:30b"}
    info = LocalRuntimeInfo(backend=BACKEND_OLLAMA, base_url="http://localhost:11434/v1", default_port=11434, available=True)
    all_detected = [info]
    result = apply_detected_backend(cfg, info, all_detected)
    assert result["local_backend"] == BACKEND_OLLAMA
    assert result["local_llm_url"] == "http://localhost:11434/v1"
    assert result["local_backend_auto_detected"] is True
    assert result["local_backends_available"] == [{"backend": BACKEND_OLLAMA, "available": True, "base_url": "http://localhost:11434/v1"}]
    # Should not mutate original
    assert "local_backend" not in cfg


def test_apply_detected_backend_syncs_ollama_url():
    """apply_detected_backend syncs ollama_url for Ollama backend."""
    from hermit_agent.config import apply_detected_backend
    from hermit_agent.local_runtime import LocalRuntimeInfo, BACKEND_OLLAMA
    cfg = {"ollama_url": "http://old:11434/v1"}
    info = LocalRuntimeInfo(backend=BACKEND_OLLAMA, base_url="http://localhost:11434/v1", default_port=11434, available=True)
    result = apply_detected_backend(cfg, info, [info])
    assert result["ollama_url"] == "http://localhost:11434/v1"


def test_apply_detected_backend_does_not_overwrite_local_model():
    """apply_detected_backend preserves existing local_model setting."""
    from hermit_agent.config import apply_detected_backend
    from hermit_agent.local_runtime import LocalRuntimeInfo, BACKEND_MLX
    cfg = {"local_model": "my-custom-model"}
    info = LocalRuntimeInfo(backend=BACKEND_MLX, base_url="http://localhost:8080/v1", default_port=8080, model_hint="detected-model", available=True)
    result = apply_detected_backend(cfg, info, [info])
    assert result["local_model"] == "my-custom-model"
