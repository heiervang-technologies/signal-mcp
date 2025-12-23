#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "mcp",
# ]
# ///
from mcp.server.fastmcp import FastMCP
from typing import Optional, Tuple, Dict, Union, Any
import asyncio
import subprocess
import shlex
import argparse
from dataclasses import dataclass
import logging
import json
import socket
from pathlib import Path
import time
from collections import deque
from typing import Deque

# Set up logging with more detailed format
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize MCP server
mcp = FastMCP(name="signal-cli")
logger.info("Initialized FastMCP server for signal-cli")


@dataclass
class SignalConfig:
    """Configuration for Signal CLI."""

    user_id: str = ""  # The user's Signal phone number
    transport: str = "sse"
    daemon_host: str = "localhost"
    daemon_port: int = 7583


@dataclass
class MessageResponse:
    """Structured result for received messages."""

    message: Optional[str] = None
    sender_id: Optional[str] = None
    group_name: Optional[str] = None
    timestamp: Optional[int] = None
    error: Optional[str] = None


class SignalError(Exception):
    """Base exception for Signal-related errors."""

    pass


class SignalCLIError(SignalError):
    """Exception raised when signal-cli command fails."""

    pass


class UsernameCache:
    """Cache for UUID<->username mappings.

    Signal-cli doesn't provide a way to look up username from UUID,
    so we cache these mappings when discovered.
    """

    def __init__(self, cache_file: Optional[Path] = None):
        """Initialize the username cache.

        Args:
            cache_file: Path to the cache file. If None, uses ~/.local/share/signal-mcp/username_cache.json
        """
        if cache_file is None:
            cache_dir = Path.home() / ".local" / "share" / "signal-mcp"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = cache_dir / "username_cache.json"

        self.cache_file = cache_file
        self.cache: Dict[str, str] = {}
        self._load()
        logger.info(f"Initialized username cache at {self.cache_file}")

    def _load(self) -> None:
        """Load cache from file."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r") as f:
                    self.cache = json.load(f)
                logger.debug(f"Loaded {len(self.cache)} entries from cache")
            except Exception as e:
                logger.warning(f"Failed to load username cache: {e}")
                self.cache = {}

    def _save(self) -> None:
        """Save cache to file."""
        try:
            with open(self.cache_file, "w") as f:
                json.dump(self.cache, f, indent=2)
            logger.debug(f"Saved {len(self.cache)} entries to cache")
        except Exception as e:
            logger.warning(f"Failed to save username cache: {e}")

    def get_username(self, uuid: str) -> Optional[str]:
        """Get username for a UUID."""
        return self.cache.get(uuid)

    def get_uuid(self, username: str) -> Optional[str]:
        """Get UUID for a username."""
        # Reverse lookup
        for uuid, cached_username in self.cache.items():
            if cached_username == username:
                return uuid
        return None

    def add_mapping(self, uuid: str, username: str) -> None:
        """Add or update a UUID<->username mapping."""
        if uuid and username:
            self.cache[uuid] = username
            self._save()
            logger.debug(f"Cached mapping: {uuid} -> {username}")


class SignalDaemonConnection:
    """Connection to signal-cli daemon via JSON-RPC."""

    def __init__(self, host: str, port: int, user_id: str):
        """Initialize daemon connection.

        Args:
            host: Daemon host (default: localhost)
            port: Daemon port (default: 7583)
            user_id: Signal phone number for the user
        """
        self.host = host
        self.port = port
        self.user_id = user_id
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self._next_id = 1
        self._lock = asyncio.Lock()
        logger.info(f"Initialized daemon connection to {host}:{port}")

    async def connect(self) -> None:
        """Connect to the signal-cli daemon."""
        if self.reader and self.writer:
            logger.debug("Already connected to daemon")
            return

        try:
            logger.info(f"Connecting to signal-cli daemon at {self.host}:{self.port}")
            self.reader, self.writer = await asyncio.open_connection(
                self.host, self.port
            )
            logger.info("Successfully connected to daemon")
        except Exception as e:
            logger.error(f"Failed to connect to daemon: {e}")
            raise SignalCLIError(f"Failed to connect to daemon: {e}")

    async def disconnect(self) -> None:
        """Disconnect from the daemon."""
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
                logger.info("Disconnected from daemon")
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
            finally:
                self.reader = None
                self.writer = None

    async def _send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send a JSON-RPC request to the daemon.

        Args:
            method: The JSON-RPC method name
            params: The method parameters

        Returns:
            The JSON-RPC response
        """
        async with self._lock:
            await self.connect()

            request_id = self._next_id
            self._next_id += 1

            request = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }

            request_json = json.dumps(request) + "\n"
            logger.debug(f"Sending JSON-RPC request: {request}")

            try:
                self.writer.write(request_json.encode())
                await self.writer.drain()

                # Read response
                response_line = await self.reader.readline()
                if not response_line:
                    raise SignalCLIError("Daemon closed connection")

                response = json.loads(response_line.decode())
                logger.debug(f"Received JSON-RPC response: {response}")

                if "error" in response:
                    error = response["error"]
                    error_msg = error.get("message", "Unknown error")
                    logger.error(f"JSON-RPC error: {error_msg}")
                    raise SignalCLIError(f"Daemon error: {error_msg}")

                return response.get("result", {})

            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON response: {e}")
                raise SignalCLIError(f"Invalid JSON response: {e}")
            except Exception as e:
                logger.error(f"Error during JSON-RPC call: {e}")
                raise SignalCLIError(f"JSON-RPC call failed: {e}")

    async def send_message(
        self, message: str, recipient: Optional[str] = None, group_id: Optional[str] = None
    ) -> bool:
        """Send a message via the daemon.

        Args:
            message: The message to send
            recipient: Username or phone number (e.g., "msh.60" or "+1234567890")
            group_id: Group ID (base64 encoded)

        Returns:
            True if successful
        """
        params = {"message": message, "account": self.user_id}

        if recipient:
            # Check if it's a username (doesn't start with +)
            if not recipient.startswith("+"):
                params["username"] = [recipient]
            else:
                params["recipient"] = [recipient]
        elif group_id:
            params["groupId"] = group_id
        else:
            raise ValueError("Either recipient or group_id must be provided")

        try:
            await self._send_request("send", params)
            logger.info(f"Successfully sent message via daemon")
            return True
        except SignalCLIError as e:
            logger.error(f"Failed to send message: {e}")
            return False

    async def receive_messages(self, timeout: Optional[float] = None) -> list:
        """Receive messages from the daemon.

        This method reads incoming notifications from the daemon.

        Args:
            timeout: Optional timeout in seconds

        Returns:
            List of received messages
        """
        await self.connect()

        messages = []
        start_time = time.time()

        try:
            while True:
                # Check timeout
                if timeout is not None:
                    elapsed = time.time() - start_time
                    if elapsed >= timeout:
                        logger.debug("Receive timeout reached")
                        break

                    remaining = timeout - elapsed
                    try:
                        # Read with timeout
                        line = await asyncio.wait_for(
                            self.reader.readline(), timeout=remaining
                        )
                    except asyncio.TimeoutError:
                        logger.debug("Read timeout, no messages")
                        break
                else:
                    # No timeout, wait indefinitely
                    line = await self.reader.readline()

                if not line:
                    logger.warning("Daemon closed connection")
                    break

                try:
                    notification = json.loads(line.decode())
                    logger.debug(f"Received notification: {notification}")

                    # Check if it's a receive notification
                    if notification.get("method") == "receive":
                        params = notification.get("params", {})
                        messages.append(params)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to decode notification: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error receiving messages: {e}")

        return messages


