# Dynamic Tool System - TRUE Hot-Reload

## Overview

The Signal MCP now supports **dynamic tool registration at runtime** using a generic gateway pattern. This allows adding new functionality WITHOUT restarting Claude Code!

## How It Works

Instead of trying to add new MCP tools (which Claude Code caches at session start), we use a **single flexible tool** that dispatches to handlers registered at runtime.

### Architecture

```
Claude Code
    ↓
execute_dynamic_tool(tool_name="hello", params={"name": "Alice"})
    ↓
Signal MCP Server (running process)
    ↓
_dynamic_tools registry → handler function → result
```

## Available Tools

### 1. `execute_dynamic_tool`

Execute a dynamically registered tool by name.

**Parameters:**
- `tool_name` (string): Name of the dynamic tool (e.g., "hello", "calculator")
- `params` (dict): JSON parameters for the tool (optional)

**Example:**
```python
execute_dynamic_tool(
    tool_name="hello",
    params={"name": "World"}
)
```

### 2. `register_dynamic_tool_handler`

Register a new tool handler at runtime using Python code.

**Parameters:**
- `tool_name` (string): Name for your new tool
- `handler_code` (string): Python code defining the handler function

**Example:**
```python
register_dynamic_tool_handler(
    tool_name="hello",
    handler_code='''
async def handler(params):
    name = params.get("name", "World")
    return {"message": f"Hello, {name}!"}
'''
)
```

### 3. `list_dynamic_tools`

List all currently registered dynamic tools.

**Returns:** List of tool names and count

## Usage Workflow

### Step 1: Register a Handler

```python
register_dynamic_tool_handler(
    tool_name="calculator",
    handler_code='''
async def handler(params):
    operation = params.get("op", "add")
    a = params.get("a", 0)
    b = params.get("b", 0)

    if operation == "add":
        result = a + b
    elif operation == "multiply":
        result = a * b
    else:
        return {"error": f"Unknown operation: {operation}"}

    return {
        "operation": operation,
        "inputs": [a, b],
        "result": result
    }
'''
)
```

**Response:**
```json
{
  "status": "registered",
  "tool_name": "calculator",
  "message": "Dynamic tool 'calculator' registered successfully",
  "usage": "execute_dynamic_tool(tool_name='calculator', params={...})"
}
```

### Step 2: Use the Tool

```python
execute_dynamic_tool(
    tool_name="calculator",
    params={"op": "add", "a": 42, "b": 8}
)
```

**Response:**
```json
{
  "status": "success",
  "tool_name": "calculator",
  "result": {
    "operation": "add",
    "inputs": [42, 8],
    "result": 50
  },
  "timestamp": 1767307500000
}
```

### Step 3: List Available Tools

```python
list_dynamic_tools()
```

**Response:**
```json
{
  "status": "ok",
  "tools": ["calculator", "hello"],
  "count": 2,
  "timestamp": 1767307500000
}
```

## Advanced Usage

### Access Signal Functionality

Handlers have access to Signal MCP internals:

```python
register_dynamic_tool_handler(
    tool_name="send_greeting",
    handler_code='''
async def handler(params):
    user_id = params.get("user_id")
    name = params.get("name", "there")

    # Access to _get_daemon, config, logger available in namespace
    daemon = _get_daemon()
    await daemon.connect()

    # Send a Signal message
    import subprocess
    result = subprocess.run([
        "signal-cli", "-a", config.user_id,
        "send", "-m", f"Hello {name}!",
        user_id
    ], capture_output=True, text=True)

    return {
        "sent": True,
        "recipient": user_id,
        "message": f"Hello {name}!"
    }
'''
)
```

### Update Existing Tools

Just re-register with the same name:

```python
# First version
register_dynamic_tool_handler(
    tool_name="greeter",
    handler_code='async def handler(params): return {"msg": "Hi!"}'
)

# Updated version (no restart needed!)
register_dynamic_tool_handler(
    tool_name="greeter",
    handler_code='''
async def handler(params):
    name = params.get("name", "friend")
    time_of_day = params.get("time", "day")
    return {"msg": f"Good {time_of_day}, {name}!"}
'''
)
```

## Benefits

### ✅ What This Solves

1. **No Claude Code Restart**: Add tools without restarting
2. **Flexible Signatures**: Each tool can have different parameters
3. **Runtime Updates**: Change tool behavior on the fly
4. **Rapid Iteration**: Test new functionality immediately

### ⚠️  Limitations

1. **Tool Discovery**: Claude Code won't auto-suggest dynamic tools (only `execute_dynamic_tool` appears)
2. **Documentation**: You need to track what parameters each tool expects
3. **Validation**: Less type safety than native MCP tools
4. **Security**: Be careful with `exec()` - only run trusted code

## Example: Voice Transcription Pipeline

```python
# Register Whisper integration (when server is accessible)
register_dynamic_tool_handler(
    tool_name="transcribe_signal_voice",
    handler_code='''
import httpx

async def handler(params):
    attachment_path = params.get("audio_file")
    whisper_url = "http://192.168.8.123:8080/v1/audio/transcriptions"

    async with httpx.AsyncClient() as client:
        with open(attachment_path, "rb") as f:
            response = await client.post(
                whisper_url,
                files={"file": f},
                data={"model": "whisper-1"}
            )

    return response.json()
'''
)

# Use it
execute_dynamic_tool(
    tool_name="transcribe_signal_voice",
    params={"audio_file": "/tmp/voice_message.m4a"}
)
```

## Implementation Details

- **Registry**: Global `_dynamic_tools` dict persists in the running process
- **Namespace**: Handlers have access to `asyncio`, `logger`, `config`, `_get_daemon`
- **Safety**: Each handler runs in isolated namespace via `exec()`
- **Performance**: No overhead beyond normal Python function call

## Testing

After Claude Code restart, test the system:

```python
# 1. Check what's available
list_dynamic_tools()  # Should return empty list initially

# 2. Register a test tool
register_dynamic_tool_handler(
    tool_name="test",
    handler_code='async def handler(params): return {"works": True}'
)

# 3. Execute it
execute_dynamic_tool(tool_name="test", params={})

# 4. Verify
list_dynamic_tools()  # Should show ["test"]
```

## Future Enhancements

Potential improvements:
- Persistent storage (save/load handlers)
- Parameter validation schemas
- Handler versioning
- Access control/sandboxing
- Integration with hot-reload watcher

---

**This achieves the goal: Add functionality to Signal MCP without restarting Claude Code!**
