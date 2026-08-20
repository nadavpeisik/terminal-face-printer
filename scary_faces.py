#!/usr/bin/env python3
"""Print scary ASCII faces in your terminal.

Usage:
  python3 scary_faces.py            # animate: cycle faces w/ flashes, glitches,
                                    # and random jump scares, until Ctrl+C
  python3 scary_faces.py --interval 0.5   # slower cycling
  python3 scary_faces.py --calm     # animation without flash/glitch/jump scares
  python3 scary_faces.py --once     # print one random face and exit
  python3 scary_faces.py skull      # print a specific face and exit
  python3 scary_faces.py --all      # print every face and exit
  python3 scary_faces.py --list     # list face names
  python3 scary_faces.py --no-color # plain output
  python3 scary_faces.py --lock                  # Ctrl+C won't quit; type the
                                                 # password 'boo' to stop it
  python3 scary_faces.py --lock --password spell # set your own stop word

Escape hatches that no program can trap, in case you ever get stuck in
--lock mode: close the terminal window, or from another terminal run
`kill -9 <pid>` (find it with `pgrep -f scary_faces`).
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


if sys.platform == "win32":
    import winsound


def win_ambient_beep():
    """Windows has no afplay/say; approximate a creepy sound with beeps."""
    low = random.choice([70, 90, 120])
    for _ in range(random.randint(2, 4)):
        winsound.Beep(random.randint(low, low + 40), random.randint(120, 220))
        time.sleep(0.05)


def win_scream_beep():
    """Windows has no afplay/say; approximate the jump-scare scream."""
    for f in range(400, 1800, 90):
        winsound.Beep(f, 20)
    for f in (1200, 600, 1200, 600, 900):
        winsound.Beep(f, 70)


RED = "\033[31m"
BRIGHT_RED = "\033[91m"
WHITE = "\033[97m"
DIM = "\033[2m"
INVERSE = "\033[7m"
RED_BG = "\033[41m"
WHITE_BG = "\033[47m"
RESET = "\033[0m"

CLEAR = "\033[2J\033[H"          # clear screen, cursor to top-left
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
ALT_SCREEN_ON = "\033[?1049h"    # alternate screen buffer: restores your
ALT_SCREEN_OFF = "\033[?1049l"   # terminal contents when the program exits

GLITCH_CHARS = "▓▒░█▚▞#%@&$?!"

# macOS-only: system sounds slowed way down (-r), or whispered speech.
CREEPY_SOUNDS = [
    ["afplay", "-r", "0.3", "/System/Library/Sounds/Basso.aiff"],
    ["afplay", "-r", "0.25", "/System/Library/Sounds/Sosumi.aiff"],
    ["afplay", "-r", "0.2", "/System/Library/Sounds/Submarine.aiff"],
    ["say", "-v", "Whisper", "behind you"],
    ["say", "-v", "Whisper", "I see you"],
    ["say", "-v", "Whisper", "don't turn around"],
    ["say", "-v", "Bad News", "it is too late"],
    ["say", "-v", "Jester", "ha ha ha ha ha ha ha"],  # maniacal cackling voice
    ["say", "-v", "Jester", "-r", "120", "you cannot escape, ha ha ha ha"],
]

SOUND_GAP = 0.8  # seconds of silence between one sound ending and the next

# Deranged high-pitched cackling scream for jump scares: the Jester voice
# pushed way up in pitch ([[pbas]]) and sped up ([[rate]]).
JUMP_SCARE_SCREAM = ["say", "-v", "Jester",
                     "[[pbas 90]] [[rate 280]] Aeeee hee hee hee ha ha ha ha haaaaa"]


def play_scream() -> None:
    """Fire the jump-scare scream immediately, on top of whatever the
    background soundtrack is playing."""
    if sys.platform == "darwin" and shutil.which(JUMP_SCARE_SCREAM[0]):
        subprocess.Popen(JUMP_SCARE_SCREAM, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    elif sys.platform == "win32":
        threading.Thread(target=win_scream_beep, daemon=True).start()
    else:
        sys.stdout.write("\a")
        sys.stdout.flush()

_sound_bag = []  # shuffled copy of CREEPY_SOUNDS; refilled when empty
_last_sound = None


def next_sound():
    """Draw the next sound from a shuffled bag.

    Nothing repeats until every sound has played once; then the bag is
    reshuffled and refilled. A refilled bag never starts with the sound
    that just played (sounds are popped from the end, so index -1 plays
    first).
    """
    global _last_sound
    if not _sound_bag:
        _sound_bag.extend(random.sample(CREEPY_SOUNDS, len(CREEPY_SOUNDS)))
        if len(_sound_bag) > 1 and _sound_bag[-1] == _last_sound:
            _sound_bag[0], _sound_bag[-1] = _sound_bag[-1], _sound_bag[0]
    cmd = _sound_bag.pop()
    _last_sound = cmd
    return cmd


def sound_loop(stop: threading.Event, pause: threading.Event = None) -> None:
    """Play creepy sounds back to back until `stop` is set.

    Each sound plays to completion, then SOUND_GAP seconds of silence,
    then the next one starts. Runs in a background thread so the visuals
    never stutter. While `pause` is set, no new sounds start (used to
    quiet things during the password prompt).
    """
    while not stop.is_set():
        if pause is not None and pause.is_set():
            if stop.wait(0.1):
                return
            continue
        cmd = next_sound()
        if sys.platform == "darwin" and shutil.which(cmd[0]):
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
            while proc.poll() is None:
                if stop.wait(0.1):
                    proc.terminate()
                    return
        elif sys.platform == "win32":
            win_ambient_beep()
        else:
            sys.stdout.write("\a")
            sys.stdout.flush()
            if stop.wait(2.0):  # bells have no duration; approximate one
                return
        if stop.wait(SOUND_GAP):
            return

FACES = {
    "skull": r"""
       .ed$$$eee..
     .d$$$$$$$$$$$$$$be.
    d$$$$$$$$$$$$$$$$$$$b
   d$$$$$$$$$$$$$$$$$$$$$b
  d$$$*"    "$$$"    "*$$$b
 4$$$P        $        $$$$L
 $$$$    @    $    @    $$$$
 $$$$b       d$b       d$$$$
 *$$$$$eeeed$$$$$eeee$$$$$$*
  "$$$$$$$$$$$$$$$$$$$$$$"
    "$$$$$ $ $ $ $ $$$$P"
      "*$$$$$$$$$$$$P"
          ""******""
