#!/usr/bin/env python3
"""
Turing Smart Screen 3.5" USB System Monitor for Linux
Protocol: 6-byte command packets, RGB565 image data, 115200 baud
Display: 320x480 portrait (3.5" IPS)
"""

import sys
import os
import time
import math
import subprocess
import struct
import re
import glob
import logging
from typing import Optional

import serial
from serial.tools import list_ports
from PIL import Image, ImageDraw, ImageFont

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("turing-display")

CMD_RESET = 101
CMD_CLEAR = 102
CMD_SCREEN_OFF = 108
CMD_SCREEN_ON = 109
CMD_SET_BRIGHTNESS = 110
CMD_SET_ORIENTATION = 121
CMD_DISPLAY_BITMAP = 197

ORIENTATION_PORTRAIT = 0
ORIENTATION_LANDSCAPE = 2

DISPLAY_WIDTH = 320
DISPLAY_HEIGHT = 480
BAUD_RATE = 115200
VID = 0x1A86
PID = 0x5722
SERIAL_ID = "USB35INCHIPSV2"


class TuringDisplay:
    def __init__(self, port: str = "AUTO"):
        self.port = port
        self.ser: serial.Serial = None  # type: ignore[assignment]
        self.orientation = ORIENTATION_PORTRAIT

    def auto_detect_port(self) -> Optional[str]:
        for p in list_ports.comports():
            if p.serial_number == SERIAL_ID:
                return p.device
            if p.vid == VID and p.pid == PID:
                return p.device
        return None

    def open(self):
        if self.port == "AUTO":
            detected = self.auto_detect_port()
            if not detected:
                log.error("Display not found. Check USB connection and udev rules.")
                sys.exit(1)
            self.port = detected
            log.info(f"Auto-detected display on {self.port}")
        self.ser = serial.Serial(self.port, BAUD_RATE, timeout=2, rtscts=False)
        log.info(f"Connected to {self.port}")

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

    def _encode_coords(self, x0, y0, x1, y1):
        buf = bytearray(6)
        buf[0] = (x0 >> 2)
        buf[1] = (((x0 & 3) << 6) + (y0 >> 4))
        buf[2] = (((y0 & 15) << 4) + (x1 >> 6))
        buf[3] = (((x1 & 63) << 2) + (y1 >> 8))
        buf[4] = (y1 & 255)
        return buf

    def send_command(self, cmd: int, x: int = 0, y: int = 0, ex: int = 0, ey: int = 0):
        buf = self._encode_coords(x, y, ex, ey)
        buf[5] = cmd
        self.ser.write(bytes(buf))

    def reset(self):
        log.info("Resetting display...")
        self.send_command(CMD_RESET)
        self.close()
        time.sleep(5)
        self.open()

    def clear(self):
        self.set_orientation(ORIENTATION_PORTRAIT)
        self.send_command(CMD_CLEAR)
        time.sleep(0.1)
        self.set_orientation(ORIENTATION_PORTRAIT)

    def set_brightness(self, level: int):
        level = max(0, min(100, level))
        abs_level = int(255 - (level / 100) * 255)
        self.send_command(CMD_SET_BRIGHTNESS, abs_level)

    def set_orientation(self, orientation: int = ORIENTATION_PORTRAIT):
        self.orientation = orientation
        w, h = self._dimensions()
        buf = bytearray(16)
        buf[5] = CMD_SET_ORIENTATION
        buf[6] = orientation + 100
        buf[7] = (w >> 8) & 0xFF
        buf[8] = w & 0xFF
        buf[9] = (h >> 8) & 0xFF
        buf[10] = h & 0xFF
        self.ser.write(bytes(buf))

    def _dimensions(self):
        if self.orientation in (ORIENTATION_PORTRAIT, 1):
            return DISPLAY_WIDTH, DISPLAY_HEIGHT
        return DISPLAY_HEIGHT, DISPLAY_WIDTH

    def send_image(self, img: Image.Image):
        w, h = self._dimensions()
        if img.size != (w, h):
            img = img.resize((w, h))
        self.send_command(CMD_DISPLAY_BITMAP, 0, 0, w - 1, h - 1)
        time.sleep(0.01)
        rgb565 = self._image_to_rgb565(img)
        chunk_size = w * 2 * 8  # 8 rows
        for chunk in self._chunked(rgb565, chunk_size):
            self.ser.write(chunk)
            self.ser.flush()
            time.sleep(0.001)

    @staticmethod
    def _image_to_rgb565(img: Image.Image) -> bytes:
        pixels = img.convert("RGB").tobytes()
        result = bytearray(len(pixels) // 3 * 2)
        for i in range(len(pixels) // 3):
            r, g, b = pixels[i * 3], pixels[i * 3 + 1], pixels[i * 3 + 2]
            val = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            struct.pack_into("<H", result, i * 2, val)
        return bytes(result)

    @staticmethod
    def _chunked(data: bytes, n: int):
        return [data[i:i + n] for i in range(0, len(data), n)]

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()


class SystemStats:
    @staticmethod
    def hostname() -> str:
        try:
            return subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip()
        except Exception:
            return "unknown"

    @staticmethod
    def uptime() -> str:
        try:
            with open("/proc/uptime") as f:
                uptime_secs = float(f.read().split()[0])
            days = int(uptime_secs // 86400)
            hours = int((uptime_secs % 86400) // 3600)
            mins = int((uptime_secs % 3600) // 60)
            parts = []
            if days:
                parts.append(f"{days}d")
            parts.append(f"{hours}h")
            parts.append(f"{mins}m")
            return "".join(parts)
        except Exception:
            return "?"

    @staticmethod
    def cpu_percent() -> float:
        prev_idle = prev_total = 0
        try:
            with open("/proc/stat") as f:
                fields = f.readline().split()
            prev_idle = int(fields[4])
            prev_total = sum(int(v) for v in fields[1:])
        except Exception:
            return 0.0
        time.sleep(0.5)
        try:
            with open("/proc/stat") as f:
                fields = f.readline().split()
            idle = int(fields[4])
            total = sum(int(v) for v in fields[1:])
        except Exception:
            return 0.0
        delta_idle = idle - prev_idle
        delta_total = total - prev_total
        return 100.0 * (1.0 - delta_idle / delta_total) if delta_total else 0.0

    @staticmethod
    def cpu_temp() -> Optional[float]:
        for p in ["/sys/class/thermal/thermal_zone0/temp",
                   "/sys/class/hwmon/hwmon*/temp1_input"]:
            try:
                for f in glob.glob(p):
                    val = int(open(f).read().strip()) / 1000
                    return val
            except Exception:
                pass
        return None

    @staticmethod
    def ram() -> tuple:
        try:
            with open("/proc/meminfo") as f:
                d = {}
                for line in f:
                    parts = line.split()
                    d[parts[0].rstrip(":")] = int(parts[1])
            total = d.get("MemTotal", 1)
            avail = d.get("MemAvailable", total)
            used = total - avail
            return used / 1024, total / 1024, (used / total) * 100
        except Exception:
            return 0, 1, 0

    @staticmethod
    def disk() -> tuple:
        try:
            r = subprocess.run(["df", "-B1", "/"], capture_output=True, text=True)
            lines = r.stdout.strip().split("\n")[1:]
            used_k, total_k = 1, 1
            for line in lines:
                parts = line.split()
                if len(parts) >= 6:
                    total_b = int(parts[1])
                    used_b = int(parts[2])
                    total_k = total_b / 1024 / 1024
                    used_k = used_b / 1024 / 1024
            return used_k, total_k, (used_k / total_k) * 100
        except Exception:
            return 0, 1, 0

    @staticmethod
    def net() -> tuple:
        try:
            with open("/proc/net/dev") as f:
                lines = f.readlines()
            rx_total = tx_total = 0
            for line in lines[2:]:
                parts = line.split()
                if len(parts) >= 10:
                    rx_total += int(parts[1])
                    tx_total += int(parts[9])
            return rx_total, tx_total
        except Exception:
            return 0, 0

    @staticmethod
    def _root_dev() -> str:
        try:
            r = subprocess.run(["findmnt", "-n", "-o", "SOURCE", "/"],
                               capture_output=True, text=True, timeout=3)
            src = r.stdout.strip()
            kernel = os.path.basename(os.path.realpath(src))
            if kernel and not kernel.startswith("loop"):
                return kernel
        except Exception:
            pass
        for guess in ("sda", "nvme0n1", "vda", "mmcblk0", "sdb"):
            if os.path.exists(f"/sys/block/{guess}"):
                return guess
        return "sda"

    @staticmethod
    def disk_io() -> tuple:
        try:
            dev = SystemStats._root_dev()
            with open("/proc/diskstats") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 14 and parts[2] == dev:
                        return int(parts[5]), int(parts[9])
            return 0, 0
        except Exception:
            return 0, 0

    @staticmethod
    def gpu_stats() -> list:
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                                "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
            results = []
            for line in r.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split(", ")
                if len(parts) >= 4:
                    results.append({
                        "gpu_util": int(parts[0]),
                        "mem_used": int(parts[1]),
                        "mem_total": int(parts[2]),
                        "temp": int(parts[3]),
                    })
            return results
        except Exception:
            return []

    @staticmethod
    def load_avg() -> str:
        try:
            with open("/proc/loadavg") as f:
                parts = f.read().split()
                return f"{parts[0]} {parts[1]} {parts[2]}"
        except Exception:
            return "?"


class DashboardRenderer:
    def __init__(self, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT):
        self.width = width
        self.height = height
        self.font_path = self._find_font()

    @staticmethod
    def _find_font() -> str:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        log.warning("No font found, installing dejavu-fonts-ttf may be needed")
        return "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    def render(self, stats) -> Image.Image:
        W, H = self.width, self.height
        img = Image.new("RGB", (W, H), (18, 18, 28))
        draw = ImageDraw.Draw(img)

        try:
            font_pct = ImageFont.truetype(self.font_path, 28)
            font_md = ImageFont.truetype(self.font_path, 14)
            font_sm = ImageFont.truetype(self.font_path, 11)
            font_xs = ImageFont.truetype(self.font_path, 9)
        except Exception:
            font_pct = font_md = font_sm = font_xs = ImageFont.load_default()

        # --- Title bar ---
        hostname = stats.hostname().split(".")[0] if stats.hostname else "server"
        draw.rectangle([0, 0, W, 26], fill=(30, 40, 60))
        draw.text((W // 2, 13), hostname, fill=(180, 210, 255), font=font_sm, anchor="mm")
        draw.text((W - 6, 13), stats.uptime(), fill=(130, 150, 180), font=font_xs, anchor="rm")

        COL = W // 2
        cpu_pct = stats.cpu_percent()
        cpu_temp = stats.cpu_temp()
        gpus = stats.gpu_stats()
        ram_used, ram_total, ram_pct = stats.ram()
        disk_used, disk_total, disk_pct = stats.disk()
        load = stats.load_avg()

        rx1, tx1 = stats.net()
        io1 = stats.disk_io()
        time.sleep(2)
        rx2, tx2 = stats.net()
        io2 = stats.disk_io()
        rx_rate = (rx2 - rx1) / (2 * 1024)
        tx_rate = (tx2 - tx1) / (2 * 1024)
        dr_bytes = (io2[0] - io1[0]) * 512 / 2
        dw_bytes = (io2[1] - io1[1]) * 512 / 2

        def fmt_speed(kbps):
            if kbps >= 1024 * 1024:
                return f"{kbps / 1024 / 1024:.1f}G"
            elif kbps >= 1024:
                return f"{kbps / 1024:.1f}M"
            return f"{kbps:.0f}K"

        def row(cy, label, pct, detail, left, bar_fg):
            draw.text((left + 8, cy), label, fill=(255, 255, 255), font=font_md, anchor="la")
            draw.text((left + COL - 8, cy + 2), f"{pct:.0f}%", fill=(255, 255, 255), font=font_pct, anchor="ra")
            by = cy + 28
            bw = COL - 16
            draw.rounded_rectangle([left + 8, by, left + 8 + bw, by + 10], radius=3, fill=(40, 50, 70))
            fw = max(4, int(bw * min(pct, 100) / 100))
            draw.rounded_rectangle([left + 8, by, left + 8 + fw, by + 10], radius=3, fill=bar_fg)
            draw.text((left + 8, by + 14), detail, fill=(140, 155, 180), font=font_sm, anchor="la")

        def mini_bar(by, pct, fg_color, label):
            bw = W - 32
            draw.rounded_rectangle([16, by, 16 + bw, by + 6], radius=2, fill=(40, 50, 70))
            fw = max(4, int(bw * min(pct, 100) / 100))
            draw.rounded_rectangle([16, by, 16 + fw, by + 6], radius=2, fill=fg_color)
            draw.text((16, by + 8), label, fill=fg_color, font=font_sm)

        r = [38, 100, 162, 220]

        # Row 1: CPU + GPU
        row(r[0], "CPU", cpu_pct,
            f"{cpu_temp:.0f}°C  load {load}" if cpu_temp else f"load {load}",
            0, (60, 180, 120))
        if gpus:
            g = gpus[0]
            mem_pct = (g["mem_used"] / max(g["mem_total"], 1)) * 100
            row(r[0], "GPU", g["gpu_util"],
                f"{g['temp']}°C  VRAM {g['mem_used']}/{g['mem_total']}M ({mem_pct:.0f}%)",
                COL, (100, 160, 220))
        else:
            draw.text((COL + 8, r[0]), "GPU", fill=(255, 255, 255), font=font_md)
            draw.text((COL + 8, r[0] + 22), "NVIDIA driver not found", fill=(100, 110, 130), font=font_sm)

        # Row 2: RAM + DISK
        row(r[1], "RAM", ram_pct,
            f"{ram_used/1024:.1f}/{ram_total/1024:.1f} GiB",
            0, (220, 180, 60))
        row(r[1], "DISK", disk_pct,
            f"{disk_used:.1f}/{disk_total:.1f} GiB",
            COL, (80, 160, 200))

        # Row 3: DISK I/O (single bar, highest direction)
        dy = r[2]
        draw.rectangle([6, dy, W - 6, dy + 48], fill=(22, 24, 36), outline=(40, 50, 70))
        draw.text((16, dy + 6), "DISK I/O", fill=(255, 255, 255), font=font_md)
        max_bw = 500 * 1024 * 1024
        io_pct = max(dr_bytes, dw_bytes) / max_bw * 100
        by = dy + 24
        bw = W - 32
        draw.rounded_rectangle([16, by, 16 + bw, by + 10], radius=3, fill=(40, 50, 70))
        fw = max(4, int(bw * min(io_pct, 100) / 100))
        draw.rounded_rectangle([16, by, 16 + fw, by + 10], radius=3, fill=(60, 200, 100))
        draw.text((16, by + 14), f"R {fmt_speed(dr_bytes)}/s", fill=(60, 200, 100), font=font_sm)
        draw.text((COL + 16, by + 14), f"W {fmt_speed(dw_bytes)}/s", fill=(100, 180, 255), font=font_sm)

        # Row 4: NET full-width
        ny = r[3]
        draw.rectangle([6, ny, W - 6, ny + 48], fill=(22, 24, 36), outline=(40, 50, 70))
        draw.text((16, ny + 6), "NETWORK", fill=(255, 255, 255), font=font_md)
        draw.text((16, ny + 26), f"▼ {fmt_speed(rx_rate)}/s", fill=(60, 200, 100), font=font_md)
        draw.text((COL + 16, ny + 26), f"▲ {fmt_speed(tx_rate)}/s", fill=(100, 180, 255), font=font_md)
        draw.text((W - 16, ny + 6), f"rcvd {fmt_speed(rx1/1024)}", fill=(100, 120, 140), font=font_sm, anchor="ra")

        # Bottom bar
        now = time.strftime("%H:%M:%S")
        draw.rectangle([0, H - 22, W, H], fill=(30, 40, 60))
        draw.text((8, H - 11), now, fill=(100, 130, 160), font=font_sm, anchor="lm")

        return img

    @staticmethod
    def _draw_bar(draw, x, y, w, h, pct, color_fg, color_bg):
        draw.rounded_rectangle([x, y, x + w, y + h], radius=3, fill=color_bg)
        fill_w = max(4, int(w * (min(pct, 100) / 100)))
        draw.rounded_rectangle([x, y, x + fill_w, y + h], radius=3, fill=color_fg)


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "AUTO"
    renderer = DashboardRenderer(width=DISPLAY_HEIGHT, height=DISPLAY_WIDTH)

    while True:
        try:
            with TuringDisplay(port) as display:
                display.set_orientation(ORIENTATION_LANDSCAPE)
                time.sleep(0.5)
                display.set_brightness(60)
                time.sleep(0.3)
                display.send_command(CMD_CLEAR)
                time.sleep(0.3)

                log.info("Starting system monitor loop...")
                while True:
                    stats = SystemStats()
                    img = renderer.render(stats)
                    display.send_image(img)
        except serial.SerialException as e:
            log.error(f"Serial error: {e}. Reconnecting in 10s...")
        except Exception as e:
            log.error(f"Error: {e}")
        time.sleep(10)


if __name__ == "__main__":
    main()
