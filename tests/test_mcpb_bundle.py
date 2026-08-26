from __future__ import annotations

import json
from pathlib import Path

from scripts.build_mcpb import MCPB_SOURCE, prepare_bundle_directory, project_version


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_mcpb_source_declares_a_uv_launcher_for_supported_desktop_platforms() -> None:
    manifest = json.loads((MCPB_SOURCE / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["manifest_version"] == "0.4"
    assert manifest["server"] == {
        "type": "uv",
        "entry_point": "server.py",
        "mcp_config": {
            "command": "uv",
            "args": ["run", "--directory", "${__dirname}", "server.py"],
            "env": {
                "HERMIT_DESKTOP_EXECUTOR_MODEL": "${user_config.executor_model}",
                "HERMIT_DESKTOP_EXECUTOR_BASE_URL": "${user_config.executor_base_url}",
                "HERMIT_DESKTOP_EXECUTOR_API_KEY": "${user_config.executor_api_key}",
            },
        },
    }
    assert manifest["compatibility"]["platforms"] == ["darwin", "win32"]
    assert [tool["name"] for tool in manifest["tools"]] == [
        "run_task",
        "check_task",
        "reply_task",
        "cancel_task",
    ]
    assert manifest["user_config"]["executor_api_key"]["sensitive"] is True


def test_prepared_mcpb_directory_pins_the_matching_pypi_runtime(tmp_path) -> None:
    version = project_version()
    bundle = prepare_bundle_directory(tmp_path / "bundle", version=version)

    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    pyproject = (bundle / "pyproject.toml").read_text(encoding="utf-8")

    assert manifest["version"] == version
    assert f'cafitac-hermit-agent=={version}' in pyproject
    assert (bundle / "server.py").read_text(encoding="utf-8") == (MCPB_SOURCE / "server.py").read_text(encoding="utf-8")
    assert "init_settings_file()" in (bundle / "server.py").read_text(encoding="utf-8")


def test_readme_documents_the_three_supported_host_install_paths() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "### Claude Code" in readme
    assert "### Codex" in readme
    assert "### Claude Desktop" in readme
    assert ".mcpb" in readme
