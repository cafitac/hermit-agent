"""HermitAgent interactive setup wizard.

Usage:
  hermit_agent-setup
  python -m hermit_agent.cli_setup
"""
from __future__ import annotations

import asyncio
import json
import secrets
import sys

from .config import DEFAULTS, GLOBAL_SETTINGS_PATH
from .local_runtime import (
    BACKEND_LLAMA_CPP,
    BACKEND_MLX,
    BACKEND_OLLAMA,
    LocalRuntimeInfo,
    detect_all_runtimes,
    detect_local_runtime,
    get_install_hints,
)


def _prompt(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def _choose(prompt: str, options: list[str]) -> int:
    print(f"\n{prompt}")
    for i, opt in enumerate(options, 1):
        print(f"  [{i}] {opt}")
    while True:
        choice = input("Choice: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return int(choice) - 1
        print(f"Enter a number between 1-{len(options)}.")


def _generate_api_key() -> str:
    return f"hermit_agent-{secrets.token_hex(16)}"


def _display_detected_backends(all_runtimes: list[LocalRuntimeInfo]) -> None:
    """Print a summary table of detected backends."""
    print("\nDetected local backends:")
    for rt in all_runtimes:
        if rt.available:
            rec = "  <- recommended" if rt.backend == BACKEND_MLX else ""
            print(f"  ✅ {rt.backend:12s} (server on :{rt.default_port}){rec}")
        else:
            hint = get_install_hints(rt.backend or "") or ""
            print(f"  ❌ {rt.backend or '???':12s} not available — {hint}")
    print()


def _pick_recommended(all_runtimes: list[LocalRuntimeInfo]) -> LocalRuntimeInfo:
    """Return the best available backend per PRD priority matrix."""
    # Priority: MLX > llama.cpp > Ollama
    priority = [BACKEND_MLX, BACKEND_LLAMA_CPP, BACKEND_OLLAMA]
    for backend in priority:
        for rt in all_runtimes:
            if rt.backend == backend and rt.available:
                return rt
    return LocalRuntimeInfo(available=False)


def _run_auto_detect(settings: dict, *, yes: bool = False) -> bool:
    """Run auto-detection and configure settings. Returns True if a backend was set."""
    all_runtimes = detect_all_runtimes()
    _display_detected_backends(all_runtimes)

    chosen = _pick_recommended(all_runtimes)
    if not chosen.available:
        print("No local LLM backend is running.")
        print("Start one of:")
        for backend, hint in [
            (BACKEND_MLX, "mlx_lm.server --model <model>"),
            (BACKEND_LLAMA_CPP, "llama-server -m <model.gguf> --port 8081"),
            (BACKEND_OLLAMA, "ollama serve"),
        ]:
            print(f"  {backend}: {hint}")
        return False

    if not yes:
        answer = _prompt(f"Use {chosen.backend} ({chosen.base_url}) as default?", "Y")
        if answer.lower() in ("n", "no"):
            # Let user pick from available backends
            available = [rt for rt in all_runtimes if rt.available]
            if len(available) <= 1:
                print("No other backends available.")
                return False
            opts = [f"{rt.backend} ({rt.base_url})" for rt in available]
            idx = _choose("Select backend:", opts)
            chosen = available[idx]

    from .config import apply_detected_backend
    settings.update(apply_detected_backend(settings, chosen, all_runtimes))
    return True


def run_setup(*, yes: bool = False) -> None:
    print("=" * 50)
    print("  HermitAgent Setup Wizard")
    print("=" * 50)
    print()

    settings = dict(DEFAULTS)

    # 1. LLM Provider selection
    providers = [
        "Auto-detect (recommended)",
        "MLX (Apple Silicon optimized)",
        "llama.cpp (lightweight, cross-platform)",
        "Ollama (universal, easy model management)",
        "z.ai GLM (cloud)",
        "OpenAI-compatible API (cloud)",
    ]
    choice = _choose("Select LLM Provider:", providers)

    if choice == 0:
        # Auto-detect
        if _run_auto_detect(settings, yes=yes):
            # Model prompt for local backends
            if not settings.get("local_model"):
                default_model = "qwen3-coder:30b"
                if settings.get("local_backend") == BACKEND_MLX:
                    default_model = "mlx-community/Qwen2.5-Coder-32B-Instruct-4bit"
                settings["local_model"] = _prompt("Model name", default_model)
            settings["model"] = settings["local_model"]
        else:
            # No local backend — fall through to cloud options
            print("\nFalling back to cloud provider selection.")
            choice = _choose("Select Cloud Provider:", [
                "z.ai GLM",
                "OpenAI-compatible API",
            ])
            if choice == 0:
                settings["llm_url"] = "https://api.z.ai/api/coding/paas/v4"
                settings["llm_api_key"] = _prompt("z.ai API Key")
                settings["model"] = _prompt("Model name", "glm-5.1")
            else:
                settings["llm_url"] = _prompt("API Base URL", "https://api.openai.com/v1")
                settings["llm_api_key"] = _prompt("API Key")
                settings["model"] = _prompt("Model name", "gpt-4o")

    elif choice == 1:
        # MLX explicit
        all_runtimes = detect_all_runtimes()
        mlx = next((r for r in all_runtimes if r.backend == BACKEND_MLX), None)
        if mlx and mlx.available:
            from .config import apply_detected_backend
            settings.update(apply_detected_backend(settings, mlx, all_runtimes))
            settings["local_model"] = _prompt("Model name", "mlx-community/Qwen2.5-Coder-32B-Instruct-4bit")
            settings["model"] = settings["local_model"]
        else:
            print(f"\nMLX not available. Install: {get_install_hints(BACKEND_MLX)}")
            print("Also ensure mlx_lm.server is running: mlx_lm.server --model <model>")
            return

    elif choice == 2:
        # llama.cpp explicit
        all_runtimes = detect_all_runtimes()
        lcpp = next((r for r in all_runtimes if r.backend == BACKEND_LLAMA_CPP), None)
        if lcpp and lcpp.available:
            from .config import apply_detected_backend
            settings.update(apply_detected_backend(settings, lcpp, all_runtimes))
            settings["local_model"] = _prompt("Model name", "")
            settings["model"] = settings["local_model"]
        else:
            print(f"\nllama.cpp not available. Install: {get_install_hints(BACKEND_LLAMA_CPP)}")
            print("Also ensure llama-server is running: llama-server -m <model.gguf> --port 8081")
            return

    elif choice == 3:
        # Ollama explicit
        all_runtimes = detect_all_runtimes()
        ollama = next((r for r in all_runtimes if r.backend == BACKEND_OLLAMA), None)
        if ollama and ollama.available:
            from .config import apply_detected_backend
            settings.update(apply_detected_backend(settings, ollama, all_runtimes))
            settings["local_model"] = _prompt("Model name", "qwen3-coder:30b")
            settings["model"] = settings["local_model"]
        else:
            print(f"\nOllama not available. Install: {get_install_hints(BACKEND_OLLAMA)}")
            print("Also ensure Ollama is running: ollama serve")
            return

    elif choice == 4:
        # z.ai GLM
        settings["llm_url"] = "https://api.z.ai/api/coding/paas/v4"
        settings["llm_api_key"] = _prompt("z.ai API Key")
        settings["model"] = _prompt("Model name", "glm-5.1")

    else:
        # OpenAI-compatible
        settings["llm_url"] = _prompt("API Base URL", "https://api.openai.com/v1")
        settings["llm_api_key"] = _prompt("API Key")
        settings["model"] = _prompt("Model name", "gpt-4o")

    # 2. Gateway settings
    print("\n--- Gateway Settings ---")
    settings["gateway_url"] = _prompt("Gateway URL", "http://localhost:8765")

    gw_key_choice = _choose("Gateway API Key:", ["Auto-generate (recommended)", "Enter manually"])
    if gw_key_choice == 0:
        settings["gateway_api_key"] = _generate_api_key()
        print(f"  Generated API Key: {settings['gateway_api_key']}")
    else:
        settings["gateway_api_key"] = _prompt("Gateway API Key")

    # 3. max_turns
    max_turns_str = _prompt("Max turns", "200")
    settings["max_turns"] = int(max_turns_str)

    # 4. Save
    settings_path = GLOBAL_SETTINGS_PATH
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nSettings saved: {settings_path}")

    # 5. DB initialization (migration)
    print("\nInitializing DB...")
    try:
        from .gateway.db import init_db
        asyncio.run(init_db())
        print("DB initialization complete")

        # Register Gateway API key in DB
        from .gateway.db import create_api_key
        asyncio.run(create_api_key(settings["gateway_api_key"], "admin", grant_all_platforms=True))
        print("Gateway API key registered")
    except Exception as e:
        print(f"DB init skipped (auto-created on Gateway start): {e}")

    # 6. Completion message
    backend_info = ""
    if settings.get("local_backend"):
        backend_info = f"""
Local backend:
  {settings['local_backend']} ({settings.get('local_llm_url', '')})"""

    print("\n" + "=" * 50)
    print("  Setup complete!")
    print("=" * 50)
    print(f"""
Start command:
  hermit_agent-gateway

Test:
  curl -H "Authorization: Bearer {settings['gateway_api_key']}" http://localhost:8765/models
{backend_info}
Settings file:
  {settings_path}
""")


def main() -> None:
    try:
        run_setup()
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(1)


if __name__ == "__main__":
    main()
