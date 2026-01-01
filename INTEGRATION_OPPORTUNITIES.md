# Integration Opportunities

Based on exploration of the codebase, here are powerful integration opportunities between existing systems.

## 1. Signal + Whisper Voice Transcription

### Current State
- **signal-mcp**: Fully operational, can send/receive Signal messages ✅
- **whisper-cpp-api**: OpenAI-compatible ASR at `192.168.8.123:8080` (needs connectivity)
- **signal-llm-bot**: Existing bot that connects Signal to LLM

### Opportunity
Combine Signal MCP + Whisper MCP for voice message transcription:

```python
# Workflow in Claude Code
voice_msg = await wait_for_message(from_user="msh.60")
if voice_msg.has_attachment and voice_msg.attachment_type == "audio":
    # Download voice message
    audio_path = download_attachment(voice_msg.attachment_id)

    # Transcribe with Whisper
    transcription = await transcribe_audio_file(audio_path)

    # Reply with transcription
    await send_message_to_user(
        user_id="msh.60",
        message=f"You said: {transcription.text}"
    )
```

**Value:** Enables voice interaction with Claude via Signal!

## 2. Signal + VibeVoice TTS Response

### Current State
- **signal-mcp**: Can send messages ✅
- **vibevoice-api**: Text-to-speech with OpenAI-compatible API
- **VibeVoice**: 7B parameter multi-speaker TTS model

### Opportunity
Claude responds to Signal messages with voice:

```python
# Receive text message
msg = await wait_for_message(from_user="msh.60")

# Generate response from LLM
response = generate_llm_response(msg.message)

# Convert to speech with VibeVoice
audio = await text_to_speech(response, voice="default")

# Send as voice message
await send_voice_message(user_id="msh.60", audio_file=audio)
```

**Value:** Natural voice conversations with AI over Signal!

## 3. Full Voice Pipeline: Whisper → LLM → VibeVoice → Signal

### The Complete Loop

```
Human speaks on Signal
    ↓ (voice message)
Signal MCP receives
    ↓
Whisper MCP transcribes
    ↓
LLM generates response (Claude/local)
    ↓
VibeVoice MCP synthesizes
    ↓
Signal MCP sends voice reply
    ↓
Human hears AI response
```

**This is the vibevoice-api voice_chat.py but over Signal!**

## 4. Core + Signal Notifications

### Current State
- **core**: Monitors GitHub notifications, spawns snail agents
- **signal-mcp**: Can send Signal messages

### Opportunity
Alert user via Signal when important GitHub events happen:

```python
# In core's notification listener
if notification.is_mention or notification.priority == "high":
    # Notify via Signal
    await send_message_to_user(
        user_id=ADMIN_SIGNAL_ID,
        message=f"🔔 {notification.title}\n{notification.url}"
    )
```

**Value:** Real-time mobile notifications for GitHub activity!

## 5. Signal as Agent Command Interface

### Opportunity
Control snail agents via Signal messages:

```python
# User sends: "@agent run tests on PR #123"
msg = await wait_for_message(from_user=ADMIN_SIGNAL_ID)

if msg.message.startswith("@agent"):
    command = parse_agent_command(msg.message)

    # Spawn snail agent
    agent_id = spawn_snail_agent(
        task=command.task,
        repo=command.repo,
        pr=command.pr
    )

    await send_message_to_user(
        user_id=ADMIN_SIGNAL_ID,
        message=f"✅ Agent {agent_id} started"
    )
```

**Value:** Mobile control of autonomous agents!

## 6. Snail Skill: Signal Notifications

### Opportunity
Create a Claude Code skill for Signal notifications:

```yaml
# ~/.config/snail/skills/signal-notify/SKILL.md
name: signal-notify
description: Send Signal notifications from Claude Code
usage: |
  Use this when you need to notify the user on their phone:
  - Task completion
  - Errors requiring attention
  - Status updates

tools:
  - send_message_to_user (from signal MCP)
```

Usage in Claude Code:
```bash
/signal-notify "Deploy completed successfully!"
```

## Implementation Priority

### High Priority (Easy + High Value)
1. ✅ **Signal MCP** - DONE, fully operational
2. 🔄 **Whisper MCP** - Template ready, needs connectivity
3. 📱 **Core Signal notifications** - Simple integration

### Medium Priority (More Complex)
4. 🎤 **Voice transcription** - Requires both Signal + Whisper MCPs
5. 🔊 **TTS responses** - Requires VibeVoice MCP
6. 🎛️ **Agent control via Signal** - Requires core integration

### Future Vision
7. 🗣️ **Full voice pipeline** - All systems integrated
8. 🌐 **Multi-user Signal bot** - Scale beyond single user

## Quick Wins Available Now

### 1. Test Whisper Connectivity
```bash
/home/me/bin/test-whisper 192.168.8.123 8080
```

### 2. Create Signal Notification Helper
```bash
# ~/.config/snail/bin/signal-notify
#!/bin/bash
/home/me/bin/call-signal send_message_to_user "{\"message\":\"$1\",\"user_id\":\"msh.60\"}"
```

Usage:
```bash
signal-notify "Task completed!"
```

### 3. Document Whisper API for Future MCP
Already done: `/home/me/ht/signal-mcp/FUTURE_WHISPER_INTEGRATION.md`

## Network Considerations

Current blocker: Container network isolation prevents reaching `192.168.8.123`

**Solutions:**
1. **Host network** (quickest): Add `network_mode: "host"` to docker-compose.yml
2. **Port forward**: Forward 8080:8080 in docker-compose.yml if Whisper is on host
3. **Reverse proxy**: nginx on host proxying to Whisper

See: `/home/me/ht/signal-mcp/CONTAINER_NETWORKING.md`

## Resources Created

| File | Purpose |
|------|---------|
| `/home/me/bin/test-whisper` | Test Whisper connectivity |
| `/home/me/ht/signal-mcp/FUTURE_WHISPER_INTEGRATION.md` | Whisper MCP design doc |
| `/home/me/ht/signal-mcp/INTEGRATION_OPPORTUNITIES.md` | This document |
| `/home/me/ht/signal-mcp/HOT_RELOAD_GUIDE.md` | MCP hot-reload system |

When the user returns, they can:
1. Run `test-whisper` to verify Whisper access
2. Choose which integration to pursue
3. Use the hot-reload system to develop rapidly
