#!/bin/bash
# Usage: wireguard_setup.sh <CONTROL_IP>
# Sets up WireGuard VPN server on the control server and generates client key pairs.
# Client .conf files are generated on-demand per learner (with their individual Training IP).
set -e

CONTROL_IP="$1"

if [ -z "$CONTROL_IP" ]; then
  echo "Usage: $0 <CONTROL_IP>" >&2
  exit 1
fi

# Use sudo only if not already root
[ "$(id -u)" -eq 0 ] && SUDO="" || SUDO="sudo"

WG_DIR="/etc/wireguard"
CLIENT_DIR="/opt/zansin/red-controller/wireguard/clients"
WG_PORT=51820
NUM_CLIENTS=30

# 1. Install WireGuard
$SUDO apt-get install -y wireguard

# 2. Enable IP forwarding
$SUDO sysctl -w net.ipv4.ip_forward=1
grep -qxF 'net.ipv4.ip_forward=1' /etc/sysctl.conf || \
  echo 'net.ipv4.ip_forward=1' | $SUDO tee -a /etc/sysctl.conf

# 3. Detect default outbound interface
OUTBOUND_IF=$(ip route | awk '/^default/ {print $5; exit}')
if [ -z "$OUTBOUND_IF" ]; then
  echo "ERROR: cannot detect default outbound interface" >&2
  exit 1
fi
echo "[*] Outbound interface: $OUTBOUND_IF"

# 4. Generate server key pair (idempotent: skip if already exists)
$SUDO mkdir -p "$WG_DIR"
$SUDO chmod 700 "$WG_DIR"
if [ ! -f "$WG_DIR/server_private.key" ]; then
  wg genkey | $SUDO tee "$WG_DIR/server_private.key" | wg pubkey | $SUDO tee "$WG_DIR/server_public.key" > /dev/null
  $SUDO chmod 600 "$WG_DIR/server_private.key"
  echo "[*] Generated new server key pair"
else
  echo "[*] Server key pair already exists, skipping"
fi
SERVER_PRIV=$($SUDO cat "$WG_DIR/server_private.key")
SERVER_PUB=$($SUDO cat "$WG_DIR/server_public.key")

# 5. Generate client key pairs (idempotent: skip individual keys that exist)
mkdir -p "$CLIENT_DIR"
chmod 750 "$CLIENT_DIR"

PEER_BLOCKS=""
for i in $(seq 1 $NUM_CLIENTS); do
  PRIV="$CLIENT_DIR/client${i}_private.key"
  PUB="$CLIENT_DIR/client${i}_public.key"
  if [ ! -f "$PRIV" ]; then
    wg genkey | tee "$PRIV" | wg pubkey > "$PUB"
    chmod 640 "$PRIV"
  fi
  CLIENT_PUB=$(cat "$PUB")
  CLIENT_IP="10.100.0.$((i + 1))"
  PEER_BLOCKS="${PEER_BLOCKS}
[Peer]
# client${i}
PublicKey = ${CLIENT_PUB}
AllowedIPs = ${CLIENT_IP}/32
"
done

# 6. Write /etc/wireguard/wg0.conf
$SUDO tee "$WG_DIR/wg0.conf" > /dev/null << WGEOF
[Interface]
Address = 10.100.0.1/24
ListenPort = ${WG_PORT}
PrivateKey = ${SERVER_PRIV}
PostUp   = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -o ${OUTBOUND_IF} -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -o ${OUTBOUND_IF} -j MASQUERADE
${PEER_BLOCKS}
WGEOF
$SUDO chmod 600 "$WG_DIR/wg0.conf"
echo "[*] Written $WG_DIR/wg0.conf"

# 7. Save Control IP for on-demand client config generation
WIREGUARD_DIR="/opt/zansin/red-controller/wireguard"
echo "$CONTROL_IP" > "$WIREGUARD_DIR/control_ip.txt"
chmod 644 "$WIREGUARD_DIR/control_ip.txt"
echo "[*] Saved Control IP to $WIREGUARD_DIR/control_ip.txt"

# 7b. Copy server public key (non-sensitive) to zansin-accessible directory
cp "$WG_DIR/server_public.key" "$WIREGUARD_DIR/server_public.key"
chmod 644 "$WIREGUARD_DIR/server_public.key"
echo "[*] Copied server_public.key to $WIREGUARD_DIR/"

# Fix ownership
chown -R zansin:zansin "/opt/zansin/red-controller/wireguard"

# 8. Allow WireGuard port in UFW if active
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  $SUDO ufw allow "${WG_PORT}/udp" comment "WireGuard"
  echo "[*] UFW: allowed ${WG_PORT}/udp"
fi

# 9. Enable and start wg-quick@wg0
$SUDO systemctl enable wg-quick@wg0
$SUDO systemctl restart wg-quick@wg0
echo "[DONE] WireGuard ready. Server public key: ${SERVER_PUB}"
