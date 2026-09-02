"""MIDI transport for the Helix.

Two backends:
  * MidoBackend  - real USB MIDI via mido + python-rtmidi (used at runtime)
  * MemoryBackend - records messages, no hardware (used in tests / dry-run)

The Helix appears on macOS as a MIDI port named like "Helix LT" (no driver needed).
Select the port with HELIX_MIDI_PORT env var or let it auto-detect any port
containing "helix" (case-insensitive).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol

from . import ccmap


@dataclass(frozen=True)
class MidiMessage:
    kind: str            # "cc" | "pc"
    channel: int         # 0-15
    number: int          # controller or program number
    value: int | None    # cc value, None for pc

    def __str__(self) -> str:
        if self.kind == "cc":
            return f"CC{self.number}={self.value} ch{self.channel + 1}"
        return f"PC{self.number} ch{self.channel + 1}"


class Backend(Protocol):
    name: str

    def send_cc(self, channel: int, control: int, value: int) -> None: ...
    def send_pc(self, channel: int, program: int) -> None: ...
    def close(self) -> None: ...


@dataclass
class MemoryBackend:
    """Collects messages; used for tests and `--dry-run`."""

    name: str = "memory"
    sent: list[MidiMessage] = field(default_factory=list)

    def send_cc(self, channel: int, control: int, value: int) -> None:
        self.sent.append(MidiMessage("cc", channel, control, value))

    def send_pc(self, channel: int, program: int) -> None:
        self.sent.append(MidiMessage("pc", channel, program, None))

    def close(self) -> None:  # pragma: no cover - nothing to do
        pass


class MidoBackend:
    """Real MIDI output through mido/python-rtmidi."""

    def __init__(self, port_name: str | None = None):
        import mido  # imported lazily so tests don't need it

        self._mido = mido
        self.name = port_name or self.autodetect(mido.get_output_names())
        self._port = mido.open_output(self.name)

    @staticmethod
    def autodetect(names: list[str]) -> str:
        for n in names:
            if "helix" in n.lower():
                return n
        raise RuntimeError(
            "No Helix MIDI port found. Available: "
            + (", ".join(names) or "<none>")
            + ". Plug in the Helix via USB or set HELIX_MIDI_PORT."
        )

    def send_cc(self, channel: int, control: int, value: int) -> None:
        self._port.send(self._mido.Message("control_change", channel=channel,
                                           control=control, value=value))

    def send_pc(self, channel: int, program: int) -> None:
        self._port.send(self._mido.Message("program_change", channel=channel,
                                           program=program))

    def close(self) -> None:
        self._port.close()


def list_output_ports() -> list[str]:
    try:
        import mido
    except ImportError:
        return []
    return mido.get_output_names()


def _clamp7(v: int) -> int:
    if not 0 <= v <= 127:
        raise ValueError(f"MIDI value must be 0-127, got {v}")
    return v


class Helix:
    """High-level Helix control. All methods return a human-readable summary."""

    def __init__(self, backend: Backend, channel: int = 1):
        if not 1 <= channel <= 16:
            raise ValueError("MIDI channel must be 1-16")
        self.backend = backend
        self.ch = channel - 1

    # -- factories ---------------------------------------------------------
    @classmethod
    def from_env(cls) -> "Helix":
        channel = int(os.environ.get("HELIX_MIDI_CHANNEL", "1"))
        if os.environ.get("HELIX_DRY_RUN"):
            return cls(MemoryBackend(), channel)
        return cls(MidoBackend(os.environ.get("HELIX_MIDI_PORT")), channel)

    # -- low level -----------------------------------------------------------
    def cc(self, control: int, value: int) -> str:
        self.backend.send_cc(self.ch, _clamp7(control), _clamp7(value))
        return f"sent CC{control}={value}"

    def pc(self, program: int) -> str:
        self.backend.send_pc(self.ch, _clamp7(program))
        return f"sent PC{program}"

    # -- presets / snapshots -------------------------------------------------
    def select_preset(self, preset: str | int, setlist: int | None = None) -> str:
        """Load a preset. `preset` is '12C' style or 0-127. Optional setlist 0-7."""
        program = ccmap.preset_to_program(preset)
        if setlist is not None:
            if not ccmap.SETLIST_MIN <= setlist <= ccmap.SETLIST_MAX:
                raise ValueError("setlist must be 0-7")
            self.backend.send_cc(self.ch, ccmap.CC_BANK_MSB, 0)
            self.backend.send_cc(self.ch, ccmap.CC_BANK_LSB, setlist)
        self.backend.send_pc(self.ch, program)
        where = f" in setlist {setlist}" if setlist is not None else ""
        return f"loaded preset {ccmap.program_to_preset(program)} (PC{program}){where}"

    def next_preset(self) -> str:
        self.backend.send_cc(self.ch, ccmap.CC_PRESET_PREV_NEXT, 127)
        return "next preset"

    def previous_preset(self) -> str:
        self.backend.send_cc(self.ch, ccmap.CC_PRESET_PREV_NEXT, 0)
        return "previous preset"

    def select_snapshot(self, snapshot: int) -> str:
        if not ccmap.SNAPSHOT_MIN <= snapshot <= ccmap.SNAPSHOT_MAX:
            raise ValueError("snapshot must be 1-8")
        self.backend.send_cc(self.ch, ccmap.CC_SNAPSHOT, snapshot - 1)
        return f"snapshot {snapshot}"

    # -- footswitches / expression --------------------------------------------
    def press_footswitch(self, fs: int) -> str:
        self.backend.send_cc(self.ch, ccmap.fs_cc(fs), ccmap.ON)
        return f"pressed FS{fs}"

    def expression(self, pedal: int, value: int) -> str:
        cc = {1: ccmap.CC_EXP1, 2: ccmap.CC_EXP2, 3: ccmap.CC_EXP3}.get(pedal)
        if cc is None:
            raise ValueError("expression pedal must be 1, 2 or 3")
        self.backend.send_cc(self.ch, cc, _clamp7(value))
        return f"EXP{pedal}={value}"

    def expression_percent(self, pedal: int, percent: float) -> str:
        if not 0 <= percent <= 100:
            raise ValueError("percent must be 0-100")
        return self.expression(pedal, round(percent * 127 / 100))

    # -- global ------------------------------------------------------------------
    def tap_tempo(self) -> str:
        self.backend.send_cc(self.ch, ccmap.CC_TAP_TEMPO, ccmap.ON)
        return "tap"

    def tuner(self, on: bool | None = None) -> str:
        # Helix toggles the tuner on any CC68 value; we still send 127/0 for clarity.
        self.backend.send_cc(self.ch, ccmap.CC_TUNER, ccmap.ON if on in (None, True) else ccmap.OFF)
        return "tuner toggled"

    # -- looper -------------------------------------------------------------------
    def looper(self, action: str) -> str:
        table = {
            "record": (ccmap.CC_LOOP_RECORD_OVERDUB, 127),
            "overdub": (ccmap.CC_LOOP_RECORD_OVERDUB, 0),
            "play": (ccmap.CC_LOOP_PLAY_STOP, 127),
            "stop": (ccmap.CC_LOOP_PLAY_STOP, 0),
            "play_once": (ccmap.CC_LOOP_PLAY_ONCE, 127),
            "undo": (ccmap.CC_LOOP_UNDO, 127),
            "forward": (ccmap.CC_LOOP_DIRECTION, 0),
            "reverse": (ccmap.CC_LOOP_DIRECTION, 127),
            "full_speed": (ccmap.CC_LOOP_SPEED, 0),
            "half_speed": (ccmap.CC_LOOP_SPEED, 127),
            "block_on": (ccmap.CC_LOOP_BLOCK, 127),
            "block_off": (ccmap.CC_LOOP_BLOCK, 0),
        }
        if action not in table:
            raise ValueError(f"unknown looper action {action!r}; one of {sorted(table)}")
        cc, val = table[action]
        self.backend.send_cc(self.ch, cc, val)
        return f"looper {action}"

    def close(self) -> None:
        self.backend.close()
