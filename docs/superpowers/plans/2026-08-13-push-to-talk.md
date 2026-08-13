# Push-to-Talk Voice Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in push-to-talk mode to voice commands — while enabled, audio only reaches the speech recognizer while a bound key is held, eliminating false-positive trigger beeps from ambient background noise.

**Architecture:** A new `keyboard`-library-based gate inserted directly in front of `VoiceCommandListener`'s existing recognizer feed (the audio capture loop and wake-word/grammar matching logic are otherwise untouched), a small config toggle+key persisted the same way `voice_commands_enabled` already is, and a Settings UI checkbox + "click to set key" capture control in `main_window.py`.

**Tech Stack:** Python, PyQt6, `keyboard` (new dependency — global key-state polling), `vosk` (existing, untouched).

## Global Constraints

- Keyboard-only. No joystick/HOTAS button support — matches this codebase's existing precedent (`binds_reader.py`'s own comment: "controller dispatch is not supported").
- `VoiceCommandListener`'s constructor is NOT changed. Push-to-talk config is set via a new public setter method, `set_push_to_talk(enabled, key)`, matching the exact existing pattern of `update_ship_commands()` / `set_nav_trigger_word()` / `set_input_device()` — all called post-construction from the main thread, read by the background `run()` loop.
- When push-to-talk is disabled (the default), behavior is byte-for-byte unchanged from today. The gate is purely additive in front of the existing `rec.AcceptWaveform(data)` call — the wake-word grammar/matching logic itself is never modified.
- **Verified directly against the real `keyboard` library** (not assumed): `keyboard.is_pressed(name)` accepts Qt's own `QKeySequence(key).toString()` output directly for the overwhelming majority of keys (letters, digits, F-keys, Tab, Space, Page Up/Down, Insert, Delete, Home, End, arrows, Backspace, Return, Escape, Caps Lock, Num Lock, Print, Pause, Menu) — `keyboard`'s internal `normalize_name()` already lowercases and handles common spacing. The ONE confirmed exception: Qt's `"ScrollLock"` (no space) does not match `keyboard`'s expected `"scroll lock"` (with space) and raises `ValueError`. No hand-rolled translation table is needed beyond a single explicit override for this one case, plus a runtime validation call (`keyboard.is_pressed()` inside a `try/except`) at key-capture time as a safety net for any other untested key.
- Bare modifier keys (Shift, Ctrl, Alt, Win/Meta) are rejected as PTT key choices at capture time — ambiguous (`keyboard` doesn't reliably resolve a bare "Meta"/Windows key: confirmed it raises `ValueError`) and poor UX (holding a bare modifier conflicts with normal OS/game modifier use).
- `vosk.KaldiRecognizer.Reset()` is a real, confirmed method (verified against the installed `vosk` package via `help()`) — used to clear recognizer state on key-release so a cut-off phrase doesn't leak into the next press.
- Settings persistence follows the exact existing `voice_commands_enabled` load/save pattern in `edc/config.py` — same dataclass-field-plus-two-JSON-lines shape, nothing novel.
- No new automated tests for the capture-loop gating itself — it's tightly coupled to the live Vosk/miniaudio pipeline, and this project's established convention (already applied to every other change in this file this session) is to verify audio features live, not via synthetic tests. The Qt-key-capture validation logic in the UI (Task 2) is simple enough to not need dedicated tests either, per the same convention already used for this file's other UI wiring.

---

## File Structure

- **Modify:** `requirements.txt` — add `keyboard>=0.13.5`.
- **Modify:** `edc/config.py` — two new `AppConfig` fields (`push_to_talk_enabled`, `push_to_talk_key`), load/save wiring.
- **Modify:** `edc/audio/voice_commands.py` — `import keyboard`, new `set_push_to_talk()` setter, new gate in the main capture loop.
- **Modify:** `edc/ui/main_window.py` — new checkbox + key-picker button in the Settings section, capture-mode handling via a temporary app-wide event filter, live wiring to the running worker.

---

### Task 1: Backend — config, dependency, listener gating

**Files:**
- Modify: `requirements.txt`
- Modify: `edc/config.py`
- Modify: `edc/audio/voice_commands.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `AppConfig.push_to_talk_enabled: bool`, `AppConfig.push_to_talk_key: str`; `VoiceCommandListener.set_push_to_talk(enabled: bool, key: str) -> None` — Task 2 calls this by exact name

- [ ] **Step 1: Add the dependency**

In `requirements.txt`, add a new line at the end:

```
keyboard>=0.13.5
```

- [ ] **Step 2: Install it and confirm it imports cleanly**

Run: `pip install keyboard>=0.13.5`
Run: `python -c "import keyboard; print('ok')"`
Expected: `ok`, no error.

- [ ] **Step 3: Add the config fields**

Re-read `edc/config.py` fresh (this file changes often across this session's plans). In the `AppConfig` dataclass, directly after the existing `voice_commands_enabled: bool = False` field, add:

```python
    push_to_talk_enabled: bool = False
    push_to_talk_key: str = "caps lock"
```

In the `load()` method's `AppConfig(...)` construction, directly after the existing `voice_commands_enabled=bool(data.get("voice_commands_enabled", False)),` line, add:

```python
                push_to_talk_enabled=bool(data.get("push_to_talk_enabled", False)),
                push_to_talk_key=str(data.get("push_to_talk_key", "caps lock") or "caps lock"),
```

In the `save()` method's JSON dict, directly after the existing `"voice_commands_enabled": bool(getattr(cfg, "voice_commands_enabled", False)),` line, add:

```python
                        "push_to_talk_enabled": bool(getattr(cfg, "push_to_talk_enabled", False)),
                        "push_to_talk_key": str(getattr(cfg, "push_to_talk_key", "caps lock") or "caps lock"),
```

- [ ] **Step 4: Byte-compile check**

Run: `python -m py_compile edc/config.py`
Expected: no output, exit code 0.

- [ ] **Step 5: Add the setter to `VoiceCommandListener`**

Re-read `edc/audio/voice_commands.py` fresh. Add `import keyboard` to the top-level imports (alongside the existing `import json` / `import logging` / `import queue` / `import time` block — `keyboard` is now a committed `requirements.txt` dependency, no lazy/optional import needed, unlike `vosk` which is imported lazily inside `run()` specifically to allow the app to start even before the (large, separately-downloaded) Vosk model exists).

In `VoiceCommandListener.__init__`, directly after the existing `self._input_device_name: str | None = None` line, add:

```python
        self._ptt_enabled = False
        self._ptt_key     = "caps lock"
```

Add a new public setter directly after `set_input_device()`:

```python
    def set_push_to_talk(self, enabled: bool, key: str):
        """Called from main thread whenever the push-to-talk setting changes."""
        self._ptt_enabled = bool(enabled)
        self._ptt_key = (key or "caps lock").strip().lower()
```

- [ ] **Step 6: Gate the capture loop**

In `run()`'s inner `while self._running:` loop (the one that starts with `try: data = audio_q.get(timeout=0.5)` — re-read the file fresh to confirm current line numbers, this region has not changed this session but always verify before editing), find where `partial_trigger_beeped = False` and `consecutive_trigger_partials = 0` are initialized, directly before that inner `while self._running:` loop starts. Add a third piece of state there:

```python
                partial_trigger_beeped = False
                consecutive_trigger_partials = 0
                ptt_was_held = True   # avoids a spurious reset on the very first PTT-gated chunk
```

Then, directly after the existing block:

```python
                        try:
                            data = audio_q.get(timeout=0.5)
                        except queue.Empty:
                            continue
```

insert the push-to-talk gate, BEFORE the existing `now = time.monotonic()` line. The `keyboard.is_pressed(self._ptt_key)` call is wrapped in its own `try/except`, in case a previously-saved key name ever becomes invalid (e.g. a future `keyboard` library version drops support for an obscure key) — on exception, log it once (an instance flag prevents spamming the log every 0.25s) and fall through as if the key were not held, rather than crashing the whole listener thread:

```python
                        if self._ptt_enabled:
                            try:
                                ptt_held = keyboard.is_pressed(self._ptt_key)
                            except Exception as exc:
                                if not getattr(self, "_ptt_error_logged", False):
                                    log.error("push-to-talk key '%s' invalid: %s", self._ptt_key, exc)
                                    self._ptt_error_logged = True
                                continue
                            if not ptt_held:
                                if ptt_was_held:
                                    # Key just released -- clear recognizer + fragment
                                    # state so a phrase cut off mid-word doesn't leak
                                    # into the next press.
                                    try:
                                        rec.Reset()
                                    except Exception:
                                        pass
                                    fragments = []
                                    partial_trigger_beeped = False
                                    consecutive_trigger_partials = 0
                                ptt_was_held = False
                                continue
                            ptt_was_held = True

                        now = time.monotonic()

                        if not rec.AcceptWaveform(data):
                            ...  # existing code, unchanged from here on
```

Initialize `self._ptt_error_logged = False` in `__init__` alongside the other `_ptt_*` attributes from Step 5.

- [ ] **Step 7: Byte-compile check**

Run: `python -m py_compile edc/audio/voice_commands.py`
Expected: no output, exit code 0.

- [ ] **Step 8: Run the full test suite to confirm no regressions**

Run: `pytest -q`
Expected: all existing tests still pass (this task adds no new automated tests, per the plan's Global Constraints — this module has none today and the gating logic isn't realistically unit-testable without mocking the entire live audio pipeline).

- [ ] **Step 9: Commit**

```bash
git add requirements.txt edc/config.py edc/audio/voice_commands.py
git commit -m "feat: add push-to-talk gating to voice command listener"
```

---

### Task 2: Settings UI — toggle, key picker, live wiring

**Files:**
- Modify: `edc/ui/main_window.py`

**Interfaces:**
- Consumes: `AppConfig.push_to_talk_enabled` / `AppConfig.push_to_talk_key` (Task 1), `VoiceCommandListener.set_push_to_talk(enabled, key)` (Task 1)
- Produces: nothing consumed by other tasks — this is the final task

- [ ] **Step 1: Add the checkbox and key-picker button**

Re-read `edc/ui/main_window.py` fresh (flagged frequently-stale by this project's CLAUDE.md). Find the existing "--- Voice commands ---" block (currently ends with `st.addWidget(self.voice_cmd_check)`, directly before the "--- Window behaviour ---" comment). Directly after `st.addWidget(self.voice_cmd_check)`, add:

```python
        ptt_row = QHBoxLayout()
        self.ptt_check = QCheckBox("Push-to-talk (hold key to speak, instead of always listening)")
        self.ptt_check.setChecked(bool(getattr(self.cfg, "push_to_talk_enabled", False)))
        self.ptt_check.toggled.connect(self._on_push_to_talk_toggled)
        ptt_row.addWidget(self.ptt_check)

        self.ptt_key_btn = QPushButton(self._ptt_key_button_label())
        self.ptt_key_btn.setToolTip("Click, then press the key you want to hold for push-to-talk.")
        self.ptt_key_btn.clicked.connect(self._on_set_ptt_key_clicked)
        ptt_row.addWidget(self.ptt_key_btn)
        ptt_row.addStretch(1)
        st.addLayout(ptt_row)
```

Confirm `QPushButton` and `QHBoxLayout` are already imported in this file's PyQt6 widget imports (this file uses both extensively elsewhere — e.g. `market_row = QHBoxLayout()` a few lines below this insertion point, and `QPushButton` is used throughout the Settings section for other buttons). If either is missing from the import list, add it.

- [ ] **Step 2: Add the instance state and helper for the button label**

In `MainWindow.__init__`, find where other capture-related instance attributes are initialized (e.g. near `self._voice_cmd_worker = None` / `self._voice_cmd_thread = None`) and add:

```python
        self._ptt_capturing = False
```

Add a new method (placed near the other small helper methods in this class, e.g. near `_feedback_volume()`):

```python
    def _ptt_key_button_label(self) -> str:
        key = str(getattr(self.cfg, "push_to_talk_key", "caps lock") or "caps lock")
        return f"Key: {key.title()}"
```

- [ ] **Step 3: Implement the toggle handler**

Add directly after `_on_voice_commands_toggled()`:

```python
    def _on_push_to_talk_toggled(self, checked: bool):
        self.cfg.push_to_talk_enabled = bool(checked)
        self.cfg_store.save(self.cfg)
        if self._voice_cmd_worker:
            self._voice_cmd_worker.set_push_to_talk(
                self.cfg.push_to_talk_enabled, self.cfg.push_to_talk_key,
            )
```

- [ ] **Step 4: Implement the key-capture flow**

Push-to-talk key capture needs to catch a keypress regardless of which child widget currently has Qt focus, so it's implemented via a temporary application-wide event filter rather than a widget-local `keyPressEvent` override. Add:

```python
    def _on_set_ptt_key_clicked(self):
        if self._ptt_capturing:
            return
        self._ptt_capturing = True
        self.ptt_key_btn.setText("Press a key... (Esc to cancel)")
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        if self._ptt_capturing and event.type() == QEvent.Type.KeyPress:
            self._finish_ptt_capture(event.key())
            return True
        return super().eventFilter(obj, event)

    def _finish_ptt_capture(self, qt_key: int) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().removeEventFilter(self)
        self._ptt_capturing = False

        if qt_key == Qt.Key.Key_Escape:
            self.ptt_key_btn.setText(self._ptt_key_button_label())
            return

        _REJECTED_KEYS = {
            Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt,
            Qt.Key.Key_Meta, Qt.Key.Key_AltGr,
        }
        if qt_key in _REJECTED_KEYS:
            self.ptt_key_btn.setText("Can't use a bare modifier key — try again")
            log.warning("Push-to-talk key capture rejected a bare modifier key")
            return

        key_name = QKeySequence(qt_key).toString()
        # keyboard's own name normalization handles case/spacing for the
        # overwhelming majority of keys directly from Qt's toString() output
        # (verified: letters, digits, F-keys, Tab/Space/arrows/Home/End/
        # PageUp/PageDown/Insert/Delete/Backspace/Return/Escape/CapsLock/
        # NumLock/Print/Pause/Menu all pass through as-is). One confirmed
        # exception needs an explicit override; anything else unexpected is
        # caught by the validation call below rather than silently accepted.
        _PTT_KEY_OVERRIDES = {"ScrollLock": "scroll lock"}
        key_name = _PTT_KEY_OVERRIDES.get(key_name, key_name)

        import keyboard
        try:
            keyboard.is_pressed(key_name)
        except Exception:
            self.ptt_key_btn.setText(f"'{key_name}' isn't supported — try a different key")
            log.warning("Push-to-talk key capture: '%s' rejected by keyboard library", key_name)
            return

        self.cfg.push_to_talk_key = key_name
        self.cfg_store.save(self.cfg)
        self.ptt_key_btn.setText(self._ptt_key_button_label())
        if self._voice_cmd_worker:
            self._voice_cmd_worker.set_push_to_talk(
                self.cfg.push_to_talk_enabled, self.cfg.push_to_talk_key,
            )
```

Confirm `QEvent` and `QKeySequence` are imported in this file (`QEvent` from `PyQt6.QtCore`, `QKeySequence` from `PyQt6.QtGui`) — add them to the existing import blocks if missing.

- [ ] **Step 5: Push the config into a freshly-started listener**

In `_sync_ship_commands_to_listener()` (which already runs whenever the listener starts or its config changes), add the push-to-talk call directly after the existing `self._voice_cmd_worker.set_input_device(...)` line:

```python
        self._voice_cmd_worker.set_push_to_talk(
            self.cfg.push_to_talk_enabled, self.cfg.push_to_talk_key,
        )
```

- [ ] **Step 6: Byte-compile check**

Run: `python -m py_compile edc/ui/main_window.py`
Expected: no output, exit code 0.

- [ ] **Step 7: Run the full test suite to confirm no regressions**

Run: `pytest -q`
Expected: all tests still pass (this task adds no new automated tests, matching this project's convention for UI wiring).

- [ ] **Step 8: Visual + live verification**

Launch the app, open Settings:
- Confirm the "Push-to-talk" checkbox and "Key: Caps Lock" button render next to the existing voice-commands checkbox.
- Click the key button, confirm it enters "Press a key... (Esc to cancel)" mode; press Escape, confirm it reverts without changing the binding.
- Click again, press a real key (e.g. F9), confirm the button updates to "Key: F9" and the setting persists across an app restart.
- Enable voice commands AND push-to-talk together. Confirm: with the bound key NOT held, speaking near the mic or making background noise produces no trigger beep and no `Voice final:` log line. Holding the key and saying a real command (e.g. "ship boost") is still recognized correctly. Releasing the key mid-phrase and re-pressing it does not cause a stale partial phrase to fire a wrong command.
- Try a bare modifier key (e.g. left Shift) — confirm it's rejected with the "can't use a bare modifier" message and the binding is unchanged.

- [ ] **Step 9: Commit**

```bash
git add edc/ui/main_window.py
git commit -m "feat: add push-to-talk Settings toggle and key picker"
```
