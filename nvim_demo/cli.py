"""Command line interface: nvim-demo record|check|keys."""

from __future__ import annotations

import argparse
import os
import shutil
import sys

from . import keys, scene as scenemod
from .recorder import Recorder, RecorderError
from .render import RenderError, render


def _human_size(path: str) -> str:
    try:
        size = os.path.getsize(path)
    except OSError:
        return "missing"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return "%d B" % value
            return "%.0f %s" % (value, unit)
        value /= 1024.0
    return "%d B" % size


def _summarize(scene: scenemod.Scene) -> None:
    print("scene:    %s" % scene.path)
    print("terminal: %dx%d" % (scene.cols, scene.rows))
    print("cwd:      %s" % scene.cwd_path)
    print("cast:     %s" % scene.cast_path)
    print("gif:      %s" % scene.out_path)
    if scene.keycast:
        print("keycast:  on (%d cells)" % scene.keycast_width)
    kinds = {}
    for step in scene.steps:
        kinds[step.kind] = kinds.get(step.kind, 0) + 1
    print("steps:    %s" % ", ".join("%d %s" % (n, k) for k, n in kinds.items()))


def cmd_record(args) -> int:
    scene = scenemod.load(args.scene)
    if args.cols or args.rows:
        cols = args.cols or scene.cols
        rows = args.rows or scene.rows
        scene.size = (cols, rows)
    _summarize(scene)

    recorder = Recorder(scene, verbose=args.verbose)
    try:
        recorder.run()
    except RecorderError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1

    print("recorded: %s (%s)" % (scene.cast_path, _human_size(scene.cast_path)))
    if args.no_render:
        return 0
    try:
        render(scene, verbose=args.verbose)
    except RenderError as exc:
        print("error: %s" % exc, file=sys.stderr)
        print("the cast was kept at %s" % scene.cast_path, file=sys.stderr)
        return 1
    print("rendered: %s (%s)" % (scene.out_path, _human_size(scene.out_path)))
    return 0


def cmd_check(args) -> int:
    scene = scenemod.load(args.scene)
    _summarize(scene)
    print("nvim:     %s" % (scene.nvim or os.environ.get("NVIM") or shutil.which("nvim") or "MISSING"))
    print("agg:      %s" % (shutil.which("agg") or "MISSING"))
    try:
        import pyte  # noqa: F401

        print("pyte:     available")
    except ImportError:
        print("pyte:     MISSING (needed for wait steps)")
    if scene.init_path:
        state = "ok" if os.path.isfile(scene.init_path) else "MISSING"
        print("init:     %s (%s)" % (scene.init_path, state))
    if not os.path.isdir(scene.cwd_path):
        print("cwd:      %s (MISSING)" % scene.cwd_path)
    return 0


def cmd_keys(args) -> int:
    try:
        encoded = keys.encode(args.keys)
    except keys.KeyError_ as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    print(encoded)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nvim-demo",
        description="Record scripted Neovim sessions to asciinema casts and GIFs.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record", help="record a scene and render it")
    record.add_argument("scene", help="scene file")
    record.add_argument("--no-render", action="store_true", help="keep only the cast")
    record.add_argument("--cols", type=int, help="override terminal columns")
    record.add_argument("--rows", type=int, help="override terminal rows")
    record.add_argument("-v", "--verbose", action="store_true")
    record.set_defaults(func=cmd_record)

    check = sub.add_parser("check", help="parse a scene and report the toolchain")
    check.add_argument("scene")
    check.set_defaults(func=cmd_check)

    keycmd = sub.add_parser("keys", help="print the bytes for key notation")
    keycmd.add_argument("keys")
    keycmd.set_defaults(func=cmd_keys)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except scenemod.SceneError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
