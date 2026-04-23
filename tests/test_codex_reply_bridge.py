from __future__ import annotations

import json
from pathlib import Path


def test_remove_codex_reply_hook_prunes_legacy_entry(tmp_path: Path):
    from hermit_agent.install_flow import remove_codex_reply_hook

    hooks_path = tmp_path / "hooks.json"
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": str((Path("/tmp/demo")).resolve() / "bin" / "codex-reply-hook.sh"),
                                }
                            ]
                        },
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/tmp/another-hook.sh",
                                }
                            ]
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    status = remove_codex_reply_hook(cwd="/tmp/demo", hooks_json_path=hooks_path)

    payload = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert status == "removed"
    retained = payload["hooks"]["UserPromptSubmit"]
    assert len(retained) == 1
    assert retained[0]["hooks"][0]["command"] == "/tmp/another-hook.sh"


def test_remove_codex_reply_hook_preserves_sibling_hooks_in_same_entry(tmp_path: Path):
    from hermit_agent.install_flow import remove_codex_reply_hook

    hooks_path = tmp_path / "hooks.json"
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": str((Path("/tmp/demo")).resolve() / "bin" / "codex-reply-hook.sh"),
                                },
                                {
                                    "type": "command",
                                    "command": "/tmp/keep-me.sh",
                                },
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    status = remove_codex_reply_hook(cwd="/tmp/demo", hooks_json_path=hooks_path)

    payload = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert status == "removed"
    retained = payload["hooks"]["UserPromptSubmit"]
    assert len(retained) == 1
    assert retained[0]["hooks"] == [{"type": "command", "command": "/tmp/keep-me.sh"}]


def test_remove_codex_reply_hook_returns_absent_when_not_installed(tmp_path: Path):
    from hermit_agent.install_flow import remove_codex_reply_hook

    hooks_path = tmp_path / "hooks.json"
    hooks_path.write_text(json.dumps({"hooks": {"UserPromptSubmit": []}}), encoding="utf-8")

    status = remove_codex_reply_hook(cwd="/tmp/demo", hooks_json_path=hooks_path)

    assert status == "absent"
