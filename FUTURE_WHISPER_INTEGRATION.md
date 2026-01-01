# Future: Whisper MCP Integration

## Context

User mentioned a Whisper server at 192.168.8.123 but it was unreachable from the snail container (network isolation). This document outlines how to integrate Whisper (speech-to-text) as an MCP server when the service becomes accessible.

## Architecture Parallel with Signal MCP

The Whisper MCP server should follow the same pattern as signal-mcp:

```
Claude Code
  ↓ MCP stdio transport
Whisper MCP Server (Python)
  ↓ HTTP API
Whisper Service (192.168.8.123:PORT)
  ↓ returns transcription
Audio files or streams
```

## Proposed Structure

```
whisper-mcp/
├── whisper_mcp/
│   └── main.py          # FastMCP server
├── pyproject.toml       # uv dependencies
├── README.md
├── .venv/               # created with uv venv
└── tests/
```

## Tools to Implement

### 1. `transcribe_audio_file`
```python
@mcp.tool()
async def transcribe_audio_file(
    file_path: str,
    language: Optional[str] = None,
    model: str = "base"
) -> TranscriptionResponse:
    """Transcribe an audio file to text using Whisper.

    Args:
        file_path: Path to audio file (mp3, wav, m4a, etc.)
        language: Optional language code (e.g., "en", "no")
        model: Whisper model size (tiny, base, small, medium, large)

    Returns:
        Transcription with text, language, duration, confidence
    """
```

### 2. `transcribe_audio_url`
```python
@mcp.tool()
async def transcribe_audio_url(
    url: str,
    language: Optional[str] = None
) -> TranscriptionResponse:
    """Download and transcribe audio from URL."""
```

### 3. `list_supported_formats`
```python
@mcp.tool()
async def list_supported_formats() -> Dict[str, List[str]]:
    """Get list of supported audio formats and languages."""
```

### 4. `get_server_status`
```python
@mcp.tool()
async def get_server_status() -> Dict[str, Any]:
    """Check Whisper server availability and loaded models."""
```

## Integration with Signal MCP

Powerful combination for voice message transcription:

```python
# Hypothetical workflow:
# 1. Receive Signal voice message
voice_msg = await wait_for_message(from_user="msh.60")

# 2. Download attachment
audio_path = download_signal_attachment(voice_msg.attachment_id)

# 3. Transcribe
transcription = await transcribe_audio_file(audio_path)

# 4. Reply with transcription
await send_message_to_user(
    user_id="msh.60",
    message=f"You said: {transcription.text}"
)
```

## MCP Configuration (.claude.json)

```json
{
  "mcpServers": {
    "signal": {
      "command": "/home/me/ht/signal-mcp/.venv/bin/python",
      "args": ["-m", "signal_mcp.main", "--user-id", "+447441392349", "--transport", "stdio"],
      "cwd": "/home/me/ht/signal-mcp"
    },
    "whisper": {
      "command": "/home/me/ht/whisper-mcp/.venv/bin/python",
      "args": ["-m", "whisper_mcp.main", "--server-url", "http://192.168.8.123:PORT", "--transport", "stdio"],
      "cwd": "/home/me/ht/whisper-mcp"
    }
  }
}
```

## Network Considerations

### Option 1: Host Network Mode (Simplest)

Modify snail's docker-compose.yml:
```yaml
dev-gpu:
  network_mode: "host"
  # Now container can reach 192.168.8.123 directly
```

**Pros:** Direct access to host LAN
**Cons:** Removes network isolation

### Option 2: Port Forward (Recommended)

If Whisper is on the Docker host:
```yaml
dev-gpu:
  ports:
    - "9000:9000"  # Forward Whisper port
```

Then access via `localhost:9000` from container.

### Option 3: Reverse Proxy

Run nginx/caddy on host to proxy Whisper service:
```
Container → host.docker.internal:9000 → nginx → 192.168.8.123:PORT
```

## Implementation Checklist

- [ ] Determine correct Whisper server IP and port
- [ ] Test connectivity from container
- [ ] Create whisper-mcp repository structure
- [ ] Implement FastMCP server with tools
- [ ] Add to .claude.json
- [ ] Test transcription workflow
- [ ] Document integration with Signal MCP
- [ ] Add to auto-reload watcher (optional)

## API Client Reference

If using OpenAI Whisper API compatible server:

```python
import httpx

async def transcribe(audio_path: str, server_url: str) -> str:
    async with httpx.AsyncClient() as client:
        with open(audio_path, "rb") as f:
            files = {"file": f}
            response = await client.post(
                f"{server_url}/v1/audio/transcriptions",
                files=files,
                data={"model": "whisper-1"}
            )
            return response.json()["text"]
```

Or if using faster-whisper server:
```python
async def transcribe(audio_path: str, server_url: str) -> str:
    async with httpx.AsyncClient() as client:
        with open(audio_path, "rb") as f:
            files = {"audio_file": f}
            response = await client.post(
                f"{server_url}/asr",
                files=files,
                params={"task": "transcribe", "language": "en"}
            )
            return response.json()["text"]
```

## Testing Plan

1. **Connectivity Test**
   ```bash
   # From inside container
   curl http://192.168.8.123:PORT/health
   ```

2. **Basic Transcription Test**
   ```bash
   call-whisper transcribe_audio_file '{"file_path":"/tmp/test.mp3"}'
   ```

3. **Integration Test with Signal**
   - Send voice message on Signal
   - Receive in Claude Code via signal-mcp
   - Transcribe with whisper-mcp
   - Reply with transcription

## Future Enhancements

- **Streaming transcription** for real-time audio
- **Speaker diarization** (who said what)
- **Translation** (transcribe + translate to English)
- **Audio summaries** (transcribe + LLM summarization)
- **Signal voice message auto-transcription** (automatic when voice message received)

## Similar Projects

- [whisper-api](https://github.com/ggerganov/whisper.cpp/tree/master/examples/server) - whisper.cpp HTTP server
- [faster-whisper-server](https://github.com/fedirz/faster-whisper-server) - Production-ready API
- [whisper-asr-webservice](https://github.com/ahmetoner/whisper-asr-webservice) - Docker-ready service

When the Whisper server becomes accessible, this document provides a complete roadmap for integration.
