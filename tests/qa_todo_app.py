"""
LLM Coding Agent Performance QA Test

Requests the local LLM to create a Django + React Todo app, then
automatically checks the completeness of the result.

Usage:
  # Default (qwen3:8b)
  python3 tests/qa_todo_app.py

  # Specify model
  python3 tests/qa_todo_app.py --model qwen3:14b

  # Specify max turns
  python3 tests/qa_todo_app.py --max-turns 30

  # Specify working directory (Default: /tmp/agent-qa-{timestamp})
  python3 tests/qa_todo_app.py --workdir /tmp/my-todo-test
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Add path to import the agent package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hermit_agent.llm_client import OllamaClient
from hermit_agent.loop import AgentLoop
from hermit_agent.tools import create_default_tools


# ──────────────────────────────────────────────
# Define prompts
# ──────────────────────────────────────────────

TASK_PROMPT = """\
Build a full-stack Todo application with the following requirements:

## Tech Stack
- Backend: Python + Django (Django REST Framework)
- Frontend: React (Create React App or Vite)
- Database: SQLite (default Django)
- Any additional libraries are allowed

## Required Features
1. **CRUD Operations**: Create, Read, Update, Delete todos
2. **Todo Model**: Each todo has: id, title, description (optional), completed (boolean), created_at
3. **REST API**: Django REST Framework API with proper serializers
4. **React Frontend**: Clean UI with:
   - Add new todo form
   - Todo list display
   - Toggle complete/incomplete
   - Delete todo button
   - Filter: All / Active / Completed
5. **CORS**: Properly configured for frontend-backend communication

## Directory Structure
Create everything under the current directory:
```
backend/         # Django project
  manage.py
  config/        # Django settings
  todos/         # Todo app
frontend/        # React project
  src/
  package.json
```

## Instructions
- Create ALL files needed to run the app
- Include a README.md with setup and run instructions
- Make sure the Django API is functional
- Make sure the React app compiles without errors
- Use modern React patterns (hooks, functional components)

