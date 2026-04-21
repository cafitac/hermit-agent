"""Prompt and response helpers for Learner LLM extraction flows."""

from __future__ import annotations

import json

_REQUIRED_FIELDS = {"name", "description", "triggers", "rule"}


def build_failure_prompt(pytest_output: str) -> str:
    return f"""You are analyzing a coding agent's failed task.

pytest output:
{pytest_output[:3000]}

Based on the failure, extract ONE concrete rule the agent should follow next time.

Respond as JSON:
{{
  \"name\": \"snake_case_rule_name\",
  \"description\": \"one-line description\",
  \"triggers\": [\"keyword1\", \"keyword2\"],
  \"scope\": [\"app_name_or_file_pattern\"],
  \"rule\": \"The actual rule in imperative form. Be specific with file paths and commands.\",
  \"why\": \"Why this rule prevents the failure\",
  \"bad_pattern\": \"What the agent did wrong\",
  \"good_pattern\": \"What the agent should do instead\",
  \"verify_cmd\": \"bash command to verify the agent followed this rule after task completion (exit 0 = success). Use empty string if not applicable. Example: 'git log --oneline -1 | grep -q .' to verify a commit was made.\"
}}

If no clear rule can be extracted, respond: NONE"""


def build_success_prompt(conversation_summary: str, tool_call_count: int) -> str:
    return f"""You are analyzing a coding agent's successfully completed task ({tool_call_count} tool calls).

Conversation summary:
{conversation_summary[:4000]}

Extract ONE reusable skill/rule from this successful workflow that would help next time.
Only extract if there's a genuinely non-obvious pattern worth saving.

Respond as JSON:
{{
  \"name\": \"snake_case_skill_name\",
  \"description\": \"one-line description (Korean OK)\",
  \"triggers\": [\"keyword1\", \"keyword2\"],
  \"scope\": [\"file_pattern_or_app\"],
  \"rule\": \"The reusable rule or workflow in imperative form.\",
  \"why\": \"Why this pattern is worth saving\",
  \"good_pattern\": \"What worked well\",
  \"bad_pattern\": \"What to avoid\",
  \"verify_cmd\": \"bash command to verify the agent followed this skill after task completion (exit 0 = success). Use empty string if not applicable. Example: 'git log --oneline -1 | grep -q .' to verify a commit was made, 'git diff --quiet' to verify no uncommitted changes.\"
}}

If no clear reusable pattern exists, respond: NONE"""


def extract_skill_data(llm, prompt: str) -> dict | None:
    try:
        response = llm.chat([{"role": "user", "content": prompt}])
        text = response.content.strip() if hasattr(response, "content") else str(response).strip()
        if text == "NONE" or not text:
            return None
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        data = json.loads(text)
        return data if _REQUIRED_FIELDS.issubset(data.keys()) else None
    except Exception:
        return None
