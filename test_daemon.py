#!/usr/bin/env python3
"""Test script to verify daemon connection and improvements."""

import asyncio
import sys
from pathlib import Path

# Add signal_mcp to path
sys.path.insert(0, str(Path(__file__).parent))

from signal_mcp.main import (
    SignalDaemonConnection,
    UsernameCache,
    _parse_daemon_notification,
    config,
)


async def test_daemon_connection():
    """Test basic daemon connection."""
    print("Testing daemon connection...")

    # Use the phone number from the running daemon
    config.user_id = "+447418639505"

    daemon = SignalDaemonConnection("localhost", 7583, config.user_id)

    try:
        await daemon.connect()
        print("✓ Successfully connected to daemon")

        # Try to receive with a short timeout
        print("Testing message receive (5 second timeout)...")
        messages = await daemon.receive_messages(timeout=5)
        print(f"✓ Received {len(messages)} notifications")

        if messages:
            print("\nFirst notification:")
            print(messages[0])

        await daemon.disconnect()
        print("✓ Successfully disconnected")

        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


async def test_username_cache():
    """Test username cache functionality."""
    print("\nTesting username cache...")

    # Create a temporary cache file
    cache_file = Path("/tmp/test_username_cache.json")
    if cache_file.exists():
        cache_file.unlink()

    cache = UsernameCache(cache_file)

    # Test adding a mapping
    cache.add_mapping("test-uuid-123", "test.user")
    print("✓ Added mapping: test-uuid-123 -> test.user")

    # Test retrieving username
    username = cache.get_username("test-uuid-123")
    assert username == "test.user", f"Expected 'test.user', got '{username}'"
    print(f"✓ Retrieved username: {username}")

    # Test retrieving UUID
    uuid = cache.get_uuid("test.user")
    assert uuid == "test-uuid-123", f"Expected 'test-uuid-123', got '{uuid}'"
    print(f"✓ Retrieved UUID: {uuid}")

    # Test persistence
    cache2 = UsernameCache(cache_file)
    username2 = cache2.get_username("test-uuid-123")
    assert username2 == "test.user", "Cache persistence failed"
    print("✓ Cache persistence works")

    # Cleanup
    cache_file.unlink()

    return True


async def test_parse_notification():
    """Test notification parsing."""
    print("\nTesting notification parsing...")

    # Sample notification structure
    test_notification = {
        "envelope": {
            "source": "+1234567890",
            "sourceUuid": "test-uuid-456",
            "sourceName": "test.username",
            "timestamp": 1234567890123,
            "dataMessage": {
                "message": "Hello, world!",
                "timestamp": 1234567890123,
            }
        }
    }

    result = _parse_daemon_notification(test_notification)

    assert result is not None, "Failed to parse notification"
    assert result.message == "Hello, world!", f"Wrong message: {result.message}"
    assert result.sender_id == "+1234567890", f"Wrong sender: {result.sender_id}"
    assert result.timestamp == 1234567890123, f"Wrong timestamp: {result.timestamp}"

    print("✓ Successfully parsed notification")
    print(f"  Message: {result.message}")
    print(f"  Sender: {result.sender_id}")
    print(f"  Timestamp: {result.timestamp}")

    return True


async def main():
    """Run all tests."""
    print("=" * 60)
    print("Signal MCP Daemon Improvements Test Suite")
    print("=" * 60)

    results = []

    # Test username cache
    try:
        result = await test_username_cache()
        results.append(("Username Cache", result))
    except Exception as e:
        print(f"✗ Username cache test failed: {e}")
        results.append(("Username Cache", False))

    # Test notification parsing
    try:
        result = await test_parse_notification()
        results.append(("Notification Parsing", result))
    except Exception as e:
        print(f"✗ Notification parsing test failed: {e}")
        results.append(("Notification Parsing", False))

    # Test daemon connection
    try:
        result = await test_daemon_connection()
        results.append(("Daemon Connection", result))
    except Exception as e:
        print(f"✗ Daemon connection test failed: {e}")
        results.append(("Daemon Connection", False))

    # Print summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    for name, passed in results:
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"{name:30} {status}")

    all_passed = all(result for _, result in results)
    print("=" * 60)
    if all_passed:
        print("All tests passed!")
        return 0
    else:
        print("Some tests failed!")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
