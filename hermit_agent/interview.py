"""Deep interview system — based on OMC's deep-interview pattern.

Transforms ambiguous ideas into clear specs via Socratic questioning.
Gates readiness using a mathematical ambiguity score.

Usage:
  /interview <idea>
  "Deep interview", "Interview", "deep interview"
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum


class ProjectType(Enum):
    GREENFIELD = "greenfield"
    BROWNFIELD = "brownfield"


class ChallengeMode(Enum):
    CONTRARIAN = "contrarian"   # Round 4+: challenge assumptions
    SIMPLIFIER = "simplifier"   # Round 6+: remove complexity
    ONTOLOGIST = "ontologist"   # Round 8+: find the essence


@dataclass
class ClarityScore:
    goal: float = 0.0
    constraints: float = 0.0
    criteria: float = 0.0
    context: float = 0.0  # brownfield only

    def ambiguity(self, project_type: ProjectType) -> float:
        if project_type == ProjectType.GREENFIELD:
            clarity = self.goal * 0.40 + self.constraints * 0.30 + self.criteria * 0.30
        else:
            clarity = self.goal * 0.35 + self.constraints * 0.25 + self.criteria * 0.25 + self.context * 0.15
        return round(1.0 - clarity, 3)

    def weakest_dimension(self, project_type: ProjectType) -> str:
        dims = {"Goal Clarity": self.goal, "Constraint Clarity": self.constraints, "Success Criteria": self.criteria}
        if project_type == ProjectType.BROWNFIELD:
            dims["Context Clarity"] = self.context
        return min(dims, key=dims.get)  # type: ignore

    def to_dict(self) -> dict:
        return {"goal": self.goal, "constraints": self.constraints, "criteria": self.criteria, "context": self.context}

    @staticmethod
    def from_dict(d: dict) -> ClarityScore:
        return ClarityScore(goal=d.get("goal", 0), constraints=d.get("constraints", 0),
                            criteria=d.get("criteria", 0), context=d.get("context", 0))


@dataclass
class InterviewRound:
    question: str
    answer: str
    scores: ClarityScore
    ambiguity: float
    challenge_mode: str | None = None


@dataclass
class InterviewState:
    interview_id: str
    project_type: ProjectType
    initial_idea: str
    rounds: list[InterviewRound] = field(default_factory=list)
    current_scores: ClarityScore = field(default_factory=ClarityScore)
    threshold: float = 0.2
    max_rounds: int = 20
    codebase_context: str = ""
    challenge_modes_used: list[str] = field(default_factory=list)

    @property
    def current_ambiguity(self) -> float:
        return self.current_scores.ambiguity(self.project_type)

    @property
    def round_count(self) -> int:
        return len(self.rounds)

    @property
    def is_complete(self) -> bool:
        return self.current_ambiguity <= self.threshold

    def to_dict(self) -> dict:
        return {
            "interview_id": self.interview_id,
            "project_type": self.project_type.value,
            "initial_idea": self.initial_idea,
            "rounds": [
                {"question": r.question, "answer": r.answer,
                 "scores": r.scores.to_dict(), "ambiguity": r.ambiguity,
                 "challenge_mode": r.challenge_mode}
                for r in self.rounds
            ],
            "current_scores": self.current_scores.to_dict(),
            "threshold": self.threshold,
            "codebase_context": self.codebase_context,
            "challenge_modes_used": self.challenge_modes_used,
        }

    @staticmethod
    def from_dict(d: dict) -> InterviewState:
        state = InterviewState(
            interview_id=d["interview_id"],
            project_type=ProjectType(d["project_type"]),
            initial_idea=d["initial_idea"],
            threshold=d.get("threshold", 0.2),
            codebase_context=d.get("codebase_context", ""),
            challenge_modes_used=d.get("challenge_modes_used", []),
        )
        state.current_scores = ClarityScore.from_dict(d.get("current_scores", {}))
        for r in d.get("rounds", []):
            state.rounds.append(InterviewRound(
                question=r["question"], answer=r["answer"],
                scores=ClarityScore.from_dict(r.get("scores", {})),
                ambiguity=r.get("ambiguity", 1.0),
                challenge_mode=r.get("challenge_mode"),
            ))
        return state


INTERVIEW_DIR = os.path.expanduser("~/.hermit/interviews")


def save_interview(state: InterviewState):
    os.makedirs(INTERVIEW_DIR, exist_ok=True)
    path = os.path.join(INTERVIEW_DIR, f"{state.interview_id}.json")
    with open(path, "w") as f:
        json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)


def load_interview(interview_id: str) -> InterviewState | None:
    path = os.path.join(INTERVIEW_DIR, f"{interview_id}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return InterviewState.from_dict(json.load(f))


def load_latest_interview() -> InterviewState | None:
    if not os.path.exists(INTERVIEW_DIR):
        return None
    files = sorted(
        [f for f in os.listdir(INTERVIEW_DIR) if f.endswith(".json")],
        key=lambda f: os.path.getmtime(os.path.join(INTERVIEW_DIR, f)),
        reverse=True,
    )
    if not files:
        return None
    with open(os.path.join(INTERVIEW_DIR, files[0])) as f:
        return InterviewState.from_dict(json.load(f))


# ─── question generation ──────────────────────────

QUESTION_STYLES = {
    "Goal Clarity": 'Ask "What exactly happens when...?" to clarify the primary objective.',
    "Constraint Clarity": 'Ask "What are the boundaries?" to clarify limitations and non-goals.',
    "Success Criteria": 'Ask "How do we know it works?" to get testable acceptance criteria.',
    "Context Clarity": 'Ask "How does this fit with existing code?" to understand integration points.',
}

CHALLENGE_PROMPTS = {
    ChallengeMode.CONTRARIAN: (
        "CONTRARIAN mode: Challenge the user's core assumption. "
        "Ask 'What if the opposite were true?' or 'What if this constraint doesn't actually exist?'"
    ),
    ChallengeMode.SIMPLIFIER: (
        "SIMPLIFIER mode: Probe whether complexity can be removed. "
        "Ask 'What's the simplest version that would still be valuable?'"
    ),
    ChallengeMode.ONTOLOGIST: (
        "ONTOLOGIST mode: The ambiguity is still high. Find the essence. "
        "Ask 'What IS this, really?' or describe it in one sentence."
    ),
}


def generate_question_prompt(state: InterviewState) -> str:
    """LLM prompt for generating the next question."""
    weakest = state.current_scores.weakest_dimension(state.project_type)
    style = QUESTION_STYLES.get(weakest, "")

    transcript = ""
    for i, r in enumerate(state.rounds):
        transcript += f"\nRound {i+1} Q: {r.question}\nA: {r.answer}\n"

    # determine challenge mode
    challenge = ""
    round_n = state.round_count + 1
    if round_n >= 8 and state.current_ambiguity > 0.3 and ChallengeMode.ONTOLOGIST.value not in state.challenge_modes_used:
        challenge = CHALLENGE_PROMPTS[ChallengeMode.ONTOLOGIST]
    elif round_n >= 6 and ChallengeMode.SIMPLIFIER.value not in state.challenge_modes_used:
        challenge = CHALLENGE_PROMPTS[ChallengeMode.SIMPLIFIER]
    elif round_n >= 4 and ChallengeMode.CONTRARIAN.value not in state.challenge_modes_used:
        challenge = CHALLENGE_PROMPTS[ChallengeMode.CONTRARIAN]

    return f"""Generate ONE focused interview question for this project idea.

