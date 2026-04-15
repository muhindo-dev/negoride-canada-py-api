#!/bin/bash
# Start the coturn TURN/STUN server for WebRTC NAT traversal
# Prerequisites: brew install coturn (macOS) or apt install coturn (Linux)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Detect the host's LAN IP. Try multiple methods with a short timeout.
LOCAL_IP=$(python3 -c "
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2)
    s.connect(('8.8.8.8', 80))
    print(s.getsockname()[0])
    s.close()
except Exception:
    pass
" 2>/dev/null)

# Fallback: grab the first non-loopback IPv4 address from ifconfig
if [ -z "$LOCAL_IP" ]; then
  LOCAL_IP=$(ifconfig | grep "inet " | grep -v "127.0.0.1" | awk '{print $2}' | head -1)
fi

# Last resort
if [ -z "$LOCAL_IP" ]; then
  LOCAL_IP="127.0.0.1"
fi

echo "========================================"
echo "  NegoRide TURN Server"
echo "  Listening on:  0.0.0.0:3478"
echo "  External IP:   $LOCAL_IP"
echo "  Credentials:   negoride / negoride2026"
echo "========================================"

exec turnserver -c "$SCRIPT_DIR/turnserver.conf" \
  --listening-ip=0.0.0.0 \
  --relay-ip=0.0.0.0 \
  --external-ip="$LOCAL_IP"
