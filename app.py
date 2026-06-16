import app
import math
import sys
import os
import random

from events.input import Buttons, BUTTON_TYPES

try:
    from time import ticks_ms, ticks_diff
except ImportError:
    from time import time as _t
    def ticks_ms():
        return int(_t() * 1000)
    def ticks_diff(a, b):
        return a - b

if sys.implementation.name == "micropython":
    _apps = os.listdir("/apps")
    _dir = "/apps/espnow_messenger"
    for _d in _apps:
        if "messenger" in _d.lower():
            _dir = "/apps/" + _d
            break
    if _dir not in sys.path:
        sys.path.insert(0, _dir)
    ASSET_PATH = _dir + "/"
else:
    ASSET_PATH = "./"

import net
from text_entry import TextEntry

try:
    import imu
    _HAS_IMU = True
except ImportError:
    _HAS_IMU = False

try:
    from tildagonos import tildagonos
    from system.eventbus import eventbus
    from system.patterndisplay.events import PatternDisable, PatternEnable
    _HAS_LEDS = True
except ImportError:
    _HAS_LEDS = False

STATE_ROOMS = 0
STATE_CHAT = 1
STATE_COMPOSE = 2
STATE_ADD_ROOM = 3
STATE_NAME = 4
STATE_NODES = 5
STATE_CREDITS = 6
STATE_DM_CHAT = 7
STATE_DM_COMPOSE = 8
STATE_SPLASH = 9

FLASH_DUR = 3000
LED_BLINK_DUR = 1500
SPLASH_DUR = 4200
SPLASH_FLY = 1100

SCREEN_R = 115  # round display radius, with a small safety margin

# --- Spaceagon palette: black bg, yellow-orange-red highlights ---
C_YEL = (1.0, 0.82, 0.15)
C_ORG = (1.0, 0.5, 0.05)
C_RED = (0.92, 0.2, 0.08)
C_TXT = (0.95, 0.72, 0.3)
C_DIM = (0.6, 0.4, 0.15)

# Button locations around the round screen, degrees clockwise from top.
# Derived from the badge LED/button pairs: UP=top, DOWN=bottom, 60 deg apart.
BTN_ANGLE = {
    "UP": 0,
    "RIGHT": 60,
    "CONFIRM": 120,
    "DOWN": 180,
    "LEFT": 240,
    "CANCEL": 300,
}
DEG = 0.01745329


