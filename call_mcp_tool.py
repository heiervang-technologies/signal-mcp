#!/usr/bin/env python3
"""Direct MCP tool caller for testing and debugging"""
import asyncio
import json
import sys
from pathlib import Path

# Add signal_mcp to path
sys.path.insert(0, str(Path(__file__).parent))

from signal_mcp.signal_client import SignalClient


async def call_tool(tool_name: str, **kwargs):
    """Call an MCP tool directly"""
    user_id = "+447441392349"
    client = SignalClient(user_id=user_id)

    # Map tool names to methods
    tool_map = {
        "list_chats": client.list_chats,
        "get_message_history": client.get_message_history,
        "send_message_to_user": client.send_message,
        "wait_for_message": client.wait_for_message,
        "receive_message": client.receive_message,
    }

    if tool_name not in tool_map:
        print(f"Unknown tool: {tool_name}", file=sys.stderr)
        print(f"Available tools: {list(tool_map.keys())}", file=sys.stderr)
        sys.exit(1)

    # Call the tool
    result = await tool_map[tool_name](**kwargs)
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: ./call_mcp_tool.py <tool_name> [json_params]")
        print("Example: ./call_mcp_tool.py list_chats")
        print("Example: ./call_mcp_tool.py get_message_history '{\"limit\": 5}'")
        sys.exit(1)

    tool_name = sys.argv[1]
    params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

    result = asyncio.run(call_tool(tool_name, **params))
    print(json.dumps(result, indent=2))
