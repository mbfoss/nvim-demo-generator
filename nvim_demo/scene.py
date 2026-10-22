"""Parse the small scene language used to drive a recording.

A scene is a line-oriented script. Blank lines and lines whose first
non-space character is ``#`` are ignored. The first word selects a directive
or a step; the rest of the line is its argument, so text steps
(``type``, ``caption``) keep their spaces verbatim.

Directives
    size COLSxROWS          terminal size (default 100x33)
    nvim PATH               Neovim binary (default: $NVIM, else "nvim")
    init PATH               vimrc passed with -u
    rtp PATH                extra runtimepath entry (repeatable)
    cwd PATH                working directory (default: the scene's directory)
    out PATH                output GIF (default: <scene>.gif)
    cast PATH               output cast (default: <out>.cast)
    env NAME=VALUE          environment entry (repeatable)
    typespeed DURATION      pause after each typed character (default 45ms)
    keyspeed DURATION       pause after each key-notation token (default 30ms)
    settle DURATION         quiet period that marks startup complete (default 150ms)
    wait-timeout DURATION   default timeout for `wait` (default 5s)
    hold DURATION           extra hold after the last step (default 1s)
    keycast on|off          show typed keys in a ticker above the statusline
                            (default off; needs the Lua helper)
    keycast-width N         fixed ticker width in cells (default 15)

Render directives (passed to agg; agg's defaults apply when omitted, except
renderer, which defaults to resvg)
    font-family NAME        font family installed on the system
    font-dir PATH           directory to load fonts from (repeatable)
    font-size PX
    line-height RATIO       >= 1.0
    theme VALUE             an agg theme name (nord, dracula, github-dark, ...)
    renderer BACKEND        swash or resvg (default: resvg)
    fps N                   frame-rate cap
    idle-time-limit SEC
    last-frame-duration SEC
    speed FACTOR

Steps
    caption TEXT            show TEXT in the tabline (needs nvim-demo's Lua helper)
    type TEXT               send TEXT one character at a time
    key KEYS                send Vim key notation, e.g. <C-f> or :qa!<CR>
    sleep DURATION          wait; output keeps being captured
    wait REGEX              wait until the regex matches the rendered screen
    wait-no REGEX           wait until the regex matches nothing on screen
    sh COMMAND              run a shell command between steps
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


class SceneError(ValueError):
    """A malformed scene file."""


@dataclass
class Step:
    kind: str  # caption | type | key | sleep | wait | sh
    value: str = ""
    seconds: float = 0.0
    line: int = 0


@dataclass
class Scene:
    path: str
    size: tuple = (100, 33)
    nvim: Optional[str] = None
    init: Optional[str] = None
    rtp: List[str] = field(default_factory=list)
    cwd: Optional[str] = None
    out: Optional[str] = None
    cast: Optional[str] = None
    env: Dict[str, str] = field(default_factory=dict)
    typespeed: float = 0.045
    keyspeed: float = 0.030
    settle: float = 0.150
    wait_timeout: float = 5.0
    hold: float = 1.0
    keycast: bool = False
    keycast_width: int = 15
    render: Dict[str, object] = field(default_factory=dict)
    steps: List[Step] = field(default_factory=list)

    # Filled in by finalize(), all absolute paths.
    scene_dir: str = ""
    init_path: Optional[str] = None
    cwd_path: str = ""
    out_path: str = ""
    cast_path: str = ""
    rtp_paths: List[str] = field(default_factory=list)

    @property
    def cols(self) -> int:
        return self.size[0]

    @property
    def rows(self) -> int:
        return self.size[1]


_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ms|s|m)?\s*$")


def parse_duration(text: str, line: int = 0) -> float:
    """Parse "250ms", "1.5s", "2m" or a bare number of seconds."""
    m = _DURATION_RE.match(text)
    if not m:
        raise SceneError("line %d: not a duration: %r" % (line, text))
    value = float(m.group(1))
    unit = m.group(2) or "s"
    if unit == "ms":
        return value / 1000.0
    if unit == "m":
        return value * 60.0
    return value


def _split(line: str) -> tuple:
    """Split a line into its first word and the verbatim rest."""
    stripped = line.lstrip()
    if not stripped:
        return "", ""
    m = re.match(r"(\S+)(?:[ \t](.*))?$", stripped, re.S)
    assert m
    return m.group(1), (m.group(2) if m.group(2) is not None else "")


def _unescape(text: str) -> str:
    """Expand the backslash escapes accepted in `type` and `caption`."""
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch != "\\" or i + 1 >= len(text):
            out.append(ch)
            i += 1
            continue
        nxt = text[i + 1]
        mapping = {"n": "\r", "r": "\r", "t": "\t", "e": "\x1b", "\\": "\\", " ": " "}
        if nxt in mapping:
            out.append(mapping[nxt])
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _parse_size(text: str, line: int) -> tuple:
    m = re.match(r"^\s*(\d+)\s*[xX]\s*(\d+)\s*$", text)
    if not m:
        raise SceneError("line %d: size must be COLSxROWS" % line)
    cols, rows = int(m.group(1)), int(m.group(2))
    if cols < 20 or rows < 5:
        raise SceneError("line %d: terminal size is too small" % line)
    return (cols, rows)


def _render_value(key: str, arg: str, line: int):
    if key in ("font-size", "fps"):
        if not arg.isdigit():
            raise SceneError("line %d: %s wants an integer" % (line, key))
        return int(arg)
    if key in ("line-height", "idle-time-limit", "last-frame-duration", "speed"):
        try:
            return float(arg)
        except ValueError:
            raise SceneError("line %d: %s wants a number" % (line, key))
    return arg


_RENDER_KEYS = {
    "font-family",
    "font-dir",
    "font-size",
    "line-height",
    "theme",
    "renderer",
    "fps",
    "idle-time-limit",
    "last-frame-duration",
    "speed",
}

_RENDERERS = {"swash", "resvg"}


def parse(text: str, path: str = "<scene>") -> Scene:
    scene = Scene(path=path)
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        word, arg = _split(line)
        low = word.lower()

        if low == "size":
            scene.size = _parse_size(arg, lineno)
        elif low == "nvim":
            scene.nvim = arg.strip()
        elif low == "init":
            scene.init = arg.strip()
        elif low == "rtp":
            scene.rtp.append(arg.strip())
        elif low == "cwd":
            scene.cwd = arg.strip()
        elif low == "out":
            scene.out = arg.strip()
        elif low == "cast":
            scene.cast = arg.strip()
        elif low == "env":
            name, sep, value = arg.partition("=")
            if not sep or not name.strip():
                raise SceneError("line %d: env wants NAME=VALUE" % lineno)
            scene.env[name.strip()] = value
        elif low == "typespeed":
            scene.typespeed = parse_duration(arg, lineno)
        elif low == "keyspeed":
            scene.keyspeed = parse_duration(arg, lineno)
        elif low == "settle":
            scene.settle = parse_duration(arg, lineno)
        elif low == "wait-timeout":
            scene.wait_timeout = parse_duration(arg, lineno)
        elif low == "hold":
            scene.hold = parse_duration(arg, lineno)
        elif low == "keycast":
            value = arg.strip().lower()
            if value not in ("on", "off"):
                raise SceneError("line %d: keycast wants on or off" % lineno)
            scene.keycast = value == "on"
        elif low == "keycast-width":
            value = arg.strip()
            if not value.isdigit() or int(value) < 8:
                raise SceneError("line %d: keycast-width wants an integer >= 8" % lineno)
            scene.keycast_width = int(value)
        elif low in _RENDER_KEYS:
            if low == "font-dir":
                scene.render.setdefault("font-dir", []).append(arg.strip())
            elif low == "renderer":
                value = arg.strip()
                if value not in _RENDERERS:
                    raise SceneError(
                        "line %d: renderer must be one of: %s"
                        % (lineno, ", ".join(sorted(_RENDERERS)))
                    )
                scene.render[low] = value
            else:
                scene.render[low] = _render_value(low, arg.strip(), lineno)
        elif low == "caption":
            scene.steps.append(Step("caption", _unescape(arg), line=lineno))
        elif low == "type":
            scene.steps.append(Step("type", _unescape(arg), line=lineno))
        elif low == "key":
            scene.steps.append(Step("key", arg.strip(), line=lineno))
        elif low == "sleep":
            scene.steps.append(Step("sleep", arg.strip(), parse_duration(arg, lineno), lineno))
        elif low in ("wait", "wait-no"):
            if not arg.strip():
                raise SceneError("line %d: %s wants a pattern" % (lineno, low))
            kind = "wait" if low == "wait" else "wait_no"
            scene.steps.append(Step(kind, arg.strip(), line=lineno))
        elif low == "sh":
            if not arg.strip():
                raise SceneError("line %d: sh wants a command" % lineno)
            scene.steps.append(Step("sh", arg, line=lineno))
        else:
            raise SceneError("line %d: unknown directive %r" % (lineno, word))
    if not scene.steps:
        raise SceneError("scene has no steps")
    return scene


def finalize(scene: Scene, base_dir: Optional[str] = None) -> Scene:
    """Resolve all paths relative to the scene file's directory."""
    scene.scene_dir = base_dir or os.path.dirname(os.path.abspath(scene.path))

    def resolve(value: str) -> str:
        value = os.path.expanduser(os.path.expandvars(value))
        if not os.path.isabs(value):
            value = os.path.join(scene.scene_dir, value)
        return os.path.normpath(value)

    if scene.init:
        scene.init_path = resolve(scene.init)
    scene.rtp_paths = [resolve(p) for p in scene.rtp]
    scene.cwd_path = resolve(scene.cwd) if scene.cwd else scene.scene_dir

    default_out = os.path.splitext(os.path.abspath(scene.path))[0] + ".gif"
    scene.out_path = resolve(scene.out) if scene.out else default_out
    if scene.cast:
        scene.cast_path = resolve(scene.cast)
    else:
        scene.cast_path = os.path.splitext(scene.out_path)[0] + ".cast"
    return scene


def load(path: str) -> Scene:
    with open(path, "r", encoding="utf-8") as fh:
        scene = parse(fh.read(), path)
    return finalize(scene)
