from events.input import BUTTON_TYPES

try:
    from machine import I2C
    _HAS_I2C = True
except ImportError:
    _HAS_I2C = False

GLYPHS = "abcdefghijklmnopqrstuvwxyz0123456789 "
START_GLYPH = GLYPHS.index("n")  # middle of the alphabet

# BBQ10/BBQ20-compatible keyboard (Keebdeck) over I2C.
KBD_ADDR = 0x1F
REG_KEY = 0x04          # FIFO read (state, keycode)
REG_KEY_COUNT = 0x05    # pending keys in FIFO (low 5 bits)
KEY_PRESSED = 1


def _scan_keyboard():
    if not _HAS_I2C:
        return None
    for port in range(1, 7):
        try:
            bus = I2C(port)
            if KBD_ADDR in bus.scan():
                return bus
        except Exception:
            continue
    return None


class TextEntry:
    """Letter-picker (up/down/right) with optional Keebdeck keyboard input."""

    def __init__(self, initial="", max_len=100):
        self.max_len = max_len
        self.buffer = list(initial[:max_len])
        self.cur = START_GLYPH  # index into GLYPHS for the glyph being selected
        self._kbd = _scan_keyboard()
        self.done = False
        self.cancelled = False

    def has_keyboard(self):
        return self._kbd is not None

    def text(self):
        return "".join(self.buffer)

    def cur_glyph(self):
        return GLYPHS[self.cur]

    # --- Letter-picker buttons ---

    def update(self, button_states):
        if button_states.get(BUTTON_TYPES["UP"]):
            button_states.clear()
            self.cur = (self.cur - 1) % len(GLYPHS)
        elif button_states.get(BUTTON_TYPES["DOWN"]):
            button_states.clear()
            self.cur = (self.cur + 1) % len(GLYPHS)
        elif button_states.get(BUTTON_TYPES["RIGHT"]):
            button_states.clear()
            if len(self.buffer) < self.max_len:
                self.buffer.append(GLYPHS[self.cur])
                self.cur = START_GLYPH
        elif button_states.get(BUTTON_TYPES["CONFIRM"]):
            button_states.clear()
            self.done = True
        elif button_states.get(BUTTON_TYPES["CANCEL"]):
            button_states.clear()
            if self.buffer:
                self.buffer.pop()
            else:
                self.cancelled = True

        self._poll_keyboard()

    # --- Keebdeck FIFO ---

    def _poll_keyboard(self):
        if not self._kbd:
            return
        try:
            cnt = self._kbd.readfrom_mem(KBD_ADDR, REG_KEY_COUNT, 1)[0] & 0x1F
        except Exception:
            self._kbd = None
            return
        for _ in range(cnt):
            try:
                state, code = self._kbd.readfrom_mem(KBD_ADDR, REG_KEY, 2)
            except Exception:
                self._kbd = None
                return
            if state != KEY_PRESSED:
                continue
            self._handle_key(code)

    def _handle_key(self, code):
        if code in (8, 127):  # backspace / delete
            if self.buffer:
                self.buffer.pop()
        elif code in (10, 13):  # enter
            self.done = True
        elif code == 27:  # escape
            self.cancelled = True
        elif 32 <= code < 127:
            if len(self.buffer) < self.max_len:
                self.buffer.append(chr(code))
