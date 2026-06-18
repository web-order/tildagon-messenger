from events.input import BUTTON_TYPES, ButtonDownEvent, ButtonUpEvent
from system.eventbus import eventbus

GLYPHS = "abcdefghijklmnopqrstuvwxyz0123456789 "
START_GLYPH = GLYPHS.index("n")  # middle of the alphabet


class TextEntry:
    """Letter-picker (up/down/right) with optional Keebdeck keyboard input.

    When a keyboard is present, typed characters arrive as ButtonDownEvents
    carrying KEYBOARD_BUTTONS (emitted by keyboard.KeyboardInput); hardware
    buttons still work as a fallback for send/back."""

    def __init__(self, initial="", max_len=100, app=None, has_keyboard=False):
        self.max_len = max_len
        self.buffer = list(initial[:max_len])
        self.cur = START_GLYPH  # index into GLYPHS for the glyph being selected
        self.done = False
        self.cancelled = False
        self._app = app
        self._kbd = has_keyboard and app is not None
        self._shift = False
        if self._kbd:
            eventbus.on(ButtonDownEvent, self._on_key_down, app)
            eventbus.on(ButtonUpEvent, self._on_key_up, app)

    def has_keyboard(self):
        return self._kbd

    def close(self):
        if self._kbd:
            eventbus.remove(ButtonDownEvent, self._on_key_down, self._app)
            eventbus.remove(ButtonUpEvent, self._on_key_up, self._app)

    def text(self):
        return "".join(self.buffer)

    def cur_glyph(self):
        return GLYPHS[self.cur]

    def _append(self, ch):
        if len(self.buffer) < self.max_len:
            self.buffer.append(ch)

    # --- Hardware buttons ---

    def update(self, button_states):
        if self._kbd:
            # Typing is driven by keyboard events; keep hardware send/back.
            if button_states.get(BUTTON_TYPES["CONFIRM"]):
                button_states.clear()
                self.done = True
            elif button_states.get(BUTTON_TYPES["CANCEL"]):
                button_states.clear()
                self.cancelled = True
            return

        if button_states.get(BUTTON_TYPES["UP"]):
            button_states.clear()
            self.cur = (self.cur - 1) % len(GLYPHS)
        elif button_states.get(BUTTON_TYPES["DOWN"]):
            button_states.clear()
            self.cur = (self.cur + 1) % len(GLYPHS)
        elif button_states.get(BUTTON_TYPES["RIGHT"]):
            button_states.clear()
            self._append(GLYPHS[self.cur])
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

    # --- Keyboard events (KEYBOARD_BUTTONS group) ---

    def _on_key_down(self, event):
        btn = event.button.find_parent_in_group("Keyboard")
        if btn is None:
            return
        name = btn.name
        if name == "SHIFT":
            self._shift = True
        elif name == "ENTER":
            self.done = True
        elif name == "ESCAPE":
            self.cancelled = True
        elif name == "BACKSPACE":
            if self.buffer:
                self.buffer.pop()
        elif name == "SPACE":
            self._append(" ")
        elif len(name) == 1:
            self._append(name if self._shift else name.lower())

    def _on_key_up(self, event):
        btn = event.button.find_parent_in_group("Keyboard")
        if btn is not None and btn.name == "SHIFT":
            self._shift = False
