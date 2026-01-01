#!/bin/bash
# MCP Hot Reload Script
# Triggers Claude Code to reload MCP servers by toggling the server config

CLAUDE_CONFIG="$HOME/.claude.json"
SERVER_NAME="signal"

echo "Reloading MCP server: $SERVER_NAME"

# Create a backup
cp "$CLAUDE_CONFIG" "$CLAUDE_CONFIG.reload_backup"

# Use Python to toggle the server (remove and re-add to force reload)
python3 <<'PYTHON'
import json
import time

config_path = "/home/me/.claude.json"

# Read config
with open(config_path, 'r') as f:
    config = json.load(f)

# Save the server config
server_config = config.get('mcpServers', {}).get('signal', {})

# Remove it (this triggers a disconnect)
if 'signal' in config.get('mcpServers', {}):
    del config['mcpServers']['signal']
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    print("Removed signal MCP server from config")
    time.sleep(0.5)

# Add it back (this triggers a reconnect)
if 'mcpServers' not in config:
    config['mcpServers'] = {}
config['mcpServers']['signal'] = server_config
with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)
print("Re-added signal MCP server to config")

PYTHON

echo "MCP reload triggered. Server should reconnect automatically."
