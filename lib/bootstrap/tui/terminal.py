from __future__ import annotations

import os
import signal
import sys
import termios
import tty
from contextlib import contextmanager
from typing import Iterator, TextIO


class TerminalError(RuntimeError):
    pass


@contextmanager
def raw_terminal(stream: TextIO = sys.stdin) -> Iterator[None]:
    if not stream.isatty():
        raise TerminalError("interactive mode requires a terminal")
    descriptor = stream.fileno()
    previous = termios.tcgetattr(descriptor)
    handlers = {name: signal.getsignal(name) for name in (signal.SIGINT, signal.SIGTERM)}

    def interrupt(_signum, _frame):
        raise KeyboardInterrupt

    try:
        for name in handlers:
            signal.signal(name, interrupt)
        tty.setraw(descriptor)
        sys.stdout.write("\x1b[?25l")
        sys.stdout.flush()
        yield
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)
        for name, handler in handlers.items():
            signal.signal(name, handler)
        sys.stdout.write("\x1b[?25h\x1b[0m\n")
        sys.stdout.flush()


def read_key(stream: TextIO = sys.stdin) -> str:
    first = os.read(stream.fileno(), 1)
    if first == b"\x1b":
        tail = os.read(stream.fileno(), 2)
        return {b"[A": "up", b"[B": "down", b"[C": "right", b"[D": "left"}.get(tail, "escape")
    if first in {b"\r", b"\n"}:
        return "enter"
    if first == b" ":
        return "space"
    if first == b"\x03":
        raise KeyboardInterrupt
    try:
        return first.decode()
    except UnicodeDecodeError:
        return ""
