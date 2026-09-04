"""helix-mcp server: exposes Helix live control (USB MIDI) and .hlx preset tools.

Run:   helix-mcp                      (stdio transport, for Claude Desktop / Claude Code)
Env:   HELIX_MIDI_PORT     exact MIDI port name (default: auto-detect "*Helix*")
       HELIX_MIDI_CHANNEL  1-16 (default 1)
       HELIX_DRY_RUN=1     don't open hardware; record messages instead
       HELIX_PRESET_DIR    where .hlx files live (default: ./presets)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import ccmap
from .hlx import Catalog, Preset
from .midi import Helix, MemoryBackend, list_output_ports

mcp = FastMCP(
    "helix",
    instructions=(
        "Control a Line 6 Helix LT over USB MIDI (presets, snapshots, footswitches, "
        "expression, looper, tap tempo) and inspect/edit/generate .hlx preset files. "
        "MIDI cannot create patches: build them as .hlx files with the preset tools, "
        "then the user imports them in HX Edit. This server is Helix-only; the BOSS Katana "
        "has its own server (katana-mcp)."
    ),
)

_helix: Helix | None = None


def helix() -> Helix:
    global _helix
    if _helix is None:
        _helix = Helix.from_env()
    return _helix


def preset_dir() -> Path:
    return Path(os.environ.get("HELIX_PRESET_DIR", "presets")).resolve()


def _catalog() -> Catalog:
    return Catalog.from_dir(preset_dir() / "reference")


# =============================================================================
# MIDI: connection
# =============================================================================

@mcp.tool()
def midi_status() -> str:
    """Show which MIDI port/channel is in use and list all available output ports."""
    ports = list_output_ports()
    try:
        h = helix()
        current = f"connected to {h.backend.name!r} on channel {h.ch + 1}"
        if isinstance(h.backend, MemoryBackend):
            current += f" (DRY RUN, {len(h.backend.sent)} messages recorded)"
    except Exception as e:  # noqa: BLE001
        current = f"not connected: {e}"
    return current + "\navailable ports: " + (", ".join(ports) or "<none>")


@mcp.tool()
def midi_dry_run_log(clear: bool = False) -> str:
    """In dry-run mode, show (and optionally clear) the recorded MIDI messages."""
    h = helix()
    if not isinstance(h.backend, MemoryBackend):
        return "not in dry-run mode"
    out = "\n".join(str(m) for m in h.backend.sent) or "<no messages>"
    if clear:
        h.backend.sent.clear()
    return out


# =============================================================================
# MIDI: presets & snapshots
# =============================================================================

@mcp.tool()
def select_preset(preset: str, setlist: int | None = None) -> str:
    """Load a preset on the Helix. `preset` like '12C' (bank 01-32, slot A-D) or a
    program number '0'-'127'. Optional `setlist` 0-7 (Bank LSB)."""
    p: str | int = int(preset) if preset.strip().isdigit() else preset
    return helix().select_preset(p, setlist)


@mcp.tool()
def next_preset() -> str:
    """Step to the next preset."""
    return helix().next_preset()


@mcp.tool()
def previous_preset() -> str:
    """Step to the previous preset."""
    return helix().previous_preset()


@mcp.tool()
def select_snapshot(snapshot: int) -> str:
    """Recall snapshot 1-8 of the current preset."""
    return helix().select_snapshot(snapshot)


# =============================================================================
# MIDI: footswitches, expression, global, looper
# =============================================================================

@mcp.tool()
def press_footswitch(fs: int) -> str:
    """Emulate pressing stomp footswitch FS1-FS11 (toggles whatever is assigned)."""
    return helix().press_footswitch(fs)


@mcp.tool()
def set_expression(pedal: int, percent: float) -> str:
    """Move expression pedal EXP1/EXP2/EXP3 to a position 0-100 % (heel=0, toe=100)."""
    return helix().expression_percent(pedal, percent)


@mcp.tool()
def sweep_expression(pedal: int, start_percent: float, end_percent: float,
                     steps: int = 16, seconds: float = 1.0) -> str:
    """Sweep an expression pedal from start to end over `seconds` (wah/volume swells)."""
    import time
    h = helix()
    steps = max(2, min(steps, 128))
    for i in range(steps):
        pct = start_percent + (end_percent - start_percent) * i / (steps - 1)
        h.expression_percent(pedal, pct)
        time.sleep(seconds / steps)
    return f"EXP{pedal} swept {start_percent:.0f}% -> {end_percent:.0f}% in {seconds}s"


@mcp.tool()
def tap_tempo(bpm: float | None = None, taps: int = 4) -> str:
    """Send tap-tempo presses. If `bpm` is given, taps are spaced to set that tempo."""
    import time
    h = helix()
    if bpm is None:
        return h.tap_tempo()
    interval = 60.0 / bpm
    for i in range(taps):
        h.tap_tempo()
        if i < taps - 1:
            time.sleep(interval)
    return f"tapped {taps}x at {bpm} BPM"


@mcp.tool()
def tuner(on: bool = True) -> str:
    """Toggle the tuner (Helix toggles on any value)."""
    return helix().tuner(on)


@mcp.tool()
def looper(action: str) -> str:
    """Looper control. action: record, overdub, play, stop, play_once, undo,
    forward, reverse, full_speed, half_speed, block_on, block_off."""
    return helix().looper(action)


@mcp.tool()
def send_cc(control: int, value: int) -> str:
    """Send a raw Control Change (for CCs you assigned to block parameters in HX Edit)."""
    return helix().cc(control, value)


@mcp.tool()
def send_program_change(program: int) -> str:
    """Send a raw Program Change 0-127."""
    return helix().pc(program)


@mcp.tool()
def midi_reference() -> str:
    """The Helix MIDI CC map this server implements."""
    return (
        "CC1/2/3 EXP1-3 | CC49-59 FS1-11 | CC60 rec(64+)/overdub(0-63) | CC61 play(64+)/stop |\n"
        "CC62 play once | CC63 undo | CC64 tap tempo | CC65 fwd/rev | CC66 full/half speed |\n"
        "CC67 looper block off/on | CC68 tuner | CC69 snapshot 0-7 | CC72 prev(0-63)/next(64+) |\n"
        "CC0 bank MSB=0, CC32 setlist 0-7, then PC 0-127 = preset 01A..32D"
    )


# =============================================================================
# Presets (.hlx files)
# =============================================================================

@mcp.tool()
def list_presets() -> str:
    """List .hlx files in the preset dir (reference/ = exported from your Helix,
    generated/ = created by this server)."""
    root = preset_dir()
    out = []
    for sub in ("reference", "generated"):
        files = sorted((root / sub).glob("*.hlx"))
        out.append(f"{sub}/ ({len(files)})")
        for f in files:
            try:
                out.append(f"  {f.name}: {Preset.load(f).name!r}")
            except Exception as e:  # noqa: BLE001
                out.append(f"  {f.name}: <unreadable: {e}>")
    return "\n".join(out)


@mcp.tool()
def inspect_preset(path: str) -> str:
    """Summarise a .hlx file: blocks, models, on/off, snapshots. `path` is relative
    to the preset dir or absolute."""
    return Preset.load(_resolve(path)).summary()


@mcp.tool()
def inspect_block(path: str, dsp: str, block: str) -> str:
    """Show every parameter of one block, e.g. dsp='dsp0', block='block2'."""
    return Preset.load(_resolve(path)).describe_block(dsp, block)


@mcp.tool()
def edit_preset(path: str, changes: list[dict[str, Any]], save_as: str | None = None,
                name: str | None = None) -> str:
    """Apply edits to a .hlx and save it (to generated/<save_as> or in place).

    Each change is one of:
      {"op":"param",  "dsp":"dsp0","block":"block2","param":"Drive","value":0.6}
      {"op":"enable", "dsp":"dsp0","block":"block4","enabled":false}
      {"op":"model",  "dsp":"dsp0","block":"block2","model":"HD2_AmpUSDoubleNrm"}   (params from catalog)
      {"op":"tempo",  "bpm":92}
      {"op":"snapshot_name","index":0,"name":"Verse"}
    """
    src = _resolve(path)
    p = Preset.load(src)
    cat: Catalog | None = None
    log = []
    for ch in changes:
        op = ch.get("op")
        if op == "param":
            p.set_param(ch["dsp"], ch["block"], ch["param"], ch["value"])
            log.append(f"{ch['dsp']}/{ch['block']} {ch['param']}={ch['value']}")
        elif op == "enable":
            p.set_enabled(ch["dsp"], ch["block"], bool(ch["enabled"]))
            log.append(f"{ch['dsp']}/{ch['block']} enabled={ch['enabled']}")
        elif op == "model":
            cat = cat or _catalog()
            p.set_model(ch["dsp"], ch["block"], ch["model"], cat.params_for(ch["model"]))
            log.append(f"{ch['dsp']}/{ch['block']} model={ch['model']}")
        elif op == "tempo":
            p.tempo = float(ch["bpm"])
            log.append(f"tempo={ch['bpm']}")
        elif op == "snapshot_name":
            p.rename_snapshot(int(ch["index"]), ch["name"])
            log.append(f"snapshot{ch['index']}={ch['name']!r}")
        else:
            raise ValueError(f"unknown op {op!r}")
    if name:
        p.name = name
        log.append(f"name={p.name!r}")
    dest = preset_dir() / "generated" / save_as if save_as else src
    if not str(dest).endswith(".hlx"):
        dest = dest.with_suffix(".hlx")
    p.save(dest)
    return f"saved {dest}\n" + "\n".join(log) + "\n\nImport in HX Edit: drag the file onto a preset slot."


@mcp.tool()
def catalog_models(search: str = "") -> str:
    """List block models (amps, cabs, effects) learned from presets/reference/*.hlx.
    Optional substring filter, e.g. 'Amp', 'Reverb', 'Fender'."""
    cat = _catalog()
    if not cat.models:
        return ("Catalog is empty. Export presets from HX Edit (right-click preset -> Export) "
                f"into {preset_dir() / 'reference'} so I can learn your firmware's model IDs.")
    if search:
        hits = cat.search(search)
        return "\n".join(f"{m.model}  ({len(m.params)} params; e.g. {', '.join(list(m.params)[:6])})"
                         for m in hits) or f"no models matching {search!r}"
    return cat.summary()


@mcp.tool()
def catalog_params(model: str) -> str:
    """Show the full parameter set (with example values) for a model ID from the catalog."""
    return json.dumps(_catalog().params_for(model), indent=1)


def _resolve(path: str) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    for cand in (preset_dir() / path, preset_dir() / "reference" / path,
                 preset_dir() / "generated" / path):
        if cand.exists():
            return cand
    raise FileNotFoundError(f"{path} not found under {preset_dir()}")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