Idea: {state.initial_idea}
Project type: {state.project_type.value}
{f"Codebase context: {state.codebase_context[:500]}" if state.codebase_context else ""}

Current clarity scores:
- Goal: {state.current_scores.goal}
- Constraints: {state.current_scores.constraints}
- Criteria: {state.current_scores.criteria}
{f"- Context: {state.current_scores.context}" if state.project_type == ProjectType.BROWNFIELD else ""}

Weakest dimension: {weakest}
{style}

{f"CHALLENGE MODE: {challenge}" if challenge else ""}

Previous Q&A:{transcript if transcript else " (none yet)"}

Generate exactly ONE question targeting the weakest dimension. Be specific, not generic.
Output ONLY the question text, nothing else."""


def generate_scoring_prompt(state: InterviewState) -> str:
    """LLM prompt for computing the ambiguity score."""
    transcript = ""
    for i, r in enumerate(state.rounds):
        transcript += f"\nRound {i+1} Q: {r.question}\nA: {r.answer}\n"

    brownfield_dim = ""
    if state.project_type == ProjectType.BROWNFIELD:
        brownfield_dim = "\n4. Context Clarity (0.0-1.0): Do we understand the existing system well enough?"

    return f"""Score clarity for this {state.project_type.value} project interview.

Idea: {state.initial_idea}
Transcript:{transcript}

