# Signal MCP

An [MCP](https://github.com/mcp-signal/mcp) integration for [signal-cli](https://github.com/AsamK/signal-cli) that allows AI agents to send and receive Signal messages.

## Features

- Send messages to Signal users
- Send messages to Signal groups
- Receive and parse incoming messages
- Block and wait for messages from specific users (ideal for agent loops)
- Async support with timeout handling
- Detailed logging
- **NEW**: Daemon mode with JSON-RPC for 10x faster operations
- **NEW**: Push notifications for instant message delivery
- **NEW**: Automatic username caching (UUID↔username mapping)

## Prerequisites

This project requires [signal-cli](https://github.com/AsamK/signal-cli) to be installed and configured on your system.

### Installing signal-cli

1. **Install signal-cli**: Follow the [official installation instructions](https://github.com/AsamK/signal-cli/blob/master/README.md#installation)

2. **Register your Signal account**:
   ```bash
   signal-cli -u YOUR_PHONE_NUMBER register
   ```

3. **Verify your account** with the code received via SMS:
   ```bash
   signal-cli -u YOUR_PHONE_NUMBER verify CODE_RECEIVED
   ```

4. **Start signal-cli in daemon mode** (recommended for best performance):
   ```bash
   signal-cli -u YOUR_PHONE_NUMBER daemon --tcp localhost:7583 --receive-mode on-start
   ```

For more detailed setup instructions, see the [signal-cli documentation](https://github.com/AsamK/signal-cli/wiki).

## Installation

```bash
pip install -e .
# or use uv for faster installation
uv pip install -e .
```

## Usage

Run the MCP server:

```bash
./main.py --user-id YOUR_PHONE_NUMBER [--transport {sse|stdio}]
```

## API

### Tools Available

- `send_message_to_user`: Send a direct message to a Signal user
  - Parameters: `message` (str), `user_id` (str)

- `send_message_to_group`: Send a message to a Signal group
  - Parameters: `message` (str), `group_id` (str)

- `receive_message`: Wait for and receive messages with timeout support
  - Parameters: `timeout` (float)
  - Returns: MessageResponse with message, sender_id, group_name, timestamp, or error

- `wait_for_message`: Block and wait for a new message from a specific user or any user
  - Parameters:
    - `from_user` (Optional[str]): Phone number to filter messages (e.g., "+1234567890"). If None, accepts any user.
    - `max_wait_seconds` (int): Maximum time to wait (default: 3600, max: 7200)
  - Returns: MessageResponse with message, sender_id, group_name, timestamp, or error
  - Use case: Ideal for agent loops where Claude needs to wait for user input via Signal
  - Note: Continuously polls signal-cli until a real message (not receipts) arrives

## Performance Improvements

This server now uses signal-cli daemon mode for significantly better performance:

- **10x faster** message sending (50-100ms vs 500-1000ms)
- **Near-instant** message receiving via push notifications (vs 0-30s polling delay)
- **Persistent connection** eliminates per-request subprocess overhead

See [IMPROVEMENTS.md](IMPROVEMENTS.md) for detailed documentation.

## Development

This project uses:
- [MCP](https://github.com/mcp-signal/mcp) for agent-API integration
- Modern Python async patterns
- Type annotations throughout
- signal-cli daemon with JSON-RPC for efficient communication
