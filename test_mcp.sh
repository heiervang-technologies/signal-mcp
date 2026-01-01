#!/bin/bash
# Quick MCP testing script - tests signal MCP functionality
set -e

WRAPPER="/home/me/ht/signal-mcp/mcp_tool_wrapper.sh"

echo "=== Signal MCP Test Suite ==="
echo

# Test 1: List chats
echo "Test 1: Listing chats..."
$WRAPPER list_chats '{}'
echo

# Test 2: Get message history
echo "Test 2: Getting recent message history..."
$WRAPPER get_message_history '{"limit": 5}'
echo

echo "=== Tests Complete ==="