""",
    "demon": r"""
        \        /
         \  /\  /
          \/  \/
      .-'''''''''-.
     /  .-.   .-.  \
    |  ( O )-( O )  |
    |   '-'   '-'   |
    |    .-'''-.    |
     \  ( VVVVV )  /
      \  '-...-'  /
       '-._____.-'
""",
    "ghost": r"""
       .-''''''-.
      /  _    _  \
     |  (o)  (o)  |
     |      >     |
     |   ______   |
     |  (      )  |
      \  '----'  /
       |        |
       |  |  |  |
       '--'  '--'
""",
    "wraith": r"""
     ▄▄▄▄▄▄▄▄▄▄▄▄▄
    ██░░░░░░░░░░░██
   ██░░▄▄░░░░░▄▄░░██
   ██░█░░█░░░█░░█░██
   ██░░▀▀░░░░░▀▀░░██
    ██░░░▄███▄░░░██
     ██░█▀░░░▀█░██
      ██░░░░░░░██
       ▀█▄▄▄▄▄█▀
""",
    "clown": r"""
        .-''''''-.
      .'  ______  '.
     /  .-'    '-.  \
    | /   .-,,-.   \ |
    | |  ( x  x )  | |
    | |    /__\    | |
    |  \  |    |  /  |
     \  '.\'--'/.'  /
      '.  '-..-'  .'
        '-......-'
