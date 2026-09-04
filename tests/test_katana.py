import unittest

from katana_mcp import sysex as k


class SysexTests(unittest.TestCase):
    def test_checksum_matches_hirsch_examples(self):
        # From katana_sysex.txt: set amp gain (00 00 04 21) to 0x32 -> checksum 0x29
        self.assertEqual(k.checksum([0x00, 0x00, 0x04, 0x21, 0x32]), 0x29)
        # editor mode on: 7F 00 00 01 01 -> 7F
        self.assertEqual(k.checksum([0x7F, 0x00, 0x00, 0x01, 0x01]), 0x7F)

    def test_build_dt1(self):
        body = k.build_dt1((0x00, 0x00, 0x04, 0x21), [0x32])
        self.assertEqual(body, [0x41, 0x00, 0x00, 0x00, 0x00, 0x33, 0x12,
                                0x00, 0x00, 0x04, 0x21, 0x32, 0x29])

    def test_build_rq1(self):
        body = k.build_rq1((0x60, 0x00, 0x00, 0x00), 16)
        self.assertEqual(body[6], k.RQ1)
        self.assertEqual(body[11:15], [0, 0, 0, 16])
        self.assertEqual(body[-1], k.checksum([0x60, 0, 0, 0, 0, 0, 0, 16]))

    def test_parse_dt1_roundtrip_and_reject(self):
        body = k.build_dt1((0x60, 0x00, 0x00, 0x00), b"Cumbia")
        d = k.parse_dt1(body)
        self.assertIsNotNone(d)
        self.assertEqual(d.address, (0x60, 0, 0, 0))
        self.assertEqual(d.data, b"Cumbia")
        body[-1] ^= 0x01  # corrupt checksum
        self.assertIsNone(k.parse_dt1(body))
        self.assertIsNone(k.parse_dt1([0x7E, 0x7F, 0x06, 0x02]))  # identity reply, not DT1

    def test_addr_math_7bit(self):
        self.assertEqual(k.addr_add((0x60, 0, 0, 0x7F), 1), (0x60, 0, 1, 0))
        self.assertEqual(k.addr_add((0x60, 0, 0x7F, 0x7F), 1), (0x60, 1, 0, 0))
        self.assertEqual(k.parse_addr("60 00 00 00"), (0x60, 0, 0, 0))
        self.assertEqual(k.parse_addr("60000451"), (0x60, 0, 0x04, 0x51))
        with self.assertRaises(ValueError):
            k.parse_addr("80 00 00 00")


class KatanaTests(unittest.TestCase):
    def setUp(self):
        self.fake = k.FakeKatana()
        self.kat = k.Katana(self.fake)
        self.fake.poke((0x60, 0, 0, 0), b"Cumbia Amazonica")
        self.fake.poke((0x60, 0x00, 0x06, 0x51), [20, 55, 50, 55, 65, 60])
        self.fake.poke((0x60, 0x00, 0x00, 0x21), [0x1D])
        self.fake.poke((0x60, 0x00, 0x00, 0x2C), [50])

    def test_read_patch_name(self):
        self.assertEqual(self.kat.get("patch_name"), "Cumbia Amazonica")

    def test_read_panel(self):
        self.assertEqual(self.kat.read_panel(), {
            "patch_name": "Cumbia Amazonica", "gain": 20, "volume": 55, "bass": 50,
            "middle": 55, "treble": 65, "presence": 60, "solo_level": 50, "amp_type": 0x1D})

    def test_read_auto_enables_editor_mode(self):
        self.assertFalse(self.kat.editor_mode)
        self.kat.get("gain")
        self.assertTrue(self.kat.editor_mode)
        self.assertEqual(self.fake.sent[0][7:12], [0x7F, 0, 0, 1, 1])

    def test_set_and_readback(self):
        self.kat.set("gain", 35)
        self.assertEqual(self.fake.sent[-1][7:12], [0x60, 0x00, 0x06, 0x51, 35])
        self.assertEqual(self.kat.get("gain"), 35)
        self.kat.set("solo_level", 60)
        self.assertEqual(self.kat.get("solo_level"), 60)
        with self.assertRaises(ValueError):
            self.kat.set("gain", 101)

    def test_editor_mode_and_channel(self):
        self.kat.set_editor_mode(True)
        self.assertEqual(self.fake.sent[-1][7:12], [0x7F, 0, 0, 1, 1])
        self.kat.select_channel("B2")
        self.assertEqual(self.fake.sent[-1][7:13], [0x00, 0x01, 0x00, 0x00, 0x00, 0x06])
        self.kat.select_channel("panel")
        self.assertEqual(self.fake.sent[-1][11:13], [0x00, 0x00])
        with self.assertRaises(ValueError):
            self.kat.select_channel("C9")

    def test_read_hex_dump(self):
        dump = self.kat.read_hex((0x60, 0, 0, 0), 16)
        self.assertIn("Cumbia Amazonica", dump)
        self.assertTrue(dump.startswith("60 00 00 00"))

    def test_multi_chunk_read(self):
        # 40 bytes spanning several 16-byte lines
        self.fake.poke((0x60, 0, 0, 0x10), bytes(range(40)))
        self.assertEqual(self.kat.read((0x60, 0, 0, 0x10), 40), bytes(range(40)))


if __name__ == "__main__":
    unittest.main()
