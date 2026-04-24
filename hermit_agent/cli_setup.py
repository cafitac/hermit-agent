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


def run_setup() -> None:
    print("=" * 50)
    print("  HermitAgent Setup Wizard")
    print("=" * 50)
    print()

    settings = dict(DEFAULTS)

    # 1. LLM Provider selection
    providers = [
        "ollama (local LLM)",
        "z.ai GLM (cloud)",
        "OpenAI-compatible API",
    ]
    choice = _choose("Select LLM Provider:", providers)

    if choice == 0:
        # ollama
        settings["llm_url"] = "http://localhost:11434/v1"
        settings["llm_api_key"] = ""
        settings["model"] = _prompt("Model name", "qwen3-coder:30b")
    elif choice == 1:
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
        asyncio.run(create_api_key(settings["gateway_api_key"], "admin"))
        print("Gateway API key registered")
    except Exception as e:
        print(f"DB init skipped (auto-created on Gateway start): {e}")

    # 6. Completion message
    print("\n" + "=" * 50)
    print("  Setup complete!")
    print("=" * 50)
    print(f"""
Start command:
  hermit_agent-gateway

Test:
  curl -H "Authorization: Bearer {settings['gateway_api_key']}" http://localhost:8765/models

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
