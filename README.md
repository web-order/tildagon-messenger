# MESH MSG

ESP-NOW mesh messenger for the [Tildagon badge](https://tildagon.badge.emfcamp.org/) at EMF Camp.

## Features

- ESP-NOW mesh chat - messages hop across badges (TTL relay with de-duplication)
- Multiple rooms - `Public` is always first; anyone can add custom rooms, visible to everyone
- Room name travels with each message and appears in the receiver's room list
- Direct messages - pick a peer from the node list and chat 1:1 (also mesh-relayed)
- Node list showing peer ids &amp; usernames, with online indicator and unread badges
- On-screen letter-picker (up/down to choose a glyph, right to add, confirm to send)
- Optional Keebdeck keyboard for direct typing - auto-detects the davedarko KeebDeck Hexpansion (TCA8418, I2C `0x34`) or Solder Party KeebDeck Basic (BBQ10/BBQ20, I2C `0x1F`); keystrokes are re-emitted as `events.input` button events using `KEYBOARD_BUTTONS` (**untested** - no hardware to verify)
- Background listener - receives even when minimised, blinks a unique rainbow LED pattern
- New messages flash across the top quarter of the screen
- Settable username

## Controls

### Rooms

| Button | Action |
|--------|--------|
| Up / Down | Select room |
| C (Confirm) | Open room |
| B (Right) | Node list |
| E (Left) | Add room |
| F (Cancel) | Exit |

### Chat

| Button | Action |
|--------|--------|
| C (Confirm) | Write message |
| Up / Down | Scroll history |
| E (Left) | Set name |
| F (Cancel) | Back to rooms |

### Nodes / direct messages

| Button | Action |
|--------|--------|
| Up / Down | Select peer |
| C (Confirm) | Open direct-message chat |
| E (Left) | Set name |
| B (Right) | Credits |
| F (Cancel) | Back to rooms |

### Text entry (no keyboard)

| Button | Action |
|--------|--------|
| Up / Down | Cycle glyph (a-z 0-9 space) |
| B (Right) | Add glyph |
| C (Confirm) | Send / save |
| F (Cancel) | Delete / back |

With a Keebdeck keyboard plugged in, just type; Enter sends, Esc goes back. (Keyboard hexpansion support is untested - no hardware available to verify.)

## Install

```
mpremote cp app.py :/apps/espnow_messenger/app.py
mpremote cp net.py :/apps/espnow_messenger/net.py
mpremote cp text_entry.py :/apps/espnow_messenger/text_entry.py
mpremote cp keyboard.py :/apps/espnow_messenger/keyboard.py
mpremote cp logo.png :/apps/espnow_messenger/logo.png
mpremote cp tildagon.toml :/apps/espnow_messenger/tildagon.toml
```

## Credits

[@webboggles](https://github.com/web-order) - [weborder.uk](https://weborder.uk)

## Licence

CC-BY-NC-4.0
