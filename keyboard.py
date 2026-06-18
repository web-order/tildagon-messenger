from events.input import ButtonDownEvent, ButtonUpEvent
from events.keyboard import KEYBOARD_BUTTONS
from system.eventbus import eventbus

try:
    from machine import I2C
    _HAS_I2C = True
except ImportError:
    _HAS_I2C = False

# --- TCA8418 keypad controller (davedarko KeebDeck Hexpansion) ---
TCA_ADDR = 0x34
_TCA_CFG = 0x01
_TCA_INT_STAT = 0x02
_TCA_KEY_EC = 0x03          # key event count (low nibble)
_TCA_KEY_EVENT = 0x04       # FIFO event (bit7 = pressed, bits6:0 = keycode)
_TCA_KP_GPIO1 = 0x1D
_TCA_KP_GPIO2 = 0x1E
_TCA_KP_GPIO3 = 0x1F

# Keycode index -> logical name. From the why2025/communicator TCA8418 maps.
TCA_KEYCODES = [
    "NOTHING", "ESCAPE", "SQUARE", "TRIANGLE", "CROSS", "CIRCLE", "CLOUD",
    "DIAMOND", "BACKSPACE", "0", "-", "`", "1", "2", "3", "4", "5", "6", "7",
    "8", "9", "TAB", "Q", "W", "E", "R", "T", "Y", "U", "I", "O", "FN", "A",
    "S", "D", "F", "G", "H", "J", "K", "L", "SHIFT", "Z", "X", "C", "V", "B",
    "N", "M", ",", ".", "LEFT", "DOWN", "RIGHT", "/", "UP", "SHIFT", ";", "'",
    "ENTER", "=", "CTRL", "SOLDERPARTY", "ALT", "\\", "SPACE", "SPACE",
    "SPACE", "ALT", "P", "[", "NA", "NA", "NA", "NA", "NA", "NA", "NA", "NA",
    "NA", "]",
]

# --- BBQ10/BBQ20 keyboard-to-I2C (Solder Party KeebDeck Basic) ---
BBQ_ADDR = 0x1F
_BBQ_KEY = 0x04             # FIFO read (state, keycode-ascii)
_BBQ_KEY_COUNT = 0x05       # pending keys in FIFO (low 5 bits)
_BBQ_PRESSED = 1
_BBQ_HELD = 2
_BBQ_RELEASED = 3

# Shifted glyphs for keys whose base name differs from the shifted symbol.
SHIFT_MAP = {
    "1": "!", "2": "@", "3": "#", "4": "$", "5": "%", "6": "^", "7": "&",
    "8": "*", "9": "(", "0": ")", "-": "_", "`": "~", ",": "<", ".": ">",
    "/": "?", ";": ":", "'": '"', "=": "+", "\\": "|", "[": "{", "]": "}",
}


