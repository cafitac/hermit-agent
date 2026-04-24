"""MonitorTool incremental streaming test (G44)."""

import os
import tempfile
import uuid
from unittest.mock import MagicMock


from hermit_agent.tools.shell.monitor import MonitorTool, _read_new
from hermit_agent.tools.shell import bash as bash_module


# --- _read_new unit tests ---

def test_read_new_full_content():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("hello world")
        path = f.name
    try:
        content, new_offset = _read_new(path, 0)
        assert content == "hello world"
        assert new_offset == len("hello world")
    finally:
        os.unlink(path)


def test_read_new_incremental():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("first")
        path = f.name
    try:
        _, offset = _read_new(path, 0)
        assert offset == 5

        # Append additional content to file
        with open(path, "a") as f:
            f.write("second")

        new_content, new_offset = _read_new(path, offset)
        assert new_content == "second"
        assert new_offset == 11
    finally:
        os.unlink(path)


def test_read_new_no_change():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("data")
        path = f.name
    try:
        _, offset = _read_new(path, 0)
        content, new_offset = _read_new(path, offset)
        assert content == ""
        assert new_offset == offset
    finally:
        os.unlink(path)


def test_read_new_missing_file():
    content, offset = _read_new("/nonexistent/path.txt", 0)
    assert content == ""
    assert offset == 0


# --- MonitorTool integration tests ---

def _register_fake_process(pid: str, stdout_content: str = "", stderr_content: str = "", running: bool = True):
    """Register a fake process for testing in the registry."""
    stdout_f = tempfile.NamedTemporaryFile(mode="w", suffix=".stdout", delete=False)
    stderr_f = tempfile.NamedTemporaryFile(mode="w", suffix=".stderr", delete=False)
    stdout_f.write(stdout_content)
    stderr_f.write(stderr_content)
    stdout_f.close()
    stderr_f.close()

    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.return_value = None if running else 0

    bash_module._background_registry[pid] = {
        "proc": mock_proc,
        "stdout_path": stdout_f.name,
        "stderr_path": stderr_f.name,
        "command": "test",
        "stdout_offset": 0,
        "stderr_offset": 0,
    }
    return stdout_f.name, stderr_f.name


def _cleanup_files(*paths):
    for p in paths:
        try:
            os.unlink(p)
        except Exception:
            pass


def test_monitor_unknown_pid():
    tool = MonitorTool()
    result = tool.execute({"process_id": "deadbeef"})
    assert result.is_error
    assert "No background process" in result.content


def test_monitor_running_process():
    pid = str(uuid.uuid4())[:8]
    stdout_path, stderr_path = _register_fake_process(pid, stdout_content="line1\n", running=True)
    try:
        tool = MonitorTool()
        result = tool.execute({"process_id": pid})
        assert not result.is_error
        assert "running" in result.content
        assert "line1" in result.content
    finally:
        _cleanup_files(stdout_path, stderr_path)
        bash_module._background_registry.pop(pid, None)


def test_monitor_incremental_output():
    """When called twice, the second call returns only new content."""
    pid = str(uuid.uuid4())[:8]
    stdout_path, stderr_path = _register_fake_process(pid, stdout_content="first\n", running=True)
    try:
        tool = MonitorTool()

        # 1st call: returns "first\n"
        result1 = tool.execute({"process_id": pid})
        assert "first" in result1.content

        # Append to file
        with open(stdout_path, "a") as f:
            f.write("second\n")

        # 2nd call: returns only "second\n"
        result2 = tool.execute({"process_id": pid})
        assert "second" in result2.content
        assert "first" not in result2.content
    finally:
        _cleanup_files(stdout_path, stderr_path)
        bash_module._background_registry.pop(pid, None)


def test_monitor_no_new_output_message():
    """Running process with no new output → (no new output) message."""
    pid = str(uuid.uuid4())[:8]
    stdout_path, stderr_path = _register_fake_process(pid, stdout_content="", running=True)
    try:
        tool = MonitorTool()
        result = tool.execute({"process_id": pid})
        assert "no new output" in result.content
    finally:
        _cleanup_files(stdout_path, stderr_path)
        bash_module._background_registry.pop(pid, None)


def test_monitor_done_process_cleans_registry():
    """Completed process → removed from the registry."""
    pid = str(uuid.uuid4())[:8]
    stdout_path, stderr_path = _register_fake_process(pid, stdout_content="done\n", running=False)
    try:
        tool = MonitorTool()
        result = tool.execute({"process_id": pid})
        assert "done (exit code 0)" in result.content
        assert pid not in bash_module._background_registry
    finally:
        _cleanup_files(stdout_path, stderr_path)
