#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "mcp",
# ]
# ///
from mcp.server.fastmcp import FastMCP
from typing import Optional, Tuple, Dict, Union, Any, List
import asyncio
import subprocess
import shlex
import argparse
from dataclasses import dataclass, field
import logging
import json
import socket
import os
import re
from pathlib import Path
from datetime import datetime
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

    async def resolve_identifier(self, identifier: str) -> Optional[str]:
        """Resolve a username or phone number to a UUID.

        Args:
            identifier: A Signal username (e.g., "msh.60"), phone number (e.g., "+1234567890"),
                       or UUID. Usernames can optionally have "u:" prefix.

        Returns:
            UUID string if resolved, None if not found or error
        """
        # If already a UUID, return as-is
        if len(identifier) == 36 and identifier.count("-") == 4:
            logger.debug(f"Identifier {identifier} is already a UUID")
            return identifier

        # Strip u: prefix if present
        clean_id = identifier[2:] if identifier.startswith("u:") else identifier

        try:
            if clean_id.startswith("+"):
                # Phone number - use recipient param
                params = {"account": self.user_id, "recipient": [clean_id]}
            else:
                # Username - use username param
                params = {"account": self.user_id, "username": [clean_id]}

            result = await self._send_request("getUserStatus", params)
            logger.debug(f"getUserStatus result: {result}")

            if isinstance(result, list) and len(result) > 0:
                user_info = result[0]
                uuid = user_info.get("uuid")
                if uuid and user_info.get("isRegistered", False):
                    logger.info(f"Resolved {identifier} to UUID {uuid}")
                    return uuid
                else:
                    logger.warning(f"User {identifier} not registered or no UUID: {user_info}")
                    return None
            return None
        except Exception as e:
            logger.error(f"Failed to resolve identifier {identifier}: {e}")
            return None

    async def send_message(
        self, message: str, recipient: Optional[str] = None, group_id: Optional[str] = None
    ) -> bool:
        """Send a message via the daemon.

        Args:
            message: The message to send
            recipient: Phone number, username (with u: prefix), or UUID
                      e.g., "+1234567890", "u:msh.60", "e6cdcf80-e4ab-4c5a-9b4c-4627f53fa824"
            group_id: Group ID (base64 encoded)

        Returns:
            True if successful
        """
        params = {"message": message, "account": self.user_id}

        if recipient:
            if recipient.startswith("+"):
                # Phone number
                params["recipient"] = [recipient]
            elif recipient.startswith("u:"):
                # Username with u: prefix - strip prefix for API
                params["recipient"] = [recipient]
            elif len(recipient) == 36 and recipient.count("-") == 4:
                # UUID format (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)
                params["recipient"] = [recipient]
            else:
                # Assume it's a username without prefix, add u: prefix
                params["recipient"] = [f"u:{recipient}"]
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

    async def send_reaction(
        self, recipient: str, target_timestamp: int, emoji: str
    ) -> bool:
        """Send a reaction to a message via the daemon.

        Args:
            recipient: Phone number, username (with u: prefix), or UUID
            target_timestamp: Timestamp of the message to react to
            emoji: The emoji to react with (e.g., "👍")

        Returns:
            True if successful
        """
        # Format recipient
        if recipient.startswith("+"):
            formatted_recipient = recipient
        elif recipient.startswith("u:"):
            formatted_recipient = recipient
        elif len(recipient) == 36 and recipient.count("-") == 4:
            formatted_recipient = recipient
        else:
            formatted_recipient = f"u:{recipient}"

        params = {
            "account": self.user_id,
            "recipient": [formatted_recipient],
            "targetTimestamp": target_timestamp,
            "emoji": emoji,
        }

        try:
            await self._send_request("sendReaction", params)
            logger.info(f"Successfully sent reaction {emoji} via daemon")
            return True
        except SignalCLIError as e:
            logger.error(f"Failed to send reaction: {e}")
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
                source_uuid = envelope.get("sourceUuid")

                # Check if message matches filter
                if from_user is None:
                    # No filter, return first message
                    self.message_queue.remove(msg)
                    return msg
                else:
                    # from_user should be a resolved UUID at this point
                    if source_uuid == from_user:
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
async def send_reaction(
    user_id: str, target_timestamp: int, emoji: str = "👍"
) -> Union[SuccessResponse, ErrorResponse]:
    """Send a reaction (emoji) to a message.

    Args:
        user_id: The user who sent the message to react to. Accepts:
                 - Signal username (e.g., "msh.60" or "u:msh.60")
                 - Phone number (e.g., "+1234567890")
                 - UUID (e.g., "e6cdcf80-e4ab-4c5a-9b4c-4627f53fa824")
        target_timestamp: The timestamp of the message to react to (from MessageResponse)
        emoji: The emoji to react with (default: "👍")

    Returns:
        Success or error response
    """
    logger.info(f"Tool called: send_reaction to {user_id} with {emoji}")

    try:
        daemon = _get_daemon()
        success = await daemon.send_reaction(user_id, target_timestamp, emoji)
        if success:
            logger.info(f"Successfully sent reaction {emoji} to {user_id}")
            return {"message": "Reaction sent successfully"}
        logger.error(f"Failed to send reaction to {user_id}")
        return {"error": "Failed to send reaction"}
    except Exception as e:
        logger.error(f"Error in send_reaction: {str(e)}", exc_info=True)
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
async def send_and_await_reply(
    message: str,
    user_id: str,
    timeout_seconds: int = 60
) -> MessageResponse:
    """Send a message to a user and wait for their reply in one atomic operation.

    This is a convenience tool that combines send_message_to_user and wait_for_message.
    It sends a message and then waits for a reply from the same user.

    Args:
        message: The message to send to the user.
        user_id: The recipient's identifier. Accepts:
                 - Signal username (e.g., "msh.60" or "u:msh.60")
                 - Phone number (e.g., "+1234567890")
                 - UUID (e.g., "e6cdcf80-e4ab-4c5a-9b4c-4627f53fa824")
        timeout_seconds: Maximum time to wait for a reply in seconds (default: 60).
                         Must be between 1 and 7200 (2 hours).

    Returns:
        MessageResponse with the reply message content, sender_id, timestamp, and optionally group_name.
        Returns error if sending fails, timeout is exceeded, or an error occurs.
    """
    logger.info(
        f"Tool called: send_and_await_reply to user {user_id} "
        f"(timeout: {timeout_seconds}s)"
    )

    # Validate timeout
    if timeout_seconds < 1 or timeout_seconds > 7200:
        error_msg = "timeout_seconds must be between 1 and 7200 (2 hours)"
        logger.error(error_msg)
        return MessageResponse(error=error_msg)

    try:
        daemon = _get_daemon()

        # Resolve user_id to UUID first (needed for filtering replies)
        resolved_user = await daemon.resolve_identifier(user_id)
        if resolved_user is None:
            error_msg = f"Could not resolve user '{user_id}' - user may not exist or is not registered"
            logger.error(error_msg)
            return MessageResponse(error=error_msg)
        logger.info(f"Resolved '{user_id}' to UUID: {resolved_user}")

        # Start the listener before sending to avoid missing quick replies
        listener = _get_listener()
        if not listener._running:
            await listener.start()

        # Send the message
        success = await daemon.send_message(message, recipient=user_id)
        if not success:
            error_msg = f"Failed to send message to {user_id}"
            logger.error(error_msg)
            return MessageResponse(error=error_msg)
        logger.info(f"Message sent to {user_id}, now waiting for reply...")

        # Wait for reply from the same user
        msg = await listener.wait_for_message(
            timeout=float(timeout_seconds),
            from_user=resolved_user
        )

        if msg is None:
            error_msg = f"No reply received from {user_id} within {timeout_seconds} seconds"
            logger.info(error_msg)
            return MessageResponse(error=error_msg)

        # Parse the reply
        result = _parse_daemon_notification(msg)

        if result and result.message:
            logger.info(
                f"Received reply from {result.sender_id}: {result.message}"
                + (f" in group {result.group_name}" if result.group_name else "")
            )
            return result
        else:
            error_msg = "Received reply but couldn't parse it"
            logger.error(error_msg)
            return MessageResponse(error=error_msg)

    except Exception as e:
        logger.error(f"Error in send_and_await_reply: {str(e)}", exc_info=True)
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
        from_user: Optional identifier to filter messages from. Accepts:
                   - Signal username (e.g., "msh.60" or "u:msh.60")
                   - Phone number (e.g., "+1234567890")
                   - UUID (e.g., "e6cdcf80-e4ab-4c5a-9b4c-4627f53fa824")
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
        # Resolve from_user to UUID if specified
        resolved_user: Optional[str] = None
        if from_user:
            daemon = _get_daemon()
            resolved_user = await daemon.resolve_identifier(from_user)
            if resolved_user is None:
                error_msg = f"Could not resolve user '{from_user}' - user may not exist or is not registered"
                logger.error(error_msg)
                return MessageResponse(error=error_msg)
            logger.info(f"Resolved '{from_user}' to UUID: {resolved_user}")

        listener = _get_listener()

        # Wait for a message using the persistent listener (filter by resolved UUID)
        msg = await listener.wait_for_message(
            timeout=float(max_wait_seconds),
            from_user=resolved_user
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


# =============================================================================
# Message History from Log
# =============================================================================

@dataclass
class HistoryMessage:
    """A message from the signal-cli daemon log."""
    sender_name: str
    sender_uuid: str
    timestamp: int
    timestamp_iso: str
    body: str


def _get_allowed_senders() -> Optional[List[str]]:
    """Get list of allowed senders from environment variable.

    Set SIGNAL_ALLOWED_SENDERS as comma-separated list of usernames, UUIDs, or phone numbers.
    Example: SIGNAL_ALLOWED_SENDERS="alice.01,bob.02,+15551234567"

    Returns None if not set (allow all senders).
    """
    allowed = os.environ.get("SIGNAL_ALLOWED_SENDERS", "").strip()
    if not allowed:
        return None
    return [s.strip() for s in allowed.split(",") if s.strip()]


def _is_sender_allowed(
    sender_uuid: str,
    sender_name: str,
    allowed_senders: Optional[List[str]]
) -> bool:
    """Check if a sender is in the whitelist.

    Args:
        sender_uuid: The sender's UUID
        sender_name: The sender's display name
        allowed_senders: List of allowed identifiers, or None to allow all

    Returns:
        True if sender is allowed
    """
    if allowed_senders is None:
        return True

    # Check UUID
    if sender_uuid in allowed_senders:
        return True

    # Check display name
    if sender_name in allowed_senders:
        return True

    # Check if we can resolve sender to username and match
    # The username might be cached
    cached_username = username_cache.get_username(sender_uuid)
    if cached_username and cached_username in allowed_senders:
        return True

    return False


def _parse_signal_log(
    log_path: str = "/tmp/signal-cli-daemon.log",
    since_timestamp: Optional[int] = None,
    from_user: Optional[str] = None,
    limit: int = 100
) -> List[HistoryMessage]:
    """Parse the signal-cli daemon log file for message history.

    Args:
        log_path: Path to the daemon log file
        since_timestamp: Only return messages after this timestamp (ms since epoch)
        from_user: Filter to messages from this sender (UUID, username, or display name)
        limit: Maximum number of messages to return

    Returns:
        List of HistoryMessage objects, newest first
    """
    messages: List[HistoryMessage] = []
    allowed_senders = _get_allowed_senders()

    try:
        with open(log_path, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        logger.warning(f"Signal daemon log not found: {log_path}")
        return []
    except Exception as e:
        logger.error(f"Error reading signal log: {e}")
        return []

    # Parse log entries - they span multiple lines
    # Format:
    # Envelope from: "Display Name" uuid (device: N) to +phone
    # Timestamp: 1234567890123 (2025-01-01T12:00:00.000Z)
    # ...
    # Body: message text

    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for envelope start
        # Note: signal-cli uses curly quotes (Unicode U+201C/U+201D) not ASCII "
        envelope_match = re.match(
            r'Envelope from: ["\u201c\u201d]([^"\u201c\u201d]*)["\u201c\u201d] ([a-f0-9-]{36}) \(device: \d+\)',
            line
        )
        if envelope_match:
            sender_name = envelope_match.group(1)
            sender_uuid = envelope_match.group(2)

            # Look for timestamp and body in next lines
            timestamp = None
            timestamp_iso = None
            body = None

            j = i + 1
            while j < len(lines) and j < i + 10:  # Look ahead up to 10 lines
                next_line = lines[j]

                # Check for next envelope (end of this message)
                if next_line.startswith("Envelope from:"):
                    break

                # Parse timestamp
                ts_match = re.match(r'Timestamp: (\d+) \(([^)]+)\)', next_line)
                if ts_match:
                    timestamp = int(ts_match.group(1))
                    timestamp_iso = ts_match.group(2)

                # Parse body
                if next_line.startswith("Body: "):
                    body = next_line[6:].rstrip()

                j += 1

            # Only add if we have a body (actual message, not just envelope)
            if body and timestamp:
                # Apply whitelist filter
                if not _is_sender_allowed(sender_uuid, sender_name, allowed_senders):
                    logger.debug(f"Skipping message from non-whitelisted sender: {sender_name}")
                    i = j
                    continue

                # Apply timestamp filter
                if since_timestamp and timestamp <= since_timestamp:
                    i = j
                    continue

                # Apply sender filter
                if from_user:
                    if not (
                        sender_uuid == from_user or
                        sender_name == from_user or
                        username_cache.get_username(sender_uuid) == from_user
                    ):
                        i = j
                        continue

                messages.append(HistoryMessage(
                    sender_name=sender_name,
                    sender_uuid=sender_uuid,
                    timestamp=timestamp,
                    timestamp_iso=timestamp_iso,
                    body=body
                ))

            i = j
        else:
            i += 1

    # Sort by timestamp descending (newest first) and limit
    messages.sort(key=lambda m: m.timestamp, reverse=True)
    return messages[:limit]


@dataclass
class MessageHistoryResponse:
    """Response from get_message_history tool."""
    messages: List[Dict[str, Any]] = field(default_factory=list)
    count: int = 0
    error: Optional[str] = None


@mcp.tool()
async def get_message_history(
    since_timestamp: Optional[int] = None,
    from_user: Optional[str] = None,
    limit: int = 50
) -> MessageHistoryResponse:
    """Get message history from the signal-cli daemon log.

    Parses the daemon log file to retrieve past messages. Messages are filtered
    by the SIGNAL_ALLOWED_SENDERS environment variable if set.

    Args:
        since_timestamp: Only return messages after this timestamp (milliseconds since epoch).
                        Use this to get only new messages since last check.
        from_user: Filter to messages from a specific sender. Accepts:
                   - Signal username (e.g., "alice.01")
                   - UUID (e.g., "a1b2c3d4-e5f6-7890-abcd-ef1234567890")
                   - Display name (e.g., "Alice Smith")
        limit: Maximum number of messages to return (default: 50, max: 500)

    Returns:
        MessageHistoryResponse with list of messages (newest first), count, and optional error.
        Each message contains: sender_name, sender_uuid, timestamp, timestamp_iso, body

    Environment:
        SIGNAL_ALLOWED_SENDERS: Comma-separated whitelist of allowed senders.
                                If not set, all senders are allowed.
                                Example: "alice.01,bob.02,+15551234567"
    """
    logger.info(
        f"Tool called: get_message_history"
        + (f" since={since_timestamp}" if since_timestamp else "")
        + (f" from={from_user}" if from_user else "")
        + f" limit={limit}"
    )

    # Validate limit
    limit = min(max(1, limit), 500)

    try:
        # Resolve from_user to UUID if specified
        resolved_user: Optional[str] = None
        if from_user:
            daemon = _get_daemon()
            resolved_uuid = await daemon.resolve_identifier(from_user)
            # Use resolved UUID if available, otherwise use original (might be display name)
            resolved_user = resolved_uuid if resolved_uuid else from_user

        messages = _parse_signal_log(
            since_timestamp=since_timestamp,
            from_user=resolved_user,
            limit=limit
        )

        # Convert to dicts for JSON serialization
        message_dicts = [
            {
                "sender_name": m.sender_name,
                "sender_uuid": m.sender_uuid,
                "timestamp": m.timestamp,
                "timestamp_iso": m.timestamp_iso,
                "body": m.body
            }
            for m in messages
        ]

        logger.info(f"Returning {len(message_dicts)} messages from history")
        return MessageHistoryResponse(
            messages=message_dicts,
            count=len(message_dicts)
        )

    except Exception as e:
        logger.error(f"Error in get_message_history: {str(e)}", exc_info=True)
        return MessageHistoryResponse(error=str(e))


@dataclass
class Chat:
    """Represents a chat (DM or group)."""
    chat_id: str  # UUID for DMs, group ID for groups
    chat_type: str  # "dm" or "group"
    name: str  # Display name or group name
    username: Optional[str] = None  # Signal username if available (DMs only)


@dataclass
class ListChatsResponse:
    """Response from list_chats tool."""
    chats: List[Dict[str, Any]] = field(default_factory=list)
    count: int = 0
    error: Optional[str] = None


@mcp.tool()
async def list_chats() -> ListChatsResponse:
    """List all chats (DMs and groups) the account is involved with.

    Returns both direct message contacts and group chats. For DMs, includes
    the contact's username and profile name. For groups, includes the group
    name and member count.

    Returns:
        ListChatsResponse with list of chats, count, and optional error.
        Each chat contains: chat_id, chat_type ("dm" or "group"), name, username (for DMs)
    """
    logger.info("Tool called: list_chats")

    try:
        daemon = _get_daemon()
        chats: List[Chat] = []

        # Get groups
        try:
            groups_result = await daemon._send_request("listGroups", {"account": config.user_id})
            if isinstance(groups_result, list):
                for group in groups_result:
                    group_id = group.get("id") or group.get("groupId", "")
                    group_name = group.get("name", "Unnamed Group")
                    chats.append(Chat(
                        chat_id=group_id,
                        chat_type="group",
                        name=group_name
                    ))
                logger.info(f"Found {len(groups_result)} groups")
        except Exception as e:
            logger.warning(f"Failed to list groups: {e}")

        # Get contacts (DMs)
        try:
            contacts_result = await daemon._send_request("listContacts", {"account": config.user_id})
            if isinstance(contacts_result, list):
                for contact in contacts_result:
                    uuid = contact.get("uuid", "")
                    username = contact.get("username")
                    profile = contact.get("profile", {})

                    # Build display name from profile or username
                    given_name = profile.get("givenName", "")
                    family_name = profile.get("familyName", "")
                    display_name = f"{given_name} {family_name}".strip()
                    if not display_name:
                        display_name = username or contact.get("name") or uuid[:8]

                    if uuid:  # Only add if we have a UUID
                        chats.append(Chat(
                            chat_id=uuid,
                            chat_type="dm",
                            name=display_name,
                            username=username
                        ))
                logger.info(f"Found {len(contacts_result)} contacts")
        except Exception as e:
            logger.warning(f"Failed to list contacts: {e}")

        # Convert to dicts
        chat_dicts = [
            {
                "chat_id": c.chat_id,
                "chat_type": c.chat_type,
                "name": c.name,
                "username": c.username
            }
            for c in chats
        ]

        logger.info(f"Returning {len(chat_dicts)} chats")
        return ListChatsResponse(
            chats=chat_dicts,
            count=len(chat_dicts)
        )

    except Exception as e:
        logger.error(f"Error in list_chats: {str(e)}", exc_info=True)
        return ListChatsResponse(error=str(e))


@mcp.tool()
async def ping_signal() -> Dict[str, Any]:
    """Ping the Signal MCP server to verify it's working.

    This is a test tool added to demonstrate hot-reload capability.
    Returns server status, connection info, and current timestamp.

    Returns:
        Dict with server status, user_id, daemon connection status, and timestamp
    """
    logger.info("Tool called: ping_signal")

    try:
        daemon = _get_daemon()

        # Try to connect to verify daemon is accessible
        try:
            await daemon.connect()
            daemon_status = "connected"
        except Exception as e:
            daemon_status = f"error: {str(e)}"

        return {
            "status": "ok",
            "server": "signal-mcp",
            "version": "1.25.0",
            "user_id": config.user_id,
            "daemon_connection": daemon_status,
            "timestamp": int(time.time() * 1000),
            "message": "Signal MCP server is operational! Hot-reload is working! 🚀"
        }
    except Exception as e:
        logger.error(f"Error in ping_signal: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "timestamp": int(time.time() * 1000)
        }


def initialize_server() -> SignalConfig:
    """Initialize the Signal server with configuration."""
    logger.info("Initializing Signal server")

    parser = argparse.ArgumentParser(description="Run the Signal MCP server")
    parser.add_argument(
        "--user-id",
        default=os.environ.get("SIGNAL_USER"),
        help="Signal phone number for the user (or set SIGNAL_USER env var)"
    )
    parser.add_argument(
        "--transport",
        choices=["sse", "stdio"],
        default="sse",
        help="Transport to use for communication with the client. (default: sse)",
    )

    args = parser.parse_args()

    if not args.user_id:
        parser.error("--user-id is required (or set SIGNAL_USER environment variable)")

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
