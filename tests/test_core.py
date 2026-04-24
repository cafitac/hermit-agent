"""HermitAgent core functionality test."""

import os
import sys
import tempfile

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hermit_agent.tools import (
    BashTool, ReadFileTool, WriteFileTool, EditFileTool,
    _expand_path, _is_safe_path, _check_secrets, create_default_tools,
)
from hermit_agent.permissions import (
    PermissionChecker, PermissionMode, PermissionBehavior,
    classify_bash_safety,
)
from hermit_agent.context import ContextManager, estimate_tokens
from hermit_agent.memory import MemorySystem
from hermit_agent.skills import SkillRegistry, Skill
from hermit_agent.interview import ClarityScore, ProjectType


def test_bash_tool_basic():
    bash = BashTool(cwd="/tmp")
    result = bash.execute({"command": "echo hello"})
    assert not result.is_error
    assert "hello" in result.content


def test_bash_dangerous_prefix():
    bash = BashTool()
    err = bash.validate({"command": "rm -rf /"})
    assert err is not None and "Blocked" in err


def test_bash_subcommand_limit():
    bash = BashTool()
    cmd = " && ".join(["echo x"] * 51)
    err = bash.validate({"command": cmd})
    assert err is not None and "51" in err


def test_bash_classify_command():
    assert BashTool.classify_command("ls -la") == "read"
    assert BashTool.classify_command("rm foo") == "write"
    assert BashTool.classify_command("ls && rm foo") == "write"
    assert BashTool.classify_command("cat foo && grep bar") == "read"


def test_read_file_tool():
    read = ReadFileTool()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("line1\nline2\nline3\n")
        path = f.name

    result = read.execute({"path": path})
    assert not result.is_error
    assert "line1" in result.content
    assert path in [os.path.abspath(p) for p in read.read_files] or os.path.abspath(path) in read.read_files
    os.unlink(path)


def test_read_file_blocked_device():
    read = ReadFileTool()
    err = read.validate({"path": "/dev/zero"})
    assert err is not None and "Blocked" in err


def test_write_file_tool():
    write = WriteFileTool()
    path = os.path.join(tempfile.gettempdir(), "hermit_agent_test_write.txt")
    result = write.execute({"path": path, "content": "hello world\n"})
    assert not result.is_error
    assert os.path.exists(path)
    os.unlink(path)


def test_write_unc_blocked():
    write = WriteFileTool()
    err = write.validate({"path": "\\\\server\\share\\file", "content": "x"})
    assert err is not None and "UNC" in err


def test_edit_file_tool():
    read = ReadFileTool()
    edit = EditFileTool(read_file_tool=read)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("def hello():\n    return 'hi'\n")
        path = f.name

    # Read first
    read.execute({"path": path})
    # Edit
    result = edit.execute({"path": path, "old_string": "return 'hi'", "new_string": "return 'hello'"})
    assert not result.is_error
    assert "Update(" in result.content

    with open(path) as f:
        assert "return 'hello'" in f.read()
    os.unlink(path)


def test_expand_path():
    assert _expand_path("~/test") == os.path.expanduser("~/test")
    assert os.path.isabs(_expand_path("./foo", "/tmp"))


def test_safe_path():
    assert _is_safe_path("/tmp/test") is None  # allowed
    result = _is_safe_path("/etc/passwd")
    assert result is not None and "traversal" in result.lower()


def test_check_secrets():
    assert len(_check_secrets("normal code")) == 0
    assert len(_check_secrets("api_key=sk-abc123xyz")) > 0
    assert len(_check_secrets("ghp_abcdefghijklmnopqrstuvwxyz0123456789")) > 0


def test_permission_modes():
    for mode in PermissionMode:
        pc = PermissionChecker(mode=mode)
        assert pc.mode == mode


def test_permission_yolo():
    pc = PermissionChecker(mode=PermissionMode.YOLO)
    assert pc.check("bash", {"command": "rm -rf /"}, False) is True


def test_permission_plan_blocks_writes():
    pc = PermissionChecker(mode=PermissionMode.PLAN)
    assert pc.check("read_file", {"path": "/tmp/x"}, True) is True
    assert pc.check("bash", {"command": "rm foo"}, False) is False


def test_permission_3step():
    pc = PermissionChecker(mode=PermissionMode.ACCEPT_EDITS)
    r = pc.check_3step("read_file", {}, True)
    assert r.behavior == PermissionBehavior.ALLOW
    r2 = pc.check_3step("edit_file", {}, False)
    assert r2.behavior == PermissionBehavior.ALLOW


def test_bash_safety_classifier():
    assert classify_bash_safety("ls -la") == "safe"
    assert classify_bash_safety("git log") == "safe"
    assert classify_bash_safety("rm -rf /") == "unsafe"
    assert classify_bash_safety("curl https://example.com") == "unknown"


def test_context_token_estimate():
    assert estimate_tokens("hello world") > 0
    assert estimate_tokens("") == 0


def test_context_compact_levels():
    cm = ContextManager(max_context_tokens=32000)
    assert cm.get_compact_level([]) == 0
    # Large message → high level
    big = [{"role": "user", "content": "x" * 100000}]
    assert cm.get_compact_level(big) > 0


def test_memory_system():
    with tempfile.TemporaryDirectory() as tmpdir:
        mem = MemorySystem(memory_dir=tmpdir)
        mem.save("test_key", "test content", "project", "test description")

        entry = mem.load("test_key")
        assert entry is not None
        assert entry.content == "test content"

        entries = mem.list_all()
        assert len(entries) == 1

        mem.delete("test_key")
        assert mem.load("test_key") is None


def test_skill_registry():
    reg = SkillRegistry()
    assert len(reg.list_skills()) >= 3  # commit, review, test, slop-clean

    # Runtime register/unregister
    reg.register(Skill(name="test_rt", description="test", content="test", source="runtime"))
    assert reg.get("test_rt") is not None
    reg.unregister("test_rt")
    assert reg.get("test_rt") is None


def test_clarity_score():
    score = ClarityScore(goal=0.9, constraints=0.5, criteria=0.7)
    ambiguity = score.ambiguity(ProjectType.GREENFIELD)
    assert 0 < ambiguity < 1
    assert score.weakest_dimension(ProjectType.GREENFIELD) == "Constraint Clarity"


def test_create_default_tools():
    tools = create_default_tools(cwd="/tmp")
    names = [t.name for t in tools]
    assert "bash" in names
    assert "read_file" in names
    assert "web_search" in names
    assert "stackoverflow_search" in names
    assert "github_search" in names
    assert len(names) >= 14


# ─── Execution ─────────────────────────────

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {test.__name__}: {e}")
            failed += 1
    print(f"\n{passed}/{passed+failed} tests passed")
    if failed:
        sys.exit(1)
