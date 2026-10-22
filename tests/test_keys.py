import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nvim_demo import keys


class EncodeTest(unittest.TestCase):
    def test_control_and_special_keys(self):
        self.assertEqual(keys.encode("<C-t>"), b"\x14")
        self.assertEqual(keys.encode("<C-f>"), b"\x06")
        self.assertEqual(keys.encode("<CR>"), b"\r")
        self.assertEqual(keys.encode("<Esc>"), b"\x1b")
        self.assertEqual(keys.encode("<Tab>"), b"\t")
        self.assertEqual(keys.encode("<BS>"), b"\x7f")
        self.assertEqual(keys.encode("<Space>"), b" ")

    def test_literal_text_mixed_with_keys(self):
        self.assertEqual(keys.encode(":qa!<CR>"), b":qa!\r")
        self.assertEqual(keys.encode("ihello<Esc>"), b"ihello\x1b")

    def test_angle_bracket_literal(self):
        self.assertEqual(keys.encode("<lt>tag>"), b"<tag>")

    def test_meta_and_control_punctuation(self):
        self.assertEqual(keys.encode("<M-x>"), b"\x1bx")
        self.assertEqual(keys.encode("<C-[>"), b"\x1b")
        self.assertEqual(keys.encode("<C-\\>"), b"\x1c")
        self.assertEqual(keys.encode("<C-Space>"), b"\x00")
        self.assertEqual(keys.encode("<S-Tab>"), b"\x1b[Z")

    def test_unknown_key(self):
        with self.assertRaises(keys.KeyError_):
            keys.encode("<NotAKey>")

    def test_unterminated(self):
        with self.assertRaises(keys.KeyError_):
            keys.encode("<C-t")

    def test_tokens(self):
        self.assertEqual(keys.tokens(":w<CR>"), [":", "w", "<CR>"])
        self.assertEqual(keys.tokens("<C-f>x"), ["<C-f>", "x"])


if __name__ == "__main__":
    unittest.main()
