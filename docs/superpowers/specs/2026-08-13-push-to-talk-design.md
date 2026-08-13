# Push-to-Talk for Voice Commands — Design

## Context

`edc/audio/voice_commands.py` runs a continuous, always-on wake-word
listener (Vosk speech recognition, small-vocabulary grammar). The module's
own comments admit the root cause of a real, reported problem: "Background
audio (music/game/TV bleeding into the mic) can get misheard as the trigger
word — the grammar is deliberately a tiny vocabulary, so any sound gets
forced into the closest match." Any match fires an audible "trigger heard"
beep, so ambient noise produces frequent false-positive clicks during long
idle sessions (confirmed live: dozens of `Voice final: [...]` log lines
overnight with no gameplay).

Push-to-talk removes the problem at its source — audio only reaches the
recognizer while a bound key is physically held — rather than trying to
tune thresholds against a model whose own design forces any sound into a
match. Added as an opt-in Settings toggle alongside the existing always-on
mode, not a replacement for it.

## Research

- This codebase has no existing global-hotkey/held-key detection anywhere
  (confirmed: no `keyboard`, `pynput`, or joystick-polling library in
  `requirements.txt` or imported anywhere in `edc/`). `pydirectinput` exists
  but is used for *sending* synthetic key presses (ship command dispatch),
  not detecting held keys.
- Controller/HOTAS button dispatch is explicitly out of scope elsewhere in
  this codebase — `binds_reader.py`'s own comment: "controller dispatch is
  not supported." Matching that precedent, push-to-talk is keyboard-only;
  joystick/HOTAS button support is a real scope increase (device
  enumeration, HID polling, a new dependency class) deferred as a
  possible future addition, not part of this design.
- `VoiceCommandListener.__init__(models_dir)` takes only `models_dir`; all
  other runtime config (ship commands, trigger word, input device) is set
  via public setter methods called post-construction from the main thread
  (`update_ship_commands()`, etc.) and read by the worker's `run()` loop.
  Push-to-talk config follows the same setter pattern, not a constructor
  change.
- `edc/config.py`'s `voice_commands_enabled: bool = False` is the existing
  precedent for a simple persisted toggle; `main_window.py`'s
  `_start_voice_commands()`/`_stop_voice_commands()` plus a checkbox
  (`self.voice_cmd_check`) is the existing precedent for how a live UI
  toggle reconfigures the running worker without a full app restart (a mic
  device change already does this: stop, reconstruct with new config,
  restart).
- No existing "click to set key" UI pattern exists anywhere in this app —
  new for this feature, using Qt's own key-event handling (works while the
  app has focus) to capture the chosen key, translated to the string format
  the `keyboard` library expects for its global (always-active, regardless
  of focus) hook.

## Design

### New dependency

`keyboard` (PyPI) — a lightweight global keyboard hook. Used only for
`keyboard.is_pressed(key_name)` polling; no event-hook complexity, no admin
elevation required for basic key-state polling on Windows. Added to
`requirements.txt`.

### Settings (`edc/config.py`)

Two new fields, same load/save pattern as `voice_commands_enabled`:

```python
push_to_talk_enabled: bool = False
push_to_talk_key: str = "caps lock"
```

### `VoiceCommandListener` (`edc/audio/voice_commands.py`)

New public setter, called the same way `update_ship_commands()` already is:

```python
def set_push_to_talk(self, enabled: bool, key: str) -> None:
    self._ptt_enabled = enabled
    self._ptt_key = (key or "caps lock").strip().lower()
```

In the main capture loop, directly where queued audio chunks are currently
pulled and fed to `rec.AcceptWaveform(data)`: when `self._ptt_enabled` is
true, a chunk is only passed to the recognizer if `keyboard.is_pressed(self._ptt_key)`
is true at that moment; chunks arriving while the key is up are discarded
without being fed to Vosk at all (not merely ignored after recognition —
the recognizer never sees them, so it can never misfire on them). On the
transition from held to released, the recognizer's in-progress state and
the fragment-recovery buffer (`fragments`) are reset, so a half-spoken
phrase cut off by releasing the key doesn't leak into the next press. When
`self._ptt_enabled` is false, behavior is byte-for-byte unchanged from
today — this is purely an additional gate in front of the existing
grammar/matching logic, not a replacement for it. With PTT on, the user
still says "ship [command]" while holding the key; the wake-word phrase
itself is untouched, only *when* audio can reach the recognizer changes.

### UI (`edc/ui/main_window.py`)

Directly beside the existing `self.voice_cmd_check` checkbox: a new
"Push-to-talk" checkbox and a "Click to set key" button showing the
currently-bound key. Clicking the button enters a short capture state
(next keypress via Qt's own `keyPressEvent`, not the `keyboard` library —
this only needs to work while the Settings UI itself has focus); the
captured `Qt.Key` is translated to the `keyboard` library's key-name string
format (a small mapping table, following the exact style of
`binds_reader.py`'s existing `KEYBOARD_KEY_MAP`). Toggling the checkbox or
changing the key calls `self._voice_cmd_worker.set_push_to_talk(enabled, key)`
live on the running worker (no restart needed, since it doesn't touch the
audio device) and persists both fields via the existing config save path.

### Testing

The gating logic lives inside the same tightly-coupled Vosk/miniaudio
capture loop as the rest of this module — per this project's established
convention for audio features (and its CLAUDE.md rule that exploration/
exobiology/combat features need live confirmation, not just synthetic
tests), this is verified live: hold the key and speak a command, confirm
it's recognized; release the key and make background noise, confirm no
beep/trigger fires; the key-capture UI is confirmed visually. The
`keyboard`-string translation table (`Qt.Key` → key name) is small and pure
enough to unit test directly if useful, but the end-to-end gating behavior
itself is not realistically unit-testable without mocking the entire audio
pipeline, which this codebase does not do elsewhere for this module.
