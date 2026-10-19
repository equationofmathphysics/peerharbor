#!/usr/bin/env python3
"""Synthetic RFB protocol fixture. This is NOT a Linux physical desktop.

The authenticated gateway passes a connected socket as stdin. This program never
binds or listens on a network or filesystem socket. RFB's None security is safe
only within that gateway-owned, already authenticated stream.
"""

import argparse
import json
import os
from pathlib import Path
import socket
import struct
import sys
import time

from PIL import Image, ImageDraw, ImageFont


WIDTH, HEIGHT = 800, 500
SERVER_PIXEL_FORMAT = struct.pack("!BBBBHHHBBB3x", 32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
MAX_BUFFER = 2 * 1024 * 1024


class Fixture:
    def __init__(self, sock, state_path, generation):
        self.sock = sock
        self.state_path = Path(state_path)
        self.generation = generation
        self.buffer = bytearray()
        self.pixel_format = SERVER_PIXEL_FORMAT
        self.revision = 0
        self.sent_revision = -1
        self.pending_request = None
        self.state = {
            "kind": "synthetic protocol fixture",
            "not_linux_physical_desktop": True,
            "generation": generation,
            "width": WIDTH,
            "height": HEIGHT,
            "connected": False,
            "typed_text": "",
            "held_keys": [],
            "button_mask": 0,
            "pointer_x": WIDTH // 2,
            "pointer_y": HEIGHT // 2,
            "click_count": 0,
            "key_events": 0,
            "pointer_events": 0,
            "clipboard_messages_ignored": 0,
            "framebuffer_updates": 0,
            "last_event": "started",
            "events": [],
        }
        self.save()

    def save(self):
        self.state["updated_at"] = time.time()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(self.state_path.name + ".tmp")
        # State is a test artifact and may contain typed test text.
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(self.state, output, indent=2)
            output.write("\n")
        os.replace(temporary, self.state_path)

    def record(self, description, redraw=True):
        self.state["last_event"] = description
        self.state["events"].append(description)
        self.state["events"] = self.state["events"][-80:]
        if redraw:
            self.revision += 1
        self.save()

    def receive_exact(self, count):
        result = bytearray()
        while len(result) < count:
            chunk = self.sock.recv(count - len(result))
            if not chunk:
                raise EOFError("peer closed")
            result.extend(chunk)
        return bytes(result)

    def send(self, payload):
        self.sock.settimeout(10)
        self.sock.sendall(payload)
        self.sock.settimeout(0.1)

    def handshake(self):
        self.sock.settimeout(10)
        self.sock.sendall(b"RFB 003.008\n")
        if self.receive_exact(12) != b"RFB 003.008\n":
            raise ValueError("only RFB 3.8 is supported")
        self.sock.sendall(b"\x01\x01")  # One security type: None, private fd only.
        if self.receive_exact(1) != b"\x01":
            raise ValueError("unsupported security type")
        self.sock.sendall(struct.pack("!I", 0))
        self.receive_exact(1)  # ClientInit shared flag.
        name = ("Synthetic protocol fixture | NOT Linux physical desktop | " + self.generation).encode()
        self.sock.sendall(struct.pack("!HH", WIDTH, HEIGHT) + SERVER_PIXEL_FORMAT + struct.pack("!I", len(name)) + name)
        self.sock.settimeout(0.1)
        self.state["connected"] = True
        self.record("RFB 3.8 initialized")

    @staticmethod
    def font(size):
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except OSError:
            return ImageFont.load_default()

    def render(self):
        image = Image.new("RGB", (WIDTH, HEIGHT), "#111827")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((18, 18, 782, 482), radius=18, fill="#19243b", outline="#3c5273", width=2)
        draw.text((38, 32), "SYNTHETIC PROTOCOL FIXTURE", font=self.font(27), fill="#77e3cf")
        draw.text((38, 74), "NOT a Linux physical desktop", font=self.font(22), fill="#ffcf86")
        draw.text((38, 112), "Generation: " + self.generation[:60], font=self.font(18), fill="#dbe7fa")
        draw.text((38, 146), "noVNC / RFB 3.8 / 800 x 500 / raw encoding", font=self.font(16), fill="#adc0dc")
        draw.rounded_rectangle((36, 192, 764, 332), radius=10, fill="#0c1424", outline="#5f7799", width=2)
        draw.text((52, 203), "Typed test keys", font=self.font(16), fill="#a1b3cf")
        lines = []
        for line in self.state["typed_text"][-180:].split("\n"):
            lines.extend([line[i:i + 51] for i in range(0, max(1, len(line)), 51)])
        draw.multiline_text((52, 235), "\n".join(lines[-3:]) or "Click here, then type a test message.", font=self.font(21), fill="#ffffff", spacing=6)
        draw.text((38, 353), "Pointer: ({}, {})   Clicks: {}   Buttons held: {}".format(self.state["pointer_x"], self.state["pointer_y"], self.state["click_count"], self.state["button_mask"]), font=self.font(17), fill="#dbe7fa")
        draw.text((38, 389), "Keys held: " + (", ".join(str(key) for key in self.state["held_keys"]) or "none"), font=self.font(17), fill="#dbe7fa")
        draw.text((38, 437), "Last event: " + self.state["last_event"][:70], font=self.font(15), fill="#adc0dc")
        x, y = self.state["pointer_x"], self.state["pointer_y"]
        color = "#ffb454" if self.state["button_mask"] else "#77e3cf"
        draw.ellipse((x - 9, y - 9, x + 9, y + 9), outline=color, width=3)
        draw.line((x - 14, y, x + 14, y), fill=color, width=1)
        draw.line((x, y - 14, x, y + 14), fill=color, width=1)
        return image

    def framebuffer(self):
        if self.pending_request is None:
            return
        incremental, x, y, width, height = self.pending_request
        if incremental and self.sent_revision == self.revision:
            return  # Hold the request; do not busy-loop empty updates.
        self.pending_request = None
        width, height = min(width, WIDTH - min(x, WIDTH)), min(height, HEIGHT - min(y, HEIGHT))
        if width <= 0 or height <= 0:
            self.send(struct.pack("!BBH", 0, 0, 0))
            return
        image = self.render().crop((x, y, x + width, y + height))
        _, _, big_endian, _, _, _, _, red, green, blue = struct.unpack("!BBBBHHHBBB3x", self.pixel_format)
        # Match the requested byte layout, especially noVNC's R0/G8/B16.
        rgb = image.tobytes()
        pixels = bytearray(width * height * 4)
        for channel, shift in enumerate((red, green, blue)):
            offset = 3 - shift // 8 if big_endian else shift // 8
            pixels[offset::4] = rgb[channel::3]
        header = struct.pack("!BBHHHHHi", 0, 0, 1, x, y, width, height, 0)
        self.send(header + pixels)
        self.sent_revision = self.revision
        self.state["framebuffer_updates"] += 1
        self.save()

    def parse_one(self):
        if not self.buffer:
            return False
        kind = self.buffer[0]
        fixed = {0: 20, 3: 10, 4: 8, 5: 6}
        if kind in fixed:
            size = fixed[kind]
        elif kind == 2:
            if len(self.buffer) < 4:
                return False
            count = struct.unpack_from("!H", self.buffer, 2)[0]
            if count > 256:
                raise ValueError("too many requested encodings")
            size = 4 + 4 * count
        elif kind == 6:
            if len(self.buffer) < 8:
                return False
            length = struct.unpack_from("!I", self.buffer, 4)[0]
            if length > 1024 * 1024:
                raise ValueError("clipboard payload rejected")
            size = 8 + length
        else:
            raise ValueError("unsupported client message: " + str(kind))
        if len(self.buffer) < size:
            return False
        packet = bytes(self.buffer[:size])
        del self.buffer[:size]
        if kind == 0:
            pixel_format = packet[4:20]
            bpp, depth, endian, true_color, rmax, gmax, bmax, red, green, blue = struct.unpack("!BBBBHHHBBB3x", pixel_format)
            if (bpp, depth, true_color, rmax, gmax, bmax) != (32, 24, 1, 255, 255, 255) or endian not in (0, 1) or sorted((red, green, blue)) != [0, 8, 16]:
                raise ValueError("unsupported pixel format; require 32 bpp, 24-bit RGB")
            self.pixel_format = pixel_format
            self.revision += 1
        elif kind == 2:
            self.state["requested_encodings"] = list(struct.unpack("!" + "i" * ((size - 4) // 4), packet[4:]))
            self.save()
        elif kind == 3:
            _, incremental, x, y, width, height = struct.unpack("!BBHHHH", packet)
            if self.pending_request and not self.pending_request[0]:
                incremental = False
            self.pending_request = (bool(incremental), x, y, width, height)
        elif kind == 4:
            _, down, keysym = struct.unpack("!BB2xI", packet)
            held = set(self.state["held_keys"])
            if down:
                held.add(keysym)
                if 32 <= keysym <= 126:
                    self.state["typed_text"] += chr(keysym)
                elif keysym == 0xFF0D:
                    self.state["typed_text"] += "\n"
                elif keysym == 0xFF08:
                    self.state["typed_text"] = self.state["typed_text"][:-1]
                elif keysym == 0xFF09:
                    self.state["typed_text"] += "    "
                self.state["typed_text"] = self.state["typed_text"][-2048:]
            else:
                held.discard(keysym)
            self.state["held_keys"] = sorted(held)
            self.state["key_events"] += 1
            self.record("key {} {}".format(keysym, "down" if down else "up"))
        elif kind == 5:
            _, mask, x, y = struct.unpack("!BBHH", packet)
            newly_pressed = mask & ~self.state["button_mask"]
            self.state["click_count"] += (newly_pressed & 7).bit_count()
            self.state["button_mask"] = mask
            self.state["pointer_x"] = min(x, WIDTH - 1)
            self.state["pointer_y"] = min(y, HEIGHT - 1)
            self.state["pointer_events"] += 1
            self.record("pointer {}, {} buttons {}".format(x, y, mask))
        elif kind == 6:
            self.state["clipboard_messages_ignored"] += 1
            self.record("clipboard ignored (disabled)", redraw=False)
        return True

    def run(self):
        self.handshake()
        print("synthetic protocol fixture ready; generation=" + self.generation, file=sys.stderr, flush=True)
        while True:
            try:
                chunk = self.sock.recv(65536)
                if not chunk:
                    return
                self.buffer.extend(chunk)
                if len(self.buffer) > MAX_BUFFER:
                    raise ValueError("input buffer limit exceeded")
                while self.parse_one():
                    pass
            except socket.timeout:
                pass
            self.framebuffer()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--generation", required=True)
    args = parser.parse_args()
    sock = socket.socket(fileno=os.dup(0))
    fixture = Fixture(sock, args.state, args.generation)
    try:
        fixture.run()
    except (EOFError, BrokenPipeError, ConnectionResetError) as exc:
        print("synthetic protocol fixture disconnected: " + str(exc), file=sys.stderr)
    except (ValueError, OSError) as exc:
        print("synthetic protocol fixture error: " + str(exc), file=sys.stderr)
        return 1
    finally:
        fixture.state["connected"] = False
        # Deliberately retain held inputs so gateway cleanup is observable.
        fixture.save()
        sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
