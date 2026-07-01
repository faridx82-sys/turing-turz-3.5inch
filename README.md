# Turing Smart Screen 3.5" USB System Monitor

A lightweight Python system monitor for the **Turing Smart Screen 3.5" IPS USB display** (CH552T). Displays real-time CPU, GPU, RAM, disk, network, and disk I/O statistics on a secondary USB screen — no HDMI needed.

![Screen](https://img.shields.io/badge/display-3.5%22%20IPS-blue)
![Python](https://img.shields.io/badge/python-3.8%2B-green)
![License](https://github.com/faridx82-sys/turing-turz-3.5inch/blob/main/LICENSE)

---

## Features

| Metric | Source | Format |
|--------|--------|--------|
| **CPU** | `/proc/stat` + `/proc/loadavg` | Usage %, temperature, load average |
| **GPU** (NVIDIA) | `nvidia-smi` | Utilization %, temperature, VRAM |
| **RAM** | `/proc/meminfo` | Usage %, used / total GiB |
| **Disk** | `df -B1 /` | Usage %, used / total GiB |
| **Network** | `/proc/net/dev` | Up/Down KB/s (cumulative total) |
| **Disk I/O** | `/proc/diskstats` | Read/Write KB/s |
| **Hostname** | `hostname` | Title bar |
| **Uptime** | `/proc/uptime` | Title bar |
| **Clock** | `time.strftime` | Bottom bar |

- 480×320 landscape rendering
- Auto-detects display via USB VID/PID
- Runs as a `systemd` service with auto-restart
- Gracefully handles USB disconnect/reconnect

---

## Hardware

| Item | Details |
|------|---------|
| **Display** | Turing Smart Screen 3.5" IPS (SKU: TM0350, TM0352, or generic) |
| **Controller** | WCH CH552T |
| **USB VID:PID** | `1a86:5722` |
| **Interface** | USB CDC ACM (`/dev/ttyACM0`) |
| **Baud rate** | 115200 |
| **Resolution** | 480×320 (landscape native) |

> **Compatibility note:** The monitor has been tested with this specific controller. Some OEM variants use different controllers (e.g., FTDI) or different protocols. Check `lsusb` for `1a86:5722`.

---

## Installation

### Quick install (recommended)

```bash
git clone https://github.com/faridx82-sys/turing-turz-3.5inch.git
cd turing-turz-3.5inch
sudo bash install.sh
```

This will:
1. Install `python3`, `pyserial`, `Pillow` via apt/pip
2. Create a udev rule (`99-turing-display.rules`) for plug-and-play access
3. Copy `monitor.py` to `/usr/local/bin/turing-display/`
4. Install the `turing-display.service` systemd unit (enabled, not started)

Then start the service:

```bash
sudo systemctl start turing-display
```

### Manual install

```bash
# Dependencies
apt install python3 python3-pip python3-serial python3-pil
# or: pip install pyserial Pillow

# Udev rule (optional — allows non-root access)
cat > /etc/udev/rules.d/99-turing-display.rules << 'EOF'
ACTION=="add", SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="5722", MODE="0660", GROUP="plugdev"
EOF
udevadm control --reload-rules && udevadm trigger

# Install
mkdir -p /usr/local/bin/turing-display
cp monitor.py /usr/local/bin/turing-display/
chmod +x /usr/local/bin/turing-display/monitor.py

# Systemd (optional)
cp turing-display.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now turing-display
```

---

## Usage

### Systemd (auto-start at boot)

```bash
sudo systemctl start   turing-display    # start now
sudo systemctl stop    turing-display    # stop
sudo systemctl restart turing-display    # restart
sudo systemctl enable  turing-display    # enable at boot
sudo systemctl status  turing-display    # check status
```

### Logs

```bash
journalctl -u turing-display -f    # follow live logs
journalctl -u turing-display -n 50 # last 50 lines
```

### Run manually (without systemd)

```bash
python3 /usr/local/bin/turing-display/monitor.py
```

Or specify a serial port:

```bash
python3 monitor.py /dev/ttyUSB0
```

---

## Display Layout

```
┌──────────────────────────────────────────────────────┐
│              hostname              ↑ uptime          │  ← Title bar
├──────────────────────┬───────────────────────────────┤
│ CPU  93%             │ GPU  45%                      │
│ ████████████░░░░░░░░░│ ██████░░░░░░░░░░░░░░░░░░░░░░░│  ← Row 1
│ 45°C  load 2.5 2.0   │ 62°C  VRAM 2048/8192M (25%)  │
├──────────────────────┼───────────────────────────────┤
│ RAM  68%             │ DISK  52%                     │
│ ██████████░░░░░░░░░░░│ ███████░░░░░░░░░░░░░░░░░░░░░░│  ← Row 2
│ 9.2/15.3 GiB         │ 120.5/234.1 GiB               │
├──────────────────────┴───────────────────────────────┤
│ NETWORK                          rcvd 1.2G           │
│ ▼ 3.5M/s          ▲ 1.2M/s                           │  ← Row 3
├──────────────────────────────────────────────────────┤
│ DISK I/O                                             │
│ ▼ 45.2M/s         ▲ 12.8M/s                          │  ← Row 4
├──────────────────────────────────────────────────────┤
│ 14:32:07                                              │  ← Bottom bar
└──────────────────────────────────────────────────────┘
```

Without NVIDIA GPU detected, the GPU panel shows "NVIDIA driver not found".

---

## Protocol Reference

The CH552T-based Turing Smart Screen uses a 6-byte command header over USB CDC ACM at 115200 baud.

### Command format

```
Byte 0-4:  Encoded coordinate rectangle (see _encode_coords)
Byte 5:     Command ID
Byte 6+:    Payload (command-specific)
```

### Commands

| ID  | Name | Payload | Description |
|-----|------|---------|-------------|
| 101 | RESET | — | Hardware reset (USB re-enumeration) |
| 102 | CLEAR | — | Clear screen to black |
| 108 | SCREEN_OFF | — | Display off |
| 109 | SCREEN_ON | — | Display on |
| 110 | BRIGHTNESS | `level` byte (0–255, inverted) | Set backlight |
| 121 | ORIENTATION | 10-byte payload | Set orientation + resolution |
| 197 | DISPLAY_BITMAP | Raw RGB565 pixel data | Draw image at coordinates |

### Orientation packet (CMD 121)

```
Byte 5:  121
Byte 6:  orientation + 100  (0+100=portrait, 2+100=landscape)
Byte 7-8: width  (big-endian)
Byte 9-10:height (big-endian)
```

### Image data format

- **Pixel format:** RGB565, little-endian (BGR order on some displays)
- **Byte order per pixel:** Low byte first, high byte second
- **Organization:** Left-to-right, top-to-bottom, row-major
- **Chunking:** Sent in row-strip chunks for flow control

---

## File Reference

| File | Purpose |
|------|---------|
| `monitor.py` | Main application — display driver, stats collector, renderer |
| `install.sh` | One-shot installer (root required) |
| `requirements.txt` | Python dependencies |
| `turing-display.service` | systemd unit for auto-start |

---

## Troubleshooting

### "Display not found"

```bash
lsusb | grep 1a86
```

If you see `1a86:5722`, check:
- The udev rule is installed (`/etc/udev/rules.d/99-turing-display.rules`)
- The device appears as a TTY: `ls /dev/ttyACM*`
- Your user is in the `plugdev` group (re-login after adding)

### Garbled / scrambled display

- Try reducing the chunk size in `send_image()` (line 130 of `monitor.py`)
- Increase the inter-chunk delay (line 134)
- The CH552T has a small buffer — do not send data faster than ~30 KB/s
- Some displays expect BGR byte order in RGB565 — try swapping bytes in `_image_to_rgb565()`
- Disable hardware flow control (`rtscts=False`)

### No NVIDIA GPU stats

The monitor gracefully skips GPU stats when `nvidia-smi` is not available or returns no data.

### Permission denied on /dev/ttyACM0

```bash
sudo usermod -a -G dialout $USER
sudo usermod -a -G plugdev $USER
# Then log out and back in
```

If still denied, the udev rule may not have been triggered:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

---

## Architecture

```
┌──────────────┐     ┌──────────────────┐     ┌───────────────────┐
│  TuringDisplay│     │  SystemStats     │     │ DashboardRenderer │
│  (serial I/O) │     │  (/proc, smi)    │     │  (Pillow draw)    │
├──────────────┤     ├──────────────────┤     ├───────────────────┤
│ open/close   │     │ cpu_percent()    │     │ render(stats)     │
│ send_command │     │ ram()            │     │  → Image          │
│ send_image   │◄────│ disk()           │◄────│  → RGB565 bytes   │
│ reset/clear  │     │ net()            │     │                   │
│ set_bright…  │     │ disk_io()        │     │                   │
│ set_orient…  │     │ gpu_stats()      │     │                   │
└──────────────┘     └──────────────────┘     └───────────────────┘
```

- `SystemStats` reads all metrics from `/proc` and `nvidia-smi`
- `DashboardRenderer` composes a 480×320 image using Pillow
- `TuringDisplay` handles the USB serial protocol and sends RGB565 frames
- Main loop samples at ~10s intervals (2s network/IO sampling + render + ~5s actual display update)

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
