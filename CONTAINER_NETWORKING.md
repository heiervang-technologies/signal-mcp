# Container Networking Notes

## Current Container Environment

**Container:** `snail-dev-gpu-0`
**Preset:** dev-gpu
**Runtime:** sysbox-runc (Docker-in-Docker capable)

## Port Mappings (from docker-compose.yml)

| Host Port | Container Port | Service |
|-----------|---------------|---------|
| 6100 | 22 | SSH |
| 7583 | 7583 | signal-cli daemon |
| 8000 | 8000 | signal-mcp SSE server |

## Network Isolation

The container runs in an isolated network namespace:
- **Cannot directly access** host's LAN IPs (like 192.168.8.123)
- **Can access** services on the host via Docker's gateway IP
- **Can access** internet and external services
- **Exposed ports** allow host → container communication

## Accessing Host Services from Container

To access a service running on the host (e.g., Whisper server at 192.168.8.123):

### Option 1: Use Host Gateway
```bash
# Find the host gateway IP
ip route | grep default
# Typically: 172.17.0.1 or similar
```

### Option 2: Host Network Mode
Modify docker-compose.yml to use:
```yaml
network_mode: "host"
```
This removes network isolation but allows direct access to host's network.

### Option 3: Port Forwarding
If the service is on the host machine, expose it:
```yaml
ports:
  - "8001:8001"  # Forward host's 8001 to container's 8001
```

## Current Issue

Attempted to reach Whisper server at `192.168.8.123` but:
- ❌ Ports 5000, 8000, 9000, 8080, 3000 all timed out
- Container network cannot route to 192.168.8.123 (likely on host's LAN)

## Solution

Need to determine:
1. Is 192.168.8.123 on the same physical machine as the Docker host?
2. What port is the Whisper server actually running on?
3. Should we use host networking or port forwarding?
