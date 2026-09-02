import unittest

from helix_mcp import ccmap
from helix_mcp.midi import Helix, MemoryBackend


class CcMapTests(unittest.TestCase):
    def test_preset_names(self):
        self.assertEqual(ccmap.preset_to_program("01A"), 0)
        self.assertEqual(ccmap.preset_to_program("01D"), 3)
        self.assertEqual(ccmap.preset_to_program("12C"), 46)
        self.assertEqual(ccmap.preset_to_program("32D"), 127)
        self.assertEqual(ccmap.program_to_preset(46), "12C")
        for n in range(128):
            self.assertEqual(ccmap.preset_to_program(ccmap.program_to_preset(n)), n)

    def test_bad_preset(self):
        for bad in ("00A", "33A", "12E", "A", ""):
            with self.assertRaises(ValueError):
                ccmap.preset_to_program(bad)

    def test_fs_cc(self):
        self.assertEqual(ccmap.fs_cc(1), 49)
        self.assertEqual(ccmap.fs_cc(11), 59)
        with self.assertRaises(ValueError):
            ccmap.fs_cc(12)


class HelixTests(unittest.TestCase):
    def setUp(self):
        self.be = MemoryBackend()
        self.h = Helix(self.be, channel=1)

    def msgs(self):
        return [str(m) for m in self.be.sent]

    def test_select_preset_with_setlist(self):
        self.h.select_preset("12C", setlist=2)
        self.assertEqual(self.msgs(), ["CC0=0 ch1", "CC32=2 ch1", "PC46 ch1"])

    def test_select_preset_no_setlist(self):
        self.h.select_preset(5)
        self.assertEqual(self.msgs(), ["PC5 ch1"])

    def test_snapshot(self):
        self.h.select_snapshot(3)
        self.assertEqual(self.msgs(), ["CC69=2 ch1"])
        with self.assertRaises(ValueError):
            self.h.select_snapshot(9)

    def test_footswitch_and_expression(self):
        self.h.press_footswitch(4)
        self.h.expression_percent(1, 50)
        self.assertEqual(self.msgs(), ["CC52=127 ch1", "CC1=64 ch1"])

    def test_looper_and_global(self):
        self.h.looper("record")
        self.h.looper("stop")
        self.h.tap_tempo()
        self.h.tuner()
        self.assertEqual(self.msgs(), ["CC60=127 ch1", "CC61=0 ch1", "CC64=127 ch1", "CC68=127 ch1"])
        with self.assertRaises(ValueError):
            self.h.looper("dance")

    def test_channel(self):
        h = Helix(self.be, channel=5)
        h.pc(1)
        self.assertEqual(self.msgs(), ["PC1 ch5"])


if __name__ == "__main__":
    unittest.main()
