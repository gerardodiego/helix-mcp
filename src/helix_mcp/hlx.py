"""Read, inspect, edit and write Line 6 Helix `.hlx` preset files.

A .hlx file is JSON ("schema": "L6Preset"). Rough shape (firmware 3.x):

    {
      "schema": "L6Preset", "version": 6,
      "meta": {...},
      "data": {
        "device": ..., "device_version": ...,
        "meta": {"name": "My Tone", ...},
        "tone": {
          "dsp0": { "block0": {"@model": "HD2_AmpUSDoubleNrm", "@enabled": true,
                                "@position": 2, "@type": 3, "@path": 0, "@stereo": false,
                                "Drive": 0.5, "Bass": 0.5, ...},
                    "block1": {...}, "inputA": {...}, "outputA": {...}, ... },
          "dsp1": {...},
          "controller": {"dsp0": {"block0": {"Drive": {"@controller": 9, "@min": 0, "@max": 1}}}},
          "global": {"@tempo": 120, "@topology0": "S", ...},
          "snapshot0": {"@name": "SNAPSHOT 1", "@ledcolor": 0, "@tempo": 120,
                         "blocks": {"dsp0": {"block0": true}},
                         "controllers": {"dsp0": {"block0": {"Drive": {"@fs_enabled": false, "@value": 0.5}}}}},
          ...
        }
      }
    }

Most parameters are normalised floats 0.0-1.0; some are booleans, enums (ints) or
real-world units (e.g. delay "Time" in seconds, "Mix" 0-1). The Catalog learns
model IDs and parameter names from reference presets exported from *your* Helix
so generated files match your firmware.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

BLOCK_RE = re.compile(r"^block\d+$")
DSPS = ("dsp0", "dsp1")

# Helix @type codes (from observed presets). Not exhaustive.
BLOCK_TYPES = {
    0: "dynamics",   # compressors / gates
    1: "distortion",
    2: "eq",
    3: "amp",
    4: "cab",
    5: "modulation",
    6: "pitch/synth",
    7: "delay/reverb",
    8: "wah",
    9: "volume/pan",
    10: "send/return",
    11: "looper",
    12: "filter",
}


@dataclass
class Block:
    dsp: str
    key: str
    model: str
    enabled: bool
    position: int
    btype: int | None
    params: dict[str, Any]

    @property
    def type_name(self) -> str:
        return BLOCK_TYPES.get(self.btype, f"type{self.btype}")


class Preset:
    """In-memory .hlx preset with convenience accessors."""

    def __init__(self, data: dict[str, Any], source: Path | None = None):
        if data.get("schema") != "L6Preset":
            raise ValueError("not a Helix preset (schema != L6Preset)")
        self.raw = data
        self.source = source

    # -- io --------------------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path) -> "Preset":
        p = Path(path)
        return cls(json.loads(p.read_text(encoding="utf-8")), p)

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        # HX Edit writes compact-ish JSON; indentation is accepted on import.
        p.write_text(json.dumps(self.raw, indent=1, ensure_ascii=False), encoding="utf-8")
        return p

    def copy(self) -> "Preset":
        return Preset(copy.deepcopy(self.raw), self.source)

    # -- meta ------------------------------------------------------------------
    @property
    def tone(self) -> dict[str, Any]:
        return self.raw["data"]["tone"]

    @property
    def name(self) -> str:
        return self.raw["data"].get("meta", {}).get("name", "")

    @name.setter
    def name(self, value: str) -> None:
        # Helix truncates names to 16 chars.
        self.raw["data"].setdefault("meta", {})["name"] = value[:16]

    @property
    def device_version(self) -> Any:
        return self.raw["data"].get("device_version")

    @property
    def tempo(self) -> float | None:
        return self.tone.get("global", {}).get("@tempo")

    @tempo.setter
    def tempo(self, bpm: float) -> None:
        self.tone.setdefault("global", {})["@tempo"] = float(bpm)
        for snap in self.snapshots():
            snap["@tempo"] = float(bpm)

    # -- blocks -----------------------------------------------------------------
    def blocks(self) -> Iterator[Block]:
        for dsp in DSPS:
            chain = self.tone.get(dsp, {})
            for key, blk in chain.items():
                if BLOCK_RE.match(key) and isinstance(blk, dict) and "@model" in blk:
                    params = {k: v for k, v in blk.items() if not k.startswith("@")}
                    yield Block(dsp, key, blk["@model"], bool(blk.get("@enabled", True)),
                                int(blk.get("@position", 0)), blk.get("@type"), params)

    def block(self, dsp: str, key: str) -> dict[str, Any]:
        try:
            return self.tone[dsp][key]
        except KeyError as e:
            raise KeyError(f"no block {dsp}/{key}") from e

    def find_blocks(self, model_substring: str) -> list[Block]:
        s = model_substring.lower()
        return [b for b in self.blocks() if s in b.model.lower()]

    def amp_blocks(self) -> list[Block]:
        return [b for b in self.blocks() if b.btype == 3 or "_Amp" in b.model]

    def set_enabled(self, dsp: str, key: str, enabled: bool, all_snapshots: bool = True) -> None:
        self.block(dsp, key)["@enabled"] = enabled
        if all_snapshots:
            for snap in self.snapshots():
                snap.setdefault("blocks", {}).setdefault(dsp, {})[key] = enabled

    def set_param(self, dsp: str, key: str, param: str, value: Any,
                  all_snapshots: bool = True) -> None:
        blk = self.block(dsp, key)
        if param not in blk:
            known = ", ".join(k for k in blk if not k.startswith("@"))
            raise KeyError(f"{blk.get('@model')} has no parameter {param!r}. Known: {known}")
        blk[param] = value
        if all_snapshots:
            for snap in self.snapshots():
                ctl = snap.get("controllers", {}).get(dsp, {}).get(key, {}).get(param)
                if isinstance(ctl, dict) and "@value" in ctl:
                    ctl["@value"] = value

    def set_model(self, dsp: str, key: str, model: str, template_params: dict[str, Any]) -> None:
        """Swap a block's model, keeping @-attributes but replacing its parameters."""
        blk = self.block(dsp, key)
        attrs = {k: v for k, v in blk.items() if k.startswith("@")}
        attrs["@model"] = model
        blk.clear()
        blk.update(attrs)
        blk.update(template_params)

    # -- snapshots ----------------------------------------------------------------
    def snapshots(self) -> list[dict[str, Any]]:
        return [self.tone[k] for k in sorted(self.tone) if k.startswith("snapshot")]

    def snapshot_names(self) -> list[str]:
        return [s.get("@name", "") for s in self.snapshots()]

    def rename_snapshot(self, index: int, name: str) -> None:
        self.snapshots()[index]["@name"] = name[:16]

    # -- reporting -------------------------------------------------------------------
    def summary(self) -> str:
        lines = [f"Preset: {self.name!r}  (device_version={self.device_version}, tempo={self.tempo})"]
        for b in sorted(self.blocks(), key=lambda b: (b.dsp, b.position)):
            state = "on " if b.enabled else "off"
            lines.append(f"  [{b.dsp}/{b.key}] {state} pos{b.position:<2} {b.type_name:<12} {b.model}")
        snaps = self.snapshot_names()
        if snaps:
            lines.append("  snapshots: " + ", ".join(snaps))
        return "\n".join(lines)

    def describe_block(self, dsp: str, key: str) -> str:
        blk = self.block(dsp, key)
        lines = [f"{dsp}/{key}  {blk.get('@model')}  enabled={blk.get('@enabled')}"]
        for k, v in blk.items():
            if not k.startswith("@"):
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)


