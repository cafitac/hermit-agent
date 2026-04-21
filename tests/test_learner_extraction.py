from __future__ import annotations

from unittest.mock import MagicMock

from hermit_agent.learner_extraction import (
    build_failure_prompt,
    build_success_prompt,
    extract_skill_data,
)


def test_extract_skill_data_parses_plain_json_response():
    llm = MagicMock()
    llm.chat.return_value = MagicMock(content='{"name": "skill", "description": "desc", "triggers": ["x"], "rule": "do x"}')

    parsed = extract_skill_data(llm, 'prompt')

    assert parsed == {
        'name': 'skill',
        'description': 'desc',
        'triggers': ['x'],
        'rule': 'do x',
    }


def test_extract_skill_data_strips_fenced_json_response():
    llm = MagicMock()
    llm.chat.return_value = MagicMock(content='```json\n{"name": "skill", "description": "desc", "triggers": ["x"], "rule": "do x"}\n```')

    parsed = extract_skill_data(llm, 'prompt')

    assert parsed is not None
    assert parsed['name'] == 'skill'


def test_extract_skill_data_returns_none_for_none_or_invalid_json():
    llm = MagicMock()
    llm.chat.return_value = MagicMock(content='NONE')
    assert extract_skill_data(llm, 'prompt') is None

    llm.chat.return_value = MagicMock(content='{bad json}')
    assert extract_skill_data(llm, 'prompt') is None


def test_prompt_builders_keep_core_guidance_text():
    failure_prompt = build_failure_prompt('pytest failure output')
    success_prompt = build_success_prompt('summary', 7)

    assert 'failed task' in failure_prompt
    assert 'pytest failure output' in failure_prompt
    assert 'successfully completed task (7 tool calls)' in success_prompt
    assert 'summary' in success_prompt
