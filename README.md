# Signal MCP

An MCP server that enables AI agents to send and receive Signal messages via [signal-cli](https://github.com/AsamK/signal-cli).

## Features

- Send messages to Signal users (by phone number, username, or UUID)
- Send messages to Signal groups
- Receive and parse incoming messages
- Block and wait for messages from specific users (ideal for agent loops)
- Daemon mode with JSON-RPC for 10x faster operations
- Push notifications for instant message delivery
- Automatic username caching (UUID↔username mapping)

## Quick Setup

### 1. Install signal-cli (native binary - no Java required)

```bash
# Download and install the latest native build
VERSION=$(curl -Ls -o /dev/null -w %{url_effective} https://github.com/AsamK/signal-cli/releases/latest | sed 's/.*\/v//')
curl -L -O "https://github.com/AsamK/signal-cli/releases/download/v${VERSION}/signal-cli-${VERSION}-Linux-native.tar.gz"
sudo tar xzf "signal-cli-${VERSION}-Linux-native.tar.gz" -C /usr/local/bin/
sudo chmod +x /usr/local/bin/signal-cli

# Verify installation
signal-cli --version
```

### 2. Register your Signal account

**Note**: Registration requires solving a captcha.

```bash
# Step 1: Attempt registration (will fail with captcha requirement)
signal-cli -u +YOUR_PHONE_NUMBER register

# Step 2: Go to https://signalcaptchas.org/registration/generate.html
# Solve the captcha, right-click "Open Signal", copy the link

# Step 3: Register with captcha token
signal-cli -u +YOUR_PHONE_NUMBER register --captcha 'signalcaptcha://...'

# Step 4: Verify with SMS code
signal-cli -u +YOUR_PHONE_NUMBER verify CODE_FROM_SMS
```

### 3. Install signal-mcp

```bash
cd /path/to/signal-mcp
uv venv
uv pip install -e .
```

### 4. Start the signal-cli daemon

The daemon must be running for the MCP to work:

```bash
signal-cli -u +YOUR_PHONE_NUMBER daemon --tcp localhost:7583 --receive-mode on-start
```

**Tip**: Run this in a tmux session or as a systemd service (see below).

### 5. Configure Claude Code

Add to `~/.mcp.json`:

```json
{
  "mcpServers": {
    "signal": {
      "command": "/path/to/signal-mcp/.venv/bin/python",
      "args": ["-m", "signal_mcp.main", "--user-id", "+YOUR_PHONE_NUMBER", "--transport", "stdio"],
      "cwd": "/path/to/signal-mcp"
    }
  }
}
```

Then restart Claude Code to pick up the new MCP server.

## API

### Tools Available

- **`send_message_to_user`**: Send a direct message to a Signal user
  - `message` (str): The message to send
  - `user_id` (str): Phone number (`+1234567890`), username (`u:username`), or UUID

- **`send_message_to_group`**: Send a message to a Signal group
  - `message` (str): The message to send
  - `group_id` (str): The group name or ID

- **`receive_message`**: Wait for and receive messages with timeout
  - `timeout` (float): Seconds to wait
  - Returns: MessageResponse with message, sender_id, group_name, timestamp

- **`wait_for_message`**: Block and wait for a message (ideal for agent loops)
  - `from_user` (Optional[str]): Filter by sender (phone/username/UUID)
  - `max_wait_seconds` (int): Max wait time (default: 3600, max: 7200)
  - Returns: MessageResponse with message, sender_id, group_name, timestamp

## Running as a Systemd Service

Create `/etc/systemd/system/signal-cli-daemon.service`:

```ini
[Unit]
Description=Signal CLI Daemon
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
ExecStart=/usr/local/bin/signal-cli -u +YOUR_PHONE_NUMBER daemon --tcp localhost:7583 --receive-mode on-start
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Then enable and start:

```bash
sudo systemctl enable signal-cli-daemon
sudo systemctl start signal-cli-daemon
```

## Troubleshooting

### "Failed to connect to daemon"
The signal-cli daemon is not running. Start it with:
```bash
signal-cli -u +YOUR_PHONE_NUMBER daemon --tcp localhost:7583 --receive-mode on-start
```

### "Captcha required for verification"
Go to https://signalcaptchas.org/registration/generate.html, solve the captcha, and use the token with `--captcha`.

### Send fails but no error details
Check the daemon output for detailed error messages. Common issues:
- Profile name not set (warning, usually still works)
- Invalid recipient format

## Development

```bash
# Lint
ruff check .

# Type check
mypy .

# Format
ruff format .
```

## License

MIT
