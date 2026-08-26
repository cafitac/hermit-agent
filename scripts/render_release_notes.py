#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Keep release rendering self-contained. Public releases must not depend on
# retired documentation files that are intentionally excluded from the product.
OPENING = (
    "Hermit keeps planner judgment premium while pushing repetitive repo work "
    "into a dedicated MCP executor lane."
)
CLOSING = "The planner stays premium; the repo mechanics stay efficient."


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def safe_git(*args: str) -> str:
    try:
        return git(*args)
    except Exception:
        return ""


def detect_previous_tag(current_tag: str) -> str:
    tags = [t.strip() for t in safe_git("tag", "--list", "v*").splitlines() if t.strip()]
    tags = [t for t in tags if t != current_tag]
    def key(tag: str):
        parts = tag.lstrip("v").split(".")
        return tuple(int(p) if p.isdigit() else 0 for p in parts)
    tags.sort(key=key)
    return tags[-1] if tags else ""


def recent_subjects(previous_tag: str) -> list[str]:
    if previous_tag:
        text = safe_git("log", "--format=%s", f"{previous_tag}..HEAD")
    else:
        text = safe_git("log", "-n", "5", "--format=%s")
    subjects = [line.strip() for line in text.splitlines() if line.strip()]
    cleaned: list[str] = []
    seen: set[str] = set()
    for subject in subjects:
        if subject.startswith("chore: release v"):
            continue
        if subject in seen:
            continue
        seen.add(subject)
        cleaned.append(subject)
    return cleaned[:5]


def sentence_case(subject: str) -> str:
    subject = re.sub(r"\s*\(#\d+\)$", "", subject).strip()
    if not subject:
        return subject
    return subject[0].upper() + subject[1:]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--reason", default="automated main-branch release")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    current_tag = args.tag
    version = args.version
    repo = args.repo
    reason = args.reason
    previous_tag = detect_previous_tag(current_tag)
    subjects = recent_subjects(previous_tag)
    headline = subjects[0] if subjects else f"Automated release for {current_tag}"
    summary = sentence_case(headline)

    bullets = []
    if subjects:
        for subject in subjects[:3]:
            bullets.append(f"- {sentence_case(subject)}")
    else:
        bullets.append(f"- Automated release for {current_tag}.")

    if previous_tag:
        range_line = f"Changes since {previous_tag}."
    else:
        range_line = "Changes from the latest main-branch release payload."

    body = f"""## Summary
{summary}

## What changed
{chr(10).join(bullets)}
- Published packages: npm @cafitac/hermit-agent@{version} and PyPI cafitac-hermit-agent=={version}.

## Why it matters
{OPENING} This release was classified as: {reason}. {range_line}

## Operator notes
- Release tag: {current_tag}
- If protected main blocks workflow write-back, the publish workflow opens a metadata-only sync PR automatically.
- README, changelog, and package metadata stay aligned through the same release path.

## Assets
- GitHub Release: https://github.com/{repo}/releases/tag/{current_tag}
- npm: https://www.npmjs.com/package/@cafitac/hermit-agent
- PyPI: https://pypi.org/project/cafitac-hermit-agent/
- README: https://github.com/{repo}#readme

> {CLOSING}
"""
    Path(args.out).write_text(body)


if __name__ == "__main__":
    main()
