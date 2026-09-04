"""BOSS Katana (MkII) backend — Roland SysEx over USB MIDI.

The Katana exposes two USB-MIDI ports on macOS: "KATANA" (SysEx, what BOSS Tone
Studio uses) and "KATANA DAW CTRL". We talk to the first one.

Protocol (Roland "RQ1/DT1"):

    F0 41 <dev> 00 00 00 33 <cmd> <addr:4> <payload> <checksum> F7
      41    Roland
      dev   device id, 0x00 (Tone Studio) — some units answer to 0x10 as well
      33    Katana model id (same header on MkI and MkII)
      cmd   0x11 = RQ1 request data (payload = size:4)   -> amp replies with DT1
            0x12 = DT1 data set     (payload = bytes)
      checksum = (128 - sum(addr + payload) % 128) % 128

Editor ("BTS") mode must be on for the edit-buffer area (0x60xxxxxx) to respond:
    DT1 7F 00 00 01 = 01   (enter)   /  = 00 (exit)

Address map (verified live on a Katana MkII, 2026-09-04, against BOSS Tone Studio):

    60 00 00 00..0F  patch name (16 ASCII)
    60 00 00 21      amp type (raw byte; 0x1D = Clean with Variation ON — table incomplete)
    60 00 00 2C      solo level
    60 00 06 51..56  gain, volume, bass, middle, treble, presence   <- what the panel/Tone Studio show
    60 00 05 70      expression pedal position (GA-FC EXP jack)
    60 00 00 22      *internal* preamp gain — the amp maps the displayed gain onto it via a
                     curve; 60 00 00 24..28 mirror B/M/T/P/volume. Turning Gain broadcasts
                     DT1s to both 00 22 and 06 51.

The MkI "live panel" area 00 00 04 2x (Hirsch, katana-midi-bridge) does NOT answer on MkII.
Patch recall 00 01 00 00 is still unverified on MkII. Discovery tools (read_hex, scan, watch)
are kept for mapping the remaining blocks (booster/mod/fx/delay/reverb, cab, contour).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

ROLAND = 0x41
KATANA_MODEL = (0x00, 0x00, 0x00, 0x33)
RQ1 = 0x11
DT1 = 0x12

ADDR_EDITOR_MODE = (0x7F, 0x00, 0x00, 0x01)
ADDR_PATCH_RECALL = (0x00, 0x01, 0x00, 0x00)   # 2 bytes: 00 00 panel, 00 01.. channels


@dataclass(frozen=True)
class Param:
    name: str
    address: tuple[int, int, int, int]
    size: int = 1
    lo: int = 0
    hi: int = 100
    verified: str = "MkI (Hirsch); expected MkII"
    enum: tuple[str, ...] | None = None

    @property
    def addr_hex(self) -> str:
        return " ".join(f"{b:02X}" for b in self.address)


VERIFIED = "verified on MkII 2026-09-04"

# The knob values shown on the amp / in Tone Studio (0-100).
PANEL_PARAMS: dict[str, Param] = {
    "gain":     Param("gain",     (0x60, 0x00, 0x06, 0x51), verified=VERIFIED),
    "volume":   Param("volume",   (0x60, 0x00, 0x06, 0x52), verified=VERIFIED),
    "bass":     Param("bass",     (0x60, 0x00, 0x06, 0x53), verified=VERIFIED),
    "middle":   Param("middle",   (0x60, 0x00, 0x06, 0x54), verified=VERIFIED),
    "treble":   Param("treble",   (0x60, 0x00, 0x06, 0x55), verified=VERIFIED),
    "presence": Param("presence", (0x60, 0x00, 0x06, 0x56), verified=VERIFIED),
    "solo_level": Param("solo_level", (0x60, 0x00, 0x00, 0x2C), verified=VERIFIED),
    "amp_type": Param("amp_type", (0x60, 0x00, 0x00, 0x21), 1, 0, 127,
                      verified=VERIFIED + " (raw byte; only 0x1D=clean+variation known)"),
}

# Other edit-buffer entries.
EDIT_PARAMS: dict[str, Param] = {
    "patch_name": Param("patch_name", (0x60, 0x00, 0x00, 0x00), 16, 0, 127, verified=VERIFIED),
    "exp_pedal":  Param("exp_pedal",  (0x60, 0x00, 0x05, 0x70), verified=VERIFIED + " (read-only in practice)"),
    "gain_internal": Param("gain_internal", (0x60, 0x00, 0x00, 0x22),
                           verified=VERIFIED + " (curve-mapped copy of gain; prefer 'gain')"),
}

ALL_PARAMS = {**PANEL_PARAMS, **EDIT_PARAMS}


# --- SysEx helpers -----------------------------------------------------------

def checksum(payload: bytes | list[int]) -> int:
    return (128 - (sum(payload) % 128)) % 128


def build(cmd: int, address: tuple[int, int, int, int] | bytes, data: bytes | list[int],
          device_id: int = 0x00) -> list[int]:
    """Return the SysEx *body* (without F0/F7) — that's what mido wants."""
    addr = list(address)
    body = [ROLAND, device_id, *KATANA_MODEL, cmd, *addr, *data]
    body.append(checksum(addr + list(data)))
    return body


