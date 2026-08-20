#!/usr/bin/env python3
"""Slender Man stalks your terminal.

A faceless tall figure appears at random spots in the dark, then slowly
grows and draws closer — glitching to new positions the way he does when
you look away — until he lunges at the screen in a full-frame jump scare
with a scream. Then it starts over.

Usage:
  python3 slenderman.py             # stalk forever until Ctrl+C
  python3 slenderman.py --once      # one approach + jump scare, then exit
  python3 slenderman.py --duration 8   # slower, longer approach (seconds)
  python3 slenderman.py --mute      # no sound
  python3 slenderman.py --no-color  # plain output

Ctrl+C quits and restores your terminal.
"""

import argparse
import random
import shutil
import signal
import subprocess
import sys
import threading
import time


def enable_windows_ansi():
    """Turn on ANSI escape processing in the classic Windows console host.

    Without this, cursor moves/colors print as raw escape junk on Windows
    (Windows Terminal already handles it; conhost.exe, still common on
    Windows 10, does not unless asked).
    """
    if sys.platform != "win32":
        return
    import ctypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
    mode = ctypes.c_uint32()
    if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING

BRIGHT_WHITE = "\033[97m"
WHITE = "\033[37m"
GRAY = "\033[90m"
RED = "\033[31m"
BRIGHT_RED = "\033[91m"
DIM = "\033[2m"
INVERSE = "\033[7m"
WHITE_BG = "\033[47m"
RESET = "\033[0m"

HOME = "\033[H"
CLEAR = "\033[2J\033[H"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
ALT_SCREEN_ON = "\033[?1049h"
ALT_SCREEN_OFF = "\033[?1049l"

# Slender Man silhouette: pale featureless head on top, long body with
# tendril-like arms hanging at the sides. HEAD_ROWS lines from the top are
# drawn bright white (the blank face); the rest is shadowy gray.
SLENDER = [
    "  ▄▄▄  ",
    "  ███  ",
    "  ███  ",
    "█ ███ █",
    "█ ███ █",
    "█ ███ █",
    "█ ███ █",
    "  ███  ",
    "  █ █  ",
    "  █ █  ",
    "  █ █  ",
]
HEAD_ROWS = 3

# Giant faceless head for the jump scare: white mass with dark eye hollows
# and a gaping dark maw. Scaled up to fill the screen.
SCARE_FACE = [
    "    ▄▄████████████▄▄    ",
    "  ▄██████████████████▄  ",
    " ████████████████████████ ",
    "████████████████████████████",
    "███████▀▀      ▀▀███████████",
    "██████            ██████████",
    "███████          ███████████",
    "█████████        ███████████",
    "███████████    █████████████",
    "████████████▄▄██████████████",
    "██████████████████████████",
    " ██████  ▄▄▄▄▄▄▄▄  ██████ ",
    "  █████ ██████████ █████  ",
    "   ████ ██▀▀▀▀▀▀██ ████   ",
    "    ▀██ █ █ █ █ ██ ██▀    ",
    "      ▀▀▀▀▀▀▀▀▀▀▀▀▀▀      ",
]

# macOS sounds. Distant murmurs during the approach, a scream at the lunge.
AMBIENT_SOUNDS = [
    ["afplay", "-r", "0.2", "/System/Library/Sounds/Submarine.aiff"],
    ["afplay", "-r", "0.25", "/System/Library/Sounds/Basso.aiff"],
    ["say", "-v", "Whisper", "he is here"],
    ["say", "-v", "Whisper", "don't look"],
]
SCREAM = ["say", "-v", "Jester",
          "[[pbas 88]] [[rate 300]] REEEEE AAAAHH hee hee hee haaaa"]


def term_size():
    cols, rows = shutil.get_terminal_size((80, 24))
    return cols, rows


def scale(lines, s):
    """Repeat each character s times across and each line s times down."""
    out = []
    for line in lines:
        wide = "".join(ch * s for ch in line)
        out.extend([wide] * s)
    return out


def play(cmd, mute):
    if mute:
        return
    if sys.platform == "darwin" and shutil.which(cmd[0]):
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        sys.stdout.write("\a")
        sys.stdout.flush()


class Screen:
    def __init__(self, use_color):
        self.out = sys.stdout
        self.use_color = use_color

    def blank(self, cols, rows):
        self.out.write(HOME + "\n".join(" " * cols for _ in range(rows)))
        self.out.flush()

    def paint(self, buf, colbuf, cols, rows):
        """Render a cell buffer (chars + per-cell color codes) at HOME."""
        lines = []
        for r in range(rows):
            if not self.use_color:
                lines.append("".join(buf[r]))
                continue
            parts = []
            cur = None
            for c in range(cols):
                ch = buf[r][c]
                code = colbuf[r][c] if ch != " " else None
                if code != cur:
                    parts.append(code if code else RESET)
                    cur = code
                parts.append(ch)
            if cur is not None:
                parts.append(RESET)
            lines.append("".join(parts))
        self.out.write(HOME + "\n".join(lines))
        self.out.flush()


def new_buffer(cols, rows):
    buf = [[" "] * cols for _ in range(rows)]
    colbuf = [[None] * cols for _ in range(rows)]
    return buf, colbuf


def add_static(buf, colbuf, cols, rows, amount):
    """Sprinkle faint background noise across empty cells."""
    chars = ".·:'"
    for _ in range(int(cols * rows * amount)):
        r = random.randrange(rows)
        c = random.randrange(cols)
        if buf[r][c] == " ":
            buf[r][c] = random.choice(chars)
            colbuf[r][c] = DIM


