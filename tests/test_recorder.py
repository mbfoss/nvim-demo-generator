import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nvim_demo.recorder import Recorder, _INCOMPLETE_CSI_RE, _normalize_sgr


class SgrTest(unittest.TestCase):
    def test_colon_truecolor_becomes_semicolon(self):
        self.assertEqual(
            _normalize_sgr("\x1b[38:2:224:226:234m keys \x1b[m"),
            "\x1b[38;2;224;226;234m keys \x1b[m",
        )

    def test_regular_sgr_is_untouched(self):
        text = "\x1b[0;1m\x1b[48;2;20;22;27mok\x1b(B\x1b[m"
        self.assertEqual(_normalize_sgr(text), text)

    def test_split_csi_is_held_back(self):
        for tail in ("\x1b", "\x1b[", "\x1b[38", "\x1b[38:2:1"):
            m = _INCOMPLETE_CSI_RE.search("text" + tail)
            self.assertIsNotNone(m, tail)
            self.assertEqual(m.start(), 4)

    def test_complete_sequences_are_not_held_back(self):
        for text in ("\x1b[38:2:1:2:3m", "\x1b[2J\x1b[H", "\x1b(B"):
            self.assertIsNone(_INCOMPLETE_CSI_RE.search(text), text)


class KeycastTest(unittest.TestCase):
    def test_ticker_is_updated_before_multikey_step_is_sent(self):
        rec = Recorder(SimpleNamespace(keyspeed=0.0))
        calls = []
        rec._send = lambda data: calls.append(("send", data))
        rec._pump = lambda seconds: None
        rec._keycast_append = lambda unit: calls.append(("cast", unit))

        rec._key("<C-w>h")

        # The ticker RPC must not land between <C-w> and h: Neovim waits for
        # the rest of the window command, and the RPC would block until it
        # arrives, which never happens because h is sent after the RPC.
        self.assertEqual(
            calls,
            [
                ("cast", "<C-w>"),
                ("cast", "h"),
                ("send", b"\x17"),
                ("send", b"h"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
