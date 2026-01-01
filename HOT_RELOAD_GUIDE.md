# Signal MCP Hot Reload Development Guide

## Overview
You now have a complete hot-reload development environment for the Signal MCP server that allows Claude to test and debug changes automatically without manual intervention.

## How It Works

### 1. Direct Tool Calling (No Claude Code restart needed)
Use the `call-signal` command to invoke MCP tools directly:

```bash
# List all chats
call-signal list_chats

# Get recent messages
call-signal get_message_history '{"limit": 5}'

# Send a message
call-signal send_message_to_user '{"message":"Test","user_id":"msh.60"}'

# Wait for a message (with timeout)
call-signal wait_for_message '{"from_user":"msh.60", "max_wait_seconds": 10}'
```

###  2. Auto-Reload Watcher (Running in background)
The auto-reload watcher monitors `/home/me/ht/signal-mcp/signal_mcp/` for changes and automatically:
- Detects when you edit MCP server code
- Triggers a reload of the MCP server configuration in Claude Code
- Logs all activity to `/tmp/mcp-autoreload.log`

**Check watcher status:**
```bash
tail -f /tmp/mcp-autoreload.log
ps aux | grep auto_reload_watcher
```

### 3. Manual Reload (if needed)
Force a reload without code changes:
```bash
/home/me/ht/signal-mcp/reload_mcp.sh
```

## Development Workflow for Claude

When Claude needs to test or debug Signal MCP:

1. **Make code changes** to `/home/me/ht/signal-mcp/signal_mcp/main.py`
2. **Test immediately** using: `call-signal <tool_name> <params>`
3. **Auto-reload happens** automatically (watcher detects changes)
4. **Iterate quickly** without manual intervention

## Example: Testing a Code Change

```bash
# 1. Claude edits the code
# (edits /home/me/ht/signal-mcp/signal_mcp/main.py)

# 2. Claude tests the change immediately
call-signal list_chats

# 3. Auto-reload happens in background (check logs if needed)
tail -f /tmp/mcp-autoreload.log

# 4. Changes are now live in Claude Code (after auto-reload completes)
```

## Available Tools

All Signal MCP tools are callable via `call-signal`:

- `send_message_to_user` - Send DM to a user
- `send_message_to_group` - Send message to a group
- `send_reaction` - React to a message with emoji
- `receive_message` - Receive messages with timeout
- `send_and_await_reply` - Send message and wait for reply
- `wait_for_message` - Block until message arrives from specific user
- `get_message_history` - Get past messages from daemon log
- `list_chats` - List all DMs and groups

## Troubleshooting

### Watcher not running
```bash
ps aux | grep auto_reload_watcher
# If not running:
cd /home/me/ht/signal-mcp && ./auto_reload_watcher.sh &
```

### Tool call fails
```bash
# Check signal-cli daemon
nc -z localhost 7583 && echo "Daemon OK" || echo "Daemon DOWN"

# Check MCP server can start
/home/me/ht/signal-mcp/.venv/bin/python -m signal_mcp.main --user-id "+447441392349" --transport stdio
# (Ctrl+C to exit)
```

### Check auto-reload logs
```bash
tail -f /tmp/mcp-autoreload.log
```

## Files Created

| File | Purpose |
|------|---------|
| `/home/me/bin/call-signal` | Direct MCP tool caller (works immediately) |
| `/home/me/ht/signal-mcp/reload_mcp.sh` | Manual MCP reload trigger |
| `/home/me/ht/signal-mcp/auto_reload_watcher.sh` | Auto-reload on code changes |
| `/tmp/mcp-autoreload.log` | Auto-reload activity log |

## Status

✅ Signal MCP server configured and working
✅ Direct tool calling available (`call-signal`)
✅ Auto-reload watcher running in background
✅ Claude can test/debug without manual intervention
