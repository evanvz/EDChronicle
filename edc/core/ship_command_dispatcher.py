"""
Dispatches ship commands to Elite Dangerous by simulating keyboard or
controller input based on the resolved binding.

Keyboard: pydirectinput (low-level SendInput — works in games)
Controller: vgamepad virtual Xbox 360 controller via ViGEmBus driver
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from edc.core.binds_reader import Binding

log = logging.getLogger(__name__)

_PRESS_DURATION = 0.05   # seconds to hold key/button
_MOD_SETTLE    = 0.02    # seconds between modifier down and main key


def _check_vigem() -> bool:
    """Return True if ViGEmBus driver is installed and vgamepad is usable."""
    try:
        import vgamepad as vg
        pad = vg.VX360Gamepad()
        del pad
        return True
    except Exception:
        return False


def _check_pydirectinput() -> bool:
    try:
        import pydirectinput  # noqa: F401
        return True
    except ImportError:
        return False


class ShipCommandDispatcher:
    """
    Thread-safe dispatcher.  Call dispatch() from any thread — it never
    blocks for more than the key press duration (~50 ms).
    """

    def __init__(self):
        self._vgamepad = None
        self._vigem_available: Optional[bool] = None
        self._pydirect_available: Optional[bool] = None

    # ── Capability checks ────────────────────────────────────────────────────

    @property
    def vigem_available(self) -> bool:
        if self._vigem_available is None:
            self._vigem_available = _check_vigem()
        return self._vigem_available

    @property
    def pydirectinput_available(self) -> bool:
        if self._pydirect_available is None:
            self._pydirect_available = _check_pydirectinput()
        return self._pydirect_available

    def install_vigem(self) -> bool:
        """
        Download and run the ViGEmBus installer.
        Returns True if the install appears to have succeeded.
        """
        import urllib.request, subprocess, tempfile, os
        url = "https://github.com/nefarius/ViGEmBus/releases/latest/download/ViGEmBus_Setup_x64.exe"
        log.info("Downloading ViGEmBus installer from %s", url)
        try:
            with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as tmp:
                urllib.request.urlretrieve(url, tmp.name)
                installer = tmp.name
            log.info("Launching ViGEmBus installer: %s", installer)
            result = subprocess.run([installer, "/silent"], timeout=120)
            os.unlink(installer)
            # Reset cached state so next check re-probes
            self._vigem_available = None
            self._vgamepad = None
            return self.vigem_available
        except Exception as exc:
            log.error("ViGEmBus install failed: %s", exc)
            return False

    # ── Virtual gamepad lifecycle ────────────────────────────────────────────

    def _get_gamepad(self):
        if self._vgamepad is not None:
            return self._vgamepad
        if not self.vigem_available:
            return None
        try:
            import vgamepad as vg
            self._vgamepad = vg.VX360Gamepad()
            log.info("vgamepad virtual Xbox 360 controller created")
            return self._vgamepad
        except Exception as exc:
            log.error("Failed to create vgamepad: %s", exc)
            return None

    # ── Dispatch ─────────────────────────────────────────────────────────────

    def dispatch(self, binding: Binding, repeat: int = 1) -> bool:
        """
        Fire the given binding. Returns True if the input was sent.
        repeat > 1 is used for pip commands (tap N times).
        """
        if binding.is_controller:
            return self._dispatch_controller(binding, repeat)
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

            log.debug("Keyboard dispatch: %s (×%d)", binding.key, repeat)
            return True
        except Exception as exc:
            log.error("Keyboard dispatch failed: %s", exc)
            return False

    def _dispatch_controller(self, binding: Binding, repeat: int) -> bool:
        pad = self._get_gamepad()
        if pad is None:
            log.warning("Controller dispatch failed: ViGEmBus not available")
            return False
        try:
            import vgamepad as vg

            def _button_const(name: str):
                return getattr(vg.XUSB_BUTTON, name, None)

            main_btn = _button_const(binding.key)
            mod_btns = [_button_const(m) for m in binding.modifiers]
            mod_btns = [b for b in mod_btns if b is not None]

            if main_btn is None:
                log.warning("Unknown controller button: %s", binding.key)
                return False

            for _ in range(repeat):
                # Press modifiers first
                for btn in mod_btns:
                    pad.press_button(button=btn)
                if mod_btns:
                    pad.update()
                    time.sleep(_MOD_SETTLE)
                # Press main button
                pad.press_button(button=main_btn)
                pad.update()
                time.sleep(_PRESS_DURATION)
                # Release all
                pad.release_button(button=main_btn)
                for btn in mod_btns:
                    pad.release_button(button=btn)
                pad.update()
                if repeat > 1:
                    time.sleep(_MOD_SETTLE)

            log.debug("Controller dispatch: %s (×%d)", binding.key, repeat)
            return True
        except Exception as exc:
            log.error("Controller dispatch failed: %s", exc)
            return False