def blit_slender(buf, colbuf, cols, rows, cx, cy, s, body_color):
    """Draw the figure centered on (cx, cy) at scale s, clipped to screen."""
    fig = scale(SLENDER, s)
    fh = len(fig)
    fw = max(len(l) for l in fig)
    head_lines = HEAD_ROWS * s
    left = int(round(cx - fw / 2))
    top = int(round(cy - fh / 2))
    for r, line in enumerate(fig):
        y = top + r
        if y < 0 or y >= rows:
            continue
        color = BRIGHT_WHITE if r < head_lines else body_color
        for c, ch in enumerate(line):
            if ch == " ":
                continue
            x = left + c
            if 0 <= x < cols:
                buf[y][x] = ch
                colbuf[y][x] = color


def max_scale(cols, rows):
    fw = max(len(l) for l in SLENDER)
    fh = len(SLENDER)
    return max(1, int(min((cols * 0.55) / fw, (rows * 0.85) / fh)))


def size_at(t, s_max):
    return 1 + round(t * (s_max - 1))


def approach(screen, mute, duration):
    """Slender Man materializes far off and closes in, then lunges."""
    cols, rows = term_size()
    rows = max(rows - 1, 4)  # keep the last line clear so we never scroll
    s_max = max_scale(cols, rows)
    frame_dt = 0.12
    steps = max(12, int(duration / frame_dt))

    target_x = cols / 2
    target_y = rows * 0.52
    cur_x = random.uniform(cols * 0.15, cols * 0.85)
    cur_y = random.uniform(rows * 0.25, rows * 0.7)

    for i in range(steps):
        t = i / (steps - 1)
        s = size_at(t, s_max)
        body = GRAY

        # Glitch: he vanishes and reappears somewhere new (look-away effect).
        if 0.1 < t < 0.8 and random.random() < 0.12:
            screen.blank(cols, rows)
            play(random.choice(AMBIENT_SOUNDS), mute)
            time.sleep(random.uniform(0.15, 0.35))
            cur_x = random.uniform(cols * 0.12, cols * 0.88)
            cur_y = random.uniform(rows * 0.25, rows * 0.7)
        else:
            # Ease toward center; faster the closer he gets.
            pull = 0.12 + 0.25 * t
            cur_x += (target_x - cur_x) * pull
            cur_y += (target_y - cur_y) * pull

        # Occasional flicker as he nears.
        if t > 0.5 and random.random() < 0.18:
            body = DIM + WHITE

        buf, colbuf = new_buffer(cols, rows)
        add_static(buf, colbuf, cols, rows, 0.01 + 0.03 * t)
        blit_slender(buf, colbuf, cols, rows, cur_x, cur_y, s, body)
        screen.paint(buf, colbuf, cols, rows)

        if random.random() < 0.06:
            play(random.choice(AMBIENT_SOUNDS), mute)
        time.sleep(frame_dt * (1.0 - 0.5 * t))  # accelerates as he approaches

    jump_scare(screen, mute)


def jump_scare(screen, mute):
    cols, rows = term_size()
    rows = max(rows - 1, 4)
    fw = max(len(l) for l in SCARE_FACE)
    fh = len(SCARE_FACE)
    s = max(1, int(min(cols / fw, rows / fh)))
    face = scale(SCARE_FACE, s)
    fw2 = max(len(l) for l in face)
    left = max((cols - fw2) // 2, 0)
    top = max((rows - len(face)) // 2, 0)

    play(SCREAM, mute)

    def draw(color, invert=False):
        buf, colbuf = new_buffer(cols, rows)
        for r, line in enumerate(face):
            y = top + r
            if y >= rows:
                break
            for c, ch in enumerate(line):
                if ch == " ":
                    continue
                x = left + c
                if 0 <= x < cols:
                    buf[y][x] = ch
                    colbuf[y][x] = color
        screen.paint(buf, colbuf, cols, rows)

    for _ in range(4):
        # full white flash
        if screen.use_color:
            screen.out.write(HOME + "\n".join(WHITE_BG + " " * cols + RESET
                                              for _ in range(rows)))
            screen.out.flush()
        time.sleep(0.05)
        draw(INVERSE + BRIGHT_WHITE if screen.use_color else BRIGHT_WHITE)
        time.sleep(0.07)
        draw(BRIGHT_RED)
        time.sleep(0.06)

    draw(BRIGHT_WHITE)
    time.sleep(1.0)


def run(once, mute, duration, use_color):
    screen = Screen(use_color)
    old_int = signal.getsignal(signal.SIGINT)
    screen.out.write(ALT_SCREEN_ON + HIDE_CURSOR + CLEAR)
    try:
        while True:
            approach(screen, mute, duration)
            if once:
                break
            cols, rows = term_size()
            screen.blank(cols, max(rows - 1, 4))
            time.sleep(random.uniform(0.8, 1.8))  # uneasy calm before he returns
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGINT, old_int)
        screen.out.write(RESET + SHOW_CURSOR + ALT_SCREEN_OFF)
        screen.out.flush()


def main():
    parser = argparse.ArgumentParser(description="Slender Man stalks your terminal.")
    parser.add_argument("--once", action="store_true",
                        help="one approach + jump scare, then exit")
    parser.add_argument("--duration", type=float, default=6.0, metavar="SECONDS",
                        help="length of each approach (default: 6)")
    parser.add_argument("--mute", action="store_true", help="no sound")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    args = parser.parse_args()

    enable_windows_ansi()
    use_color = sys.stdout.isatty() and not args.no_color
    if not sys.stdout.isatty():
        print("slenderman needs an interactive terminal to run.", file=sys.stderr)
        return 1

    run(args.once, args.mute, max(args.duration, 1.0), use_color)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
