from __future__ import annotations

import asyncio
import pytest


def test_ask_user_via_elicitation_accepts_free_text():
    from hermit_agent.codex_ask_mcp import ask_user_via_elicitation

    calls = {}

    class Result:
        action = "accept"

        class Data:
            answer = "staging"

        data = Data()

    class Ctx:
        async def elicit(self, *, message, schema):
            calls["message"] = message
            calls["schema"] = schema
            return Result()

    answer = asyncio.run(
        ask_user_via_elicitation(question="Which environment should we use?", options=None, ctx=Ctx())
    )

    assert answer == "staging"
    assert calls["message"] == "Which environment should we use?"


def test_ask_user_via_elicitation_rejects_cancel():
    from hermit_agent.codex_ask_mcp import ask_user_via_elicitation

    class Result:
        action = "cancel"
        data = None

    class Ctx:
        async def elicit(self, *, message, schema):
            return Result()

    with pytest.raises(RuntimeError, match="cancelled"):
        asyncio.run(
            ask_user_via_elicitation(question="Which environment should we use?", options=None, ctx=Ctx())
        )
