"""Translate Vim-style key notation into bytes a terminal would send."""

from __future__ import annotations

from typing import List

# Keys whose byte sequence does not follow the generic patterns below.
_SPECIAL = {
    "cr": b"\r",
    "enter": b"\r",
    "return": b"\r",
    "lf": b"\n",
    "nl": b"\n",
    "tab": b"\t",
    "esc": b"\x1b",
    "escape": b"\x1b",
    "bs": b"\x7f",
    "backspace": b"\x7f",
    "space": b" ",
    "lt": b"<",
    "gt": b">",
    "bar": b"|",
    "bslash": b"\\",
    "nul": b"\x00",
    "del": b"\x1b[3~",
    "delete": b"\x1b[3~",
    "ins": b"\x1b[2~",
    "insert": b"\x1b[2~",
    "home": b"\x1b[H",
    "end": b"\x1b[F",
    "up": b"\x1b[A",
    "down": b"\x1b[B",
    "right": b"\x1b[C",
    "left": b"\x1b[D",
    "pageup": b"\x1b[5~",
    "pagedown": b"\x1b[6~",
    "f1": b"\x1bOP",
    "f2": b"\x1bOQ",
    "f3": b"\x1bOR",
    "f4": b"\x1bOS",
    "f5": b"\x1b[15~",
    "f6": b"\x1b[17~",
    "f7": b"\x1b[18~",
    "f8": b"\x1b[19~",
    "f9": b"\x1b[20~",
    "f10": b"\x1b[21~",
    "f11": b"\x1b[23~",
    "f12": b"\x1b[24~",
}

# Control characters for punctuation, by their ASCII value.
_CONTROL_BY_CHAR = {
    "@": 0,
    "[": 27,
    "\\": 28,
    "]": 29,
    "^": 30,
    "_": 31,
    "/": 31,
}


class KeyError_(ValueError):
    """An unparseable or unsupported key token."""


def _control(name: str) -> bytes:
    if name.lower() in ("space", "@"):
        return b"\x00"
    if len(name) != 1:
        raise KeyError_("unknown control key <C-%s>" % name)
    upper = name.upper()
    if "A" <= upper <= "Z":
        return bytes([ord(upper) - 64])
    if upper in _CONTROL_BY_CHAR:
        return bytes([_CONTROL_BY_CHAR[upper]])
    if name == "?":
        return b"\x7f"
    raise KeyError_("unknown control key <C-%s>" % name)


def _token(name: str) -> bytes:
    key = name.strip().lower()
    if not key:
        raise KeyError_("empty key token <>")

    # Modifiers are peeled off left to right, so <C-S-x> and <S-C-x> agree.
    if key.startswith("c-"):
        return _control(name.strip()[2:])
    if key.startswith("m-") or key.startswith("a-"):
        rest = name.strip()[2:]
        if rest.lower().startswith("c-"):
            return b"\x1b" + _control(rest[2:])
        if len(rest) == 1:
            return b"\x1b" + rest.encode("utf-8")
        return b"\x1b" + _token(rest)
    if key.startswith("s-"):
        rest = name.strip()[2:]
        if rest.lower() == "tab":
            return b"\x1b[Z"
        return rest.upper().encode("utf-8") if len(rest) == 1 else _token(rest)

    if key in _SPECIAL:
        return _SPECIAL[key]

    # A bare printable token such as <A> or <1> is just that character.
    if len(name) == 1:
        return name.encode("utf-8")

    raise KeyError_("unknown key <%s>" % name)


def tokens(keys: str) -> List[str]:
    """Split a key-notation string into top-level tokens.

    Each ``<...>`` group is one token; every other character is a token of its
    own, so callers can pace inputs one keystroke at a time.
    """
    out = []
    i = 0
    while i < len(keys):
        if keys[i] != "<":
            out.append(keys[i])
            i += 1
            continue
        close = keys.find(">", i + 1)
        if close == -1:
            raise KeyError_("unterminated key notation at %r" % keys[i:])
        out.append(keys[i : close + 1])
        i = close + 1
    return out


def encode(keys: str) -> bytes:
    """Return the terminal bytes for a Vim key-notation string.

    ``<C-t>``, ``<CR>`` and friends are expanded; every other character is sent
    literally. A literal ``<`` can be written as ``<lt>``.
    """
    out = bytearray()
    i = 0
    while i < len(keys):
        if keys[i] != "<":
            out.extend(keys[i].encode("utf-8"))
            i += 1
            continue
        close = keys.find(">", i + 1)
        if close == -1:
            raise KeyError_("unterminated key notation at %r" % keys[i:])
        out.extend(_token(keys[i + 1 : close]))
        i = close + 1
    return bytes(out)
