#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/usr/local/bin/turing-display"
SERVICE_NAME="turing-display"

echo "==> Turing Smart Screen 3.5\" Monitor — Installation"
echo ""

# --- Dependencies ---
echo "[1/4] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-serial python3-pil 2>/dev/null || {
    # Fallback: pip install
    pip3 install --break-system-packages pyserial Pillow 2>/dev/null ||
    pip3 install pyserial Pillow
}
echo "  OK"

# --- udev rule ---
echo "[2/4] Installing udev rule for display access..."
cat > /etc/udev/rules.d/99-turing-display.rules << 'RULE'
# Turing Smart Screen / USB monitor (WCH CH552T)
ACTION=="add", SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="5722", MODE="0660", GROUP="plugdev"
RULE
udevadm control --reload-rules 2>/dev/null || true
udevadm trigger 2>/dev/null || true
usermod -a -G plugdev "$SUDO_USER" 2>/dev/null || true
echo "  OK"

# --- Copy files ---
echo "[3/4] Installing application to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
cp monitor.py "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/monitor.py"
echo "  OK"

# --- Systemd service ---
echo "[4/4] Installing systemd service..."
cp turing-display.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable turing-display.service
echo "  OK"

echo ""
echo "==> Installation complete!"
echo ""
echo "  Start now:  systemctl start turing-display"
echo "  Status:     systemctl status turing-display"
echo "  Logs:       journalctl -u turing-display -f"
echo ""
echo "  If the display is not detected, check:"
echo "    - USB connection (lsusb should show 1a86:5722)"
echo "    - The port appears as /dev/ttyACM* or /dev/ttyUSB*"
echo "    - You may need to log out/in for the plugdev group to apply"
