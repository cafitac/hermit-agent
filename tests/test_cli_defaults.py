"""Tests for CLI argument defaults in hermit_agent.__main__."""
from hermit_agent.__main__ import (
    _render_idle_menu_state,
    _run_idle_menu,
    _run_idle_menu_loop,
    _run_status_watch,
    _resolve_api_key,
    _resolve_model,
    _should_auto_use_cli_channel,
    parse_args,
)


class TestDefaultBaseUrl:
    def test_default_base_url_is_gateway(self):
        """--base-url default must point to the local Hermit gateway, not Ollama."""
        ns = parse_args([])
        assert ns.base_url == "http://localhost:8765/v1"

    def test_custom_base_url_overrides_default(self):
        ns = parse_args(["--base-url", "http://x"])
        assert ns.base_url == "http://x"


class TestDefaultApiKey:
    """--api-key falls through: CLI flag > HERMIT_API_KEY env > settings.json::gateway_api_key."""

    def test_cli_flag_wins(self, monkeypatch):
        monkeypatch.setenv("HERMIT_API_KEY", "env-tok")
        ns = parse_args(["--api-key", "cli-tok"])
        assert _resolve_api_key(ns) == "cli-tok"

    def test_env_var_fallback(self, monkeypatch):
        monkeypatch.setenv("HERMIT_API_KEY", "env-tok")
        ns = parse_args([])
        assert _resolve_api_key(ns) == "env-tok"

    def test_none_when_env_and_settings_missing(self, monkeypatch, tmp_path):
        monkeypatch.delenv("HERMIT_API_KEY", raising=False)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("hermit_agent.config.GLOBAL_SETTINGS_PATH", tmp_path / "nope.json")
        ns = parse_args([])
        assert _resolve_api_key(ns) is None