class KeyboardInput:
    """Detects a Keebdeck keyboard (TCA8418 or BBQ10/20) and re-emits each
    keystroke as a ButtonDownEvent/ButtonUpEvent using KEYBOARD_BUTTONS."""

    def __init__(self):
        self._mode = None       # "tca" | "bbq" | None
        self._i2c = None
        self._shift = False
        if _HAS_I2C:
            self._probe()

    def present(self):
        return self._mode is not None

    # --- Detection ---

    def _probe(self):
        for port in range(1, 7):
            try:
                bus = I2C(port)
                found = bus.scan()
            except Exception:
                continue
            if TCA_ADDR in found:
                self._i2c = bus
                if self._init_tca():
                    self._mode = "tca"
                    return
            if BBQ_ADDR in found:
                self._i2c = bus
                self._mode = "bbq"
                return
        self._i2c = None

    def _init_tca(self):
        try:
            # Route all matrix rows/cols to the keypad engine.
            self._i2c.writeto_mem(TCA_ADDR, _TCA_KP_GPIO1, b"\xff")
            self._i2c.writeto_mem(TCA_ADDR, _TCA_KP_GPIO2, b"\xff")
            self._i2c.writeto_mem(TCA_ADDR, _TCA_KP_GPIO3, b"\x03")
            # Enable key-event interrupt, auto-increment.
            self._i2c.writeto_mem(TCA_ADDR, _TCA_CFG, b"\x91")
            self._i2c.writeto_mem(TCA_ADDR, _TCA_INT_STAT, b"\x01")
            return True
        except Exception:
            return False

    # --- Polling (call once per frame while focused) ---

    def poll(self):
        if self._mode == "tca":
            self._poll_tca()
        elif self._mode == "bbq":
            self._poll_bbq()

    def _poll_tca(self):
        try:
            cnt = self._i2c.readfrom_mem(TCA_ADDR, _TCA_KEY_EC, 1)[0] & 0x0F
        except Exception:
            self._mode = None
            return
        for _ in range(cnt):
            try:
                e = self._i2c.readfrom_mem(TCA_ADDR, _TCA_KEY_EVENT, 1)[0]
            except Exception:
                self._mode = None
                return
            pressed = bool(e & 0x80)
            key = e & 0x7F
            if 0 < key < len(TCA_KEYCODES):
                self._emit_name(TCA_KEYCODES[key], pressed)
        if cnt:
            try:
                self._i2c.writeto_mem(TCA_ADDR, _TCA_INT_STAT, b"\x01")
            except Exception:
                pass

    def _poll_bbq(self):
        try:
            cnt = self._i2c.readfrom_mem(BBQ_ADDR, _BBQ_KEY_COUNT, 1)[0] & 0x1F
        except Exception:
            self._mode = None
            return
        for _ in range(cnt):
            try:
                state, code = self._i2c.readfrom_mem(BBQ_ADDR, _BBQ_KEY, 2)
            except Exception:
                self._mode = None
                return
            self._emit_ascii(code, state)

    # --- Mapping to KEYBOARD_BUTTONS + emit ---

    def _emit_name(self, name, pressed):
        """Handle a logical key name from the TCA8418 (tracks its own shift)."""
        if name in ("NOTHING", "NA", "SOLDERPARTY", "CTRL", "ALT", "TAB"):
            return
        if name in ("SQUARE", "TRIANGLE", "CROSS", "CIRCLE", "CLOUD", "DIAMOND", "FN"):
            return
        if name == "SHIFT":
            self._shift = pressed
            return
        out = SHIFT_MAP.get(name, name) if self._shift else name
        is_letter = self._shift and out == name and len(name) == 1 and name.isalpha()
        self._emit_button(out, pressed, wrap_shift=is_letter)

    def _emit_ascii(self, code, state):
        """Handle a raw ASCII keystroke from the BBQ10/20 keyboard."""
        pressed = state in (_BBQ_PRESSED, _BBQ_HELD)
        name, wrap = _ascii_to_name(code)
        if name is None:
            return
        self._emit_button(name, pressed, wrap_shift=wrap and pressed)

    def _emit_button(self, name, pressed, wrap_shift=False):
        btn = KEYBOARD_BUTTONS.get(name)
        if btn is None:
            return
        if not pressed:
            eventbus.emit(ButtonUpEvent(button=btn))
            return
        if wrap_shift:
            shift_btn = KEYBOARD_BUTTONS["SHIFT"]
            eventbus.emit(ButtonDownEvent(button=shift_btn))
            eventbus.emit(ButtonDownEvent(button=btn))
            eventbus.emit(ButtonUpEvent(button=shift_btn))
        else:
            eventbus.emit(ButtonDownEvent(button=btn))


def _ascii_to_name(code):
    """Map a BBQ ASCII code to (KEYBOARD_BUTTONS name, needs_shift_wrap)."""
    if code in (8, 127):
        return "BACKSPACE", False
    if code in (10, 13):
        return "ENTER", False
    if code == 27:
        return "ESCAPE", False
    if code == 32:
        return "SPACE", False
    if 65 <= code <= 90:            # A-Z -> wrap with SHIFT so case is kept
        return chr(code), True
    if 97 <= code <= 122:           # a-z -> lowercase letter button
        return chr(code).upper(), False
    if 33 <= code <= 126:           # digits and symbols are direct buttons
        return chr(code), False
    return None, False
