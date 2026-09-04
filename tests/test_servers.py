"""Both servers import independently and expose disjoint tool sets."""
import asyncio
import unittest


class ServerSplitTests(unittest.TestCase):
    def _tools(self, mcp):
        return {t.name for t in asyncio.run(mcp.list_tools())}

    def test_helix_server_has_no_katana_tools(self):
        from helix_mcp.server import mcp
        names = self._tools(mcp)
        self.assertIn("select_preset", names)
        self.assertFalse([n for n in names if n.startswith("katana_")], names)

    def test_katana_server_is_katana_only(self):
        from katana_mcp.server import mcp
        names = self._tools(mcp)
        self.assertIn("katana_read_panel", names)
        self.assertIn("katana_set_panel", names)
        self.assertTrue(all(n.startswith("katana_") for n in names), names)

    def test_no_cross_imports(self):
        import katana_mcp.server, katana_mcp.sysex, helix_mcp.server  # noqa: F401
        import sys
        self.assertFalse(any(m.startswith("helix_mcp") for m in sys.modules
                             if "katana" in m), "katana_mcp must not import helix_mcp")
        from pathlib import Path
        root = Path(__file__).resolve().parents[1] / "src"
        for f in (root / "katana_mcp").glob("*.py"):
            self.assertNotIn("helix_mcp", f.read_text(), f)
        for f in (root / "helix_mcp").glob("*.py"):
            self.assertNotIn("katana_mcp", f.read_text(), f)


if __name__ == "__main__":
    unittest.main()
