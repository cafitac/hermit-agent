from __future__ import annotations

import json

from hermit_agent.pending_interactions import (
    PendingInteraction,
    PendingOption,
    _resolve_cli_answer,
    _resolve_interaction_reply,
    _summarize_interaction,
    build_idle_operator_overview,
    _presentable_options,
    _presentable_question,
    build_operator_status_summary,
    build_pending_interaction_summary,
    get_pending_interactions,
    get_latest_pending_interaction,
    maybe_handle_pending_interaction,
    run_pending_interaction_loop,
)
from hermit_agent.tui_render import compact_count_label, ellipsize_segment, sanitize_dynamic_text, strip_ansi, visible_length


def test_resolve_cli_answer_maps_numeric_selection_to_option():
    options = [PendingOption(label="Yes", value="yes"), PendingOption(label="No", value="no")]
    assert _resolve_cli_answer("2", options) == "no"
    assert _resolve_cli_answer(" yes ", options) == "yes"


def test_get_latest_pending_interaction_reads_state_file(tmp_path, monkeypatch):
    state_dir = tmp_path / ".codex-channels"
    state_dir.mkdir()
    state_file = state_dir / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "interactions": [
                    {
                        "id": "older",
                        "kind": "user_input_request",
                        "payload": {"message": "Older question", "options": ["a"]},
                        "createdAt": "2026-01-01T00:00:00Z",
                        "status": "pending",
                    },
                    {
                        "id": "latest",
                        "kind": "approval_request",
                        "payload": {
                            "message": "Latest question",
                            "options": [{"label": "Yes (once)", "value": "yes"}],
                        },
                        "createdAt": "2026-01-01T00:00:01Z",
                        "status": "delivered",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "hermit_agent.pending_interactions.load_settings",
        lambda cwd=None: {
            "codex_channels": {
                "enabled": True,
                "host": "127.0.0.1",
                "port": 4317,
                "state_file": str(state_file),
            }
        },
    )

    interaction = get_latest_pending_interaction(cwd=str(tmp_path))

    assert interaction is not None
    assert interaction.interaction_id == "latest"
    assert interaction.question == "Latest question"
    assert interaction.options == [PendingOption(label="Yes (once)", value="yes")]
    assert interaction.kind == "approval_request"


def test_get_pending_interactions_returns_sorted_actionable_items(tmp_path, monkeypatch):
    state_dir = tmp_path / ".codex-channels"
    state_dir.mkdir()
    state_file = state_dir / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "interactions": [
                    {
                        "id": "ignore-progress",
                        "kind": "progress_update",
                        "payload": {"message": "ignore"},
                        "createdAt": "2026-01-01T00:00:00Z",
                        "status": "delivered",
                    },
                    {
                        "id": "later",
                        "kind": "user_input_request",
                        "payload": {"message": "Later"},
                        "createdAt": "2026-01-01T00:00:02Z",
                        "status": "pending",
                    },
                    {
                        "id": "earlier",
                        "kind": "approval_request",
                        "payload": {"message": "Earlier"},
                        "createdAt": "2026-01-01T00:00:01Z",
                        "status": "delivered",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "hermit_agent.pending_interactions.load_settings",
        lambda cwd=None: {
            "codex_channels": {
                "enabled": True,
                "host": "127.0.0.1",
                "port": 4317,
                "state_file": str(state_file),
            }
        },
    )

    interactions = get_pending_interactions(cwd=str(tmp_path))

    assert [item.interaction_id for item in interactions] == ["later", "earlier"]


def test_summarize_interaction_prefixes_kind_and_truncates():
    interaction = PendingInteraction(
        interaction_id="i1",
        kind="approval_request",
        question="x" * 120,
        options=[],
        host="127.0.0.1",
        port=4317,
        state_file="/tmp/state.json",
    )

    summary = _summarize_interaction(interaction, max_chars=20)

    assert summary.startswith("[approval_request] ")
    assert "…" in summary


def test_tui_render_helpers_sanitize_and_ellipsize():
    raw = "안녕\x00하세요\x1b[31m!!!\x1b[0m"
    sanitized = sanitize_dynamic_text(raw)
    assert "\x00" not in sanitized
    assert strip_ansi(sanitized) == "안녕하세요!!!"
    assert visible_length(sanitized) == len("안녕하세요!!!")
    assert ellipsize_segment("abcdefghijklmnopqrstuvwxyz", 8) == "abcd…xyz"
    assert compact_count_label("count", 1530) == "count:1.5k"


def test_build_pending_interaction_summary_handles_empty_and_nonempty_lists(tmp_path, monkeypatch):
    monkeypatch.setattr("hermit_agent.pending_interactions.get_pending_interactions", lambda **kwargs: [])
    assert "No pending interactions" in build_pending_interaction_summary(cwd=str(tmp_path))

    interactions = [
        PendingInteraction(
            interaction_id="first",
            question="Need approval",
            options=[PendingOption(label="yes", value="yes"), PendingOption(label="no", value="no")],
            kind="approval_request",
            host="127.0.0.1",
            port=4317,
            state_file=str(tmp_path / "state.json"),
        )
    ]
    monkeypatch.setattr("hermit_agent.pending_interactions.get_pending_interactions", lambda **kwargs: interactions)
    summary = build_pending_interaction_summary(cwd=str(tmp_path))
    assert "Pending interactions (count:1):" in summary
    assert "[approval_request] Need approval" in summary


def test_build_operator_status_summary_reports_gateway_mcp_codex_and_pending(tmp_path, monkeypatch):
    interaction = PendingInteraction(
        interaction_id="first",
        question="Need approval",
        options=[PendingOption(label="yes", value="yes"), PendingOption(label="no", value="no")],
        kind="approval_request",
        host="127.0.0.1",
        port=4317,
        state_file=str(tmp_path / "state.json"),
    )

    class Heal:
        gateway_status = "healthy"
        mcp_registration_status = "registered"
        codex_runtime_status = "installed"

    monkeypatch.setattr("hermit_agent.pending_interactions.run_startup_self_heal", lambda **kwargs: Heal())
    monkeypatch.setattr("hermit_agent.pending_interactions.get_pending_interactions", lambda **kwargs: [interaction])

    summary = build_operator_status_summary(cwd=str(tmp_path))

    assert "[Hermit] Status" in summary
    assert "- gateway: healthy" in summary
    assert "- mcp registration: registered" in summary
    assert "- codex integration: installed" in summary
    assert "- codex-facing surface: hermit-channel MCP" in summary
    assert "- pending interactions: count:1" in summary
    assert "[approval_request] Need approval" in summary


def test_build_idle_operator_overview_reports_recommended_action(tmp_path, monkeypatch):
    interaction = PendingInteraction(
        interaction_id="first",
        question="Need approval",
        options=[PendingOption(label="yes", value="yes"), PendingOption(label="no", value="no")],
        kind="approval_request",
        host="127.0.0.1",
        port=4317,
        state_file=str(tmp_path / "state.json"),
    )

    class Heal:
        gateway_status = "healthy"
        mcp_registration_status = "registered"
        codex_runtime_status = "installed"

    monkeypatch.setattr("hermit_agent.pending_interactions.run_startup_self_heal", lambda **kwargs: Heal())
    monkeypatch.setattr("hermit_agent.pending_interactions.get_pending_interactions", lambda **kwargs: [interaction])

    overview = build_idle_operator_overview(cwd=str(tmp_path))

    assert "[Hermit] Ready" in overview
    assert "codex:installed" in overview
    assert "pending:1" in overview
    assert "recommended: answer pending interactions" in overview


def test_maybe_handle_pending_interaction_prompts_and_replies(tmp_path, monkeypatch, capsys):
    interaction = PendingInteraction(
        interaction_id="pending-1",
        question="Allow?",
        options=[PendingOption(label="Yes", value="yes"), PendingOption(label="No", value="no")],
        kind="approval_request",
        host="127.0.0.1",
        port=4317,
        state_file=str(tmp_path / "state.json"),
    )

    class DummyChannel:
        def _present_question(self, question, options):
            assert question == "Allow?"
            assert options == ["Yes", "No"]
            return "1"

    sent: list[str] = []

    monkeypatch.setattr("hermit_agent.pending_interactions.get_pending_interactions", lambda **kwargs: [interaction])
    monkeypatch.setattr("hermit_agent.pending_interactions.CLIChannel", DummyChannel)
    monkeypatch.setattr("hermit_agent.pending_interactions._ensure_runtime", lambda interaction, cwd: None)
    monkeypatch.setattr("hermit_agent.pending_interactions._send_reply", lambda interaction, answer: sent.append(answer))

    handled = maybe_handle_pending_interaction(cwd=str(tmp_path))

    assert handled is True
    assert sent == ["yes"]
    assert "Replied to pending interaction pending-1." in capsys.readouterr().out


def test_maybe_handle_pending_interaction_allows_selecting_from_multiple_items(tmp_path, monkeypatch, capsys):
    first = PendingInteraction(
        interaction_id="first",
        question="First?",
        options=[PendingOption(label="Yes", value="yes"), PendingOption(label="No", value="no")],
        kind="approval_request",
        host="127.0.0.1",
        port=4317,
        state_file=str(tmp_path / "state.json"),
    )
    second = PendingInteraction(
        interaction_id="second",
        question="Second?",
        options=[PendingOption(label="A", value="a"), PendingOption(label="B", value="b")],
        kind="user_input_request",
        host="127.0.0.1",
        port=4317,
        state_file=str(tmp_path / "state.json"),
    )

    answers = iter(["2", "1"])

    class DummyChannel:
        def _present_question(self, question, options):
            return next(answers)

    sent: list[tuple[str, str]] = []

    monkeypatch.setattr("hermit_agent.pending_interactions.get_pending_interactions", lambda **kwargs: [first, second])
    monkeypatch.setattr("hermit_agent.pending_interactions.CLIChannel", DummyChannel)
    monkeypatch.setattr("hermit_agent.pending_interactions._ensure_runtime", lambda interaction, cwd: None)
    monkeypatch.setattr("hermit_agent.pending_interactions._send_reply", lambda interaction, answer: sent.append((interaction.interaction_id, answer)))

    handled = maybe_handle_pending_interaction(cwd=str(tmp_path))

    assert handled is True
    assert sent == [("second", "a")]
    assert "Replied to pending interaction second." in capsys.readouterr().out


def test_run_pending_interaction_loop_can_continue_for_multiple_items(tmp_path, monkeypatch):
    first = PendingInteraction(
        interaction_id="first",
        question="First?",
        options=[PendingOption(label="yes", value="yes"), PendingOption(label="no", value="no")],
        kind="approval_request",
        host="127.0.0.1",
        port=4317,
        state_file=str(tmp_path / "state.json"),
    )
    second = PendingInteraction(
        interaction_id="second",
        question="Second?",
        options=[PendingOption(label="left", value="left"), PendingOption(label="right", value="right")],
        kind="user_input_request",
        host="127.0.0.1",
        port=4317,
        state_file=str(tmp_path / "state.json"),
    )

    snapshots = iter([[first, second], [second], []])
    monkeypatch.setattr("hermit_agent.pending_interactions.get_pending_interactions", lambda **kwargs: next(snapshots))

    asked = iter(["yes"])

    class DummyChannel:
        def _present_question(self, question, options):
            return next(asked)

    monkeypatch.setattr("hermit_agent.pending_interactions.CLIChannel", DummyChannel)

    handled_order = iter([True, True])
    monkeypatch.setattr("hermit_agent.pending_interactions.maybe_handle_pending_interaction", lambda **kwargs: next(handled_order))

    assert run_pending_interaction_loop(cwd=str(tmp_path)) is True


def test_presentable_question_and_options_support_header_and_description():
    interaction = PendingInteraction(
        interaction_id="i1",
        header="Permission request",
        question="Choose a path",
        options=[
            PendingOption(label="Proceed", value="proceed", description="Continue with the current plan"),
            PendingOption(label="Revise", value="revise"),
        ],
        kind="approval_request",
        host="127.0.0.1",
        port=4317,
        state_file="/tmp/state.json",
        allow_other=True,
        other_label="Other",
    )

    assert _presentable_question(interaction) == "Permission request\nChoose a path"
    assert _presentable_options(interaction) == [
        "Proceed — Continue with the current plan",
        "Revise",
        "Other",
    ]


def test_resolve_interaction_reply_supports_other_text():
    interaction = PendingInteraction(
        interaction_id="i1",
        question="Choose",
        options=[PendingOption(label="Proceed", value="proceed")],
        kind="user_input_request",
        host="127.0.0.1",
        port=4317,
        state_file="/tmp/state.json",
        allow_other=True,
        other_label="Other",
    )

    answers = iter(["2", "free-form"])

    class DummyChannel:
        def _present_question(self, question, options):
            return next(answers)

    assert _resolve_interaction_reply(DummyChannel(), interaction) == "free-form"
