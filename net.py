import struct

try:
    from time import ticks_ms, ticks_diff
except ImportError:
    from time import time as _t
    def ticks_ms():
        return int(_t() * 1000)
    def ticks_diff(a, b):
        return a - b

try:
    import espnow
    import network
    _HAS_NET = True
except ImportError:
    _HAS_NET = False

BCAST = b'\xff\xff\xff\xff\xff\xff'

PKT_HELLO = 0x01
PKT_MSG = 0x10
PKT_DM = 0x11

HELLO_INT = 2000
NODE_TIMEOUT = 30000
DEDUP_TTL = 15000
MSG_TTL = 4

NAME_MAX = 6
ROOM_MAX = 16
TEXT_MAX = 100
ROOM_HISTORY = 30
DM_HISTORY = 30

DEFAULT_ROOM = "Public"


class NetManager:
    def __init__(self):
        self._e = None
        self.rx_count = 0
        self.origin_id = 0
        self._seq = 0
        self._hello_t = 0

        self.nodes = {}          # origin_id -> {'name', 'time'}
        self.rooms = [DEFAULT_ROOM]
        self.messages = {DEFAULT_ROOM: []}
        self.dms = {}            # peer_id -> [msgs]
        self.dm_names = {}       # peer_id -> last known name
        self.room_unread = {}    # room -> count
        self.dm_unread = {}      # peer_id -> count
        self._seen = {}          # (origin_id, seq) -> time
        self.inbox = []          # new messages awaiting app pickup

        if _HAS_NET:
            try:
                sta = network.WLAN(network.STA_IF)
                sta.active(True)
                try:
                    sta.disconnect()
                except Exception:
                    pass
                try:
                    sta.config(channel=1)
                except Exception:
                    pass
                try:
                    mac = sta.config('mac')
                    self.origin_id = (mac[4] << 8) | mac[5]
                except Exception:
                    self.origin_id = 0
                self._e = espnow.ESPNow()
                self._e.active(True)
                self._e.add_peer(BCAST)
            except Exception:
                self._e = None

    # --- Rooms ---

    def add_room(self, room):
        room = room.strip()[:ROOM_MAX]
        if room and room not in self.rooms:
            self.rooms.append(room)
            self.messages.setdefault(room, [])
        return room

    def _store_message(self, room, name, text, mine=False):
        buf = self.messages.setdefault(room, [])
        buf.append({'name': name, 'text': text, 'time': ticks_ms(), 'mine': mine})
        if len(buf) > ROOM_HISTORY:
            del buf[0:len(buf) - ROOM_HISTORY]

    def _store_dm(self, peer, name, text, mine=False):
        buf = self.dms.setdefault(peer, [])
        buf.append({'name': name, 'text': text, 'time': ticks_ms(), 'mine': mine})
        if len(buf) > DM_HISTORY:
            del buf[0:len(buf) - DM_HISTORY]

    # --- Unread tracking ---

    def mark_read_room(self, room):
        self.room_unread[room] = 0

    def mark_read_dm(self, peer):
        self.dm_unread[peer] = 0

    # --- Direct messages ---

    def send_dm(self, name, dest, text):
        text = text[:TEXT_MAX]
        self._seq = (self._seq + 1) & 0xFFFF
        self._store_dm(dest, name, text, mine=True)
        self._seen[(self.origin_id, self._seq)] = ticks_ms()
        self._tx_dm(MSG_TTL, self.origin_id, self._seq, dest, name, text)

    def _tx_dm(self, ttl, origin, seq, dest, name, text):
        if not self._e:
            return
        nb = name.encode()[:NAME_MAX]
        tb = text.encode()[:TEXT_MAX]
        pkt = (struct.pack('<BBHHH', PKT_DM, ttl & 0xFF, origin, seq, dest)
               + struct.pack('<B', len(nb)) + nb + tb)
        try:
            self._e.send(BCAST, pkt, False)
        except Exception:
            pass

    def get_dm_thread(self, peer):
        return self.dms.get(peer, [])

    def dm_peers(self):
        """Peers available to DM: currently seen nodes plus any with history."""
        oids = set(self.dms.keys()) | set(self.nodes.keys())
        out = []
        for oid in oids:
            name = (self.nodes.get(oid, {}).get('name')
                    or self.dm_names.get(oid) or '?')
            out.append((oid, name, oid in self.nodes, self.dm_unread.get(oid, 0)))
        out.sort(key=lambda p: (-p[3], not p[2], p[0]))
        return out

    def peer_name(self, oid):
        return ((self.nodes.get(oid, {}).get('name')
                 or self.dm_names.get(oid) or '?')).strip()

    # --- Sending ---

    def send_hello(self, name):
        if not self._e:
            return
        nb = name.encode()[:NAME_MAX]
        pkt = struct.pack('<BH', PKT_HELLO, self.origin_id) + nb
        try:
            self._e.send(BCAST, pkt, False)
        except Exception:
            pass

    def send_message(self, name, room, text):
        room = room.strip()[:ROOM_MAX]
        text = text[:TEXT_MAX]
        self._seq = (self._seq + 1) & 0xFFFF
        self.add_room(room)
        self._store_message(room, name, text, mine=True)
        self._seen[(self.origin_id, self._seq)] = ticks_ms()
        self._tx_message(MSG_TTL, self.origin_id, self._seq, name, room, text)

    def _tx_message(self, ttl, origin, seq, name, room, text):
        if not self._e:
            return
        rb = room.encode()[:ROOM_MAX]
        nb = name.encode()[:NAME_MAX]
        tb = text.encode()[:TEXT_MAX]
        pkt = (struct.pack('<BBHH', PKT_MSG, ttl & 0xFF, origin, seq)
               + struct.pack('<B', len(rb)) + rb
               + struct.pack('<B', len(nb)) + nb
               + tb)
        try:
            self._e.send(BCAST, pkt, False)
        except Exception:
            pass

    def tick(self, name, delta):
        self._hello_t += delta
        if self._hello_t >= HELLO_INT:
            self._hello_t = 0
            self.send_hello(name)

    # --- Receiving ---

    def receive(self):
        """Drain inbound packets. Returns number of newly displayed messages."""
        if not self._e:
            return 0
        new_msgs = 0
        now = ticks_ms()

        for _ in range(12):
            try:
                if not self._e.any():
                    break
                mac, data = self._e.irecv(0)
            except Exception:
                break
            if mac is None or data is None or len(data) < 1:
                continue
            self.rx_count += 1
            pt = data[0]

            if pt == PKT_HELLO and len(data) >= 3:
                oid = struct.unpack('<H', data[1:3])[0]
                try:
                    pname = data[3:3 + NAME_MAX].decode('utf-8')
                except Exception:
                    pname = 'anon'
                if oid != self.origin_id:
                    self.nodes[oid] = {'name': pname, 'time': now}

            elif pt == PKT_MSG and len(data) >= 7:
                if self._handle_msg(data, now):
                    new_msgs += 1

            elif pt == PKT_DM and len(data) >= 9:
                if self._handle_dm(data, now):
                    new_msgs += 1

        self._expire(now)
        return new_msgs

    def _handle_msg(self, data, now):
        try:
            _, ttl, origin, seq = struct.unpack('<BBHH', data[:6])
            i = 6
            rlen = data[i]; i += 1
            room = data[i:i + rlen].decode('utf-8'); i += rlen
            nlen = data[i]; i += 1
            name = data[i:i + nlen].decode('utf-8'); i += nlen
            text = data[i:].decode('utf-8')
        except Exception:
            return False

        if origin == self.origin_id:
            return False
        key = (origin, seq)
        if key in self._seen:
            return False
        self._seen[key] = now

        self.nodes[origin] = {'name': name, 'time': now}
        self.dm_names[origin] = name
        self.add_room(room)
        self._store_message(room, name, text, mine=False)
        self.room_unread[room] = self.room_unread.get(room, 0) + 1
        self.inbox.append({'kind': 'room', 'name': name, 'room': room, 'text': text})

        if ttl > 1:
            self._tx_message(ttl - 1, origin, seq, name, room, text)
        return True

    def _handle_dm(self, data, now):
        try:
            _, ttl, origin, seq, dest = struct.unpack('<BBHHH', data[:8])
            i = 8
            nlen = data[i]; i += 1
            name = data[i:i + nlen].decode('utf-8'); i += nlen
            text = data[i:].decode('utf-8')
        except Exception:
            return False

        if origin == self.origin_id:
            return False
        key = (origin, seq)
        if key in self._seen:
            return False
        self._seen[key] = now

        self.nodes[origin] = {'name': name, 'time': now}
        self.dm_names[origin] = name

        if dest == self.origin_id:
            self._store_dm(origin, name, text, mine=False)
            self.dm_unread[origin] = self.dm_unread.get(origin, 0) + 1
            self.inbox.append({'kind': 'dm', 'peer': origin, 'name': name, 'text': text})
            return True

        # Not for us - relay onward so it crosses the mesh.
        if ttl > 1:
            self._tx_dm(ttl - 1, origin, seq, dest, name, text)
        return False

    def pop_inbox(self):
        if not self.inbox:
            return None
        return self.inbox.pop(0)

    def _expire(self, now):
        dead = [k for k, v in self.nodes.items()
                if ticks_diff(now, v['time']) > NODE_TIMEOUT]
        for k in dead:
            del self.nodes[k]
        old = [k for k, t in self._seen.items()
               if ticks_diff(now, t) > DEDUP_TTL]
        for k in old:
            del self._seen[k]

    def close(self):
        if self._e:
            try:
                self._e.active(False)
            except Exception:
                pass