Score each dimension from 0.0 to 1.0:
1. Goal Clarity (0.0-1.0): Is the primary objective unambiguous?
2. Constraint Clarity (0.0-1.0): Are boundaries and non-goals clear?
3. Success Criteria Clarity (0.0-1.0): Could you write tests that verify success?{brownfield_dim}

Respond as JSON only:
{{"goal": 0.0, "constraints": 0.0, "criteria": 0.0{', "context": 0.0' if state.project_type == ProjectType.BROWNFIELD else ''}}}"""


def generate_spec(state: InterviewState) -> str:
    """Generate the final spec document."""
    scores = state.current_scores
    ambiguity = state.current_ambiguity
    ptype = state.project_type

    transcript = ""
    for i, r in enumerate(state.rounds):
        mode = f" [{r.challenge_mode}]" if r.challenge_mode else ""
        transcript += f"\n### Round {i+1}{mode}\n**Q:** {r.question}\n**A:** {r.answer}\n**Ambiguity:** {r.ambiguity*100:.0f}%\n"

    if ptype == ProjectType.GREENFIELD:
        clarity_table = f"""| Goal | {scores.goal:.2f} | 0.40 | {scores.goal*0.40:.2f} |
| Constraints | {scores.constraints:.2f} | 0.30 | {scores.constraints*0.30:.2f} |
| Success Criteria | {scores.criteria:.2f} | 0.30 | {scores.criteria*0.30:.2f} |"""
    else:
        clarity_table = f"""| Goal | {scores.goal:.2f} | 0.35 | {scores.goal*0.35:.2f} |
| Constraints | {scores.constraints:.2f} | 0.25 | {scores.constraints*0.25:.2f} |
| Success Criteria | {scores.criteria:.2f} | 0.25 | {scores.criteria*0.25:.2f} |
| Context | {scores.context:.2f} | 0.15 | {scores.context*0.15:.2f} |"""

    return f"""# Deep Interview Spec

## Metadata
- Interview ID: {state.interview_id}
- Rounds: {state.round_count}
- Final Ambiguity: {ambiguity*100:.0f}%
- Type: {ptype.value}
- Threshold: {state.threshold*100:.0f}%

## Clarity Breakdown
| Dimension | Score | Weight | Weighted |
|-----------|-------|--------|----------|
{clarity_table}
| **Ambiguity** | | | **{ambiguity*100:.0f}%** |

## Original Idea
{state.initial_idea}