class TestDefaultModel:
    def test_cli_flag_wins(self):
        ns = parse_args(["--model", "custom-model"])
        assert _resolve_model(ns) == "custom-model"

    def test_fallback_to_hardcoded_default_when_settings_empty(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("hermit_agent.config.GLOBAL_SETTINGS_PATH", tmp_path / "nope.json")
        ns = parse_args([])
        assert _resolve_model(ns) == "qwen3-coder:30b"

    def test_auto_model_uses_first_available_priority_model(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "hermit_agent.config.load_settings",
            lambda cwd=None: {
                "model": "__auto__",
                "routing": {"priority_models": [{"model": "glm-5.1"}, {"model": "gpt-5.4", "reasoning_effort": "medium"}]},
            },
        )
        monkeypatch.setattr("hermit_agent.config.get_primary_model", lambda cfg, available_only=False: "glm-5.1")
        ns = parse_args([])
        assert _resolve_model(ns) == "glm-5.1"


def test_install_parser_defaults_codex_scope_to_user():
    from hermit_agent.__main__ import _build_install_parser

    ns = _build_install_parser().parse_args([])

    assert ns.codex_scope == "user"


def test_install_parser_can_skip_agent_learner_for_smoke_runs():
    from hermit_agent.__main__ import _build_install_parser

    ns = _build_install_parser().parse_args(["--skip-agent-learner"])

    assert ns.skip_agent_learner is True


def test_install_parser_can_print_hermes_mcp_config_without_mutating_state():
    from hermit_agent.__main__ import _build_install_parser

    ns = _build_install_parser().parse_args(["--print-hermes-mcp-config"])

    assert ns.print_hermes_mcp_config is True


def test_main_dispatches_install(monkeypatch, capsys):
    from hermit_agent import __main__ as main_mod
    from hermit_agent.install_flow import InstallSummary

    seen = []
    monkeypatch.setattr(
        main_mod.sys,
        "argv",
        ["hermit-agent", "install", "--cwd", "/tmp/demo", "--yes", "--skip-agent-learner"],
    )

    def fake_run_install(**kwargs):
        seen.append(kwargs)
        return InstallSummary(
            settings_path="/tmp/settings.json",
            gateway_api_key_created=True,
            gateway_api_key_present=True,
            mcp_registration_status="registered",
            codex_install_status="installed",
        )

    monkeypatch.setattr(
        "hermit_agent.install_flow.run_install",
        fake_run_install,
    )

    main_mod.main()

    assert "Hermit install is ready." in capsys.readouterr().out
    assert seen == [
        {
            "cwd": "/tmp/demo",
            "codex_command": "codex",
            "codex_scope": "user",
            "assume_yes": True,
            "skip_mcp_register": False,
            "skip_codex": False,
            "skip_agent_learner": True,
        }
    ]


def test_main_prints_hermes_mcp_config_without_running_install(monkeypatch, capsys):
    from hermit_agent import __main__ as main_mod

    monkeypatch.setattr(main_mod.sys, "argv", ["hermit-agent", "install", "--print-hermes-mcp-config", "--cwd", "/tmp/demo"])
    monkeypatch.setattr("hermit_agent.install_flow.run_install", lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not install")))

    main_mod.main()

    out = capsys.readouterr().out
    assert "Hermit MCP for Hermes Agent" in out
    assert "hermes mcp add hermit-channel" in out


def test_main_dispatches_mcp_server(monkeypatch):
    from hermit_agent import __main__ as main_mod

    seen = []
    monkeypatch.setattr(main_mod.sys, "argv", ["hermit-agent", "mcp-server", "--http", "3737"])
    monkeypatch.setattr("hermit_agent.mcp_launcher.main", lambda: seen.append(list(main_mod.sys.argv)))

    main_mod.main()

    assert seen == [["hermit-agent", "--http", "3737"]]


def test_main_dispatches_pending(monkeypatch, capsys):
    from hermit_agent import __main__ as main_mod

    monkeypatch.setattr(main_mod.sys, "argv", ["hermit-agent", "pending", "--cwd", "/tmp/demo"])
    monkeypatch.setattr("hermit_agent.pending_interactions.build_pending_interaction_summary", lambda **kwargs: "[Hermit] Pending interactions:")

    main_mod.main()

    assert "[Hermit] Pending interactions:" in capsys.readouterr().out


def test_main_dispatches_status(monkeypatch, capsys):
    from hermit_agent import __main__ as main_mod

    monkeypatch.setattr(main_mod.sys, "argv", ["hermit-agent", "status", "--cwd", "/tmp/demo"])
    monkeypatch.setattr("hermit_agent.pending_interactions.build_operator_status_summary", lambda **kwargs: "[Hermit] Status")

    main_mod.main()

    assert "[Hermit] Status" in capsys.readouterr().out


def test_main_dispatches_status_watch(monkeypatch):
    from hermit_agent import __main__ as main_mod

    monkeypatch.setattr(main_mod.sys, "argv", ["hermit-agent", "status", "--cwd", "/tmp/demo", "--watch", "--interval", "0.2"])
    seen = []
    monkeypatch.setattr("hermit_agent.__main__._run_status_watch", lambda **kwargs: seen.append(kwargs))

    main_mod.main()

    assert seen == [{"cwd": "/tmp/demo", "interval": 0.2}]


def test_main_dispatches_doctor(monkeypatch, capsys):
    from hermit_agent import __main__ as main_mod

    monkeypatch.setattr(main_mod.sys, "argv", ["hermit-agent", "doctor", "--cwd", "/tmp/demo"])

    class DummyReport:
        def format(self):
            return "HermitAgent Doctor — overall: PASS"

    monkeypatch.setattr("hermit_agent.doctor.run_diagnostics", lambda **kwargs: DummyReport())

    main_mod.main()

    assert "HermitAgent Doctor — overall: PASS" in capsys.readouterr().out


def test_main_dispatches_doctor_fix(monkeypatch, capsys):
    from hermit_agent import __main__ as main_mod

    monkeypatch.setattr(main_mod.sys, "argv", ["hermit-agent", "doctor", "--cwd", "/tmp/demo", "--fix"])
    monkeypatch.setattr("hermit_agent.doctor.format_doctor_fix_summary", lambda **kwargs: "Hermit doctor --fix complete.")

    main_mod.main()

    assert "Hermit doctor --fix complete." in capsys.readouterr().out


def test_main_prints_startup_self_heal_summary_when_repairs_happen(monkeypatch, capsys):
    from hermit_agent import __main__ as main_mod
    from hermit_agent.install_flow import StartupHealSummary

    monkeypatch.setattr(main_mod.sys, "argv", ["hermit-agent", "hello"])
    monkeypatch.setattr(
        "hermit_agent.install_flow.run_startup_self_heal",
        lambda **kwargs: StartupHealSummary(
            settings_initialized=True,
            gateway_api_key_created=False,
            gateway_status="started",
            mcp_registration_status="missing",
            codex_runtime_status="missing",
        ),
    )
    monkeypatch.setattr("hermit_agent.install_flow.format_startup_heal_summary", lambda summary: "[Hermit startup self-heal]")
    monkeypatch.setattr("hermit_agent.__main__._resolve_api_key", lambda args: "tok")
    monkeypatch.setattr("hermit_agent.__main__._resolve_model", lambda args: "model")

    class DummyLLM:
        model = "model"
        fallback_model = None

    class DummyAgent:
        streaming = False
        messages = []
        turn_count = 0
        session_id = "sid"

    class DummySession:
        def __init__(self, **kwargs):
            self._agent = DummyAgent()

        def run(self, message):
            return "ok"

    monkeypatch.setattr("hermit_agent.__main__.create_llm_client", lambda **kwargs: DummyLLM())
    monkeypatch.setattr("hermit_agent.__main__.CLIAgentSession", DummySession)

    main_mod.main()

    captured = capsys.readouterr()
    assert "[Hermit startup self-heal]" in captured.err


def test_auto_cli_channel_enables_for_interactive_one_shot(monkeypatch):
    ns = parse_args(["hello"])
    monkeypatch.setattr("hermit_agent.__main__._stdio_interactive", lambda: True)

    assert _should_auto_use_cli_channel(ns) is True


def test_auto_cli_channel_stays_disabled_without_message_or_with_explicit_channel(monkeypatch):
    monkeypatch.setattr("hermit_agent.__main__._stdio_interactive", lambda: True)

    assert _should_auto_use_cli_channel(parse_args([])) is False
    assert _should_auto_use_cli_channel(parse_args(["hello", "--channel", "cli"])) is False


def test_main_uses_cli_channel_automatically_for_interactive_one_shot(monkeypatch, capsys):
    from hermit_agent import __main__ as main_mod
    from hermit_agent.install_flow import StartupHealSummary

    monkeypatch.setattr(main_mod.sys, "argv", ["hermit-agent", "hello"])
    monkeypatch.setattr("hermit_agent.install_flow.run_startup_self_heal", lambda **kwargs: StartupHealSummary())
    monkeypatch.setattr("hermit_agent.__main__._stdio_interactive", lambda: True)
    monkeypatch.setattr("hermit_agent.__main__._resolve_api_key", lambda args: "tok")
    monkeypatch.setattr("hermit_agent.__main__._resolve_model", lambda args: "model")

    class DummyLLM:
        model = "model"
        fallback_model = None

    created_channels = []

    class DummyChannel:
        def __init__(self):
            created_channels.append(self)

        def start(self):
            pass

        def stop(self):
            pass

        def make_progress_hook(self):
            return None

        question_queue = None
        reply_queue = None

    class DummyAgent:
        streaming = False
        messages = []
        turn_count = 0
        session_id = "sid"

    class DummySession:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self._agent = DummyAgent()
            assert kwargs["channel"] is created_channels[0]

        def run(self, message):
            return "ok"

    monkeypatch.setattr("hermit_agent.__main__.create_llm_client", lambda **kwargs: DummyLLM())
    monkeypatch.setattr("hermit_agent.interfaces.CLIChannel", DummyChannel)
    monkeypatch.setattr("hermit_agent.interfaces.cli.CLIChannel", DummyChannel)
    monkeypatch.setattr("hermit_agent.__main__.CLIAgentSession", DummySession)

    main_mod.main()

    assert created_channels
    assert "ok" in capsys.readouterr().out


def test_main_handles_pending_interaction_before_falling_back_to_idle_message(monkeypatch):
    from hermit_agent import __main__ as main_mod
    from hermit_agent.install_flow import StartupHealSummary

    monkeypatch.setattr(main_mod.sys, "argv", ["hermit-agent"])
    monkeypatch.setattr("hermit_agent.install_flow.run_startup_self_heal", lambda **kwargs: StartupHealSummary())
    monkeypatch.setattr("hermit_agent.__main__._stdio_interactive", lambda: True)
    monkeypatch.setattr("hermit_agent.pending_interactions.run_pending_interaction_loop", lambda **kwargs: True)
    monkeypatch.setattr("hermit_agent.pending_interactions.build_idle_operator_overview", lambda **kwargs: "[Hermit] Ready")
    monkeypatch.setattr("hermit_agent.__main__._run_idle_menu_loop", lambda **kwargs: None)

    main_mod.main()


def test_main_can_run_guided_install_before_idle_shell(monkeypatch, capsys):
    from hermit_agent import __main__ as main_mod
    from hermit_agent.install_flow import InstallSummary, StartupHealSummary

    monkeypatch.setattr(main_mod.sys, "argv", ["hermit-agent"])
    monkeypatch.setattr(
        "hermit_agent.install_flow.run_startup_self_heal",
        lambda **kwargs: StartupHealSummary(
            gateway_status="healthy",
            mcp_registration_status="missing",
            codex_runtime_status="missing",
        ),
    )
    monkeypatch.setattr("hermit_agent.__main__._stdio_interactive", lambda: True)
    monkeypatch.setattr("hermit_agent.__main__._prompt_guided_install", lambda **kwargs: True)
    monkeypatch.setattr(
        "hermit_agent.install_flow.run_install",
        lambda **kwargs: InstallSummary(
            settings_path="/tmp/settings.json",
            gateway_api_key_present=True,
            gateway_status="healthy",
            mcp_registration_status="registered",
            codex_install_status="installed",
        ),
    )
    monkeypatch.setattr("hermit_agent.install_flow.format_install_summary", lambda summary: "Hermit install is ready.")
    monkeypatch.setattr("hermit_agent.pending_interactions.run_pending_interaction_loop", lambda **kwargs: False)
    monkeypatch.setattr("hermit_agent.pending_interactions.build_idle_operator_overview", lambda **kwargs: "[Hermit] Ready")
    monkeypatch.setattr("hermit_agent.__main__._run_idle_menu_loop", lambda **kwargs: print("[Hermit] idle-loop"))

    main_mod.main()

    captured = capsys.readouterr()
    assert "Hermit install is ready." in captured.out
    assert "[Hermit] Ready" in captured.out


def test_main_skips_guided_install_prompt_when_startup_is_healthy(monkeypatch):
    from hermit_agent import __main__ as main_mod
    from hermit_agent.install_flow import StartupHealSummary

    monkeypatch.setattr(main_mod.sys, "argv", ["hermit-agent"])
    monkeypatch.setattr(
        "hermit_agent.install_flow.run_startup_self_heal",
        lambda **kwargs: StartupHealSummary(
            gateway_status="healthy",
            mcp_registration_status="registered",
            codex_runtime_status="installed",
        ),
    )
    monkeypatch.setattr("hermit_agent.__main__._stdio_interactive", lambda: True)
    monkeypatch.setattr("hermit_agent.__main__._prompt_guided_install", lambda **kwargs: (_ for _ in ()).throw(AssertionError("unexpected prompt")))
    monkeypatch.setattr("hermit_agent.pending_interactions.run_pending_interaction_loop", lambda **kwargs: False)
    monkeypatch.setattr("hermit_agent.pending_interactions.build_idle_operator_overview", lambda **kwargs: "[Hermit] Ready")
    monkeypatch.setattr("hermit_agent.__main__._run_idle_menu_loop", lambda **kwargs: None)

    main_mod.main()


def test_main_prints_pending_summary_when_idle_interactive_and_nothing_to_reply(monkeypatch, capsys):
    from hermit_agent import __main__ as main_mod
    from hermit_agent.install_flow import StartupHealSummary

    monkeypatch.setattr(main_mod.sys, "argv", ["hermit-agent"])
    monkeypatch.setattr("hermit_agent.install_flow.run_startup_self_heal", lambda **kwargs: StartupHealSummary())
    monkeypatch.setattr("hermit_agent.__main__._stdio_interactive", lambda: True)
    monkeypatch.setattr("hermit_agent.pending_interactions.run_pending_interaction_loop", lambda **kwargs: False)
    monkeypatch.setattr("hermit_agent.pending_interactions.build_idle_operator_overview", lambda **kwargs: "[Hermit] Ready")
    monkeypatch.setattr("hermit_agent.__main__._run_idle_menu_loop", lambda **kwargs: print("[Hermit] idle-loop"))

    main_mod.main()

    captured = capsys.readouterr()
    assert "[Hermit] Ready" in captured.out
    assert "[Hermit] idle-loop" in captured.out


def test_run_idle_menu_dispatches_status(monkeypatch, capsys):
    monkeypatch.setattr("hermit_agent.__main__._prompt_idle_menu_choice", lambda **kwargs: "2")
    monkeypatch.setattr("hermit_agent.pending_interactions.build_operator_status_summary", lambda **kwargs: "[Hermit] Status")
    monkeypatch.setattr("hermit_agent.pending_interactions.get_pending_interactions", lambda **kwargs: [])
    monkeypatch.setattr(
        "hermit_agent.__main__._render_idle_menu_state",
        lambda **kwargs: {"pending_count": 0, "repair_recommended": False, "latest_preview": None},
    )

    handled = _run_idle_menu(cwd="/tmp/demo")

    assert handled == "handled"
    assert "[Hermit] Status" in capsys.readouterr().out


def test_run_idle_menu_dispatches_doctor_fix(monkeypatch, capsys):
    monkeypatch.setattr("hermit_agent.__main__._prompt_idle_menu_choice", lambda **kwargs: "3")
    monkeypatch.setattr("hermit_agent.doctor.format_doctor_fix_summary", lambda **kwargs: "Hermit doctor --fix complete.")
    monkeypatch.setattr("hermit_agent.pending_interactions.get_pending_interactions", lambda **kwargs: [])
    monkeypatch.setattr(
        "hermit_agent.__main__._render_idle_menu_state",
        lambda **kwargs: {"pending_count": 0, "repair_recommended": False, "latest_preview": None},
    )

    handled = _run_idle_menu(cwd="/tmp/demo")

    assert handled == "handled"
    assert "Hermit doctor --fix complete." in capsys.readouterr().out


def test_run_idle_menu_loop_repeats_until_exit(monkeypatch):
    calls = iter(["handled", "handled", "exit"])
    seen = []

    def fake_run_idle_menu(*, cwd: str):
        seen.append(cwd)
        return next(calls)

    monkeypatch.setattr("hermit_agent.__main__._run_idle_menu", fake_run_idle_menu)

    _run_idle_menu_loop(args=type("Args", (), {"cwd": "/tmp/demo"})())

    assert seen == ["/tmp/demo", "/tmp/demo", "/tmp/demo"]


def test_run_idle_menu_loop_can_start_new_task(monkeypatch):
    calls = iter(["task", "exit"])
    prompts = iter(["do something"])
    seen = []

    monkeypatch.setattr("hermit_agent.__main__._run_idle_menu", lambda **kwargs: next(calls))
    monkeypatch.setattr("hermit_agent.__main__._prompt_new_task_message", lambda: next(prompts))
    monkeypatch.setattr("hermit_agent.__main__._run_message_mode", lambda **kwargs: seen.append(kwargs["message"]))

    args = type(
        "Args",
        (),
        {
            "cwd": "/tmp/demo",
            "channel": "none",
            "base_url": "http://localhost:8765/v1",
            "model": "model",
            "api_key": "tok",
            "fallback_model": None,
            "yolo": False,
            "ask": False,
            "accept_edits": False,
            "dont_ask": False,
            "plan": False,
            "max_turns": 50,
            "max_context": 32000,
            "no_stream": False,
        },
    )()

    _run_idle_menu_loop(args=args)

    assert seen == ["do something"]


def test_run_status_watch_renders_until_keyboard_interrupt(monkeypatch, capsys):
    calls = {"count": 0}

    def fake_summary(*, cwd: str):
        calls["count"] += 1
        return f"[Hermit] Status #{calls['count']}"

    def fake_sleep(_seconds: float):
        raise KeyboardInterrupt

    monkeypatch.setattr("hermit_agent.pending_interactions.build_operator_status_summary", fake_summary)
    monkeypatch.setattr("hermit_agent.__main__.time.sleep", fake_sleep)

    _run_status_watch(cwd="/tmp/demo", interval=0.5)

    out = capsys.readouterr().out
    assert "[Hermit] Status #1" in out
    assert "Stopped status watch." in out


def test_prompt_idle_menu_choice_can_receive_state_aware_labels(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt: "5")

    from hermit_agent.__main__ import _prompt_idle_menu_choice

    choice = _prompt_idle_menu_choice(pending_count=2, repair_recommended=True)
    output = capsys.readouterr().out

    assert choice == "5"
    assert "Answer pending interactions (count:2)" in output
    assert "Repair setup (recommended)" in output


def test_render_idle_menu_state_exposes_pending_and_repair_recommendation(monkeypatch):
    monkeypatch.setattr(
        "hermit_agent.install_flow.run_startup_self_heal",
        lambda **kwargs: type("Heal", (), {"gateway_status": "started", "mcp_registration_status": "missing", "codex_runtime_status": "installed"})(),
    )
    monkeypatch.setattr(
        "hermit_agent.pending_interactions.get_pending_interactions",
        lambda **kwargs: [type("Interaction", (), {"kind": "approval_request", "question": "Need approval"})()],
    )
    monkeypatch.setattr("hermit_agent.pending_interactions._summarize_interaction", lambda interaction, max_chars=50: "[approval_request] Need approval")

    state = _render_idle_menu_state(cwd="/tmp/demo")

    assert state["pending_count"] == 1
    assert state["repair_recommended"] is True
    assert state["latest_preview"] == "[approval_request] Need approval"


def test_run_idle_menu_prints_latest_preview(monkeypatch, capsys):
    monkeypatch.setattr("hermit_agent.__main__._prompt_idle_menu_choice", lambda **kwargs: "5")
    monkeypatch.setattr(
        "hermit_agent.__main__._render_idle_menu_state",
        lambda **kwargs: {"pending_count": 2, "repair_recommended": True, "latest_preview": "[approval_request] Need approval"},
    )
    monkeypatch.setattr("hermit_agent.pending_interactions.get_pending_interactions", lambda **kwargs: [])

    handled = _run_idle_menu(cwd="/tmp/demo")

    assert handled == "exit"
    assert "latest pending: [approval_request] Need approval" in capsys.readouterr().out


def test_main_uses_idle_menu_loop_when_no_pending_interactions(monkeypatch, capsys):
    from hermit_agent import __main__ as main_mod
    from hermit_agent.install_flow import StartupHealSummary

    monkeypatch.setattr(main_mod.sys, "argv", ["hermit-agent"])
    monkeypatch.setattr("hermit_agent.install_flow.run_startup_self_heal", lambda **kwargs: StartupHealSummary())
    monkeypatch.setattr("hermit_agent.__main__._stdio_interactive", lambda: True)
    monkeypatch.setattr("hermit_agent.pending_interactions.run_pending_interaction_loop", lambda **kwargs: False)
    monkeypatch.setattr("hermit_agent.pending_interactions.build_idle_operator_overview", lambda **kwargs: "[Hermit] Ready")
    monkeypatch.setattr("hermit_agent.__main__._run_idle_menu_loop", lambda **kwargs: print("[Hermit] idle-loop"))

    main_mod.main()

    captured = capsys.readouterr()
    assert "[Hermit] Ready" in captured.out
    assert "[Hermit] idle-loop" in captured.out


def test_main_stays_in_shell_after_processing_pending(monkeypatch, capsys):
    from hermit_agent import __main__ as main_mod
    from hermit_agent.install_flow import StartupHealSummary

    monkeypatch.setattr(main_mod.sys, "argv", ["hermit-agent"])
    monkeypatch.setattr("hermit_agent.install_flow.run_startup_self_heal", lambda **kwargs: StartupHealSummary())
    monkeypatch.setattr("hermit_agent.__main__._stdio_interactive", lambda: True)
    monkeypatch.setattr("hermit_agent.pending_interactions.run_pending_interaction_loop", lambda **kwargs: True)
    monkeypatch.setattr("hermit_agent.pending_interactions.build_idle_operator_overview", lambda **kwargs: "[Hermit] Ready")
    monkeypatch.setattr("hermit_agent.__main__._run_idle_menu_loop", lambda **kwargs: print("[Hermit] idle-loop"))

    main_mod.main()

    captured = capsys.readouterr()
    assert "Pending interaction queue is clear." in captured.out
    assert "[Hermit] Ready" in captured.out
    assert "[Hermit] idle-loop" in captured.out
