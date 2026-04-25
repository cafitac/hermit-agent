from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP
from pydantic import create_model


server = FastMCP("hermit_ask_user")


async def ask_user_via_elicitation(
    *,
    question: str,
    options: list[str] | None,
    ctx: Context,
) -> str:
    normalized_options = [option.strip() for option in (options or []) if option.strip()]
    message = question.strip() or "Input required."
    if normalized_options:
        message = f"{message}\nOptions: {', '.join(normalized_options)}"
    schema = create_model("AskUserQuestionResponse", answer=(str, ...))
    result = await ctx.elicit(message=message, schema=schema)
    if result.action != "accept" or result.data is None:
        raise RuntimeError("User cancelled the interactive input request.")
    return str(result.data.answer)


@server.tool(
    name="ask_user_question",
    description=(
        "Ask the user a question through the host interactive input surface and wait for the reply. "
        "Use this whenever you need missing user input before you can continue."
    ),
)
async def ask_user_question(
    question: str,
    options: list[str] | None = None,
    ctx: Context | None = None,
) -> str:
    if ctx is None:
        raise RuntimeError("Context is required for ask_user_question.")
    return await ask_user_via_elicitation(question=question, options=options, ctx=ctx)


if __name__ == "__main__":
    server.run()
