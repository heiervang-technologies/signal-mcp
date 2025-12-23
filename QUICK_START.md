# Quick Start Guide - Signal MCP with Daemon Mode

## TL;DR

The signal-mcp server now uses daemon mode for **10x faster** operations and **instant** message receiving.

## Setup (One-time)

### 1. Start the signal-cli daemon

```bash
signal-cli -u YOUR_PHONE_NUMBER daemon --tcp localhost:7583 --receive-mode on-start
```

Keep this running in the background (use tmux/screen or systemd).

### 2. Run the MCP server

```bash
cd ~/.local/share/signal-mcp
source .venv/bin/activate
./signal_mcp/main.py --user-id YOUR_PHONE_NUMBER
```

That's it! The server will automatically:
- Connect to the daemon
- Use fast JSON-RPC calls instead of subprocesses
- Receive messages via push notifications
- Cache username mappings

## What Changed?

### Before (Subprocess Mode)
```
Every operation → New subprocess → signal-cli command → Result
Time: 500-1000ms per message
Receive: Poll every 30 seconds
```

### After (Daemon Mode)
```
Persistent connection → JSON-RPC request → Instant result
Time: 50-100ms per message
Receive: Push notification in <1 second
```

## New Features

### 1. Username Cache
Automatically remembers UUID↔username mappings:
```
User sends message → Cache stores UUID + username → Future lookups are instant
```

Cache location: `~/.local/share/signal-mcp/username_cache.json`

### 2. Push Notifications
No more polling delays:
```
Message arrives → Daemon pushes notification → MCP receives instantly
```

### 3. Fast JSON-RPC
Direct communication with daemon:
```
Send message → JSON-RPC call → Done in ~50ms
```

## Testing

Run the test suite:
```bash
cd ~/.local/share/signal-mcp
source .venv/bin/activate
python test_daemon.py
```

Expected output:
```
Username Cache                 ✓ PASSED
Notification Parsing           ✓ PASSED
Daemon Connection              ✓ PASSED
All tests passed!
```

## Troubleshooting

### "Failed to connect to daemon"
**Problem**: Daemon not running or wrong port

**Fix**:
```bash
# Check if daemon is running
ps aux | grep signal-cli | grep daemon

# If not running, start it
signal-cli -u YOUR_PHONE daemon --tcp localhost:7583 --receive-mode on-start
```

### "No messages received"
**Problem**: Daemon not in receive mode

**Fix**: Make sure you used `--receive-mode on-start` when starting daemon

### Cache not working
**Problem**: Permission issues or disk full

**Fix**:
```bash
# Check cache file
ls -lh ~/.local/share/signal-mcp/username_cache.json

# Check disk space
df -h ~/.local/share/signal-mcp/
```

## Performance Comparison

| Operation | Old (subprocess) | New (daemon) | Speedup |
|-----------|-----------------|--------------|---------|
| Send 1 message | ~500ms | ~50ms | 10x |
| Send 10 messages | ~5s | ~500ms | 10x |
| Receive (wait time) | 0-30s | <1s | Up to 30x |
| Username lookup | N/A | <1ms | ∞ (new!) |

## API (Unchanged)

All existing tools work exactly the same:

```python
# Send to user
send_message_to_user(message="Hello!", user_id="+1234567890")

# Send to group
send_message_to_group(message="Hello group!", group_id="group-name")

# Receive messages
receive_message(timeout=30)

# Wait for specific user
wait_for_message(from_user="+1234567890", max_wait_seconds=3600)
```

## Systemd Service (Optional)

To run daemon as a system service:

1. Create `/etc/systemd/system/signal-cli-daemon.service`:
```ini
[Unit]
Description=Signal CLI Daemon
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
ExecStart=/usr/local/bin/signal-cli -u YOUR_PHONE daemon --tcp localhost:7583 --receive-mode on-start
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

2. Enable and start:
```bash
sudo systemctl enable signal-cli-daemon
sudo systemctl start signal-cli-daemon
```

## More Information

- Full documentation: `IMPROVEMENTS.md`
- Change summary: `CHANGES_SUMMARY.md`
- Code location: `signal_mcp/main.py`
- Tests: `test_daemon.py` and `test_integration.py`

## Questions?

Check the logs for detailed debugging:
```bash
# Run MCP server with debug logging
./signal_mcp/main.py --user-id YOUR_PHONE 2>&1 | tee signal-mcp.log
```