""",
}


def face_lines(name: str) -> list:
    lines = [line.rstrip() for line in FACES[name].strip("\n").split("\n")]
    margin = min(len(line) - len(line.lstrip()) for line in lines if line)
    return [line[margin:] for line in lines]


def scale(lines: list, sx: int, sy: int) -> list:
    """Upscale character art: repeat each char sx times, each line sy times."""
    out = []
    for line in lines:
        widened = "".join(ch * sx for ch in line)
        out.extend([widened] * sy)
    return out


def fit_scale(lines: list, frac: float) -> int:
    """Biggest uniform scale that keeps the art within `frac` of the terminal.

    The faces are drawn to look right on a 1:1 character grid, so width
    and height must scale together or they stretch.
    """
    cols, rows = shutil.get_terminal_size()
    width = max(len(line) for line in lines)
    height = len(lines)
    return max(1, min(int(cols * frac) // width, int(rows * frac) // height))


def center(lines: list) -> list:
    cols, rows = shutil.get_terminal_size()
    width = max(len(line) for line in lines)
    pad_left = max((cols - width) // 2, 0)
    pad_top = max((rows - len(lines)) // 2, 0)
    return [""] * pad_top + [" " * pad_left + line for line in lines]


def corrupt(lines: list, use_color: bool, frame_color: str, rate: float = 0.08) -> list:
    """Randomly replace characters with glitch noise and tear lines sideways."""
    out = []
    for line in lines:
        shift = random.randint(-3, 3)
        line = " " * shift + line if shift > 0 else line[-shift:]
        chars = []
        for ch in line:
            if ch != " " and random.random() < rate:
                glitch = random.choice(GLITCH_CHARS)
                if use_color:
                    chars.append(random.choice([WHITE, RED, DIM]) + glitch + frame_color)
                else:
                    chars.append(glitch)
            else:
                chars.append(ch)
        out.append("".join(chars))
    return out


class Screen:
    def __init__(self, use_color: bool):
        self.out = sys.stdout
        self.use_color = use_color

    def draw(self, lines: list, color: str = BRIGHT_RED) -> None:
        body = "\n".join(lines)
        if self.use_color:
            body = f"{color}{body}{RESET}"
        self.out.write(CLEAR + body)
        self.out.flush()

    def fill(self, color_bg: str, hold: float) -> None:
        """Flash the whole screen as a solid color."""
        cols, rows = shutil.get_terminal_size()
        if self.use_color:
            block = f"{color_bg}{' ' * cols}{RESET}"
        else:
            block = "█" * cols
        self.out.write(CLEAR + "\n".join([block] * rows))
        self.out.flush()
        time.sleep(hold)

    def draw_face(self, name: str, frac: float, color: str,
                  glitched: bool = False) -> None:
        lines = face_lines(name)
        s = fit_scale(lines, frac)
        lines = center(scale(lines, s, s))
        if glitched:
            lines = corrupt(lines, self.use_color, color)
        self.draw(lines, color)


def jump_scare(screen: Screen, name: str, mute: bool) -> None:
    """Zoom a face from small to full screen, then strobe it."""
    if not mute:
        play_scream()
    lines = face_lines(name)
    max_s = fit_scale(lines, 0.95)
    for s in range(1, max_s + 1):
        screen.draw(center(scale(lines, s, s)), WHITE)
        time.sleep(0.03)
    full = center(scale(lines, max_s, max_s))
    for _ in range(3):
        screen.fill(WHITE_BG, 0.05)
        screen.draw(full, INVERSE + BRIGHT_RED if screen.use_color else BRIGHT_RED)
        time.sleep(0.07)
    screen.draw(full, BRIGHT_RED)
    time.sleep(0.6)


# Set by the signal handler when the user tries to quit a locked session;
# the animation loop notices it and shows the password gate.
_prompt_flag = threading.Event()


def _request_prompt(signum, frame) -> None:
    """Signal handler for --lock: don't die, just ask for the password."""
    _prompt_flag.set()


def banish_prompt(screen: "Screen", password: str) -> bool:
    """Show the password gate. Return True only if the right word is typed."""
    screen.out.write(SHOW_CURSOR + CLEAR)
    lines = [
        "",
        "   T H E   F A C E S   W I L L   N O T   R E S T",
        "",
        "   Speak the word of banishing to make them stop.",
        "   (Ctrl+C and Ctrl+Z will not save you.)",
        "",
        "   > ",
    ]
    body = "\n".join(lines)
    if screen.use_color:
        body = BRIGHT_RED + body + RESET
    screen.out.write(body)
    screen.out.flush()
    try:
        answer = input()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    screen.out.write(HIDE_CURSOR)
    screen.out.flush()
    return answer.strip() == password