class SignalMessageListener:
    """Persistent listener for incoming Signal messages.

    Maintains a dedicated connection to the daemon that continuously
    listens for push notifications and queues them for processing.
    """

    def __init__(self, host: str, port: int, user_id: str):
        self.host = host
        self.port = port
        self.user_id = user_id
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.message_queue: Deque[Dict[str, Any]] = deque(maxlen=1000)
        self._listener_task: Optional[asyncio.Task] = None
        self._running = False
        self._new_message_event = asyncio.Event()
        logger.info(f"Initialized message listener for {host}:{port}")

    async def start(self) -> None:
        """Start the persistent listener."""
        if self._running:
            logger.debug("Listener already running")
            return

        try:
            logger.info(f"Starting persistent listener on {self.host}:{self.port}")
            self.reader, self.writer = await asyncio.open_connection(
                self.host, self.port
            )
            self._running = True
            self._listener_task = asyncio.create_task(self._listen_loop())
            logger.info("Persistent listener started successfully")
        except Exception as e:
            logger.error(f"Failed to start listener: {e}")
            raise SignalCLIError(f"Failed to start listener: {e}")

    async def stop(self) -> None:
        """Stop the persistent listener."""
        self._running = False
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        logger.info("Persistent listener stopped")

    async def _listen_loop(self) -> None:
        """Background loop that continuously reads notifications."""
        logger.info("Listener loop started")
        while self._running:
            try:
                if not self.reader:
                    logger.warning("Reader not available, reconnecting...")
                    await asyncio.sleep(1)
                    await self.start()
                    continue

                line = await self.reader.readline()
                if not line:
                    logger.warning("Daemon closed connection, reconnecting...")
                    self._running = False
                    await asyncio.sleep(1)
                    await self.start()
                    continue

                try:
                    notification = json.loads(line.decode())
                    logger.debug(f"Listener received: {notification}")

                    # Check if it's a receive notification with a message
                    if notification.get("method") == "receive":
                        params = notification.get("params", {})
                        envelope = params.get("envelope", {})
                        data_message = envelope.get("dataMessage", {})

                        # Only queue if there's an actual message body
                        if data_message.get("message"):
                            self.message_queue.append(params)
                            self._new_message_event.set()
                            logger.info(f"Queued message, queue size: {len(self.message_queue)}")

                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to decode notification: {e}")

            except asyncio.CancelledError:
                logger.info("Listener loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in listener loop: {e}")
                await asyncio.sleep(1)

    async def wait_for_message(self, timeout: float, from_user: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Wait for a message, optionally from a specific user.

        Args:
            timeout: Maximum time to wait in seconds
            from_user: Optional username or phone number to filter by

        Returns:
            Message dict or None if timeout
        """
        # Ensure listener is running
        if not self._running:
            await self.start()

        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                logger.debug("Wait timeout reached")
                return None

            # Check queue for matching messages
            for i, msg in enumerate(self.message_queue):
                envelope = msg.get("envelope", {})
                source = envelope.get("source") or envelope.get("sourceNumber")
                source_uuid = envelope.get("sourceUuid")

                # Check if message matches filter
                if from_user is None:
                    # No filter, return first message
                    self.message_queue.remove(msg)
                    return msg
                else:
                    # Check various sender identifiers
                    if source == from_user or source_uuid == from_user:
                        self.message_queue.remove(msg)
                        return msg
                    # Also check username cache
                    cached_username = username_cache.get_username(source_uuid) if source_uuid else None
                    if cached_username == from_user:
                        self.message_queue.remove(msg)
                        return msg

            # No matching message in queue, wait for new ones
            self._new_message_event.clear()
            remaining = timeout - elapsed
            try:
                await asyncio.wait_for(self._new_message_event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                logger.debug("Wait for new message timed out")
                return None


SuccessResponse = Dict[str, str]
ErrorResponse = Dict[str, str]

# Global instances
config = SignalConfig()
username_cache = UsernameCache()
daemon_connection: Optional[SignalDaemonConnection] = None
message_listener: Optional[SignalMessageListener] = None


def _get_daemon() -> SignalDaemonConnection:
    """Get or create the daemon connection."""
    global daemon_connection
    if daemon_connection is None:
        daemon_connection = SignalDaemonConnection(
            config.daemon_host, config.daemon_port, config.user_id
        )
    return daemon_connection


def _get_listener() -> SignalMessageListener:
    """Get or create the persistent message listener."""
    global message_listener
    if message_listener is None:
        message_listener = SignalMessageListener(
            config.daemon_host, config.daemon_port, config.user_id
        )
    return message_listener


async def _run_signal_cli(cmd: str) -> Tuple[str, str, int | None]:
    """Helper method to run a signal-cli command.

    This is kept for backward compatibility but deprecated in favor of daemon connection.
    """
    logger.debug(f"Executing signal-cli command: {cmd}")
    try:
        process = await asyncio.create_subprocess_shell(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        stdout, stderr = await process.communicate()
        stdout_str, stderr_str = stdout.decode(), stderr.decode()

        if process.returncode != 0:
            logger.warning(
                f"signal-cli command failed with return code {process.returncode}"
            )
            logger.warning(f"stderr: {stderr_str}")
        else:
            logger.debug("signal-cli command completed successfully")

        return stdout_str, stderr_str, process.returncode

    except Exception as e:
        logger.error(f"Error running signal-cli command: {str(e)}", exc_info=True)
        raise SignalCLIError(f"Failed to run signal-cli: {str(e)}")


async def _get_group_id(group_name: str) -> Optional[str]:
    """Get the group name for a given group name."""
    logger.info(f"Looking up group with name: {group_name}")

    list_cmd = f"signal-cli -u {shlex.quote(config.user_id)} listGroups"
    stdout, stderr, return_code = await _run_signal_cli(list_cmd)

    if return_code != 0:
        logger.error(f"Error listing groups: {stderr}")
        return None

    # Parse the output to find the group name
    for line in stdout.split("\n"):
        if "Name: " in line and group_name in line:
            logger.info(f"Found group: {group_name}")
            return group_name

    logger.error(f"Could not find group with name: {group_name}")
    return None


async def _send_message(message: str, target: str, is_group: bool = False) -> bool:
    """Send a message to either a user or group using daemon connection."""
    target_type = "group" if is_group else "user"
    logger.info(f"Sending message to {target_type}: {target}")

    try:
        daemon = _get_daemon()
        if is_group:
            success = await daemon.send_message(message, group_id=target)
        else:
            success = await daemon.send_message(message, recipient=target)

        if success:
            logger.info(f"Successfully sent message to {target_type}: {target}")
        else:
            logger.error(f"Failed to send message to {target_type}: {target}")

        return success
    except Exception as e:
        logger.error(f"Failed to send message to {target_type}: {str(e)}")
        return False


def _parse_daemon_notification(notification: Dict[str, Any]) -> Optional[MessageResponse]:
    """Parse a daemon notification into a MessageResponse.

    Args:
        notification: The daemon notification dict

    Returns:
        MessageResponse if the notification contains a message, None otherwise
    """
    try:
        # The notification structure from daemon should have an envelope
        envelope = notification.get("envelope", {})

        # Extract sender information
        source = envelope.get("source") or envelope.get("sourceNumber")
        source_uuid = envelope.get("sourceUuid")
        source_name = envelope.get("sourceName")

        # Cache username mapping if available
        if source_uuid and source_name:
            username_cache.add_mapping(source_uuid, source_name)
        if source_uuid and source:
            username_cache.add_mapping(source_uuid, source)

        # Extract message
        data_message = envelope.get("dataMessage", {})
        message_body = data_message.get("message")

        # Extract timestamp
        timestamp = envelope.get("timestamp")

        # Extract group info
        group_info = data_message.get("groupInfo")
        group_name = None
        if group_info:
            group_name = group_info.get("name")

        # Only return if we have a message body
        if message_body:
            sender_id = source or source_uuid
            logger.info(
                f"Parsed message from {sender_id}"
                + (f" in group {group_name}" if group_name else "")
            )
            return MessageResponse(
                message=message_body,
                sender_id=sender_id,
                group_name=group_name,
                timestamp=timestamp,
            )

        return None

    except Exception as e:
        logger.warning(f"Failed to parse daemon notification: {e}")
        return None


async def _parse_receive_output(
    stdout: str,
) -> Optional[MessageResponse]:
    """Parse the output of signal-cli receive command.

    This is kept for backward compatibility with subprocess mode.
    """
    logger.debug("Parsing received message output")

    lines = stdout.split("\n")

    # Process each envelope section separately
    current_envelope: Dict[str, Any] = {}
    current_sender: Optional[str] = None

    for i, line in enumerate(lines):
        line = line.strip()

        if not line:
            continue

        if line.startswith("Envelope from:"):
            # Start of a new envelope block
            current_envelope = {}

            # Extract phone number using a straightforward approach
            # Format: Envelope from: "Bob Sagat" +11234567890 (device: 4) to +15551234567
            parts = line.split("+")
            if len(parts) > 1:
                # Get the phone number part
                phone_part = parts[1].split()[0]
                current_sender = "+" + phone_part
                current_envelope["sender"] = current_sender
                logger.debug(f"Found sender: {current_sender}")

        elif line.startswith("Timestamp:"):
            # Extract timestamp
            if current_envelope:
                timestamp_str = line[10:].strip()
                try:
                    # Parse timestamp (format: 1234567890123)
                    timestamp = int(timestamp_str)
                    current_envelope["timestamp"] = timestamp
                    logger.debug(f"Found timestamp: {timestamp}")
                except ValueError:
                    logger.warning(f"Failed to parse timestamp: {timestamp_str}")

        elif line.startswith("Body:"):
            # Found a message body
            if current_envelope:
                message_body = line[5:].strip()
                current_envelope["message"] = message_body
                current_envelope["has_body"] = True
                logger.debug(f"Found message body: {message_body}")

                # If we have a valid message with body, return it
                if current_envelope.get("has_body") and "sender" in current_envelope:
                    sender = current_envelope["sender"]
                    msg = current_envelope["message"]
                    group = current_envelope.get("group")
                    timestamp = current_envelope.get("timestamp")

                    if isinstance(sender, str) and isinstance(msg, str):
                        logger.info(
                            f"Successfully parsed message from {sender}"
                            + (f" in group {group}" if group else "")
                        )
                        return MessageResponse(
                            message=msg,
                            sender_id=sender,
                            group_name=group,
                            timestamp=timestamp,
                        )

        elif line.startswith("Group info:"):
            if current_envelope:
                current_envelope["in_group"] = True

        elif (
            line.startswith("Name:")
            and current_envelope
            and current_envelope.get("in_group")
        ):
            group_name = line[5:].strip()
            current_envelope["group"] = group_name
            logger.debug(f"Found group name: {group_name}")

    logger.warning("Failed to parse message from output")
    return None


@mcp.tool()
async def send_message_to_user(
    message: str, user_id: str
) -> Union[SuccessResponse, ErrorResponse]:
    """Send a message to a specific user using signal-cli."""
    logger.info(f"Tool called: send_message_to_user for user {user_id}")

    try:
        success = await _send_message(message, user_id, is_group=False)
        if success:
            logger.info(f"Successfully sent message to user {user_id}")
            return {"message": "Message sent successfully"}
        logger.error(f"Failed to send message to user {user_id}")
        return {"error": "Failed to send message"}
    except Exception as e:
        logger.error(f"Error in send_message_to_user: {str(e)}", exc_info=True)
        return {"error": str(e)}


@mcp.tool()
async def send_message_to_group(
    message: str, group_id: str
) -> Union[SuccessResponse, ErrorResponse]:
    """Send a message to a group using signal-cli."""
    logger.info(f"Tool called: send_message_to_group for group {group_id}")

    try:
        group_name = await _get_group_id(group_id)
        if not group_name:
            logger.error(f"Could not find group: {group_id}")
            return {"error": f"Could not find group: {group_id}"}

        success = await _send_message(message, group_name, is_group=True)
        if success:
            logger.info(f"Successfully sent message to group {group_id}")
            return {"message": "Message sent successfully"}
        logger.error(f"Failed to send message to group {group_id}")
        return {"error": "Failed to send message"}
    except Exception as e:
        logger.error(f"Error in send_message_to_group: {str(e)}", exc_info=True)
        return {"error": str(e)}


@mcp.tool()
async def receive_message(timeout: float) -> MessageResponse:
    """Wait for and receive a message using daemon connection."""
    logger.info(f"Tool called: receive_message with timeout {timeout}s")

    try:
        daemon = _get_daemon()
        notifications = await daemon.receive_messages(timeout=timeout)

        if not notifications:
            logger.info("No message received within timeout")
            return MessageResponse()

        # Process notifications and find the first one with a message
        for notification in notifications:
            result = _parse_daemon_notification(notification)
            if result:
                logger.info(
                    f"Successfully received message from {result.sender_id}"
                    + (f" in group {result.group_name}" if result.group_name else "")
                )
                return result

        logger.info("Received notifications but no messages with body")
        return MessageResponse()

    except Exception as e:
        logger.error(f"Error in receive_message: {str(e)}", exc_info=True)
        return MessageResponse(error=str(e))


@mcp.tool()
async def wait_for_message(
    from_user: Optional[str] = None, max_wait_seconds: int = 3600
) -> MessageResponse:
    """Block and wait for a new message to arrive from a specific user or any user.

    This tool uses a persistent listener with push notifications to efficiently
    wait for messages. The listener runs in the background and queues incoming
    messages for immediate retrieval.

    Args:
        from_user: Optional phone number to filter messages from (e.g., "+1234567890").
                   If None, accepts messages from any user.
        max_wait_seconds: Maximum time to wait in seconds (default: 3600 = 1 hour).
                          Must be between 1 and 7200 (2 hours).

    Returns:
        MessageResponse with message content, sender_id, timestamp, and optionally group_name.
        Returns error if max_wait_seconds is exceeded or if an error occurs.
    """
    logger.info(
        f"Tool called: wait_for_message"
        + (f" from user {from_user}" if from_user else " from any user")
        + f" (max wait: {max_wait_seconds}s)"
    )

    # Validate max_wait_seconds
    if max_wait_seconds < 1 or max_wait_seconds > 7200:
        error_msg = "max_wait_seconds must be between 1 and 7200 (2 hours)"
        logger.error(error_msg)
        return MessageResponse(error=error_msg)

    try:
        listener = _get_listener()

        # Wait for a message using the persistent listener
        msg = await listener.wait_for_message(
            timeout=float(max_wait_seconds),
            from_user=from_user
        )

        if msg is None:
            error_msg = f"No message received within {max_wait_seconds} seconds"
            logger.info(error_msg)
            return MessageResponse(error=error_msg)

        # Parse the message
        result = _parse_daemon_notification(msg)

        if result and result.message:
            logger.info(
                f"Received message from {result.sender_id}: {result.message}"
                + (f" in group {result.group_name}" if result.group_name else "")
            )
            return result
        else:
            error_msg = "Received message but couldn't parse it"
            logger.error(error_msg)
            return MessageResponse(error=error_msg)

    except Exception as e:
        logger.error(f"Error in wait_for_message: {str(e)}", exc_info=True)
        return MessageResponse(error=str(e))


def initialize_server() -> SignalConfig:
    """Initialize the Signal server with configuration."""
    logger.info("Initializing Signal server")

    parser = argparse.ArgumentParser(description="Run the Signal MCP server")
    parser.add_argument(
        "--user-id", required=True, help="Signal phone number for the user"
    )
    parser.add_argument(
        "--transport",
        choices=["sse", "stdio"],
        default="sse",
        help="Transport to use for communication with the client. (default: sse)",
    )

    args = parser.parse_args()
    logger.info(f"Parsed arguments: user_id={args.user_id}, transport={args.transport}")

    # Set global config
    config.user_id = args.user_id
    config.transport = args.transport

    logger.info(f"Initialized Signal server for user: {config.user_id}")
    return config


def run_mcp_server():
    """Run the MCP server in the current event loop."""
    config = initialize_server()

    transport = config.transport
    logger.info(f"Starting MCP server with transport: {transport}")

    return transport


def main():
    """Main function to run the Signal MCP server."""
    logger.info("Starting Signal MCP server")
    try:
        transport = run_mcp_server()
        mcp.run(transport)
    except Exception as e:
        logger.error(f"Error running Signal MCP server: {str(e)}", exc_info=True)
        raise
    finally:
        logger.info("Signal MCP server shutting down")


if __name__ == "__main__":
    main()
