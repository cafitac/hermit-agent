from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from hermit_agent.learner import Learner
from hermit_agent.learner_verification import run_verify_command
from hermit_agent.learner_storage import SkillMeta, parse_skill_file, write_skill_file


def _make_learner(tmp_path):
    return Learner(root=str(tmp_path))


def _write_skill(base: Path, folder: str, meta: SkillMeta, body: str = '## Rule\n\nBody') -> str:
    path = base / '.hermit' / 'skills' / folder / f'{meta.name}.md'
    write_skill_file(str(path), meta, body)
    return str(path)


def test_run_verify_cmds_prefers_skill_frontmatter_over_rules(tmp_path):
    learner = _make_learner(tmp_path)
    meta = SkillMeta(
        name='verify_me',
        description='desc',
        triggers=['pytest'],
        status='approved',
        verify_cmd='frontmatter-cmd',
    )
    _write_skill(tmp_path, 'learned-feedback/approved', meta)

    with patch('hermit_agent.learner._load_verify_rules', return_value={'by_name': {'verify_me': 'rule-cmd'}}), \
         patch('subprocess.run') as mock_run:
        mock_run.return_value.returncode = 0
        result = learner.run_verify_cmds(['verify_me'], str(tmp_path))

    assert result == {'verify_me': True}
    mock_run.assert_called_once()
    assert mock_run.call_args.args[0] == ["frontmatter-cmd"]


def test_run_verify_cmds_uses_trigger_keyword_rules_when_frontmatter_missing(tmp_path):
    learner = _make_learner(tmp_path)
    meta = SkillMeta(
        name='keyword_skill',
        description='desc',
        triggers=['gateway', 'pytest'],
        status='approved',
    )
    _write_skill(tmp_path, 'learned-feedback/approved', meta)

    with patch('hermit_agent.learner._load_verify_rules', return_value={'by_trigger_keyword': {'pytest': 'trigger-cmd'}}),          patch('subprocess.run') as mock_run:
        mock_run.return_value.returncode = 0
        result = learner.run_verify_cmds(['keyword_skill'], str(tmp_path))

    assert result == {'keyword_skill': True}
    assert mock_run.call_args.args[0] == ["trigger-cmd"]


def test_cleanup_marks_needs_review_before_deprecation(tmp_path):
    learner = _make_learner(tmp_path)
    meta = SkillMeta(
        name='review_me',
        description='desc',
        status='approved',
        use_count=5,
        success_count=1,
        fail_count=4,
        last_used='2026-04-20',
    )
    approved_path = Path(_write_skill(tmp_path, 'learned-feedback/approved', meta))

    deprecated = learner.cleanup()

    assert deprecated == []
    updated, _ = parse_skill_file(str(approved_path))
    assert updated is not None
    assert updated.needs_review is True
    assert updated.status == 'approved'


def test_cleanup_deprecates_reviewed_skill_after_continued_failures(tmp_path):
    learner = _make_learner(tmp_path)
    meta = SkillMeta(
        name='deprecate_me',
        description='desc',
        status='approved',
        use_count=10,
        success_count=2,
        fail_count=8,
        needs_review=True,
        last_used='2026-04-20',
    )
    approved_path = Path(_write_skill(tmp_path, 'learned-feedback/approved', meta))

    deprecated = learner.cleanup()

    deprecated_path = tmp_path / '.hermit' / 'skills' / 'learned-feedback' / 'deprecated' / 'deprecate_me.md'
    assert deprecated == ['deprecate_me']
    assert not approved_path.exists()
    assert deprecated_path.exists()


def test_cleanup_marks_old_low_signal_skill_for_review(tmp_path):
    learner = _make_learner(tmp_path)
    meta = SkillMeta(
        name='stale_skill',
        description='desc',
        status='approved',
        use_count=2,
        success_count=1,
        fail_count=1,
        last_used='2025-02-01',
    )
    approved_path = tmp_path / '.hermit' / 'skills' / 'learned-feedback' / 'approved' / 'stale_skill.md'
    write_skill_file(str(approved_path), meta, '## Rule\n\nBody')

    deprecated = learner.cleanup()

    updated, _ = parse_skill_file(str(approved_path))
    assert deprecated == []
    assert updated is not None
    assert updated.needs_review is True


def test_run_verify_command_uses_argv_without_shell():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0

        result = run_verify_command("git diff --quiet", "/tmp/demo")

    assert result is True
    assert mock_run.call_args.args[0] == ["git", "diff", "--quiet"]
    assert "shell" not in mock_run.call_args.kwargs


def test_run_verify_command_rejects_shell_operators():
    with patch("subprocess.run") as mock_run:
        result = run_verify_command("git log --oneline -1 | grep -q .", "/tmp/demo")

    assert result is None
    mock_run.assert_not_called()
