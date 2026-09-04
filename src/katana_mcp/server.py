"""katana-mcp server: BOSS Katana MkII over Roland SysEx (USB MIDI port "KATANA").

Run:   katana-mcp                     (stdio transport, for Claude Desktop / Claude Code)
Env:   KATANA_MIDI_PORT   exact port name (default: auto-detect "*KATANA*" minus "DAW")
       KATANA_DEVICE_ID   Roland device id (default 0)
       KATANA_DRY_RUN=1   in-memory fake amp, no hardware
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from .sysex import ALL_PARAMS, Katana, addr_add, parse_addr

mcp = FastMCP(
    "katana",
    instructions=(
        "Control a BOSS Katana MkII amplifier over Roland SysEx. Read/write the panel knobs "
        "(gain, volume, bass, middle, treble, presence, solo level), read the patch name, "
        "recall channels, and use the discovery tools (katana_watch / katana_scan / "
        "katana_read_hex) to map addresses that are not yet in katana_params. Knob values "
        "are 0-100 exactly as Tone Studio shows them. This server is Katana-only; the Line 6 "
        "Helix has its own server (helix-mcp)."
    ),
)

_katana: Katana | None = None


def katana() -> Katana:
    global _katana
    if _katana is None:
        _katana = Katana.from_env()
    return _katana


# =============================================================================
# Connection
# =============================================================================

@mcp.tool()
def katana_status() -> str:
    """Connection status for the BOSS Katana (SysEx port), plus identity reply."""
    try:
        k = katana()
    except Exception as e:  # noqa: BLE001
        return f"not connected: {e}"
    return (f"connected to {k.t.name!r} (device id {k.device_id:02X}, editor mode {k.editor_mode})\n"
            f"identity: {k.identify()}")


@mcp.tool()
def katana_editor_mode(on: bool = True) -> str:
    """Enter/exit Tone Studio-style editor mode. Reads of the edit buffer switch it on
    automatically; use this to switch it off again."""
    return katana().set_editor_mode(on)


# =============================================================================
# Panel & patch
# =============================================================================

@mcp.tool()
def katana_read_panel() -> str:
    """Read the current patch: name, gain, volume, bass, middle, treble, presence, solo level,
    amp type (raw byte). Values are exactly what Tone Studio displays (0-100)."""
    return json.dumps(katana().read_panel(), indent=1)


@mcp.tool()
def katana_get(name: str) -> str:
    """Read one named parameter (see katana_params for names)."""
    return f"{name} = {katana().get(name)}"


@mcp.tool()
def katana_set(name: str, value: str) -> str:
    """Write one named parameter, e.g. name='gain' value='35'. Knob values 0-100."""
    v: int | str = int(value) if value.strip().lstrip("-").isdigit() else value
    return katana().set(name, v)


@mcp.tool()
def katana_set_panel(gain: int | None = None, volume: int | None = None, bass: int | None = None,
                     middle: int | None = None, treble: int | None = None,
                     presence: int | None = None, solo_level: int | None = None) -> str:
    """Set several knobs at once (0-100 each; omitted ones are left alone). Returns the panel after."""
    k = katana()
    for name, val in (("gain", gain), ("volume", volume), ("bass", bass), ("middle", middle),
                      ("treble", treble), ("presence", presence), ("solo_level", solo_level)):
        if val is not None:
            k.set(name, val)
    return json.dumps(k.read_panel(), indent=1)


@mcp.tool()
def katana_select_channel(channel: str) -> str:
    """Recall a channel: 'panel', 'A1'..'A4', 'B1'..'B4'. (Recall address not yet verified on MkII.)"""
    return katana().select_channel(channel)


@mcp.tool()
def katana_params() -> str:
    """List the known parameter addresses and how well each is verified on MkII."""
    return "\n".join(f"{p.name:<14} {p.addr_hex}  size={p.size} range={p.lo}-{p.hi}  [{p.verified}]"
                     for p in ALL_PARAMS.values())


# =============================================================================
# Discovery
# =============================================================================

@mcp.tool()
def katana_read_hex(address: str, size: int = 16) -> str:
    """Raw RQ1 read: address like '60 00 00 00', size in bytes. Hex + ASCII dump."""
    return katana().read_hex(parse_addr(address), size)


@mcp.tool()
def katana_write_hex(address: str, data_hex: str) -> str:
    """Raw DT1 write: address '60 00 06 51', data_hex '20'. Use with care."""
    data = [int(x, 16) for x in data_hex.split()]
    return str(katana().write(parse_addr(address), data))


@mcp.tool()
def katana_watch(seconds: float = 5.0) -> str:
    """Listen for parameter-change broadcasts from the amp for N seconds. Turn a knob or
    switch channels on the amp/Tone Studio meanwhile — the DT1s reveal MkII addresses.
    Repeated values for the same address are collapsed to first..last."""
    msgs = katana().watch(seconds)
    if not msgs:
        return "<nothing received — is editor mode on?>"
    # collapse runs on the same address so a knob sweep doesn't flood the output
    lines: list[str] = []
    run_addr, first, last, n = None, None, None, 0
    for m in msgs:
        if m.address == run_addr:
            last, n = m, n + 1
            continue
        if run_addr is not None:
            lines.append(_run(first, last, n))
        run_addr, first, last, n = m.address, m, m, 1
    lines.append(_run(first, last, n))
    return "\n".join(lines)


def _run(first, last, n) -> str:
    if n == 1:
        return str(first)
    return f"DT1 {first.addr_hex} = {first.data.hex(' ').upper()} .. {last.data.hex(' ').upper()}  ({n} msgs)"


@mcp.tool()
def katana_scan(start: str, count: int = 8, stride: int = 16) -> str:
    """Read `count` consecutive `stride`-byte chunks from `start` for address mapping."""
    k = katana()
    out = []
    a = parse_addr(start)
    for _ in range(count):
        try:
            out.append(k.read_hex(a, stride))
        except TimeoutError as e:
            out.append(f"{' '.join(f'{b:02X}' for b in a)}  <no reply: {e}>")
        a = addr_add(a, stride)
    return "\n".join(out)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
