"""Line 6 Helix MIDI implementation (Helix Floor / LT / Rack, firmware 3.x).

Source: Helix owner's manual "MIDI" chapter and helixhelp.com/tips-and-guides/universal/midi.
All values are 7-bit (0-127). Default MIDI channel is 1 (0-based: 0).
"""

# --- Expression pedals ------------------------------------------------------
CC_EXP1 = 1
CC_EXP2 = 2
CC_EXP3 = 3  # Floor/Rack/LT with external pedal

# --- Stomp footswitches FS1..FS11 -------------------------------------------
# CC 49..59 -> FS1..FS11. Value emulates a press (any value); use 127.
CC_FS_BASE = 49
FS_MIN, FS_MAX = 1, 11

# --- Looper -----------------------------------------------------------------
CC_LOOP_RECORD_OVERDUB = 60  # 0-63 overdub, 64-127 record
CC_LOOP_PLAY_STOP = 61       # 0-63 stop, 64-127 play
CC_LOOP_PLAY_ONCE = 62       # 64-127
CC_LOOP_UNDO = 63            # 64-127
CC_LOOP_DIRECTION = 65       # 0-63 forward, 64-127 reverse
CC_LOOP_SPEED = 66           # 0-63 full, 64-127 half
CC_LOOP_BLOCK = 67           # 0-63 off, 64-127 on

# --- Global -----------------------------------------------------------------
CC_TAP_TEMPO = 64            # 64-127
CC_TUNER = 68                # any value toggles (0-127)

# --- Preset / snapshot navigation -------------------------------------------
CC_BANK_MSB = 0              # always 0 on Helix
CC_BANK_LSB = 32             # setlist 0-7
CC_SNAPSHOT = 69             # 0-7 -> snapshot 1-8
CC_PRESET_PREV_NEXT = 72     # 0-63 previous, 64-127 next

SETLIST_MIN, SETLIST_MAX = 0, 7
SNAPSHOT_MIN, SNAPSHOT_MAX = 1, 8

ON = 127
OFF = 0


def fs_cc(fs_number: int) -> int:
    """Footswitch number (1-11) -> CC number (49-59)."""
    if not FS_MIN <= fs_number <= FS_MAX:
        raise ValueError(f"footswitch must be {FS_MIN}-{FS_MAX}, got {fs_number}")
    return CC_FS_BASE + fs_number - 1


def preset_to_program(preset: str | int) -> int:
    """Convert a Helix preset name like '12C' (bank 01-32, slot A-D) or an int 0-127
    to a Program Change number (0-127).

    '01A' -> 0, '01D' -> 3, '02A' -> 4, '32D' -> 127.
    """
    if isinstance(preset, int):
        if not 0 <= preset <= 127:
            raise ValueError("program number must be 0-127")
        return preset
    s = preset.strip().upper()
    if len(s) < 2 or s[-1] not in "ABCD":
        raise ValueError(f"preset must look like '12C' (01-32 + A-D), got {preset!r}")
    bank = int(s[:-1])
    if not 1 <= bank <= 32:
        raise ValueError("bank must be 01-32")
    return (bank - 1) * 4 + "ABCD".index(s[-1])


def program_to_preset(program: int) -> str:
    """Inverse of preset_to_program: 46 -> '12C'."""
    if not 0 <= program <= 127:
        raise ValueError("program number must be 0-127")
    return f"{program // 4 + 1:02d}{'ABCD'[program % 4]}"
