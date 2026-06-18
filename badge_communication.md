# Badge-to-Badge Communication

The Tildagon badge (ESP32) supports **ESP-NOW** for direct badge-to-badge radio communication without a router or access point.

## Key Facts

- Works over 2.4&nbsp;GHz Wi-Fi radio, no network join required
- As of **TildagonOS 1.9.0**, broadcast works - no need to know the recipient's MAC address
- Use broadcast MAC `b'\xff\xff\xff\xff\xff\xff'` to reach all listening badges
- Reference implementation: [TildaDrop](https://github.com/ntflix/TildaDrop)
- Full API: [MicroPython ESP-NOW docs](https://docs.micropython.org/en/latest/library/espnow.html)
- Official docs: [Inter-Badge Communication](https://tildagon.badge.emfcamp.org/tildagon-apps/examples/inter-badge-communications/)

## Get Your Badge MAC Address

```python
import network
import ubinascii

wlan_sta = network.WLAN(network.STA_IF)
wlan_sta.active(True)

wlan_mac = wlan_sta.config("mac")
mac_str = ubinascii.hexlify(wlan_mac).decode()
print(f"MAC address: {mac_str}")
```

## Minimal Broadcast Example

```python
import espnow
import network

wlan = network.WLAN(network.STA_IF)
wlan.active(True)

e = espnow.ESPNow()
e.active(True)
e.add_peer(b'\xff\xff\xff\xff\xff\xff')

# Send to all badges in range
e.send(b'\xff\xff\xff\xff\xff\xff', b'hello from mesh msg')

# Receive
host, msg = e.recv()
```

## Mesh Messenger Protocol

This app layers a small mesh protocol on top of ESP-NOW broadcast (see `net.py`):

- **`PKT_HELLO` (0x01)** - periodic presence beacon (`origin_id` + name) so the node list populates without traffic
- **`PKT_MSG` (0x10)** - room message: `ttl`, `origin_id`, `seq`, room, sender name, text
- **`PKT_DM` (0x11)** - direct message: as above plus a `dest_id` for the target peer

Mesh behaviour:

- `origin_id` is the low 2 bytes of the sender's MAC; messages are de-duplicated on `(origin_id, seq)`
- Each unseen packet is re-broadcast with `ttl - 1` until `ttl` reaches 0, giving multi-hop reach
- Room messages are displayed and relayed by everyone; direct messages are only displayed by the addressed peer but still relayed by others
- Caps keep packets within the 250-byte ESP-NOW limit: name 6, room 16, text 100 chars
