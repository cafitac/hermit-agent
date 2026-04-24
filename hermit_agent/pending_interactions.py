from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from .codex_channels_adapter import build_runtime_serve_command, load_codex_channels_settings
from .config import load_settings
from .interfaces.cli import CLIChannel
from .install_flow import run_startup_self_heal
from .tui_render import compact_count_label, ellipsize_segment, sanitize_dynamic_text


@dataclass(frozen=True)
class PendingOption:
    label: str
    value: str
    description: str | None = None


@dataclass(frozen=True)
class PendingInteraction:
    interaction_id: str
    question: str
    options: list[PendingOption]
    kind: str
    host: str
    port: int
    state_file: str
    header: str | None = None
    allow_other: bool = False
    other_label: str = "Other"


def _normalize_options(raw_options: list[Any] | None) -> list[PendingOption]:
    values: list[PendingOption] = []
    for item in raw_options or []:
        if isinstance(item, dict):
            label = sanitize_dynamic_text(str(item.get("label") or item.get("value") or "").strip())
            value = sanitize_dynamic_text(str(item.get("value") or label).strip())
            description = sanitize_dynamic_text(str(item.get("description") or "").strip()) or None
            if label:
                values.append(PendingOption(label=label, value=value or label, description=description))
        else:
            label = sanitize_dynamic_text(str(item).strip())
            if label:
                values.append(PendingOption(label=label, value=label))
    return values


def _load_state_interactions(state_file: Path) -> list[dict[str, Any]]:
    if not state_file.exists():
        return []
    try:
        payload = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return []
    interactions = payload.get("interactions")
    return interactions if isinstance(interactions, list) else []


def _build_pending_interaction(item: dict[str, Any], *, host: str, port: int, state_file: str) -> PendingInteraction:
    raw_payload = item.get("payload")
    payload: dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else {}
    question = sanitize_dynamic_text(str(payload.get("message") or payload.get("question") or "").strip())
    header = sanitize_dynamic_text(str(payload.get("header") or "").strip()) or None
    raw_policy = item.get("policy")
    policy: dict[str, Any] = raw_policy if isinstance(raw_policy, dict) else {}
    return PendingInteraction(
        interaction_id=str(item.get("id") or ""),
        question=question,
        options=_normalize_options(payload.get("options") if isinstance(payload.get("options"), list) else None),
        kind=str(item.get("kind") or ""),
        host=host,
        port=port,
        state_file=state_file,
        header=header,
        allow_other=bool(policy.get("allowFreeText", False)),
        other_label=sanitize_dynamic_text(str(payload.get("other_label") or "Other").strip()) or "Other",
    )


def get_pending_interactions(*, cwd: str) -> list[PendingInteraction]:
    cfg = load_settings(cwd=cwd)
    settings = load_codex_channels_settings(cfg, cwd)
    interactions = _load_state_interactions(Path(settings.state_file))
    actionable = [
        item for item in interactions
        if isinstance(item, dict)
        and item.get("kind") != "progress_update"
        and item.get("status") in {"pending", "delivered"}
    ]
    actionable.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
    return [
        _build_pending_interaction(item, host=settings.host, port=settings.port, state_file=settings.state_file)
        for item in actionable
    ]


def get_latest_pending_interaction(*, cwd: str) -> PendingInteraction | None:
    interactions = get_pending_interactions(cwd=cwd)
    return interactions[0] if interactions else None


def _runtime_health_url(interaction: PendingInteraction) -> str:
    return f"http://{interaction.host}:{interaction.port}/health"


def _runtime_reply_url(interaction: PendingInteraction) -> str:
    return f"http://{interaction.host}:{interaction.port}/interactions/{interaction.interaction_id}/respond"


def _probe_runtime(interaction: PendingInteraction, *, timeout: float = 2.0) -> bool:
    try:
        with urlopen(_runtime_health_url(interaction), timeout=timeout) as response:
            return 200 <= getattr(response, "status", 200) < 300
    except (URLError, OSError, ValueError):
        return False


