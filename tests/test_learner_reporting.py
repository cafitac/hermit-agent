from __future__ import annotations

from hermit_agent.learner_storage import SkillMeta, write_skill_file
from hermit_agent.learner_reporting import build_status_report, collect_active_skills


def _write_skill(base, rel_dir: str, meta: SkillMeta, body: str = '## Rule\n\nBody') -> None:
    path = base / '.hermit' / 'skills' / rel_dir / f'{meta.name}.md'
    write_skill_file(str(path), meta, body)


def test_collect_active_skills_filters_by_keywords_across_scope_and_triggers(tmp_path):
    approved_meta = SkillMeta(
        name='approved_skill',
        description='desc',
        triggers=['gateway'],
        scope=['tests/auth'],
        status='approved',
    )
    auto_meta = SkillMeta(
        name='auto_skill',
        description='desc',
        triggers=['pytest'],
        scope=['tests/payments'],
        status='auto-learned',
    )
    _write_skill(tmp_path, 'learned-feedback/approved', approved_meta, 'approved body')
    _write_skill(tmp_path, 'auto-learned', auto_meta, 'auto body')

    skills = collect_active_skills(
        approved_dir=str(tmp_path / '.hermit' / 'skills' / 'learned-feedback' / 'approved'),
        auto_learned_dir=str(tmp_path / '.hermit' / 'skills' / 'auto-learned'),
        parse_skill_file=None,
        context_keywords=['auth'],
    )

    assert skills == [('approved_skill', 'approved body')]


def test_build_status_report_lists_approved_and_auto_learned_entries(tmp_path):
    approved_meta = SkillMeta(
        name='approved_skill',
        description='desc',
        status='approved',
        use_count=3,
        success_count=2,
        fail_count=1,
    )
    auto_meta = SkillMeta(
        name='auto_skill',
        description='desc',
        status='auto-learned',
        use_count=4,
    )
    _write_skill(tmp_path, 'learned-feedback/pending', SkillMeta(name='pending_skill', description='desc'))
    _write_skill(tmp_path, 'learned-feedback/approved', approved_meta)
    _write_skill(tmp_path, 'learned-feedback/deprecated', SkillMeta(name='deprecated_skill', description='desc', status='deprecated'))
    _write_skill(tmp_path, 'auto-learned', auto_meta)

    report = build_status_report(
        pending_dir=str(tmp_path / '.hermit' / 'skills' / 'learned-feedback' / 'pending'),
        approved_dir=str(tmp_path / '.hermit' / 'skills' / 'learned-feedback' / 'approved'),
        deprecated_dir=str(tmp_path / '.hermit' / 'skills' / 'learned-feedback' / 'deprecated'),
        auto_learned_dir=str(tmp_path / '.hermit' / 'skills' / 'auto-learned'),
        parse_skill_file=None,
    )

    assert '[Learned Skills] pending:1 approved:1 auto-learned:1 deprecated:1' in report
    assert '• approved_skill: 67% (2✓/1✗, 3x)' in report
    assert '✦ auto_skill [auto] (4x)' in report
