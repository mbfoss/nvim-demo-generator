"""Drive Neovim through a pseudoterminal and write an asciinema v2 cast."""

from __future__ import annotations

import codecs
import fcntl
import json
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import tempfile
import termios
import time
import unicodedata
from typing import List, Optional

from . import keys
from .scene import Scene

try:  # pyte is only needed for `wait` steps and screen dumps.
    import pyte
except ImportError:  # pragma: no cover - exercised by users without pyte
    pyte = None


class RecorderError(RuntimeError):
    """The session could not be recorded."""


TOOL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# How control characters appear in the keystroke ticker.
_CONTROL_DISPLAY = {
    "\r": "<CR>",
    "\n": "<CR>",
    "\t": "<Tab>",
    "\x1b": "<Esc>",
    "\x7f": "<BS>",
    "\x00": "<C-@>",
}


def _display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


# pyte's parser predates ITU T.416 colon-separated SGR parameters. Neovim
# emits truecolor as ``\x1b[38:2:R:G:Bm``, and pyte ends the sequence at the
# first colon, printing "2:R:G:Bm" as screen content. The semicolon form means
# the same thing, so rewrite colons before pyte sees the text.
_COLON_SGR_RE = re.compile(r"\x1b\[([0-9:;?]*)m")
# A CSI sequence that has not received its final byte yet, e.g. a read that
# splits ``\x1b[38:2:`` from the rest. Hold it back so the rewrite sees it whole.
_INCOMPLETE_CSI_RE = re.compile(r"\x1b(?:\[[0-9:;?]*)?$")


def _normalize_sgr(text: str) -> str:
    return _COLON_SGR_RE.sub(
        lambda m: "\x1b[" + m.group(1).replace(":", ";") + "m", text
    )


def _lua_long_bracket(text: str) -> str:
    level = 0
    while ("]" + "=" * level + "]") in text:
        level += 1
    eq = "=" * level
    return "[" + eq + "[" + text + "]" + eq + "]"


