#!/bin/bash
# MCP Tool Wrapper - Allows calling MCP tools directly from bash
# Usage: ./mcp_tool_wrapper.sh <tool_name> <json_params>
# Example: ./mcp_tool_wrapper.sh send_message_to_user '{"message":"test","user_id":"msh.60"}'

TOOL_NAME="$1"
PARAMS="${2:-{}}"

if [ -z "$TOOL_NAME" ]; then
    echo "Usage: $0 <tool_name> <json_params>"
    echo "Available tools:"
    echo "  - send_message_to_user"
    echo "  - send_message_to_group"
    echo "  - receive_message"
    echo "  - wait_for_message"
    echo "  - send_and_await_reply"
    echo "  - send_reaction"
    echo "  - get_message_history"
    echo "  - list_chats"
    exit 1
fi

MCP_SERVER="/home/me/ht/signal-mcp/.venv/bin/python"
USER_ID="+447441392349"

# Create the JSON-RPC request
REQUEST=$(cat <<EOF
{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"bash-wrapper","version":"1.0.0"}},"id":1}
{"jsonrpc":"2.0","method":"tools/call","params":{"name":"$TOOL_NAME","arguments":$PARAMS},"id":2}
EOF
)

# Call the MCP server
echo "$REQUEST" | $MCP_SERVER -m signal_mcp.main --user-id "$USER_ID" --transport stdio 2>/dev/null | grep -v '"id":1' | jq -r '.result.content[0].text // .error // .'
