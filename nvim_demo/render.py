"""Render a recorded cast to GIF with asciinema's agg."""

from __future__ import annotations

import os
import shutil
import subprocess

from .scene import Scene


class RenderError(RuntimeError):
    """agg is missing or rejected the scene's render settings."""


# Options that take a value and may be given in a scene's render section.
_VALUE_OPTIONS = {
    "font-family": "--font-family",
    "font-size": "--font-size",
    "line-height": "--line-height",
    "theme": "--theme",
    "renderer": "--renderer",
    "fps": "--fps-cap",
    "idle-time-limit": "--idle-time-limit",
    "last-frame-duration": "--last-frame-duration",
    "speed": "--speed",
}


def command(scene: Scene, cast_path: str, out_path: str) -> list:
    agg = shutil.which("agg")
    if not agg:
        raise RenderError("agg is not on PATH (brew install agg)")

    cmd = [agg, "--quiet"]
    render = scene.render
    # agg's default swash backend leaves notches where rounded box-drawing
    # glyphs (╭╮╰╯) meet straight border segments; resvg draws them cleanly.
    cmd += ["--renderer", str(render.get("renderer", "resvg"))]
    for key, option in _VALUE_OPTIONS.items():
        if key != "renderer" and key in render:  # renderer is always set above
            cmd += [option, str(render[key])]
    for directory in render.get("font-dir", []):
        cmd += ["--font-dir", os.path.expanduser(directory)]
    cmd += [cast_path, out_path]
    return cmd


def render(scene: Scene, verbose: bool = False) -> str:
    os.makedirs(os.path.dirname(scene.out_path), exist_ok=True)
    cmd = command(scene, scene.cast_path, scene.out_path)
    if verbose:
        print("$ " + " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RenderError(
            "agg failed (%d): %s"
            % (result.returncode, (result.stderr or result.stdout).strip())
        )
    return scene.out_path
