import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nvim_demo import scene as scenemod


class ParseTest(unittest.TestCase):
    def parse(self, text):
        return scenemod.parse(text, "/tmp/demo/scene.scene")

    def test_directives_and_steps(self):
        s = self.parse(
            "\n".join(
                [
                    "# a comment",
                    "size 90x24",
                    "init init.lua",
                    "rtp ..",
                    "rtp ~/other",
                    "cwd ..",
                    "out out/demo.gif",
                    "cast out/demo.cast",
                    "typespeed 60ms",
                    "hold 1.5s",
                    "keycast on",
                    "keycast-width 40",
                    "theme nord",
                    "renderer resvg",
                    "font-size 17",
                    "font-dir ~/Library/Fonts",
                    "caption Hello  ·  world",
                    "type :Locate files",
                    "key <CR>",
                    "sleep 250ms",
                    "wait Files",
                    "wait-no Loading",
                    "sh touch marker",
                ]
            )
        )
        self.assertEqual(s.size, (90, 24))
        self.assertEqual(s.init, "init.lua")
        self.assertEqual(s.rtp, ["..", "~/other"])
        self.assertEqual(s.typespeed, 0.06)
        self.assertEqual(s.hold, 1.5)
        self.assertTrue(s.keycast)
        self.assertEqual(s.keycast_width, 40)
        self.assertEqual(s.render["theme"], "nord")
        self.assertEqual(s.render["renderer"], "resvg")
        self.assertEqual(s.render["font-size"], 17)
        self.assertEqual(s.render["font-dir"], ["~/Library/Fonts"])
        kinds = [step.kind for step in s.steps]
        self.assertEqual(
            kinds, ["caption", "type", "key", "sleep", "wait", "wait_no", "sh"]
        )
        self.assertEqual(s.steps[0].value, "Hello  ·  world")
        self.assertEqual(s.steps[3].seconds, 0.25)

    def test_durations(self):
        self.assertEqual(scenemod.parse_duration("250ms"), 0.25)
        self.assertEqual(scenemod.parse_duration("1.5s"), 1.5)
        self.assertEqual(scenemod.parse_duration("2m"), 120.0)
        self.assertEqual(scenemod.parse_duration("2"), 2.0)
        with self.assertRaises(scenemod.SceneError):
            scenemod.parse_duration("soon")

    def test_type_escapes(self):
        s = self.parse("type a\\tb\\nc\\\\d")
        self.assertEqual(s.steps[0].value, "a\tb\rc\\d")

    def test_unknown_directive(self):
        with self.assertRaises(scenemod.SceneError):
            self.parse("nonsense 1")

    def test_invalid_renderer(self):
        with self.assertRaises(scenemod.SceneError):
            self.parse("renderer cairo\ntype hi")

    def test_invalid_keycast(self):
        with self.assertRaises(scenemod.SceneError):
            self.parse("keycast sometimes\ntype hi")
        with self.assertRaises(scenemod.SceneError):
            self.parse("keycast-width 4\ntype hi")

    def test_empty_scene_rejected(self):
        with self.assertRaises(scenemod.SceneError):
            self.parse("# nothing here")

    def test_finalize_relative_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "out"))
            scene_path = os.path.join(tmp, "demo.scene")
            with open(scene_path, "w", encoding="utf-8") as fh:
                fh.write("init init.lua\nout out/demo.gif\ntype hi\n")
            s = scenemod.load(scene_path)
            self.assertEqual(s.init_path, os.path.join(tmp, "init.lua"))
            self.assertEqual(s.out_path, os.path.join(tmp, "out", "demo.gif"))
            self.assertEqual(s.cast_path, os.path.join(tmp, "out", "demo.cast"))
            self.assertEqual(s.cwd_path, tmp)


if __name__ == "__main__":
    unittest.main()