Start by creating the backend, then the frontend. Test each step.
"""


# ──────────────────────────────────────────────
# QA check items
# ──────────────────────────────────────────────

@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


@dataclass
class QAReport:
    checks: list[CheckResult] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    total_turns: int = 0
    model: str = ""
    workdir: str = ""

    def add(self, name: str, passed: bool, detail: str = ""):
        self.checks.append(CheckResult(name, passed, detail))

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def total_count(self) -> int:
        return len(self.checks)

    @property
    def score(self) -> float:
        if self.total_count == 0:
            return 0.0
        return self.passed_count / self.total_count * 100

    @property
    def elapsed(self) -> float:
        return self.end_time - self.start_time

    def print_report(self):
        BOLD = "\033[1m"
        GREEN = "\033[32m"
        RED = "\033[31m"
        DIM = "\033[2m"
        RESET = "\033[0m"

        print(f"\n{'=' * 60}")
        print(f"{BOLD}QA REPORT — Todo App Build Test{RESET}")
        print(f"{'=' * 60}")
        print(f"{DIM}Model: {self.model}{RESET}")
        print(f"{DIM}Workdir: {self.workdir}{RESET}")
        print(f"{DIM}Turns: {self.total_turns} | Time: {self.elapsed:.0f}s{RESET}")
        print(f"{'─' * 60}")

        for check in self.checks:
            status = f"{GREEN}PASS{RESET}" if check.passed else f"{RED}FAIL{RESET}"
            print(f"  [{status}] {check.name}")
            if check.detail:
                print(f"         {DIM}{check.detail}{RESET}")

        print(f"{'─' * 60}")
        color = GREEN if self.score >= 70 else RED
        print(f"  {BOLD}Score: {color}{self.passed_count}/{self.total_count} ({self.score:.0f}%){RESET}")
        print(f"{'=' * 60}")


def run_qa_checks(workdir: str) -> QAReport:
    """Perform QA checks on the output."""
    report = QAReport(workdir=workdir)
    wd = Path(workdir)

    # ── Backend Checks ──

    # 1. Django project exists
    manage_py = wd / "backend" / "manage.py"
    report.add("backend/manage.py exists", manage_py.exists())

    # 2. Django settings exist
    settings_candidates = list((wd / "backend").rglob("settings.py"))
    report.add("Django settings.py exists", len(settings_candidates) > 0,
               str(settings_candidates[0]) if settings_candidates else "not found")

    # 3. Todo model exists
    models_candidates = list((wd / "backend").rglob("models.py"))
    has_todo_model = False
    for mp in models_candidates:
        content = mp.read_text(errors="ignore")
        if "class Todo" in content or "class TodoItem" in content:
            has_todo_model = True
            break
    report.add("Todo model defined", has_todo_model)

    # 4. Serializer exists
    serializer_files = list((wd / "backend").rglob("serializers.py"))
    report.add("DRF serializer exists", len(serializer_files) > 0)

    # 5. URL routing
    url_files = list((wd / "backend").rglob("urls.py"))
    has_api_urls = False
    for uf in url_files:
        content = uf.read_text(errors="ignore")
        if "todo" in content.lower() or "router" in content.lower():
            has_api_urls = True
            break
    report.add("API URL routing configured", has_api_urls)

    # 6. Views/ViewSet exist
    view_files = list((wd / "backend").rglob("views.py"))
    has_views = False
    for vf in view_files:
        content = vf.read_text(errors="ignore")
        if "ViewSet" in content or "APIView" in content or "def " in content:
            has_views = True
            break
    report.add("API views/viewsets defined", has_views)

    # 7. CORS settings
    cors_configured = False
    for sf in settings_candidates:
        content = sf.read_text(errors="ignore")
        if "cors" in content.lower():
            cors_configured = True
            break
    report.add("CORS configured", cors_configured)

    # 8. Django syntax check (manage.py check)
    django_check_ok = False
    try:
        result = subprocess.run(
            [sys.executable, "manage.py", "check", "--no-color"],
            capture_output=True, text=True, cwd=str(wd / "backend"), timeout=30,
        )
        django_check_ok = result.returncode == 0
        detail = "OK" if django_check_ok else result.stderr[:100]
    except Exception as e:
        detail = str(e)
    report.add("Django check passes", django_check_ok, detail)

    # ── Frontend Checks ──

    # 9. package.json exists
    pkg_json = wd / "frontend" / "package.json"
    report.add("frontend/package.json exists", pkg_json.exists())

    # 10. React dependencies
    has_react = False
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text())
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            has_react = "react" in deps
        except Exception:
            pass
    report.add("React in dependencies", has_react)

    # 11. src/ directory
    src_dir = wd / "frontend" / "src"
    report.add("frontend/src/ exists", src_dir.exists())

    # 12. App component exists
    app_files = list((wd / "frontend" / "src").rglob("App.*")) if src_dir.exists() else []
    report.add("App component exists", len(app_files) > 0)

    # 13. Todo-related components/code
    has_todo_component = False
    if src_dir.exists():
        for f in src_dir.rglob("*"):
            if f.is_file() and f.suffix in (".js", ".jsx", ".tsx", ".ts"):
                content = f.read_text(errors="ignore")
                if "todo" in content.lower() and ("useState" in content or "useEffect" in content):
                    has_todo_component = True
                    break
    report.add("Todo component with React hooks", has_todo_component)

    # 14. API call code (fetch/axios)
    has_api_call = False
    if src_dir.exists():
        for f in src_dir.rglob("*"):
            if f.is_file() and f.suffix in (".js", ".jsx", ".tsx", ".ts"):
                content = f.read_text(errors="ignore")
                if "fetch(" in content or "axios" in content:
                    has_api_call = True
                    break
    report.add("API calls in frontend (fetch/axios)", has_api_call)

    # ── Documentation check ──

    # 15. README exists
    readme = wd / "README.md"
    report.add("README.md exists", readme.exists())

    return report


# ──────────────────────────────────────────────
# Main execution
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="QA Test: Todo App Build")
    parser.add_argument("--model", default="qwen3:8b", help="Model name")
    parser.add_argument("--base-url", default="http://localhost:11434/v1", help="API base URL")
    parser.add_argument("--max-turns", type=int, default=50, help="Max agent turns")
    parser.add_argument("--workdir", default=None, help="Working directory for the project")
    parser.add_argument("--check-only", default=None, help="Skip build, only run QA checks on existing dir")
    args = parser.parse_args()

    # check-only mode
    if args.check_only:
        report = run_qa_checks(args.check_only)
        report.model = "(check-only)"
        report.print_report()
        return

    # Create working directory
    if args.workdir:
        workdir = args.workdir
    else:
        workdir = f"/tmp/agent-qa-{int(time.time())}"
    os.makedirs(workdir, exist_ok=True)

    print(f"{'=' * 60}")
    print("QA TEST: Todo App Build")
    print(f"{'=' * 60}")
    print(f"Model:   {args.model}")
    print(f"Workdir: {workdir}")
    print(f"Max turns: {args.max_turns}")
    print(f"{'=' * 60}\n")

    # Agent configuration
    llm = OllamaClient(base_url=args.base_url, model=args.model)
    tools = create_default_tools(cwd=workdir)
    loop = AgentLoop(llm=llm, tools=tools, cwd=workdir)
    loop.MAX_TURNS = args.max_turns

    # Agent execution
    start_time = time.time()
    print("Starting agent...\n")

    try:
        result = loop.run(TASK_PROMPT)
        print(f"\n{result}\n")
    except KeyboardInterrupt:
        print("\n[Interrupted by user]")
    except Exception as e:
        print(f"\n[Agent error: {e}]")

    end_time = time.time()

    # QA check
    report = run_qa_checks(workdir)
    report.model = args.model
    report.start_time = start_time
    report.end_time = end_time
    report.total_turns = loop.turn_count
    report.print_report()

    # Also save results as JSON
    report_path = os.path.join(workdir, "qa_report.json")
    with open(report_path, "w") as f:
        json.dump({
            "model": report.model,
            "score": report.score,
            "passed": report.passed_count,
            "total": report.total_count,
            "turns": report.total_turns,
            "elapsed_seconds": round(report.elapsed, 1),
            "workdir": report.workdir,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail}
                for c in report.checks
            ],
        }, f, indent=2)
    print(f"\nReport saved to: {report_path}")


if __name__ == "__main__":
    main()