class MessengerApp(app.App):
    def __init__(self):
        self.button_states = Buttons(self)
        self.state = STATE_SPLASH
        self.splash_t = 0

        self.player_name = self._load_name()
        self.net_mgr = net.NetManager()
        self._load_rooms()

        self.room_sel = 0
        self.node_sel = 0
        self.chat_scroll = 0
        self.entry = None
        self.dm_peer = None
        self.name_return_state = STATE_CHAT

        self.flash_t = 0
        self.flash_msg = None
        self.led_blink_t = 0
        self._led_phase = 0.0

        self.tilt_x = 0.0
        self.tilt_y = 0.0

        self._stars = self._make_stars(34)
        self._splash_stars = self._make_splash_stars(7)

        if _HAS_LEDS:
            eventbus.emit(PatternDisable())

    # --- Background (runs even when minimised) ---

    def background_update(self, delta):
        self.net_mgr.tick(self.player_name, delta)
        if self.net_mgr.receive() > 0:
            self._on_new_messages()
        self._led_update(delta)

    def _on_new_messages(self):
        msg = self.net_mgr.pop_inbox()
        got = False
        while msg:
            self.flash_msg = msg
            self.flash_t = FLASH_DUR
            got = True
            msg = self.net_mgr.pop_inbox()
        if got:
            self.led_blink_t = LED_BLINK_DUR

    # --- Update dispatch ---

    def update(self, delta):
        if self.flash_t > 0:
            self.flash_t -= delta
        if self.state == STATE_SPLASH:
            self._up_splash(delta)
        elif self.state == STATE_ROOMS:
            self._up_rooms()
        elif self.state == STATE_CHAT:
            self._up_chat()
        elif self.state == STATE_DM_CHAT:
            self._up_dm()
        elif self.state in (STATE_COMPOSE, STATE_DM_COMPOSE, STATE_ADD_ROOM, STATE_NAME):
            self._up_entry()
        elif self.state == STATE_NODES:
            self._up_nodes()
        elif self.state == STATE_CREDITS:
            self._up_credits(delta)

    def _up_splash(self, delta):
        self.splash_t += delta
        if self.splash_t >= SPLASH_DUR:
            self.state = STATE_ROOMS
            return
        if self.splash_t > 400:
            for btn in BUTTON_TYPES.values():
                if self.button_states.get(btn):
                    self.button_states.clear()
                    self.state = STATE_ROOMS
                    return

    def _rooms(self):
        return self.net_mgr.rooms

    def _up_rooms(self):
        rooms = self._rooms()
        if self.button_states.get(BUTTON_TYPES["UP"]):
            self.button_states.clear()
            self.room_sel = (self.room_sel - 1) % len(rooms)
        elif self.button_states.get(BUTTON_TYPES["DOWN"]):
            self.button_states.clear()
            self.room_sel = (self.room_sel + 1) % len(rooms)
        elif self.button_states.get(BUTTON_TYPES["CONFIRM"]):
            self.button_states.clear()
            self.chat_scroll = 0
            self.state = STATE_CHAT
        elif self.button_states.get(BUTTON_TYPES["RIGHT"]):
            self.button_states.clear()
            self.state = STATE_NODES
        elif self.button_states.get(BUTTON_TYPES["LEFT"]):
            self.button_states.clear()
            self.entry = TextEntry("", net.ROOM_MAX)
            self.state = STATE_ADD_ROOM
        elif self.button_states.get(BUTTON_TYPES["CANCEL"]):
            self.button_states.clear()
            self._leds_restore()
            self.minimise()

    def _cur_room(self):
        rooms = self._rooms()
        return rooms[self.room_sel % len(rooms)]

    def _up_chat(self):
        room = self._cur_room()
        self.net_mgr.mark_read_room(room)
        msgs = self.net_mgr.messages.get(room, [])
        if self.button_states.get(BUTTON_TYPES["CONFIRM"]):
            self.button_states.clear()
            self.entry = TextEntry("", net.TEXT_MAX)
            self.state = STATE_COMPOSE
        elif self.button_states.get(BUTTON_TYPES["UP"]):
            self.button_states.clear()
            self.chat_scroll = min(self.chat_scroll + 1, max(0, len(msgs) - 1))
        elif self.button_states.get(BUTTON_TYPES["DOWN"]):
            self.button_states.clear()
            self.chat_scroll = max(0, self.chat_scroll - 1)
        elif self.button_states.get(BUTTON_TYPES["LEFT"]):
            self.button_states.clear()
            self.name_return_state = STATE_CHAT
            self.entry = TextEntry(self.player_name.strip(), net.NAME_MAX)
            self.state = STATE_NAME
        elif self.button_states.get(BUTTON_TYPES["CANCEL"]):
            self.button_states.clear()
            self.state = STATE_ROOMS

    def _up_dm(self):
        self.net_mgr.mark_read_dm(self.dm_peer)
        msgs = self.net_mgr.get_dm_thread(self.dm_peer)
        if self.button_states.get(BUTTON_TYPES["CONFIRM"]):
            self.button_states.clear()
            self.entry = TextEntry("", net.TEXT_MAX)
            self.state = STATE_DM_COMPOSE
        elif self.button_states.get(BUTTON_TYPES["UP"]):
            self.button_states.clear()
            self.chat_scroll = min(self.chat_scroll + 1, max(0, len(msgs) - 1))
        elif self.button_states.get(BUTTON_TYPES["DOWN"]):
            self.button_states.clear()
            self.chat_scroll = max(0, self.chat_scroll - 1)
        elif self.button_states.get(BUTTON_TYPES["CANCEL"]):
            self.button_states.clear()
            self.state = STATE_NODES

    def _up_entry(self):
        self.entry.update(self.button_states)
        if self.entry.done:
            txt = self.entry.text().strip()
            if self.state == STATE_COMPOSE:
                if txt:
                    self.net_mgr.send_message(self.player_name, self._cur_room(), txt)
                self.state = STATE_CHAT
            elif self.state == STATE_DM_COMPOSE:
                if txt and self.dm_peer is not None:
                    self.net_mgr.send_dm(self.player_name, self.dm_peer, txt)
                self.state = STATE_DM_CHAT
            elif self.state == STATE_ADD_ROOM:
                if txt:
                    room = self.net_mgr.add_room(txt)
                    self._save_rooms()
                    if room in self._rooms():
                        self.room_sel = self._rooms().index(room)
                self.state = STATE_ROOMS
            elif self.state == STATE_NAME:
                if txt:
                    self.player_name = (txt + "      ")[:net.NAME_MAX]
                    self._save_name()
                self.state = self.name_return_state
            self.entry = None
        elif self.entry.cancelled:
            if self.state == STATE_COMPOSE:
                self.state = STATE_CHAT
            elif self.state == STATE_DM_COMPOSE:
                self.state = STATE_DM_CHAT
            elif self.state == STATE_NAME:
                self.state = self.name_return_state
            else:
                self.state = STATE_ROOMS
            self.entry = None

    def _up_nodes(self):
        peers = self.net_mgr.dm_peers()
        n = len(peers)
        if self.button_states.get(BUTTON_TYPES["UP"]):
            self.button_states.clear()
            if n:
                self.node_sel = (self.node_sel - 1) % n
        elif self.button_states.get(BUTTON_TYPES["DOWN"]):
            self.button_states.clear()
            if n:
                self.node_sel = (self.node_sel + 1) % n
        elif self.button_states.get(BUTTON_TYPES["CONFIRM"]):
            self.button_states.clear()
            if n:
                self.dm_peer = peers[self.node_sel % n][0]
                self.net_mgr.mark_read_dm(self.dm_peer)
                self.chat_scroll = 0
                self.state = STATE_DM_CHAT
        elif self.button_states.get(BUTTON_TYPES["LEFT"]):
            self.button_states.clear()
            self.name_return_state = STATE_NODES
            self.entry = TextEntry(self.player_name.strip(), net.NAME_MAX)
            self.state = STATE_NAME
        elif self.button_states.get(BUTTON_TYPES["RIGHT"]):
            self.button_states.clear()
            self.state = STATE_CREDITS
        elif self.button_states.get(BUTTON_TYPES["CANCEL"]):
            self.button_states.clear()
            self.state = STATE_ROOMS

    def _up_credits(self, delta):
        if _HAS_IMU:
            try:
                acc = imu.acc_read()
                self.tilt_x = acc[0] * 0.5
                self.tilt_y = acc[1] * 0.5
            except Exception:
                pass
        for btn in BUTTON_TYPES.values():
            if self.button_states.get(btn):
                self.button_states.clear()
                self.state = STATE_ROOMS
                return

    # --- Draw dispatch ---

    def draw(self, ctx):
        ctx.save()
        if self.state == STATE_SPLASH:
            self._dr_splash(ctx)
        elif self.state == STATE_ROOMS:
            self._dr_rooms(ctx)
        elif self.state == STATE_CHAT:
            self._dr_chat(ctx)
        elif self.state == STATE_DM_CHAT:
            self._dr_dm(ctx)
        elif self.state == STATE_COMPOSE:
            self._dr_entry(ctx, "MESSAGE", "#" + self._cur_room())
        elif self.state == STATE_DM_COMPOSE:
            self._dr_entry(ctx, "DM", self.net_mgr.peer_name(self.dm_peer))
        elif self.state == STATE_ADD_ROOM:
            self._dr_entry(ctx, "NEW ROOM", "")
        elif self.state == STATE_NAME:
            self._dr_entry(ctx, "YOUR NAME", "")
        elif self.state == STATE_NODES:
            self._dr_nodes(ctx)
        elif self.state == STATE_CREDITS:
            self._dr_credits(ctx)
        if self.flash_t > 0 and self.flash_msg:
            self._dr_flash(ctx)
        ctx.restore()

    @staticmethod
    def _make_stars(n):
        stars = []
        for _ in range(n):
            while True:
                x = random.uniform(-112, 112)
                y = random.uniform(-112, 112)
                if x * x + y * y <= SCREEN_R * SCREEN_R:
                    break
            stars.append((x, y, random.uniform(0.18, 0.6), random.choice((1, 1, 1, 2))))
        return stars

    def _bg(self, ctx):
        ctx.rgb(0.0, 0.0, 0.0).rectangle(-120, -120, 240, 240).fill()
        for x, y, b, s in self._stars:
            ctx.rgb(b, b * 0.78, b * 0.4).rectangle(x, y, s, s).fill()

    # --- Splash animation ---

    @staticmethod
    def _make_splash_stars(n):
        out = []
        for _ in range(n):
            ang = random.uniform(0, 6.2832)
            dist = random.uniform(36, 104)
            fx = math.cos(ang) * dist
            fy = math.sin(ang) * dist * 0.85 - 8
            R = random.uniform(6, 15)
            ph = random.uniform(0, 6.2832)
            d = random.uniform(0, 6.2832)
            out.append((fx, fy, R, ph, math.cos(d), math.sin(d)))
        return out

    @staticmethod
    def _sparkle(ctx, cx, cy, R, rot):
        """Sharp 4-point star: rhombus tips with concave bezier sides."""
        ir = R * 0.16
        tips = []
        for k in range(4):
            a = rot + k * 1.5708
            tips.append((cx + math.cos(a) * R, cy + math.sin(a) * R))
        ctx.begin_path()
        ctx.move_to(*tips[0])
        for k in range(4):
            ma = rot + (k + 0.5) * 1.5708
            ix = cx + math.cos(ma) * ir
            iy = cy + math.sin(ma) * ir
            nx, ny = tips[(k + 1) % 4]
            ctx.curve_to(ix, iy, ix, iy, nx, ny)
        ctx.fill()

    def _planet_body(self, ctx, cx, cy, r, spin):
        steps = 7
        for k in range(steps, 0, -1):
            rad = r * k / steps
            f = 1.0 - k / steps  # 0 edge .. ~1 centre
            ctx.rgb(0.5 + 0.5 * f, 0.18 + 0.42 * f, 0.0 + 0.15 * f)
            ctx.begin_path()
            ctx.arc(cx, cy, rad, 0, 6.2832, 0)
            ctx.fill()
        bands = 4
        for k in range(bands):
            ph = ((spin * 0.5) + k / bands) % 1.0
            xb = (ph * 2 - 1) * r
            if abs(xb) >= r:
                continue
            hh = math.sqrt(r * r - xb * xb) * 0.95
            edgef = 1 - abs(xb) / r
            ctx.rgba(0.85, 0.3 * edgef + 0.1, 0.0, 0.16)
            ctx.rectangle(cx + xb - 1.5, cy - hh, 3, hh * 2).fill()
        ctx.begin_path()
        ctx.arc(cx - r * 0.32, cy - r * 0.32, r * 0.46, 0, 6.2832, 0)
        ctx.rgba(1.0, 0.85, 0.45, 0.28)
        ctx.fill()

    def _draw_planet(self, ctx, cx, cy, r, spin):
        tilt = -0.5
        squash = 0.30 + 0.12 * math.sin(spin * 0.7)
        rout = r * 1.7
        # ring (back, full)
        ctx.save()
        ctx.translate(cx, cy)
        ctx.rotate(tilt)
        ctx.scale(1.0, squash)
        ctx.line_width = r * 0.16
        ctx.rgba(0.6, 0.3, 0.05, 0.7)
        ctx.begin_path()
        ctx.arc(0, 0, rout, 0, 6.2832, 0)
        ctx.stroke()
        ctx.restore()
        # planet
        self._planet_body(ctx, cx, cy, r, spin)
        # ring (front, near half over planet)
        ctx.save()
        ctx.translate(cx, cy)
        ctx.rotate(tilt)
        ctx.scale(1.0, squash)
        ctx.line_width = r * 0.16
        ctx.rgba(1.0, 0.6, 0.1, 0.95)
        ctx.begin_path()
        ctx.arc(0, 0, rout, 0, 3.1416, 0)
        ctx.stroke()
        ctx.restore()

    def _dr_splash(self, ctx):
        t = self.splash_t
        ctx.rgb(0.0, 0.0, 0.0).rectangle(-120, -120, 240, 240).fill()

        for x, y, b, s in self._stars:
            tw = 0.35 + 0.65 * abs(math.sin(t * 0.004 + x * 0.05 + y * 0.03))
            bb = b * tw
            ctx.rgb(bb, bb * 0.8, bb * 0.4).rectangle(x, y, s, s).fill()

        fly = min(1.0, t / SPLASH_FLY)
        ease = 1 - (1 - fly) ** 3

        py = -6 - (1 - ease) * 70
        pr = 8 + 44 * ease
        self._draw_planet(ctx, 0, py, pr, t * 0.004)

        for fx, fy, R, ph, dx, dy in self._splash_stars:
            sx = fx + dx * (1 - ease) * 150
            sy = fy + dy * (1 - ease) * 150
            tw = 0.5 + 0.5 * math.sin(t * 0.006 + ph)
            ctx.rgba(1.0, 0.68 + 0.27 * tw, 0.12 + 0.3 * tw, ease * (0.45 + 0.55 * tw))
            self._sparkle(ctx, sx, sy, R * (0.55 + 0.45 * tw), t * 0.0015 + ph)

        if t > 600:
            ta = min(1.0, (t - 600) / 600)
            ctx.font_size = 27
            s = "MESH MSG"
            ctx.rgba(1.0, 0.5, 0.05, ta)
            ctx.move_to(-ctx.text_width(s) * 0.5, 80 + (1 - ta) * 12).text(s)

        if t > 1700:
            ta = min(1.0, (t - 1700) / 400)
            ctx.font_size = 11
            h = "weborder.uk"
            ctx.rgba(0.55, 0.35, 0.12, ta)
            ctx.move_to(-ctx.text_width(h) * 0.5, 104).text(h)

    @staticmethod
    def _window(count, sel, size):
        if count <= size:
            return 0
        start = sel - size // 2
        return max(0, min(start, count - size))

    @staticmethod
    def _safe_half(y, fs):
        """Half-width available inside the round display at baseline y."""
        yy = abs(y) + fs * 0.5
        r2 = SCREEN_R * SCREEN_R - yy * yy
        if r2 <= 1:
            return 0.0
        return math.sqrt(r2)

    def _ctext(self, ctx, s, y, fs, pad=6):
        """Draw text centred horizontally, truncated to fit the circle at y."""
        ctx.font_size = fs
        maxw = max(0.0, 2 * self._safe_half(y, fs) - pad * 2)
        while s and ctx.text_width(s) > maxw:
            s = s[:-1]
        ctx.move_to(-ctx.text_width(s) * 0.5, y).text(s)
        return s

    def _cbar(self, ctx, y, h, fs, cap=104):
        """Selection bar centred and clamped to the circle at y."""
        hw = min(cap, self._safe_half(y, fs))
        ctx.rectangle(-hw, y - h * 0.72, hw * 2, h).fill()

    def _arc_label(self, ctx, text, deg, fs, color):
        """Draw a short label as text-on-path along the inner rim at `deg`."""
        ctx.rgb(*color)
        ctx.font_size = fs
        radius = SCREEN_R - 1
        widths = [ctx.text_width(c) for c in text]
        ext = sum(widths) / radius
        base = deg * DEG
        flip = 90 < (deg % 360) < 270
        d = -fs if flip else fs
        if not flip:
            a = base - ext * 0.5
            for c, w in zip(text, widths):
                ca = a + (w * 0.5) / radius
                ctx.save()
                ctx.translate(radius * math.sin(ca), -radius * math.cos(ca))
                ctx.rotate(ca)
                ctx.move_to(-w * 0.5, d).text(c)
                ctx.restore()
                a += w / radius
        else:
            a = base + ext * 0.5
            for c, w in zip(text, widths):
                ca = a - (w * 0.5) / radius
                ctx.save()
                ctx.translate(radius * math.sin(ca), -radius * math.cos(ca))
                ctx.rotate(ca + math.pi)
                ctx.move_to(-w * 0.5, d).text(c)
                ctx.restore()
                a -= w / radius

    def _hints(self, ctx, mapping, fs=12, color=C_DIM):
        for btn, label in mapping.items():
            self._arc_label(ctx, label, BTN_ANGLE[btn], fs, color)

    def _dr_rooms(self, ctx):
        self._bg(ctx)
        ctx.rgb(*C_ORG)
        self._ctext(ctx, "ROOMS", -74, 20)

        rooms = self._rooms()
        visible = 4
        start = self._window(len(rooms), self.room_sel, visible)
        y = -36
        for i in range(start, min(len(rooms), start + visible)):
            room = rooms[i]
            unread = self.net_mgr.room_unread.get(room, 0)
            label = room + (" ({})".format(unread) if unread else "")
            if i == self.room_sel:
                ctx.rgb(*C_ORG)
                self._cbar(ctx, y, 26, 17)
                ctx.rgb(0.0, 0.0, 0.0)
            elif i == 0:
                ctx.rgb(*C_YEL)
            else:
                ctx.rgb(*C_TXT)
            self._ctext(ctx, label, y, 17)
            y += 28

        self._hints(ctx, {"CONFIRM": "open", "RIGHT": "nodes",
                          "LEFT": "+room", "CANCEL": "exit"})

    def _dr_msgs(self, ctx, msgs):
        visible = 6
        end = len(msgs) - self.chat_scroll
        start = max(0, end - visible)
        y = -44
        for m in msgs[start:end]:
            if m['mine']:
                ctx.rgb(*C_YEL)
            else:
                ctx.rgb(*C_ORG)
            line = "{}: {}".format(m['name'].strip(), m['text'])
            self._ctext(ctx, line, y, 13)
            y += 19

    def _dr_chat(self, ctx):
        self._bg(ctx)
        ctx.rgb(*C_ORG)
        self._ctext(ctx, "#" + self._cur_room(), -76, 18)
        self._dr_msgs(ctx, self.net_mgr.messages.get(self._cur_room(), []))
        self._hints(ctx, {"CONFIRM": "write", "LEFT": "name",
                          "CANCEL": "back", "UP": "scroll"})

    def _dr_dm(self, ctx):
        self._bg(ctx)
        ctx.rgb(*C_RED)
        self._ctext(ctx, "DM " + self.net_mgr.peer_name(self.dm_peer), -76, 18)
        self._dr_msgs(ctx, self.net_mgr.get_dm_thread(self.dm_peer))
        self._hints(ctx, {"CONFIRM": "write", "CANCEL": "back", "UP": "scroll"})

    def _dr_entry(self, ctx, title, sub):
        self._bg(ctx)
        ctx.rgb(*C_ORG)
        self._ctext(ctx, title, -72, 18)
        if sub:
            ctx.rgb(*C_DIM)
            self._ctext(ctx, sub, -52, 13)

        ctx.rgb(*C_TXT)
        self._ctext(ctx, self.entry.text()[-30:], -6, 16)

        if not self.entry.has_keyboard():
            g = self.entry.cur_glyph()
            disp = "[ space ]" if g == " " else "[ {} ]".format(g)
            ctx.rgb(*C_YEL)
            self._ctext(ctx, disp, 38, 30)
            self._hints(ctx, {"UP": "char", "DOWN": "char", "RIGHT": "add",
                              "CONFIRM": "send", "CANCEL": "del"})
        else:
            self._hints(ctx, {"CONFIRM": "send", "CANCEL": "back"})

    def _dr_nodes(self, ctx):
        self._bg(ctx)
        ctx.rgb(*C_ORG)
        self._ctext(ctx, "NODES", -80, 18)
        ctx.rgb(*C_YEL)
        self._ctext(ctx, "you  " + self.player_name.strip(), -58, 13)

        peers = self.net_mgr.dm_peers()
        visible = 5
        start = self._window(len(peers), self.node_sel, visible)
        y = -36
        if not peers:
            ctx.rgb(*C_DIM)
            self._ctext(ctx, "(no peers yet)", y, 14)
        for i in range(start, min(len(peers), start + visible)):
            oid, name, online, unread = peers[i]
            label = "{:04x} {}".format(oid, name.strip())
            if unread:
                label += " ({})".format(unread)
            if i == self.node_sel:
                ctx.rgb(*C_ORG)
                self._cbar(ctx, y, 24, 14)
                ctx.rgb(0.0, 0.0, 0.0)
            elif online:
                ctx.rgb(*C_TXT)
            else:
                ctx.rgb(0.5, 0.32, 0.2)
            shown = self._ctext(ctx, label, y, 14, pad=16)
            w = ctx.text_width(shown)
            ctx.rgb(*(C_YEL if online else (0.5, 0.15, 0.08)))
            ctx.rectangle(-w * 0.5 - 14, y - 9, 7, 7).fill()
            y += 23

        self._hints(ctx, {"CONFIRM": "dm", "LEFT": "name",
                          "RIGHT": "credits", "CANCEL": "back"})

    def _dr_credits(self, ctx):
        self._bg(ctx)
        tx, ty = self.tilt_x, self.tilt_y

        lw, lh = 128, 71
        ctx.image(ASSET_PATH + "logo.png", -lw * 0.5 + tx, -94 + ty, lw, lh)

        lines = [
            ("@webboggles", C_YEL),
            ("weborder.uk", C_ORG),
            ("", None),
            ("ESP-NOW Mesh Chat", C_DIM),
            ("Hop mesh rooms", C_DIM),
        ]
        y = -4
        for txt, col in lines:
            if not txt:
                y += 10
                continue
            ctx.rgb(*col)
            fs = 14
            ctx.font_size = fs
            yy = y + ty * 0.5
            maxw = max(0.0, 2 * self._safe_half(yy, fs) - 12)
            s = txt
            while s and ctx.text_width(s) > maxw:
                s = s[:-1]
            ctx.move_to(-ctx.text_width(s) * 0.5 + tx * 0.5, yy).text(s)
            y += 19

        self._hints(ctx, {"CANCEL": "back"})

    def _dr_flash(self, ctx):
        m = self.flash_msg
        a = min(0.9, self.flash_t / 600.0)
        is_dm = m.get('kind') == 'dm'
        if is_dm:
            ctx.rgba(0.45, 0.08, 0.0, a).rectangle(-120, -112, 240, 66).fill()
            head = "DM {}".format(m['name'].strip())
            ctx.rgb(*C_RED)
        else:
            ctx.rgba(0.4, 0.22, 0.0, a).rectangle(-120, -112, 240, 66).fill()
            head = "#{} {}".format(m['room'][:10], m['name'].strip())
            ctx.rgb(*C_YEL)
        self._ctext(ctx, head, -90, 13)
        ctx.rgb(1.0, 0.95, 0.85)
        self._ctext(ctx, m['text'], -68, 15)

    # --- Persistence ---

    def _load_name(self):
        try:
            with open(ASSET_PATH + "name.txt", "r") as f:
                n = f.read().strip()[:net.NAME_MAX]
                if n:
                    return (n + "      ")[:net.NAME_MAX]
        except Exception:
            pass
        name = "".join(random.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(4))
        return (name + "      ")[:net.NAME_MAX]

    def _save_name(self):
        try:
            with open(ASSET_PATH + "name.txt", "w") as f:
                f.write(self.player_name)
        except Exception:
            pass

    def _load_rooms(self):
        try:
            with open(ASSET_PATH + "rooms.txt", "r") as f:
                for line in f:
                    self.net_mgr.add_room(line.strip())
        except Exception:
            pass

    def _save_rooms(self):
        try:
            custom = [r for r in self.net_mgr.rooms if r != net.DEFAULT_ROOM]
            with open(ASSET_PATH + "rooms.txt", "w") as f:
                f.write("\n".join(custom))
        except Exception:
            pass

    # --- Lifecycle ---

    def background(self):
        self._leds_restore()

    # --- LEDs ---

    def _leds_restore(self):
        if _HAS_LEDS:
            eventbus.emit(PatternEnable())

    def _led_update(self, delta):
        if not _HAS_LEDS:
            return
        if self.led_blink_t > 0:
            self.led_blink_t -= delta
            self._led_phase += delta * 0.012
            for i in range(12):
                h = (self._led_phase + i / 12.0) % 1.0
                tildagonos.leds[i + 1] = self._fire(h)
            tildagonos.leds.write()
            if self.led_blink_t <= 0:
                for i in range(12):
                    tildagonos.leds[i + 1] = (0, 0, 0)
                tildagonos.leds.write()

    def _fire(self, h):
        """Warm red -> orange -> yellow chase to match the Spaceagon theme."""
        t = abs((h * 2.0) - 1.0)  # 0..1..0, smooth loop
        r = 120
        g = int(20 + 90 * t)
        b = int(8 * t)
        return (r, g, b)


__app_export__ = MessengerApp
