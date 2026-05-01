from __future__ import annotations

from hermit_agent.doctor import DiagCheck, DiagStatus
from hermit_agent.orchestrators import AdapterHealthStatus, AdapterInstallStatus, OrchestratorAdapter
from hermit_agent.orchestrators.hermes import HermesMcpAdapter


def test_hermes_adapter_prints_instructions_without_mutating(monkeypatch):
    calls: list[str] = []

    def fake_snippet(*, cwd: str) -> str:
        calls.append(cwd)
        return "Hermit MCP for Hermes Agent\nhermes mcp add hermit-channel --command hermit --args mcp-server"

    monkeypatch.setattr("hermit_agent.orchestrators.hermes.format_hermes_mcp_config_snippet", fake_snippet)
    monkeypatch.setattr(
        "hermit_agent.orchestrators.hermes.ensure_hermes_mcp_registered",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("print-only path must not mutate Hermes config")),
    )

    adapter: OrchestratorAdapter = HermesMcpAdapter()
    result = adapter.install_or_print_instructions(cwd="/repo", fix=False)

    assert result.name == "hermes"
    assert result.status == AdapterInstallStatus.PRINTED
    assert result.changed is False
    assert "print-only" in result.message
    assert result.details == ("Hermit MCP for Hermes Agent", "hermes mcp add hermit-channel --command hermit --args mcp-server")
    assert calls == ["/repo"]


def test_hermes_adapter_maps_fix_statuses_to_install_results(monkeypatch):
    statuses = iter(["registered", "unchanged", "missing-hermes-cli", "failed (boom)"])
    monkeypatch.setattr(
        "hermit_agent.orchestrators.hermes.ensure_hermes_mcp_registered",
        lambda *, cwd: next(statuses),
    )

    adapter = HermesMcpAdapter()

    registered = adapter.install_or_print_instructions(cwd="/repo", fix=True)
    unchanged = adapter.install_or_print_instructions(cwd="/repo", fix=True)
    missing = adapter.install_or_print_instructions(cwd="/repo", fix=True)
    failed = adapter.install_or_print_instructions(cwd="/repo", fix=True)

    assert registered.status == AdapterInstallStatus.REGISTERED
    assert registered.changed is True
    assert unchanged.status == AdapterInstallStatus.UNCHANGED
    assert unchanged.changed is False
    assert missing.status == AdapterInstallStatus.FAILED
    assert missing.message == "missing-hermes-cli"
    assert failed.status == AdapterInstallStatus.FAILED
    assert failed.message == "failed (boom)"


def test_hermes_adapter_health_maps_doctor_check(monkeypatch):
    checks = iter(
        [
            DiagCheck("Hermes MCP", DiagStatus.PASS, "hermit-channel registered for Hermes Agent"),
            DiagCheck("Hermes MCP", DiagStatus.WARN, "hermit-channel missing"),
            DiagCheck("Hermes MCP", DiagStatus.FAIL, "unexpected failure"),
        ]
    )
    monkeypatch.setattr("hermit_agent.orchestrators.hermes.check_hermes_mcp", lambda cwd: next(checks))

    adapter = HermesMcpAdapter()

    passed = adapter.health(cwd="/repo")
    warned = adapter.health(cwd="/repo")
    failed = adapter.health(cwd="/repo")

    assert passed.status == AdapterHealthStatus.PASS
    assert passed.message == "hermit-channel registered for Hermes Agent"
    assert warned.status == AdapterHealthStatus.WARN
    assert warned.message == "hermit-channel missing"
    assert failed.status == AdapterHealthStatus.FAIL
    assert failed.message == "unexpected failure"


def test_hermes_adapter_live_smoke_maps_probe_result(monkeypatch):
    statuses = iter(["passed", "missing-hermes-cli", "failed (timeout)"])
    monkeypatch.setattr(
        "hermit_agent.orchestrators.hermes.run_hermes_mcp_connection_test",
        lambda *, cwd: next(statuses),
    )

    adapter = HermesMcpAdapter()

    passed = adapter.live_smoke(cwd="/repo")
    missing = adapter.live_smoke(cwd="/repo")
    failed = adapter.live_smoke(cwd="/repo")

    assert passed.status == AdapterHealthStatus.PASS
    assert passed.message == "passed"
    assert missing.status == AdapterHealthStatus.WARN
    assert missing.message == "missing-hermes-cli"
    assert failed.status == AdapterHealthStatus.FAIL
    assert failed.message == "failed (timeout)"
