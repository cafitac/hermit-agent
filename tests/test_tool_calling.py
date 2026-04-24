"""
Qwen3 + Ollama Tool Calling test

Ollama must be running and the qwen3:8b model must be installed.
  ollama pull qwen3:8b

Run:
  python3 tests/test_tool_calling.py
"""

import json
import urllib.request

OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
MODEL = "qwen3:8b"

# Define tools for testing
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file at the given path",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute file path to read"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell command and return stdout/stderr",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in a directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Directory path to list"}
                },
                "required": ["directory"]
            }
        }
    }
]


def call_ollama(messages, tools=None):
    """Ollama OpenAI-compatible API call"""
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.0,
    }
    if tools:
        payload["tools"] = tools

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def execute_tool(name, arguments):
    """Actual tool execution (simple implementation for testing)"""
    import subprocess
    import os

    if name == "read_file":
        path = arguments.get("path", "")
        try:
            with open(path) as f:
                content = f.read(2000)
            return f"[{len(content)} chars]\n{content}"
        except Exception as e:
            return f"Error: {e}"

    elif name == "run_command":
        cmd = arguments.get("command", "")
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return (result.stdout + result.stderr)[:2000] or "(no output)"
        except Exception as e:
            return f"Error: {e}"

    elif name == "list_files":
        directory = arguments.get("directory", ".")
        try:
            files = os.listdir(directory)
            return "\n".join(files[:50])
        except Exception as e:
            return f"Error: {e}"

    return f"Unknown tool: {name}"


def test_simple_chat():
    """Test 1: Simple conversation without tools"""
    print("=" * 60)
    print("TEST 1: Simple chat (no tools)")
    print("=" * 60)

    messages = [{"role": "user", "content": "Say hello in Korean, one sentence only."}]
    result = call_ollama(messages)

    if "error" in result:
        print(f"  FAIL: {result['error']}")
        return False

    content = result["choices"][0]["message"]["content"]
    print(f"  Response: {content}")
    print("  PASS")
    return True


def test_tool_calling():
    """Test 2: Tool calling (whether LLM generates tool_call)"""
    print("\n" + "=" * 60)
    print("TEST 2: Tool calling (tool_calls generation)")
    print("=" * 60)

    messages = [
        {"role": "user", "content": "List the files in /tmp directory."}
    ]
    result = call_ollama(messages, tools=TOOLS)

    if "error" in result:
        print(f"  FAIL: {result['error']}")
        return False

    message = result["choices"][0]["message"]
    tool_calls = message.get("tool_calls", [])

    if not tool_calls:
        print("  FAIL: No tool_calls in response")
        print(f"  Content: {message.get('content', '(empty)')[:200]}")
        return False

    tc = tool_calls[0]
    func_name = tc["function"]["name"]
    func_args = tc["function"]["arguments"]
    if isinstance(func_args, str):
        func_args = json.loads(func_args)

    print(f"  Tool called: {func_name}")
    print(f"  Arguments: {json.dumps(func_args)}")
    print("  PASS")
    return True


def test_agent_loop():
    """Test 3: Agent loop (tool call → result feedback → final response)"""
    print("\n" + "=" * 60)
    print("TEST 3: Agent loop (tool → feedback → response)")
    print("=" * 60)

    messages = [
        {
            "role": "system",
            "content": "You are a helpful coding assistant. Use tools to answer questions. Be concise."
        },
        {
            "role": "user",
            "content": "How many .md files are in the current directory? Use the run_command tool to find out."
        },
    ]

    max_turns = 5
    for turn in range(max_turns):
        print(f"\n  --- Turn {turn + 1} ---")
        result = call_ollama(messages, tools=TOOLS)

        if "error" in result:
            print(f"  FAIL: {result['error']}")
            return False

        message = result["choices"][0]["message"]
        tool_calls = message.get("tool_calls", [])

        if not tool_calls:
            # No tool call → final response
            content = message.get("content", "(empty)")
            print(f"  Final response: {content[:300]}")
            print(f"  PASS (completed in {turn + 1} turns)")
            return True

        # Tool call present → execution + result feedback
        messages.append(message)  # Add assistant message

        for tc in tool_calls:
            func_name = tc["function"]["name"]
            func_args = tc["function"]["arguments"]
            if isinstance(func_args, str):
                func_args = json.loads(func_args)

            print(f"  Tool: {func_name}({json.dumps(func_args)})")
            tool_result = execute_tool(func_name, func_args)
            print(f"  Result: {tool_result[:100]}...")

            # Feed tool_result back into the conversation
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": tool_result,
            })

    print(f"  FAIL: Max turns ({max_turns}) reached without completion")
    return False


def test_multi_tool():
    """Test 4: Consecutive multiple tool calls (file read → analysis)"""
    print("\n" + "=" * 60)
    print("TEST 4: Consecutive tool calls (read_file → analysis)")
    print("=" * 60)

    messages = [
        {
            "role": "system",
            "content": "You are a coding assistant. Use tools when needed. Be concise."
        },
        {
            "role": "user",
            "content": "Read the file docs/01-overview.md (relative to the repo root) and tell me how many sections it has."
        },
    ]

    max_turns = 5
    for turn in range(max_turns):
        print(f"\n  --- Turn {turn + 1} ---")
        result = call_ollama(messages, tools=TOOLS)

        if "error" in result:
            print(f"  FAIL: {result['error']}")
            return False

        message = result["choices"][0]["message"]
        tool_calls = message.get("tool_calls", [])

        if not tool_calls:
            content = message.get("content", "(empty)")
            print(f"  Final response: {content[:300]}")
            print(f"  PASS (completed in {turn + 1} turns)")
            return True

        messages.append(message)
        for tc in tool_calls:
            func_name = tc["function"]["name"]
            func_args = tc["function"]["arguments"]
            if isinstance(func_args, str):
                func_args = json.loads(func_args)

            print(f"  Tool: {func_name}({json.dumps(func_args)})")
            tool_result = execute_tool(func_name, func_args)
            print(f"  Result: {tool_result[:100]}...")

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": tool_result,
            })

    print(f"  FAIL: Max turns ({max_turns}) reached")
    return False


if __name__ == "__main__":
    print(f"Model: {MODEL}")
    print(f"Endpoint: {OLLAMA_URL}")
    print()

    results = {}
    results["simple_chat"] = test_simple_chat()
    results["tool_calling"] = test_tool_calling()
    results["agent_loop"] = test_agent_loop()
    results["multi_tool"] = test_multi_tool()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")

    total = len(results)
    passed = sum(1 for v in results.values() if v)
    print(f"\n  {passed}/{total} tests passed")