def _ensure_runtime(interaction: PendingInteraction, *, cwd: str) -> subprocess.Popen[str] | None:
    if _probe_runtime(interaction):
        return None
    settings = load_codex_channels_settings(load_settings(cwd=cwd), cwd)
    proc = subprocess.Popen(
        build_runtime_serve_command(settings=settings),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.time() + 10
    while time.time() < deadline:
        if _probe_runtime(interaction, timeout=1.0):
            return proc
        time.sleep(0.25)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
        proc.wait(timeout=5)
    raise RuntimeError("codex-channels runtime did not become healthy in time")


def _send_reply(interaction: PendingInteraction, answer: str) -> None:
    payload = json.dumps({"action": "text", "values": [answer]}).encode("utf-8")
    request = Request(
        _runtime_reply_url(interaction),
        method="POST",
        data=payload,
        headers={"content-type": "application/json"},
    )
    with urlopen(request, timeout=10) as response:
        if not (200 <= getattr(response, "status", 200) < 300):
            raise RuntimeError(f"reply failed: {getattr(response, 'status', '?')}")


def _resolve_cli_answer(answer: str, options: list[PendingOption]) -> str:
    normalized = answer.strip()
    if normalized.isdigit():
        idx = int(normalized) - 1
        if 0 <= idx < len(options):
            return options[idx].value
    return normalized


def _summarize_interaction(interaction: PendingInteraction, *, max_chars: int = 80) -> str:
    text = sanitize_dynamic_text(interaction.question.replace("\n", " ").strip())
    shortened = ellipsize_segment(text, max_chars)
    kind = sanitize_dynamic_text(interaction.kind)
    return f"[{kind}] {shortened}" if kind else shortened


def _option_display(option: PendingOption) -> str:
    if option.description:
        return f"{option.label} — {option.description}"
    return option.label


def _presentable_question(interaction: PendingInteraction) -> str:
    if interaction.header:
        return f"{interaction.header}\n{interaction.question}"
    return interaction.question


def _presentable_options(interaction: PendingInteraction) -> list[str]:
    options = [_option_display(option) for option in interaction.options]
    if interaction.allow_other:
        options.append(interaction.other_label)
    return options


def _choose_interaction(interactions: list[PendingInteraction]) -> PendingInteraction:
    if len(interactions) == 1:
        return interactions[0]
    channel = CLIChannel()
    options = [_summarize_interaction(item) for item in interactions]
    selection = channel._present_question("Select a pending interaction to answer:", options).strip()
    if selection.isdigit():
        idx = int(selection) - 1
        if 0 <= idx < len(interactions):
            return interactions[idx]
    for idx, option in enumerate(options):
        if selection == option:
            return interactions[idx]
    return interactions[0]


def _resolve_interaction_reply(channel: CLIChannel, interaction: PendingInteraction) -> str:
    selection = channel._present_question(_presentable_question(interaction), _presentable_options(interaction))
    normalized = selection.strip()
    if normalized.isdigit():
        idx = int(normalized) - 1
        if 0 <= idx < len(interaction.options):
            return interaction.options[idx].value
        if interaction.allow_other and idx == len(interaction.options):
            other = channel._present_question(f"{interaction.other_label}:", [])
            return other.strip()
    if interaction.allow_other and normalized.lower() == interaction.other_label.lower():
        other = channel._present_question(f"{interaction.other_label}:", [])
        return other.strip()
    return normalized


def build_pending_interaction_summary(*, cwd: str) -> str:
    interactions = get_pending_interactions(cwd=cwd)
    if not interactions:
        return "[Hermit] No pending interactions. Ask a task or run `hermit install` if you still need setup help."

    lines = [f"[Hermit] Pending interactions ({compact_count_label('count', len(interactions))}):"]
    for idx, interaction in enumerate(interactions[:5], 1):
        lines.append(f"  {idx}. {_summarize_interaction(interaction)}")
    if len(interactions) > 5:
        lines.append(f"  … and {len(interactions) - 5} more")
    lines.append("Run `hermit` in an interactive terminal to answer one now.")
    return "\n".join(lines)


def build_operator_status_summary(*, cwd: str) -> str:
    heal = run_startup_self_heal(cwd=cwd)
    interactions = get_pending_interactions(cwd=cwd)
    lines = ["[Hermit] Status"]
    lines.append(f"- gateway: {sanitize_dynamic_text(heal.gateway_status)}")
    lines.append(f"- mcp registration: {sanitize_dynamic_text(heal.mcp_registration_status)}")
    lines.append(f"- codex integration: {sanitize_dynamic_text(heal.codex_runtime_status)}")
    lines.append(f"- pending interactions: {compact_count_label('count', len(interactions))}")
    lines.append("- codex-facing surface: hermit-channel MCP")
    if interactions:
        lines.append(f"- latest: {_summarize_interaction(interactions[0])}")
        lines.append("Run `hermit` to answer pending interactions interactively.")
    else:
        lines.append("No pending interactions right now.")
    return "\n".join(lines)


def build_idle_operator_overview(*, cwd: str) -> str:
    heal = run_startup_self_heal(cwd=cwd)
    interactions = get_pending_interactions(cwd=cwd)
    lines = ["[Hermit] Ready"]
    lines.append(
        "  "
        + " | ".join(
            [
                f"gateway:{sanitize_dynamic_text(heal.gateway_status)}",
                f"mcp:{sanitize_dynamic_text(heal.mcp_registration_status)}",
                f"codex:{sanitize_dynamic_text(heal.codex_runtime_status)}",
                compact_count_label("pending", len(interactions)),
            ]
        )
    )
    if interactions:
        lines.append(f"  latest: {_summarize_interaction(interactions[0], max_chars=60)}")
        lines.append("  recommended: answer pending interactions")
    elif heal.gateway_status != "healthy" or heal.mcp_registration_status != "registered" or heal.codex_runtime_status != "installed":
        lines.append("  recommended: repair setup")
    else:
        lines.append("  recommended: start a new task")
    return "\n".join(lines)


def maybe_handle_pending_interaction(*, cwd: str) -> bool:
    interactions = get_pending_interactions(cwd=cwd)
    if not interactions:
        return False
    interaction = _choose_interaction(interactions)
    if not interaction.interaction_id:
        return False

    channel = CLIChannel()
    answer = _resolve_interaction_reply(channel, interaction)
    if not answer:
        return False

    proc = _ensure_runtime(interaction, cwd=cwd)
    try:
        _send_reply(interaction, answer)
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
                proc.wait(timeout=5)
    print(f"[Hermit] Replied to pending interaction {interaction.interaction_id}.", flush=True)
    return True


def run_pending_interaction_loop(*, cwd: str) -> bool:
    handled_any = False
    while True:
        interactions = get_pending_interactions(cwd=cwd)
        if not interactions:
            return handled_any
        if handled_any:
            channel = CLIChannel()
            yes_no_options = [
                PendingOption(label="yes", value="yes"),
                PendingOption(label="no", value="no"),
            ]
            answer = _resolve_cli_answer(
                channel._present_question(
                    "There are still pending interactions. Answer another one?",
                    ["yes", "no"],
                ),
                yes_no_options,
            ).lower()
            if answer not in {"yes", "y", "1"}:
                return handled_any
        handled = maybe_handle_pending_interaction(cwd=cwd)
        if not handled:
            return handled_any
        handled_any = True