def build_rq1(address, size: int, device_id: int = 0x00) -> list[int]:
    size_bytes = [(size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F]
    return build(RQ1, address, size_bytes, device_id)


def build_dt1(address, data: bytes | list[int], device_id: int = 0x00) -> list[int]:
    return build(DT1, address, data, device_id)


@dataclass(frozen=True)
class Dt1:
    address: tuple[int, int, int, int]
    data: bytes

    @property
    def addr_hex(self) -> str:
        return " ".join(f"{b:02X}" for b in self.address)

    def __str__(self) -> str:
        return f"DT1 {self.addr_hex} = {' '.join(f'{b:02X}' for b in self.data)}"


def parse_dt1(body: list[int] | bytes) -> Dt1 | None:
    """Parse a received SysEx body (no F0/F7). Returns None if it isn't a Katana DT1."""
    b = list(body)
    if len(b) < 12 or b[0] != ROLAND or tuple(b[2:6]) != KATANA_MODEL or b[6] != DT1:
        return None
    addr = tuple(b[7:11])
    data = bytes(b[11:-1])
    if checksum(list(addr) + list(data)) != b[-1]:
        return None
    return Dt1(addr, data)  # type: ignore[arg-type]


def addr_add(address: tuple[int, int, int, int], offset: int) -> tuple[int, int, int, int]:
    """Roland addresses are 7-bit per byte."""
    n = (address[0] << 21) | (address[1] << 14) | (address[2] << 7) | address[3]
    n += offset
    return ((n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F)


def parse_addr(text: str) -> tuple[int, int, int, int]:
    """'60 00 00 00' or '60000000' -> tuple."""
    s = text.replace("0x", "").replace(",", " ").strip()
    parts = s.split() if " " in s else [s[i:i + 2] for i in range(0, len(s), 2)]
    if len(parts) != 4:
        raise ValueError("address must be 4 bytes, e.g. '60 00 00 00'")
    t = tuple(int(p, 16) for p in parts)
    if any(b > 0x7F for b in t):
        raise ValueError("address bytes must be 00-7F")
    return t  # type: ignore[return-value]


# --- transports ------------------------------------------------------------------

class SysexTransport(Protocol):
    name: str

    def send(self, body: list[int]) -> None: ...
    def receive(self, timeout: float) -> list[list[int]]:
        """Return SysEx bodies received within `timeout` seconds."""
        ...
    def close(self) -> None: ...


@dataclass
class FakeKatana:
    """In-memory Katana for tests: a byte-addressable memory that answers RQ1 with DT1."""

    name: str = "fake-katana"
    memory: dict[int, int] = field(default_factory=dict)
    sent: list[list[int]] = field(default_factory=list)
    _inbox: list[list[int]] = field(default_factory=list)

    @staticmethod
    def _lin(addr) -> int:
        return (addr[0] << 21) | (addr[1] << 14) | (addr[2] << 7) | addr[3]

    def poke(self, address, data: bytes | list[int]) -> None:
        base = self._lin(address)
        for i, v in enumerate(data):
            self.memory[base + i] = v

    def send(self, body: list[int]) -> None:
        self.sent.append(body)
        cmd = body[6]
        addr = tuple(body[7:11])
        if cmd == RQ1:
            s = body[11:15]
            size = (s[0] << 21) | (s[1] << 14) | (s[2] << 7) | s[3]
            base = self._lin(addr)
            data = [self.memory.get(base + i, 0) for i in range(size)]
            self._inbox.append(build_dt1(addr, data))
        elif cmd == DT1:
            self.poke(addr, body[11:-1])

    def receive(self, timeout: float) -> list[list[int]]:
        out, self._inbox = self._inbox, []
        return out

    def close(self) -> None:
        pass


class MidoSysexTransport:
    """USB MIDI duplex via mido. Picks the port containing 'KATANA' but not 'DAW'."""

    def __init__(self, port_name: str | None = None):
        import mido
        self._mido = mido
        outs, ins = mido.get_output_names(), mido.get_input_names()
        self.name = port_name or self.autodetect(outs)
        in_name = port_name if port_name in ins else self.autodetect(ins)
        self._out = mido.open_output(self.name)
        self._in = mido.open_input(in_name)

    @staticmethod
    def autodetect(names: list[str]) -> str:
        for n in names:
            if "katana" in n.lower() and "daw" not in n.lower():
                return n
        raise RuntimeError("No KATANA MIDI port found. Available: " + (", ".join(names) or "<none>"))

    def send(self, body: list[int]) -> None:
        self._out.send(self._mido.Message("sysex", data=body))

    def receive(self, timeout: float) -> list[list[int]]:
        deadline = time.monotonic() + timeout
        out: list[list[int]] = []
        while time.monotonic() < deadline:
            got = False
            for msg in self._in.iter_pending():
                got = True
                if msg.type == "sysex":
                    out.append(list(msg.data))
            if not got:
                time.sleep(0.005)
        return out

    def close(self) -> None:
        self._out.close()
        self._in.close()


# --- high level ------------------------------------------------------------------

class Katana:
    def __init__(self, transport: SysexTransport, device_id: int = 0x00, reply_timeout: float = 0.4):
        self.t = transport
        self.device_id = device_id
        self.reply_timeout = reply_timeout
        self.editor_mode = False

    @classmethod
    def from_env(cls) -> "Katana":
        if os.environ.get("KATANA_DRY_RUN"):
            return cls(FakeKatana())
        return cls(MidoSysexTransport(os.environ.get("KATANA_MIDI_PORT")),
                   device_id=int(os.environ.get("KATANA_DEVICE_ID", "0"), 0))

    # -- raw ------------------------------------------------------------------
    def write(self, address, data: bytes | list[int]) -> Dt1:
        self.t.send(build_dt1(address, data, self.device_id))
        return Dt1(tuple(address), bytes(data))  # type: ignore[arg-type]

    def read(self, address, size: int) -> bytes:
        """RQ1 + collect DT1 replies covering [address, address+size).

        The 60 xx xx xx edit buffer only answers in editor mode, so we switch it on once."""
        if address[0] == 0x60 and not self.editor_mode:
            self.set_editor_mode(True)
        self.t.send(build_rq1(address, size, self.device_id))
        buf = bytearray(size)
        got = 0
        base = FakeKatana._lin(address)
        deadline = time.monotonic() + self.reply_timeout * 3
        while got < size and time.monotonic() < deadline:
            for body in self.t.receive(self.reply_timeout):
                d = parse_dt1(body)
                if d is None:
                    continue
                off = FakeKatana._lin(d.address) - base
                for i, v in enumerate(d.data):
                    if 0 <= off + i < size:
                        buf[off + i] = v
                        got += 1
            if isinstance(self.t, FakeKatana):
                break
        if got == 0:
            raise TimeoutError(
                f"no reply from Katana for {' '.join(f'{b:02X}' for b in address)} "
                f"(editor mode {'on' if self.editor_mode else 'OFF - try katana_editor_mode(True)'})")
        return bytes(buf)

    def read_hex(self, address, size: int) -> str:
        data = self.read(address, size)
        lines = []
        for i in range(0, len(data), 16):
            chunk = data[i:i + 16]
            a = addr_add(tuple(address), i)  # type: ignore[arg-type]
            hexs = " ".join(f"{b:02X}" for b in chunk)
            asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            lines.append(f"{' '.join(f'{b:02X}' for b in a)}  {hexs:<47}  {asc}")
        return "\n".join(lines)

    # -- session -----------------------------------------------------------
    def set_editor_mode(self, on: bool) -> str:
        self.write(ADDR_EDITOR_MODE, [0x01 if on else 0x00])
        self.editor_mode = on
        time.sleep(0.1)  # amp needs ~50-100 ms to settle
        return f"editor mode {'on' if on else 'off'}"

    def identify(self) -> str:
        """Universal SysEx Identity Request; returns raw reply hex (fingerprints MkI vs MkII)."""
        self.t.send([0x7E, 0x7F, 0x06, 0x01])
        replies = self.t.receive(self.reply_timeout)
        if not replies:
            return "no identity reply"
        return "\n".join("F0 " + " ".join(f"{b:02X}" for b in r) + " F7" for r in replies)

    def watch(self, seconds: float) -> list[Dt1]:
        """Log every DT1 the amp broadcasts (turn knobs / switch channels to learn addresses)."""
        out = []
        for body in self.t.receive(seconds):
            d = parse_dt1(body)
            if d:
                out.append(d)
        return out

    # -- musical -------------------------------------------------------------------
    def select_channel(self, channel: str) -> str:
        """channel: 'panel', 'A1'..'A4', 'B1'..'B4'."""
        c = channel.strip().upper()
        if c == "PANEL":
            value = 0
        elif len(c) == 2 and c[0] in "AB" and c[1] in "1234":
            value = ("AB".index(c[0]) * 4) + int(c[1])
        else:
            raise ValueError("channel must be panel, A1-A4 or B1-B4")
        self.write(ADDR_PATCH_RECALL, [0x00, value])
        return f"channel {c} (recall value {value:02X}; verify on MkII)"

    def get(self, name: str) -> int | str:
        p = ALL_PARAMS[name]
        data = self.read(p.address, p.size)
        if name == "patch_name":
            return data.decode("ascii", "replace").rstrip()
        v = data[0]
        return p.enum[v] if p.enum and v < len(p.enum) else v

    def set(self, name: str, value: int | str) -> str:
        p = ALL_PARAMS[name]
        if p.enum and isinstance(value, str):
            value = p.enum.index(value.lower())
        if name == "patch_name":
            data = str(value).encode("ascii", "replace")[:16].ljust(16)
        else:
            v = int(value)
            if not p.lo <= v <= p.hi:
                raise ValueError(f"{name} must be {p.lo}-{p.hi}")
            data = [v]
        self.write(p.address, data)
        return f"{name} = {value}  ({p.addr_hex}; {p.verified})"

    def read_panel(self) -> dict[str, int | str]:
        """Patch name + every knob the front panel / Tone Studio shows, in one call."""
        out: dict[str, int | str] = {"patch_name": self.get("patch_name")}
        block = self.read((0x60, 0x00, 0x06, 0x51), 6)
        for i, n in enumerate(("gain", "volume", "bass", "middle", "treble", "presence")):
            out[n] = block[i]
        out["solo_level"] = self.get("solo_level")
        out["amp_type"] = self.get("amp_type")
        return out

    def close(self) -> None:
        self.t.close()
