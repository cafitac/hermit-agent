from __future__ import annotations

import threading

from .session_support import run_pytest


def _load_learner_class():
    from .learner import Learner

    return Learner


def _load_kb_class():
    from .kb_learner import KBLearner

    return KBLearner


def schedule_bridge_post_task_learning(agent, *, session_kind: str | None) -> None:
    """Run bridge-mode pytest/learner/KB follow-up in the background."""
    if session_kind in ("gateway", "mcp"):
        return

    def _run():
        try:
            Learner = _load_learner_class()
            KBLearner = _load_kb_class()
            learner = Learner(llm=agent.llm)
            active_skills = [name for name, _ in learner.get_active_skills()]

            passed, output = run_pytest(agent.cwd)

            if active_skills:
                learner.record_run(active_skills, passed)

            status = "✓ passed" if passed else "✗ failed"
            print(f"\n\033[35m  [Learner] pytest {status}\033[0m")

            if not passed and learner.llm:
                skill_data = learner.extract_from_failure(agent.messages, output)
                if skill_data:
                    path = learner.save_pending(skill_data)
                    if path:
                        print(f"\033[35m  [Learner] saved improvement rule to pending: {skill_data['name']}\033[0m")

            try:
                kb = KBLearner(cwd=agent.cwd, llm=agent.llm)
                kb.post_task_update(agent.messages, passed)
            except Exception as kb_err:
                print(f"\033[33m  [KB] error: {kb_err}\033[0m")

        except Exception as e:
            print(f"\033[33m  [Learner] error: {e}\033[0m")

    threading.Thread(target=_run, daemon=True).start()
