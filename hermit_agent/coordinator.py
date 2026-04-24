"""Multi-agent coordination — based on Claude Code's coordinator/ + AgentTool pattern.

Three modes:
1. Coordinator: hub directs workers (does not write code itself)
2. Parallel: run independent tasks concurrently
3. Pipeline: sequential agent chain
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum

from .llm_client import LLMClientBase
from .permissions import PermissionMode
from .tools.base import Tool, ToolResult


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentTask:
    task_id: str
    description: str
    prompt: str
    status: AgentStatus = AgentStatus.PENDING
    result: str = ""
    error: str = ""
    elapsed: float = 0.0


@dataclass
class CoordinatorResult:
    tasks: list[AgentTask]
    total_elapsed: float = 0.0

    @property
    def summary(self) -> str:
        lines = [f"Completed {len(self.tasks)} tasks in {self.total_elapsed:.1f}s:\n"]
        for t in self.tasks:
            status = "OK" if t.status == AgentStatus.COMPLETED else "FAIL"
            lines.append(f"  [{status}] {t.description} ({t.elapsed:.1f}s)")
            if t.error:
                lines.append(f"        Error: {t.error[:100]}")
        return "\n".join(lines)


def classify_task_complexity(task: dict) -> str:
    """Classify task complexity: 'simple', 'medium', 'complex'.
    Determines max_turns for the sub-agent."""
    prompt = task.get("prompt", "")
    if len(prompt) < 100:
        return "simple"
    keywords_complex = ["refactor", "redesign", "migrate", "architecture", "integrate", "implement full"]
    if any(k in prompt.lower() for k in keywords_complex):
        return "complex"
    keywords_medium = ["add", "create", "update", "modify", "fix", "test"]
    if any(k in prompt.lower() for k in keywords_medium):
        return "medium"
    return "medium"


COMPLEXITY_CONFIG: dict[str, dict[str, float | int]] = {
    "simple": {"max_turns": 10, "temperature": 0.0},
    "medium": {"max_turns": 20, "temperature": 0.0},
    "complex": {"max_turns": 40, "temperature": 0.1},
}


def run_parallel_agents(
    tasks: list[dict],
    llm: LLMClientBase,
    cwd: str = ".",
    max_workers: int = 3,
    emitter=None,
) -> CoordinatorResult:
    """Run independent tasks in parallel.

    tasks: [{"description": "...", "prompt": "..."}, ...]
    """
    from .loop import AgentLoop
    from .tools import create_default_tools

    agent_tasks = [
        AgentTask(
            task_id=uuid.uuid4().hex[:8],
            description=t["description"],
            prompt=t["prompt"],
        )
        for t in tasks
    ]

    start = time.time()

    def _run_one(task: AgentTask) -> AgentTask:
        task.status = AgentStatus.RUNNING
        task_start = time.time()
        try:
            tools = create_default_tools(cwd=cwd)
            agent = AgentLoop(
                llm=llm,
                tools=tools,
                cwd=cwd,
                permission_mode=PermissionMode.YOLO,
            )
            complexity = classify_task_complexity({"prompt": task.prompt})
            config = COMPLEXITY_CONFIG[complexity]
            agent.MAX_TURNS = int(config["max_turns"])
            agent.streaming = True
            if emitter:
                agent.emitter = emitter
            task.result = agent.run(task.prompt)
            task.status = AgentStatus.COMPLETED
        except Exception as e:
            task.status = AgentStatus.FAILED
            task.error = str(e)
        task.elapsed = time.time() - task_start
        return task

    # Parallel execution (ThreadPoolExecutor)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_run_one, t): t for t in agent_tasks}
        for future in as_completed(futures):
            task = futures[future]
            try:
                future.result()
            except Exception as e:
                task.status = AgentStatus.FAILED
                task.error = str(e)

    return CoordinatorResult(
        tasks=agent_tasks,
        total_elapsed=time.time() - start,
    )


def run_pipeline_agents(
    steps: list[dict],
    llm: LLMClientBase,
    cwd: str = ".",
    emitter=None,
) -> CoordinatorResult:
    """Sequential agent chain. Previous step's result is included in next step's input.

    steps: [{"description": "...", "prompt": "..."}, ...]
    """
    from .loop import AgentLoop
    from .tools import create_default_tools

    agent_tasks = []
    previous_result = ""
    start = time.time()

    for step in steps:
        task = AgentTask(
            task_id=uuid.uuid4().hex[:8],
            description=step["description"],
            prompt=step["prompt"],
        )
        task.status = AgentStatus.RUNNING
        task_start = time.time()

        try:
            tools = create_default_tools(cwd=cwd)
            agent = AgentLoop(
                llm=llm,
                tools=tools,
                cwd=cwd,
                permission_mode=PermissionMode.YOLO,
            )
            agent.MAX_TURNS = 20
            agent.streaming = True
            if emitter:
                agent.emitter = emitter

            # Include previous result in context
            prompt = step["prompt"]
            if previous_result:
                prompt = f"Previous step result:\n{previous_result[:3000]}\n\nYour task:\n{prompt}"

            task.result = agent.run(prompt)
            task.status = AgentStatus.COMPLETED
            previous_result = task.result
        except Exception as e:
            task.status = AgentStatus.FAILED
            task.error = str(e)
            previous_result = f"[Previous step failed: {e}]"

        task.elapsed = time.time() - task_start
        agent_tasks.append(task)

    return CoordinatorResult(
        tasks=agent_tasks,
        total_elapsed=time.time() - start,
    )


# ─── Coordinator tool (used by AgentLoop) ─────────────

class CoordinatorTool(Tool):
    """Multi-agent coordination tool.

    Simplified from Claude Code's TeamCreateTool + AgentTool pattern.
    """

    name = "coordinate"
    description = "Run multiple sub-agents in parallel or as a pipeline. Use for complex tasks that benefit from decomposition."

    def __init__(self, llm: LLMClientBase, cwd: str = "."):
        self.llm = llm
        self.cwd = cwd

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["parallel", "pipeline"],
                    "description": "parallel: independent tasks at once. pipeline: sequential chain.",
                },
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "prompt": {"type": "string"},
                        },
                        "required": ["description", "prompt"],
                    },
                    "description": "List of tasks to execute",
                },
            },
            "required": ["mode", "tasks"],
        }

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema(),
            },
        }

    @property
    def is_read_only(self) -> bool:
        return False

    @property
    def is_concurrent_safe(self) -> bool:
        return False

    def validate(self, input: dict) -> str | None:
        if not input.get("tasks"):
            return "At least one task is required"
        return None

    def execute(self, input: dict) -> ToolResult:
        mode = input.get("mode", "parallel")
        tasks = input.get("tasks", [])

        print(f"\n\033[35m  [Coordinator: {mode} mode, {len(tasks)} tasks]\033[0m")

        if mode == "pipeline":
            result = run_pipeline_agents(tasks, self.llm, self.cwd)
        else:
            result = run_parallel_agents(tasks, self.llm, self.cwd)

        print(f"\033[35m  [Coordinator done: {result.total_elapsed:.1f}s]\033[0m")
        return ToolResult(content=result.summary)
