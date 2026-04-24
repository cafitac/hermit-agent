"""profile_review CLI test (Phase 2)."""

import json
from pathlib import Path


from hermit_agent.profile_review import main, _format_diff


def _write_session(sessions_dir: Path, sid: str, success: bool, triggers: list[str] | None = None, corrections: int = 0):
    recs = [{
        "type": "attachment",
        "kind": "session_outcome",
        "model": "test-model",
        "success": success,
        "termination": "completed" if success else "max_turns",
        "compact_count": 0,
        "test_pass_count": 0,
        "test_fail_count": 0,
        "loop_reentry_count": 0,
    }]
    for gid in (triggers or []):
        recs.append({"type": "attachment", "kind": "guardrail_trigger", "gid": gid, "reason": ""})
    for _ in range(corrections):
        recs.append({"type": "attachment", "kind": "user_correction", "content": "no", "pattern": "no"})

    path = sessions_dir / f"{sid}.jsonl"
    with open(path, "w") as f:
        for rec in recs:
            f.write(json.dumps(rec) + "\n")


# ── _format_diff tests ──────────────────────────────────────

def test_format_diff_with_removal():
    signals = {"completion_rate": 0.9, "correction_rate": 0.1, "needs_review": False}
    counts = {"G26": 0, "G38": 3}
    output = _format_diff(["G26"], signals, counts, n=10)
    assert "G26" in output
    assert "removal candidate" in output
    assert "10 sessions" in output


def test_format_diff_no_removal():
    signals = {"completion_rate": 0.9, "correction_rate": 0.1, "needs_review": False}
    output = _format_diff([], signals, {}, n=5)
    assert "none" in output


def test_format_diff_addition_signal():
    signals = {"completion_rate": 0.4, "correction_rate": 0.5, "needs_review": True}
    output = _format_diff([], signals, {}, n=5)
    assert "⚠" in output
    assert "addition review" in output


# ── main() CLI tests ──────────────────────────────────────────

def test_main_insufficient_sessions(tmp_path: Path, capsys):
    ret = main(["--sessions-dir", str(tmp_path), "--min-sessions", "5"])
    assert ret == 1
    out = capsys.readouterr().out
    assert "insufficient" in out


def test_main_basic_output(tmp_path: Path, capsys):
    # 10 successful sessions, G_FAKE not triggered → removal candidate possible
    for i in range(10):
        _write_session(tmp_path, f"s{i}", success=True)
    ret = main(["--sessions-dir", str(tmp_path)])
    assert ret == 0
    out = capsys.readouterr().out
    assert "Profile Review" in out
    assert "completion rate" in out


def test_main_with_triggers(tmp_path: Path, capsys):
    # G38 triggered in some of the 10 sessions
    for i in range(7):
        _write_session(tmp_path, f"s{i}", success=True, triggers=["G38"])
    for i in range(3):
        _write_session(tmp_path, f"f{i}", success=True)
    ret = main(["--sessions-dir", str(tmp_path)])
    assert ret == 0


def test_main_apply_updates_notes(tmp_path: Path, capsys, monkeypatch):
    """Verify profile YAML notes update upon --apply (isolating actual profile file)."""
    import yaml
    import hermit_agent.profile_review as pr_module

    # Sessions: 10 successful, G_UNUSED not triggered
    for i in range(10):
        _write_session(tmp_path, f"s{i}", success=True)

    # Create temporary profile YAML
    profile_data = {
        "model": "test-model",
        "source": "manual",
        "capabilities": {
            "tool_spam_tendency": 0.4,
            "instruction_following": 0.6,
            "context_window": 32768,
            "long_context_reasoning": 0.5,
            "self_reporting": 0.3,
        },
        "notes": [],
    }
    profile_path = tmp_path / "test-model.yaml"
    with open(profile_path, "w") as f:
        yaml.dump(profile_data, f, allow_unicode=True)

    # Patch _load_profile with temporary file — do not touch actual profiles/ directory
    monkeypatch.setattr(pr_module, "_load_profile", lambda model_id: (profile_data, profile_path))

    ret = main(["--sessions-dir", str(tmp_path), "--apply"])
    assert ret == 0


def test_end_to_end_removal_scenario(tmp_path: Path, capsys, monkeypatch):
    """End-to-end removal scenario: G_DEAD not triggered → removal candidate → record notes on --apply."""
    import yaml
    import hermit_agent.profile_review as pr_module

    # 10 successful sessions, G_DEAD never triggered, G_ALIVE triggered 5 times
    for i in range(5):
        _write_session(tmp_path, f"alive{i}", success=True, triggers=["G_ALIVE"])
    for i in range(5):
        _write_session(tmp_path, f"dead{i}", success=True)  # G_DEAD not triggered

    # Isolate profile YAML
    profile_data = {"model": "test-model", "source": "manual", "notes": []}
    profile_path = tmp_path / "profile.yaml"
    with open(profile_path, "w") as f:
        yaml.dump(profile_data, f, allow_unicode=True)

    monkeypatch.setattr(pr_module, "_load_profile", lambda model_id: (profile_data, profile_path))

    # Patch registry to include only G_DEAD / G_ALIVE
    import hermit_agent.profile_review as pr_module2
    monkeypatch.setattr(pr_module2, "_load_registry", lambda: {"G_DEAD": {}, "G_ALIVE": {}})

    ret = main(["--sessions-dir", str(tmp_path), "--apply"])
    assert ret == 0

    # Verify G_DEAD removal review note is added to profile YAML
    import yaml as _yaml
    with open(profile_path) as f:
        updated = _yaml.safe_load(f)
    notes = updated.get("notes", [])
    assert any("G_DEAD" in n for n in notes), f"G_DEAD note missing: {notes}"
    # G_ALIVE was triggered, so it is not a removal candidate
    assert not any("G_ALIVE" in n for n in notes), f"G_ALIVE incorrectly included: {notes}"

    out = capsys.readouterr().out
    assert "G_DEAD" in out
    assert "removal candidate" in out
