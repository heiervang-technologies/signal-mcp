#!/bin/bash
# Auto-reload MCP server when code changes are detected
# Usage: ./auto_reload_watcher.sh

WATCH_DIR="/home/me/ht/signal-mcp/signal_mcp"
RELOAD_SCRIPT="/home/me/ht/signal-mcp/reload_mcp.sh"

echo "Watching for changes in: $WATCH_DIR"
echo "Will auto-reload MCP server on changes..."

# Check if inotifywait is available
if ! command -v inotifywait &> /dev/null; then
    echo "Installing inotify-tools..."
    sudo apt-get update && sudo apt-get install -y inotify-tools
fi

# Watch for changes and auto-reload
while true; do
    inotifywait -r -e modify,create,delete "$WATCH_DIR" 2>/dev/null
    echo "[$(date '+%H:%M:%S')] Code change detected, reloading MCP server..."
    bash "$RELOAD_SCRIPT"
    echo "[$(date '+%H:%M:%S')] Reload complete, waiting for next change..."
    sleep 1  # Debounce rapid changes
done