## Interview Transcript
{transcript}
"""


class DeepInterviewer:
    """Deep interview runner. Invoked via the /interview command from AgentLoop."""

    def __init__(self, llm, cwd: str = "."):
        self.llm = llm
        self.cwd = cwd

    def start(self, idea: str) -> InterviewState:
        """Start a new interview."""
        # detect brownfield
        has_source = any(
            os.path.exists(os.path.join(self.cwd, f))
            for f in ["package.json", "setup.py", "pyproject.toml", "Cargo.toml", "go.mod", "Makefile"]
        )
        ptype = ProjectType.BROWNFIELD if has_source else ProjectType.GREENFIELD

        state = InterviewState(
            interview_id=uuid.uuid4().hex[:12],
            project_type=ptype,
            initial_idea=idea,
        )
        save_interview(state)
        return state

    def generate_question(self, state: InterviewState) -> str:
        """Generate the next question."""
        prompt = generate_question_prompt(state)
        response = self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            system="You are a Socratic interviewer. Ask exactly ONE targeted question.",
            temperature=0.3,
        )
        return response.content or "What is the most important thing this should do?"

    def score_answer(self, state: InterviewState) -> ClarityScore:
        """Compute the ambiguity score for the current interview state."""
        prompt = generate_scoring_prompt(state)
        response = self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            system="Score project clarity. Respond as JSON only.",
            temperature=0.1,
        )
        try:
            # extract JSON
            text = response.content or "{}"
            match = re.search(r'\{[^}]+\}', text)
            if match:
                data = json.loads(match.group())
                return ClarityScore.from_dict(data)
        except Exception:
            pass
        return state.current_scores  # keep previous scores on failure

    def add_round(self, state: InterviewState, question: str, answer: str) -> float:
        """Add a round and update scores. Returns ambiguity."""
        # track challenge mode
        round_n = state.round_count + 1
        challenge_mode = None
        if round_n >= 8 and state.current_ambiguity > 0.3 and ChallengeMode.ONTOLOGIST.value not in state.challenge_modes_used:
            challenge_mode = ChallengeMode.ONTOLOGIST.value
            state.challenge_modes_used.append(challenge_mode)
        elif round_n >= 6 and ChallengeMode.SIMPLIFIER.value not in state.challenge_modes_used:
            challenge_mode = ChallengeMode.SIMPLIFIER.value
            state.challenge_modes_used.append(challenge_mode)
        elif round_n >= 4 and ChallengeMode.CONTRARIAN.value not in state.challenge_modes_used:
            challenge_mode = ChallengeMode.CONTRARIAN.value
            state.challenge_modes_used.append(challenge_mode)

        # compute scores
        scores = self.score_answer(state)
        state.current_scores = scores
        ambiguity = state.current_ambiguity

        state.rounds.append(InterviewRound(
            question=question, answer=answer,
            scores=scores, ambiguity=ambiguity,
            challenge_mode=challenge_mode,
        ))
        save_interview(state)
        return ambiguity

    def format_progress(self, state: InterviewState) -> str:
        """Format the current progress."""
        s = state.current_scores
        ambiguity = state.current_ambiguity
        weakest = s.weakest_dimension(state.project_type)

        lines = [
            f"Round {state.round_count} | Ambiguity: {ambiguity*100:.0f}%",
            "",
            "| Dimension | Score | Gap |",
            "|-----------|-------|-----|",
            f"| Goal | {s.goal:.2f} | {'Clear' if s.goal >= 0.9 else s.weakest_dimension(state.project_type) if 'Goal' in weakest else ''} |",
            f"| Constraints | {s.constraints:.2f} | {'Clear' if s.constraints >= 0.9 else ''} |",
            f"| Criteria | {s.criteria:.2f} | {'Clear' if s.criteria >= 0.9 else ''} |",
        ]
        if state.project_type == ProjectType.BROWNFIELD:
            lines.append(f"| Context | {s.context:.2f} | {'Clear' if s.context >= 0.9 else ''} |")

        if ambiguity <= state.threshold:
            lines.append("\nClarity threshold met! Ready to proceed.")
        else:
            lines.append(f"\nNext question targets: {weakest}")

        return "\n".join(lines)

    def crystallize_spec(self, state: InterviewState) -> str:
        """Generate and save the final spec."""
        spec = generate_spec(state)
        spec_dir = os.path.expanduser("~/.hermit/specs")
        os.makedirs(spec_dir, exist_ok=True)
        slug = re.sub(r'[^a-zA-Z0-9]', '-', state.initial_idea[:30].lower()).strip('-')
        path = os.path.join(spec_dir, f"deep-interview-{slug}.md")
        with open(path, "w") as f:
            f.write(spec)
        return path
