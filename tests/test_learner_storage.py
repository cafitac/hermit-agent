from __future__ import annotations

from hermit_agent.learner_storage import SkillMeta, add_hub_backlink, parse_skill_file, write_skill_file


def test_write_and_parse_skill_file_round_trip(tmp_path):
    path = tmp_path / 'skill.md'
    meta = SkillMeta(
        name='round_trip',
        description='Round-trip test',
        triggers=['pytest', 'learn'],
        scope=['tests/'],
        status='approved',
        created_at='2026-04-21',
        last_used='2026-04-22',
        use_count=3,
        success_count=2,
        fail_count=1,
        missed_count=1,
        needs_review=True,
        verify_cmd='pytest -q',
    )
    body = '## Rule\n\nKeep learner storage round-trippable.'

    write_skill_file(str(path), meta, body)

    parsed = parse_skill_file(str(path))
    assert parsed is not None
    parsed_meta, parsed_body = parsed
    assert parsed_meta == meta
    assert parsed_body == body


def test_add_hub_backlink_is_idempotent(tmp_path):
    path = tmp_path / 'skill.md'
    path.write_text('---\nname: skill\ndescription: demo\n---\n\nBody\n')

    add_hub_backlink(str(path), '_hub_auto')
    add_hub_backlink(str(path), '_hub_auto')

    content = path.read_text()
    assert content.endswith('---\n← [[_hub_auto|Auto-Learning Hub]]\n')
    assert content.count('[[_hub_auto|Auto-Learning Hub]]') == 1
