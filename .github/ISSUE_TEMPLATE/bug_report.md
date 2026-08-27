---
name: Bug report
about: Something broke
title: ""
labels: bug
---

## What happened

A short description.

## Reproduction

```bash
# exact command(s) you ran
```

Output (trim to the relevant part):

```
...
```

## Safe Hermit diagnosis

For installation, MCP registration, gateway, or executor problems, run this
from the affected repository and paste its output here:

```bash
hermit doctor --json
```

The report masks API keys, gateway keys, Bearer tokens, and URL credentials.
Still do **not** attach `~/.hermit/settings.json`, `.env` files, terminal
history, or any original key/token value.

## Expected

What you thought would happen.

## Environment

- HermitAgent commit / version: `git rev-parse --short HEAD` →
- Python: `python --version` →
- LLM backend: (ollama qwen3-coder:30b / z.ai glm-5.1 / ...)
- OS:
