"""
Dispatches ship commands to Elite Dangerous by simulating keyboard input
based on the resolved binding.

Keyboard: pydirectinput (low-level SendInput — works in games)

Controller dispatch is intentionally not supported: Elite Dangerous binds
gamepad actions to a specific physical device (e.g. a Steam Input virtual
controller), and a separately created virtual controller is not recognised
as that device. Actions without a keyboard binding cannot be voice-dispatched
until one is added in ED's own Controls settings.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from edc.core.binds_reader import Binding

log = logging.getLogger(__name__)

_PRESS_DURATION = 0.08   # seconds to hold key/button
_MOD_SETTLE    = 0.06    # seconds between modifier down and main key — ED can miss fast chords


def _check_pydirectinput() -> bool:
    try:
        import pydirectinput  # noqa: F401
        return True
    except ImportError:
        return False


def game_window_focused() -> bool:
    """
    True if Elite Dangerous is the foreground window. Dispatched keystrokes go
    to whatever window has focus — sending them anywhere else (including our
    own UI, where arrow keys move the sidebar selection) does the wrong thing.
    Fails open: if the check itself errors, dispatch proceeds.
    """
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return False
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return "elite" in buf.value.lower()
    except Exception:
        return True


class ShipCommandDispatcher:
    """
    Thread-safe dispatcher.  Call dispatch() from any thread — it never
    blocks for more than the key press duration (~50 ms).
    """

    def __init__(self):
        self._pydirect_available: Optional[bool] = None

    # ── Capability checks ────────────────────────────────────────────────────

    @property
    def pydirectinput_available(self) -> bool:
        if self._pydirect_available is None:
            self._pydirect_available = _check_pydirectinput()
        return self._pydirect_available

    # ── Dispatch ─────────────────────────────────────────────────────────────

    def dispatch(self, binding: Binding, repeat: int = 1) -> bool:
        """
        Fire the given binding. Returns True if the input was sent.
        repeat > 1 is used for pip commands (tap N times).
        """
        if binding.is_controller:
            log.warning("Controller dispatch not supported — add a keyboard "
                        "binding in ED Controls for this action")
            return False
        return self._dispatch_keyboard(binding, repeat)

    def _dispatch_keyboard(self, binding: Binding, repeat: int) -> bool:
        if not self.pydirectinput_available:
            log.warning("pydirectinput not available — cannot send keyboard input")
            return False
        try:
            import pydirectinput
            pydirectinput.PAUSE = 0

            for _ in range(repeat):
                # Hold modifiers
                for mod in binding.modifiers:
                    pydirectinput.keyDown(mod)
                if binding.modifiers:
                    time.sleep(_MOD_SETTLE)
                # Press main key
                pydirectinput.keyDown(binding.key)
                time.sleep(_PRESS_DURATION)
                pydirectinput.keyUp(binding.key)
                # Release modifiers
                for mod in reversed(binding.modifiers):
                    pydirectinput.keyUp(mod)
                if repeat > 1:
                    time.sleep(_MOD_SETTLE)

            mod_str = "+".join(binding.modifiers + [binding.key]) if binding.modifiers else binding.key
            log.info("Keyboard dispatch: %s (×%d)", mod_str, repeat)
            return True
        except Exception as exc:
            log.error("Keyboard dispatch failed: %s", exc)
            return False
