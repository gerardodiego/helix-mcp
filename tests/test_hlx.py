import json
import tempfile
import unittest
from pathlib import Path

from helix_mcp.hlx import Catalog, Preset

SAMPLE = {
    "schema": "L6Preset",
    "version": 6,
    "meta": {"original": 0, "pbn": 0, "premium": 0},
    "data": {
        "device": 2162689,
        "device_version": 50659328,
        "meta": {"name": "Sample"},
        "tone": {
            "dsp0": {
                "block0": {"@model": "HD2_CompressorRochesterComp", "@enabled": True,
                           "@position": 0, "@type": 0, "@path": 0, "@stereo": False,
                           "Threshold": 0.5, "Ratio": 3, "Level": 0.5},
                "block1": {"@model": "HD2_AmpUSDoubleNrm", "@enabled": True,
                           "@position": 1, "@type": 3, "@path": 0, "@stereo": False,
                           "Drive": 0.4, "Bass": 0.5, "Mid": 0.5, "Treble": 0.6,
                           "ChVol": 0.6, "Master": 0.7},
                "block2": {"@model": "HD2_ReverbSpring", "@enabled": False,
                           "@position": 2, "@type": 7, "@path": 0, "@stereo": True,
                           "Decay": 0.3, "Mix": 0.2, "Level": 0.0},
                "inputA": {"@model": "HD2_AppDSPFlowInput", "@input": 1},
                "outputA": {"@model": "HD2_AppDSPFlowOutput", "@output": 1},
            },
            "dsp1": {},
            "controller": {"dsp0": {"block1": {"Drive": {"@controller": 9, "@min": 0.0, "@max": 1.0}}}},
            "global": {"@tempo": 120.0},
            "snapshot0": {"@name": "SNAPSHOT 1", "@tempo": 120.0,
                          "blocks": {"dsp0": {"block0": True, "block1": True, "block2": False}},
                          "controllers": {"dsp0": {"block1": {"Drive": {"@fs_enabled": False, "@value": 0.4}}}}},
            "snapshot1": {"@name": "SNAPSHOT 2", "@tempo": 120.0,
                          "blocks": {"dsp0": {"block0": True, "block1": True, "block2": True}},
                          "controllers": {"dsp0": {"block1": {"Drive": {"@fs_enabled": False, "@value": 0.4}}}}},
        },
    },
}


class PresetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sample.hlx"
        self.path.write_text(json.dumps(SAMPLE))
        self.p = Preset.load(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_blocks(self):
        models = [b.model for b in self.p.blocks()]
        self.assertEqual(models, ["HD2_CompressorRochesterComp", "HD2_AmpUSDoubleNrm", "HD2_ReverbSpring"])
        self.assertEqual([b.model for b in self.p.amp_blocks()], ["HD2_AmpUSDoubleNrm"])
        self.assertIn("HD2_ReverbSpring", self.p.summary())

    def test_set_param_propagates_to_snapshots(self):
        self.p.set_param("dsp0", "block1", "Drive", 0.9)
        snaps = self.p.snapshots()
        self.assertEqual(snaps[0]["controllers"]["dsp0"]["block1"]["Drive"]["@value"], 0.9)
        self.assertEqual(snaps[1]["controllers"]["dsp0"]["block1"]["Drive"]["@value"], 0.9)

    def test_unknown_param(self):
        with self.assertRaises(KeyError):
            self.p.set_param("dsp0", "block1", "Sparkle", 1)

    def test_enable_and_name_and_tempo(self):
        self.p.set_enabled("dsp0", "block2", True)
        self.assertTrue(self.p.snapshots()[0]["blocks"]["dsp0"]["block2"])
        self.p.name = "A very long preset name indeed"
        self.assertEqual(len(self.p.name), 16)
        self.p.tempo = 92
        self.assertEqual(self.p.snapshots()[1]["@tempo"], 92.0)

    def test_save_roundtrip(self):
        out = self.p.save(Path(self.tmp.name) / "gen" / "out.hlx")
        again = Preset.load(out)
        self.assertEqual(again.summary(), self.p.summary())

    def test_catalog(self):
        cat = Catalog()
        cat.add(self.p)
        self.assertEqual(len(cat.models), 3)
        self.assertEqual(set(cat.params_for("HD2_ReverbSpring")), {"Decay", "Mix", "Level"})
        self.assertEqual([m.model for m in cat.search("amp")], ["HD2_AmpUSDoubleNrm"])
        with self.assertRaises(KeyError):
            cat.params_for("HD2_Nope")

    def test_set_model_from_catalog(self):
        cat = Catalog()
        cat.add(self.p)
        self.p.set_model("dsp0", "block2", "HD2_CompressorRochesterComp",
                         cat.params_for("HD2_CompressorRochesterComp"))
        blk = self.p.block("dsp0", "block2")
        self.assertEqual(blk["@model"], "HD2_CompressorRochesterComp")
        self.assertEqual(blk["@position"], 2)
        self.assertIn("Threshold", blk)
        self.assertNotIn("Decay", blk)


if __name__ == "__main__":
    unittest.main()