# --- Catalog: learn models/params from reference presets ------------------------

@dataclass
class ModelInfo:
    model: str
    btype: int | None
    params: dict[str, Any]            # example values (from first sighting)
    seen_in: list[str] = field(default_factory=list)


class Catalog:
    """Index of every block model seen in a folder of .hlx files.

    Used to (a) validate model IDs when generating presets and (b) provide a
    complete, firmware-correct parameter set for a model.
    """

    def __init__(self) -> None:
        self.models: dict[str, ModelInfo] = {}
        self.presets: dict[str, Preset] = {}

    @classmethod
    def from_dir(cls, folder: str | Path) -> "Catalog":
        cat = cls()
        for p in sorted(Path(folder).glob("*.hlx")):
            try:
                cat.add(Preset.load(p))
            except Exception as e:  # noqa: BLE001 - skip unreadable files, keep going
                print(f"catalog: skipping {p.name}: {e}")
        return cat

    def add(self, preset: Preset) -> None:
        self.presets[preset.name or str(preset.source)] = preset
        for b in preset.blocks():
            info = self.models.get(b.model)
            if info is None:
                info = ModelInfo(b.model, b.btype, dict(b.params))
                self.models[b.model] = info
            else:
                for k, v in b.params.items():
                    info.params.setdefault(k, v)
            info.seen_in.append(preset.name)

    def search(self, needle: str) -> list[ModelInfo]:
        n = needle.lower()
        return [m for m in self.models.values() if n in m.model.lower()]

    def params_for(self, model: str) -> dict[str, Any]:
        if model not in self.models:
            raise KeyError(f"model {model!r} not in catalog; export a preset using it from HX Edit")
        return dict(self.models[model].params)

    def summary(self) -> str:
        by_type: dict[str, list[str]] = {}
        for m in self.models.values():
            by_type.setdefault(BLOCK_TYPES.get(m.btype, f"type{m.btype}"), []).append(m.model)
        lines = [f"{len(self.presets)} reference presets, {len(self.models)} models"]
        for t in sorted(by_type):
            lines.append(f"  {t}: " + ", ".join(sorted(by_type[t])))
        return "\n".join(lines)