class Recorder:
    def __init__(self, scene: Scene, verbose: bool = False):
        self.scene = scene
        self.verbose = verbose
        self.master: Optional[int] = None
        self.proc: Optional[subprocess.Popen] = None
        self.screen = None
        self.stream = None
        self.decoder = None
        self.events: List[list] = []
        self.start = 0.0
        self.recording = False
        self.exited = False
        self.tmpdir: Optional[str] = None
        self.sock: Optional[str] = None
        self._socket_ready = False
        self.keycast_units: List[str] = []
        self.keycast_width = 0
        self._screen_pending = ""

    # -- process ---------------------------------------------------------

    def _nvim(self) -> str:
        return self.scene.nvim or os.environ.get("NVIM") or "nvim"

    def _spawn(self) -> None:
        if shutil.which(self._nvim()) is None:
            raise RecorderError("Neovim not found: %s" % self._nvim())
        if self.scene.init_path and not os.path.isfile(self.scene.init_path):
            raise RecorderError("init file not found: %s" % self.scene.init_path)
        if not os.path.isdir(self.scene.cwd_path):
            raise RecorderError("cwd not found: %s" % self.scene.cwd_path)

        self.tmpdir = tempfile.mkdtemp(prefix="nvim-demo-")
        self.sock = os.path.join(self.tmpdir, "nvim.sock")

        cmd = [self._nvim(), "--clean"]
        if self.scene.init_path:
            cmd += ["-u", self.scene.init_path]
        cmd += ["--listen", self.sock]
        cmd += ["--cmd", "lua vim.opt.rtp:prepend(vim.env.NVIM_DEMO_TOOL)"]
        for path in self.scene.rtp_paths:
            cmd += ["--cmd", "lua vim.opt.rtp:append(%s)" % _lua_long_bracket(path)]

        env = dict(os.environ)
        env.update(
            {
                "TERM": "xterm-256color",
                "COLORTERM": "truecolor",
                "NVIM_DEMO_TOOL": TOOL_ROOT,
                "LANG": env.get("LANG") or "en_US.UTF-8",
            }
        )
        env.update(self.scene.env)

        cols, rows = self.scene.size
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                env=env,
                cwd=self.scene.cwd_path,
                close_fds=True,
                start_new_session=True,
            )
        finally:
            os.close(slave)
        self.master = master

        self.screen = pyte.Screen(cols, rows) if pyte else None
        self.stream = pyte.Stream(self.screen) if pyte else None
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._screen_pending = ""

    def _feed_screen(self, text: str) -> None:
        """Feed decoded output to pyte, working around its SGR parser."""
        if self.stream is None or not text:
            return
        buf = self._screen_pending + text
        tail = _INCOMPLETE_CSI_RE.search(buf)
        if tail:
            buf, self._screen_pending = buf[: tail.start()], buf[tail.start():]
        else:
            self._screen_pending = ""
        if buf:
            self.stream.feed(_normalize_sgr(buf))

    def _consume(self, data: bytes) -> None:
        text = self.decoder.decode(data)
        if text:
            self._feed_screen(text)
            if self.recording:
                self.events.append([round(time.monotonic() - self.start, 6), "o", text])

    def _read_once(self, timeout: float) -> bool:
        if self.exited or self.master is None:
            return False
        try:
            readable, _, _ = select.select([self.master], [], [], timeout)
        except (OSError, ValueError):
            self.exited = True
            return False
        if not readable:
            return False
        try:
            data = os.read(self.master, 65536)
        except OSError:
            self.exited = True
            return False
        if not data:
            self.exited = True
            return False
        self._consume(data)
        return True

    def _pump(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self._read_once(min(0.05, remaining))

    def _send(self, data: bytes) -> None:
        if self.master is None:
            raise RecorderError("Neovim is not running")
        os.write(self.master, data)

    # -- startup ---------------------------------------------------------

    def _wait_for_startup(self) -> None:
        deadline = time.monotonic() + 6.0
        last_output = time.monotonic()
        saw_output = False
        while time.monotonic() < deadline:
            if self._read_once(0.02):
                saw_output = True
                last_output = time.monotonic()
            elif saw_output and time.monotonic() - last_output >= self.scene.settle:
                return
        if self.verbose:
            print("warning: startup did not settle; recording anyway")

    def _wait_for_socket(self) -> None:
        if not self.sock:
            return
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if os.path.exists(self.sock):
                self._socket_ready = True
                return
            self._pump(0.02)
        raise RecorderError("Neovim never created its RPC socket")

    def _begin_cast(self) -> None:
        self.events = []
        self.recording = False
        self.decoder.reset()
        self._screen_pending = ""
        # Start from a known blank screen, then make Neovim repaint all of it.
        blank = "\x1b[2J\x1b[H"
        self._feed_screen(blank)
        self.start = time.monotonic()
        self.events.append([0.0, "o", blank])
        self.recording = True
        self._send(b"\x0c")  # CTRL-L: full redraw
        self._pump(0.15)

    # -- RPC -------------------------------------------------------------

    def _rpc(self, expression: str) -> str:
        if not self._socket_ready:
            self._wait_for_socket()
        cmd = [self._nvim(), "--server", self.sock, "--remote-expr", expression]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RecorderError(
                "RPC failed (%s): %s" % (" ".join(cmd), (result.stderr or result.stdout).strip())
            )
        return result.stdout

    def _caption(self, text: str) -> None:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        expr = 'luaeval("require(\'nvim_demo\').caption(_A)", "%s")' % escaped
        self._rpc(expr)
        self._pump(0.03)

    def _keycast_append(self, unit: str) -> None:
        """Add one key to the ticker and push the new text to Neovim."""
        if not self.scene.keycast:
            return
        unit = _CONTROL_DISPLAY.get(unit, unit)
        # The float has a border, a one-cell pad on each side and a margin.
        limit = min(self.scene.keycast_width, max(8, self.scene.cols - 10))
        self.keycast_units.append(unit)
        self.keycast_width += _display_width(unit)
        while self.keycast_width > limit and len(self.keycast_units) > 1:
            self.keycast_width -= _display_width(self.keycast_units.pop(0))
        # Center the keys in the fixed width so the box does not grow.
        content = "".join(self.keycast_units)
        pad = max(0, limit - self.keycast_width)
        left = pad // 2
        text = " " * left + content + " " * (pad - left)
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        expr = 'luaeval("require(\'nvim_demo\').keys(_A)", "%s")' % escaped
        self._rpc(expr)

    # -- steps -----------------------------------------------------------

    def _screen_text(self) -> str:
        if self.screen is None:
            raise RecorderError("a `wait` step needs pyte: pip install pyte")
        return "\n".join(self.screen.display)

    def _wait_for(self, pattern: str, line: int, absent: bool = False) -> None:
        regex = re.compile(pattern)
        deadline = time.monotonic() + self.scene.wait_timeout
        while time.monotonic() < deadline:
            if bool(regex.search(self._screen_text())) != absent:
                return
            if self.exited:
                raise RecorderError(
                    "line %d: Neovim exited while waiting for %r" % (line, pattern)
                )
            self._read_once(0.05)
        tail = "\n".join(self._screen_text().splitlines()[-12:])
        raise RecorderError(
            "line %d: timed out waiting for %r to %s\n--- screen ---\n%s"
            % (line, pattern, "disappear" if absent else "appear", tail)
        )

    def _type(self, text: str) -> None:
        delay = max(self.scene.typespeed, 0.004)
        for ch in text:
            self._send(ch.encode("utf-8"))
            self._pump(delay)
            self._keycast_append(ch)

    def _key(self, text: str) -> None:
        delay = max(self.scene.keyspeed, 0.004)
        tokens = keys.tokens(text)
        # Update the ticker for the whole step before sending any key. A token
        # like <C-w> or the first g of gg leaves Neovim waiting for the rest of
        # a multi-key command; an RPC in that state blocks until the next key
        # arrives, and the next key is only sent once the RPC returns.
        for token in tokens:
            self._keycast_append(token)
        for token in tokens:
            self._send(keys.encode(token))
            self._pump(delay)

    def _shell(self, command: str, line: int) -> None:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=self.scene.cwd_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        while proc.poll() is None:
            self._pump(0.02)
        out = proc.communicate()[0] or ""
        if proc.returncode != 0:
            raise RecorderError(
                "line %d: shell command failed (%d): %s\n%s"
                % (line, proc.returncode, command, out.strip())
            )

    def _run_steps(self) -> None:
        for step in self.scene.steps:
            if step.kind == "caption":
                self._caption(step.value)
            elif step.kind == "type":
                self._type(step.value)
            elif step.kind == "key":
                self._key(step.value)
            elif step.kind == "sleep":
                self._pump(step.seconds)
            elif step.kind == "wait":
                self._wait_for(step.value, step.line)
            elif step.kind == "wait_no":
                self._wait_for(step.value, step.line, absent=True)
            elif step.kind == "sh":
                self._shell(step.value, step.line)
            else:  # pragma: no cover - parse() rejects these
                raise RecorderError("line %d: unknown step %r" % (step.line, step.kind))

    # -- cast ------------------------------------------------------------

    def _write_cast(self) -> None:
        if not self.events:
            return
        os.makedirs(os.path.dirname(self.scene.cast_path), exist_ok=True)
        header = {
            "version": 2,
            "width": self.scene.cols,
            "height": self.scene.rows,
            "timestamp": int(time.time()),
            "env": {"TERM": "xterm-256color", "SHELL": os.environ.get("SHELL", "/bin/sh")},
        }
        with open(self.scene.cast_path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(header, ensure_ascii=False) + "\n")
            for event in self.events:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _shutdown(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except OSError:
                pass
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except OSError:
                    pass
                self.proc.wait(timeout=2)
        if self.master is not None:
            try:
                os.close(self.master)
            except OSError:
                pass
            self.master = None
        if self.tmpdir:
            shutil.rmtree(self.tmpdir, ignore_errors=True)
            self.tmpdir = None

    # -- entry point -----------------------------------------------------

    def run(self) -> str:
        try:
            self._spawn()
            self._wait_for_startup()
            self._wait_for_socket()
            self._begin_cast()
            self._run_steps()
            self._pump(self.scene.hold)
            return self.scene.cast_path
        finally:
            self._write_cast()
            self._shutdown()
