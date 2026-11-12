"""A live one-line progress display for `evalkit run`, drawn on stderr when it is a terminal.

The bar fills with Claude's model calls against the step limit (max_steps in settings.json).
A run that finishes early stops short of full: the bar shows how much of the limit was used.
"""
import asyncio
import shutil
import sys
import time

SPINNER = "|/-\\"
BAR_WIDTH = 20


class Progress:
    def __init__(self, stream=None, enabled=None):
        self.stream = stream or sys.stderr
        self.enabled = _is_terminal(self.stream) if enabled is None else enabled
        self._task = None
        self._reset("", 0)

    def _reset(self, label, max_steps):
        self.label, self.max_steps = label, max_steps
        self.steps, self.calls, self.doing = 0, 0, "starting"
        self._started, self._frame = time.monotonic(), 0

    def start(self, label, max_steps):
        """A new run: `label` such as 'R21 run 1/3'."""
        self._reset(label, max_steps)
        if self.enabled:
            try:
                self._task = asyncio.get_running_loop().create_task(self._tick())
            except RuntimeError:  # no event loop: draw on events only
                self._task = None
        self.draw()

    def step(self, n):
        self.steps, self.doing = n, "Claude thinking"
        self.draw()

    def tool(self, name):
        self.calls += 1
        self.doing = f"calling {name}"
        self.draw()

    def judging(self):
        self.doing = "judge grading"
        self.draw()

    def extracting(self):
        self.doing = "reading EPs and numbers from the answer"
        self.draw()

    def stop(self):
        if self._task:
            self._task.cancel()
            self._task = None
        self.clear()

    def line(self):
        filled = round(BAR_WIDTH * min(self.steps, self.max_steps) / self.max_steps) if self.max_steps else 0
        bar = "█" * filled + "░" * (BAR_WIDTH - filled)
        secs = int(time.monotonic() - self._started)
        spin = SPINNER[self._frame % len(SPINNER)]
        calls = f"{self.calls} tool call{'' if self.calls == 1 else 's'}"
        return (f"  {spin} {self.label} [{bar}] step {self.steps}/{self.max_steps} · {calls} · "
                f"{self.doing} · {secs // 60}:{secs % 60:02d}")

    def draw(self):
        if not self.enabled:
            return
        width = _width()
        self.stream.write("\r" + self.line()[:width].ljust(width))
        self.stream.flush()

    def clear(self):
        if self.enabled:
            self.stream.write("\r" + " " * _width() + "\r")
            self.stream.flush()

    async def _tick(self):
        while True:  # keeps the clock and spinner moving while a model call is in flight
            await asyncio.sleep(0.25)
            self._frame += 1
            self.draw()


QUIET = Progress(enabled=False)


def _is_terminal(stream):
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


def _width():
    return max(40, shutil.get_terminal_size((100, 20)).columns - 1)