def animate(interval: float, use_color: bool, calm: bool, mute: bool,
            lock_password: str = None) -> None:
    """Cycle faces with flashes, glitches, and jump scares.

    Normally Ctrl+C quits. If `lock_password` is set, Ctrl+C and Ctrl+Z
    instead raise a password gate, and only the correct word stops it.
    """
    names = list(FACES)
    previous = None
    frames_since_scare = 0
    screen = Screen(use_color)
    stop_sounds = threading.Event()
    pause_sounds = threading.Event()
    player = None
    if not mute and not calm:
        player = threading.Thread(target=sound_loop,
                                  args=(stop_sounds, pause_sounds), daemon=True)
        player.start()

    locked = lock_password is not None
    old_handlers = {}
    if locked:
        _prompt_flag.clear()
        old_handlers[signal.SIGINT] = signal.signal(signal.SIGINT, _request_prompt)
        if hasattr(signal, "SIGTSTP"):
            try:
                old_handlers[signal.SIGTSTP] = signal.signal(
                    signal.SIGTSTP, _request_prompt)
            except (ValueError, OSError):
                pass

    screen.out.write(ALT_SCREEN_ON + HIDE_CURSOR)
    try:
        while True:
            if locked and _prompt_flag.is_set():
                _prompt_flag.clear()
                pause_sounds.set()
                unlocked = banish_prompt(screen, lock_password)
                pause_sounds.clear()
                if unlocked:
                    break
                continue

            name = random.choice([n for n in names if n != previous])
            previous = name
            frames_since_scare += 1

            if not calm and frames_since_scare > 8 and random.random() < 0.12:
                jump_scare(screen, name, mute)
                frames_since_scare = 0
                continue

            if not calm and random.random() < 0.15:
                screen.fill(RED_BG, 0.04)

            if not calm and random.random() < 0.35:
                screen.draw_face(name, 0.75, WHITE, glitched=True)
                time.sleep(0.06)

            color = random.choices([BRIGHT_RED, RED, WHITE], weights=[6, 2, 1])[0]
            screen.draw_face(name, 0.75, color)
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        stop_sounds.set()
        if player is not None:
            player.join(timeout=1.0)
        screen.out.write(RESET + SHOW_CURSOR + ALT_SCREEN_OFF)
        screen.out.flush()


def colorize(art: str, use_color: bool) -> str:
    if not use_color:
        return art
    return f"{BRIGHT_RED}{art}{RESET}"


def print_face(name: str, use_color: bool) -> None:
    label = f"{DIM}--- {name} ---{RESET}" if use_color else f"--- {name} ---"
    print(label)
    print(colorize(FACES[name], use_color))


def main() -> int:
    parser = argparse.ArgumentParser(description="Print scary ASCII faces.")
    parser.add_argument("name", nargs="?", help="face to print once (skips animation)")
    parser.add_argument("--once", action="store_true", help="print one random face and exit")
    parser.add_argument("--all", action="store_true", help="print every face and exit")
    parser.add_argument("--list", action="store_true", help="list available faces")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    parser.add_argument("--calm", action="store_true",
                        help="animate without flashes, glitches, or jump scares")
    parser.add_argument("--mute", action="store_true",
                        help="disable the creepy soundtrack")
    parser.add_argument("--lock", action="store_true",
                        help="require a password to quit (Ctrl+C / Ctrl+Z won't work)")
    parser.add_argument("--password", default="boo", metavar="WORD",
                        help="stop word for --lock mode (default: boo)")
    parser.add_argument(
        "--interval",
        type=float,
        default=0.2,
        metavar="SECONDS",
        help="seconds between faces when animating (default: 0.2)",
    )
    args = parser.parse_args()

    enable_windows_ansi()
    use_color = sys.stdout.isatty() and not args.no_color

    if args.list:
        print("\n".join(FACES))
        return 0

    if args.all:
        for name in FACES:
            print_face(name, use_color)
        return 0

    if args.name:
        if args.name not in FACES:
            print(f"unknown face: {args.name!r} (try --list)", file=sys.stderr)
            return 1
        print_face(args.name, use_color)
        return 0

    if args.once:
        print_face(random.choice(list(FACES)), use_color)
        return 0

    if not sys.stdout.isatty():
        print("not a terminal; printing one face instead of animating", file=sys.stderr)
        print_face(random.choice(list(FACES)), use_color)
        return 0

    animate(max(args.interval, 0.01), use_color, args.calm, args.mute,
            lock_password=args.password if args.lock else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
