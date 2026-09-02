# helix-mcp

An [MCP](https://modelcontextprotocol.io) server that lets Claude drive a **Line 6 Helix LT**
(also Floor/Rack) over USB MIDI and build/edit **`.hlx` presets**.

Ask Claude for "the Pipeline surf tone" → it writes `presets/generated/pipeline.hlx` →
you drag it into HX Edit → Claude switches to it and drives snapshots, footswitches,
expression and tempo live.

## Two layers

| Layer | Transport | What it can do |
|---|---|---|
| **Live control** | USB MIDI (CC / PC) | select preset & snapshot, press FS1–11, move EXP1–3, tap tempo, tuner, looper, raw CC for anything you've assigned in HX Edit |
| **Patch creation** | `.hlx` JSON files | inspect / edit / generate presets: amp & effect models, parameters, block on/off, snapshot names, tempo |

MIDI alone **cannot** create or restructure a patch — Line 6 only exposes that through HX Edit.
The `.hlx` file route is the documented, supported way to get a new preset onto the unit
(HX Edit → drag & drop or *Import*).

## Install (macOS)

```bash
git clone git@github.com:gerardodiego/helix-mcp.git
cd helix-mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest        # 16 tests, no hardware needed
```

Plug the Helix in via USB. No driver is needed on macOS; it shows up as a MIDI port
named like `Helix LT`.

## Claude Desktop / Claude Code config

```json
{
  "mcpServers": {
    "helix": {
      "command": "/ABS/PATH/helix-mcp/.venv/bin/helix-mcp",
      "env": {
        "HELIX_PRESET_DIR": "/ABS/PATH/helix-mcp/presets"
      }
    }
  }
}
```

Environment variables:

| Var | Default | Meaning |
|---|---|---|
| `HELIX_MIDI_PORT` | auto (`*Helix*`) | exact MIDI output port name |
| `HELIX_MIDI_CHANNEL` | `1` | 1–16, must match Helix *Global Settings → MIDI/Tempo → MIDI Base Channel* |
| `HELIX_DRY_RUN` | unset | set to `1` to run without hardware and record messages |
| `HELIX_PRESET_DIR` | `./presets` | folder containing `reference/` and `generated/` |

## Teach it your firmware

The `.hlx` schema (model IDs like `HD2_AmpUSDoubleNrm`, parameter names, `@type` codes)
is learned from presets **exported from your own Helix**, so generated files always match
your firmware:

1. HX Edit → right-click a preset → **Export…**
2. Save into `presets/reference/`
3. Export a handful with different amps, cabs, delays, reverbs, drives — the more models
   the catalog sees, the more it can generate.

Then in Claude: `catalog_models` / `catalog_models search="Reverb"` / `catalog_params model=...`.

## Tools

**MIDI:** `midi_status`, `midi_reference`, `select_preset("12C", setlist=0)`, `next_preset`,
`previous_preset`, `select_snapshot(1-8)`, `press_footswitch(1-11)`, `set_expression(pedal, %)`,
`sweep_expression(...)`, `tap_tempo(bpm)`, `tuner`, `looper(action)`, `send_cc`, `send_program_change`,
`midi_dry_run_log`

**Presets:** `list_presets`, `inspect_preset(path)`, `inspect_block(path, dsp, block)`,
`edit_preset(path, changes, save_as, name)`, `catalog_models(search)`, `catalog_params(model)`

## Helix MIDI map (firmware 3.x)

| CC | Function |
|---|---|
| 1 / 2 / 3 | EXP 1 / 2 / 3 |
| 49–59 | FS1–FS11 (stomp mode) |
| 60 | 0–63 overdub · 64–127 record |
| 61 | 0–63 stop · 64–127 play |
| 62 / 63 | play once / undo |
| 64 | tap tempo |
| 65 / 66 / 67 | looper direction / speed / block on-off |
| 68 | tuner |
| 69 | snapshot 0–7 |
| 72 | 0–63 previous preset · 64–127 next |
| 0 + 32 + PC | Bank MSB (0), setlist 0–7, preset 0–127 (= 01A…32D) |

Sources: Helix Owner's Manual (MIDI chapter), [helixhelp.com MIDI guide](https://helixhelp.com/tips-and-guides/universal/midi).

## Roadmap

- [ ] `create_preset(tone_spec)` — build a preset from a high-level spec (amp, cab, chain, params, snapshots) using the catalog
- [ ] Automate the HX Edit import step on macOS
- [ ] Katana MkII backend (USB SysEx, see [katana-midi-bridge](https://github.com/snhirsch/katana-midi-bridge))

## Lineage

Spiritual successor to *Real-Time Facial-Expression Interpretation for Controlling Sound
Effect Parameters* (G. de la Riva, MSc thesis, Gjøvik University College, 2013), which drove a
Korg AX3000G over MIDI CC from FaceOSC. Same pipeline — input → mapper → controller
messages — with Claude as the input layer.
