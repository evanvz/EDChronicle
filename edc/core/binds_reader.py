"""
Parses the active Elite Dangerous .binds file and resolves keyboard and
controller bindings per action.

Active preset is determined by StartPreset.4.start in the bindings folder.
The highest-version non-backup .binds file for that preset name is used.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET

log = logging.getLogger(__name__)

# Maps GamePad key names from .binds — used only to detect that a controller
# binding exists (for status display); controller dispatch is not supported.
GAMEPAD_KEY_MAP: dict[str, str] = {
    "GamePad_FaceDown":    "XUSB_GAMEPAD_A",
    "GamePad_FaceRight":   "XUSB_GAMEPAD_B",
    "GamePad_FaceLeft":    "XUSB_GAMEPAD_X",
    "GamePad_FaceUp":      "XUSB_GAMEPAD_Y",
    "GamePad_LBumper":     "XUSB_GAMEPAD_LEFT_SHOULDER",
    "GamePad_RBumper":     "XUSB_GAMEPAD_RIGHT_SHOULDER",
    "GamePad_DPadUp":      "XUSB_GAMEPAD_DPAD_UP",
    "GamePad_DPadDown":    "XUSB_GAMEPAD_DPAD_DOWN",
    "GamePad_DPadLeft":    "XUSB_GAMEPAD_DPAD_LEFT",
    "GamePad_DPadRight":   "XUSB_GAMEPAD_DPAD_RIGHT",
    "GamePad_LThumb":      "XUSB_GAMEPAD_LEFT_THUMB",
    "GamePad_RThumb":      "XUSB_GAMEPAD_RIGHT_THUMB",
    "GamePad_Start":       "XUSB_GAMEPAD_START",
    "GamePad_Back":        "XUSB_GAMEPAD_BACK",
    "GamePad_LTrigger":    "XUSB_GAMEPAD_LEFT_THUMB",   # triggers need axis not button
    "GamePad_RTrigger":    "XUSB_GAMEPAD_RIGHT_THUMB",
}

# Maps Key_* names from .binds to pydirectinput key strings
KEYBOARD_KEY_MAP: dict[str, str] = {
    "Key_Space":       "space",
    "Key_Return":      "enter",
    "Key_Tab":         "tab",
    "Key_Escape":      "esc",
    "Key_BackSpace":   "backspace",
    "Key_Delete":      "delete",
    "Key_Insert":      "insert",
    "Key_Home":        "home",
    "Key_End":         "end",
    "Key_PageUp":      "pageup",
    "Key_PageDown":    "pagedown",
    "Key_UpArrow":     "up",
    "Key_DownArrow":   "down",
    "Key_LeftArrow":   "left",
    "Key_RightArrow":  "right",
    "Key_LeftShift":   "shiftleft",
    "Key_RightShift":  "shiftright",
    "Key_LeftControl": "ctrlleft",
    "Key_RightControl":"ctrlright",
    "Key_LeftAlt":     "altleft",
    "Key_RightAlt":    "altright",
    "Key_F1": "f1",  "Key_F2": "f2",  "Key_F3": "f3",  "Key_F4": "f4",
    "Key_F5": "f5",  "Key_F6": "f6",  "Key_F7": "f7",  "Key_F8": "f8",
    "Key_F9": "f9",  "Key_F10": "f10","Key_F11": "f11","Key_F12": "f12",
    "Key_Minus":       "-",
    "Key_Equals":      "=",
    "Key_LeftBracket": "[",
    "Key_RightBracket":"]",
    "Key_BackSlash":   "\\",
    "Key_SemiColon":   ";",
    "Key_Apostrophe":  "'",
    "Key_Comma":       ",",
    "Key_Period":      ".",
    "Key_Slash":       "/",
    "Key_BackQuote":   "`",
    "Key_Numpad_0":    "num0", "Key_Numpad_1": "num1", "Key_Numpad_2": "num2",
    "Key_Numpad_3":    "num3", "Key_Numpad_4": "num4", "Key_Numpad_5": "num5",
    "Key_Numpad_6":    "num6", "Key_Numpad_7": "num7", "Key_Numpad_8": "num8",
    "Key_Numpad_9":    "num9",
}


@dataclass
class Binding:
    """A single resolved binding — key to press plus any modifiers."""
    key: str                        # pydirectinput key string or XUSB constant
    modifiers: list[str] = field(default_factory=list)  # same format as key
    is_controller: bool = False


@dataclass
class ActionBinding:
    """Resolved binding info for one ED action."""
    action: str
    display_name: str
    keyboard: Optional[Binding] = None
    controller: Optional[Binding] = None

    def resolve(self, prefer: str) -> Optional[Binding]:
        """Return the binding to use based on input preference with fallback."""
        if prefer == "controller":
            return self.controller or self.keyboard
        return self.keyboard or self.controller


# In-game menu names for common actions. Frontier's internal action codes
# rarely match what Options → Controls displays (UseBoostJuice = "Engine
# Boost"), so the picker uses these; anything unmapped falls back to a
# CamelCase split of the code.
FRIENDLY_NAMES: dict[str, str] = {
    # Flight
    "UseBoostJuice":                "Engine Boost",
    "HyperSuperCombination":        "Frame Shift Drive Combined",
    "Supercruise":                  "Supercruise",
    "Hyperspace":                   "Hyperspace Jump",
    "ToggleFlightAssist":           "Flight Assist",
    "ToggleReverseThrottleInput":   "Reverse Throttle",
    "UseAlternateFlightValuesToggle": "Alternate Flight Controls",
    "DisableRotationCorrectToggle": "Rotational Correction",
    "OrbitLinesToggle":             "Orbit Lines",
    "SetSpeedMinus100":             "Set Speed -100%",
    "SetSpeedMinus75":              "Set Speed -75%",
    "SetSpeedMinus50":              "Set Speed -50%",
    "SetSpeedMinus25":              "Set Speed -25%",
    "SetSpeedZero":                 "Set Speed 0%",
    "SetSpeed25":                   "Set Speed 25%",
    "SetSpeed50":                   "Set Speed 50%",
    "SetSpeed75":                   "Set Speed 75%",
    "SetSpeed100":                  "Set Speed 100%",
    # Ship systems
    "LandingGearToggle":            "Landing Gear",
    "ToggleCargoScoop":             "Cargo Scoop",
    "ShipSpotLightToggle":          "Ship Lights",
    "NightVisionToggle":            "Night Vision",
    "ToggleButtonUpInput":          "Silent Running",
    "DeployHeatSink":               "Heat Sink",
    "FireChaffLauncher":            "Chaff Launcher",
    "ChargeECM":                    "ECM",
    "UseShieldCell":                "Shield Cell",
    "EjectAllCargo":                "Eject All Cargo",
    "RadarIncreaseRange":           "Increase Sensor Range",
    "RadarDecreaseRange":           "Decrease Sensor Range",
    # Targeting
    "SelectTarget":                 "Select Target Ahead",
    "CycleNextTarget":              "Cycle Next Ship",
    "CyclePreviousTarget":          "Cycle Previous Ship",
    "SelectHighestThreat":          "Select Highest Threat",
    "CycleNextHostileTarget":       "Cycle Next Hostile Ship",
    "CyclePreviousHostileTarget":   "Cycle Previous Hostile Ship",
    "CycleNextSubsystem":           "Cycle Next Subsystem",
    "CyclePreviousSubsystem":       "Cycle Previous Subsystem",
    "TargetNextRouteSystem":        "Next System in Route",
    "TargetWingman0":               "Wingman 1",
    "TargetWingman1":               "Wingman 2",
    "TargetWingman2":               "Wingman 3",
    "SelectTargetsTarget":          "Select Wingman's Target",
    "WingNavLock":                  "Wingman Nav-Lock",
    # Weapons
    "PrimaryFire":                  "Primary Fire",
    "SecondaryFire":                "Secondary Fire",
    "CycleFireGroupNext":           "Next Fire Group",
    "CycleFireGroupPrevious":       "Previous Fire Group",
    "DeployHardpointToggle":        "Deploy Hardpoints",
    # Power distribution
    "IncreaseEnginesPower":         "Divert Power to Engines",
    "IncreaseWeaponsPower":         "Divert Power to Weapons",
    "IncreaseSystemsPower":         "Divert Power to Systems",
    "ResetPowerDistribution":       "Balance Power Distribution",
    # Fighter orders
    "OrderDefensiveBehaviour":      "Fighter: Defend",
    "OrderAggressiveBehaviour":     "Fighter: Attack",
    "OrderFocusTarget":             "Fighter: Attack My Target",
    "OrderHoldFire":                "Fighter: Hold Fire",
    "OrderHoldPosition":            "Fighter: Hold Position",
    "OrderFollow":                  "Fighter: Follow Me",
    "OrderRequestDock":             "Fighter: Dock",
    # Interface / panels / maps
    "FocusLeftPanel":               "External Panel",
    "FocusRightPanel":              "Internal Panel",
    "FocusCommsPanel":              "Comms Panel",
    "QuickCommsPanel":              "Quick Comms",
    "FocusRadarPanel":              "Role Panel",
    "GalaxyMapOpen":                "Galaxy Map",
    "SystemMapOpen":                "System Map",
    "Pause":                        "Pause Menu",
    "FriendsMenu":                  "Friends Menu",
    "OpenCodexGoToDiscovery":       "Codex",
    "PlayerHUDModeToggle":          "Switch HUD Mode",
    "HeadLookToggle":               "Toggle Headlook",
    "MicrophoneMute":               "Mute Microphone",
    # Exploration
    "ExplorationFSSEnter":          "Enter FSS Mode",
    "ExplorationFSSQuit":           "Exit FSS Mode",
    "ExplorationFSSDiscoveryScan":  "Discovery Scan",
}


def _action_display_name(action: str) -> str:
    """In-game menu name where known, else 'LandingGearToggle' → 'Landing Gear Toggle'."""
    friendly = FRIENDLY_NAMES.get(action)
    if friendly:
        return friendly
    return re.sub(r'([A-Z])', r' \1', action).strip()


def _parse_key_element(elem) -> Optional[tuple[str, list[str], bool]]:
    """
    Parse a <Primary> or <Secondary> element.
    Returns (key, modifiers, is_controller) or None if unbound.
    """
    device = elem.get("Device", "")
    key_raw = elem.get("Key", "")

    if not device or device == "{NoDevice}" or not key_raw:
        return None

    is_controller = device != "Keyboard"

    # Parse modifier children
    modifiers = []
    for mod in elem.findall("Modifier"):
        mod_device = mod.get("Device", "")
        mod_key = mod.get("Key", "")
        if mod_device and mod_device != "{NoDevice}" and mod_key:
            mod_is_ctrl = mod_device != "Keyboard"
            resolved_mod = _resolve_key(mod_key, mod_is_ctrl)
            if resolved_mod:
                modifiers.append(resolved_mod)

    resolved = _resolve_key(key_raw, is_controller)
    if not resolved:
        return None

    return resolved, modifiers, is_controller


def _resolve_key(key_raw: str, is_controller: bool) -> Optional[str]:
    if is_controller:
        return GAMEPAD_KEY_MAP.get(key_raw)
    # Keyboard: check map first, then strip Key_ prefix for single letters
    if key_raw in KEYBOARD_KEY_MAP:
        return KEYBOARD_KEY_MAP[key_raw]
    if key_raw.startswith("Key_") and len(key_raw) == 5:
        return key_raw[4].lower()
    return None


def _find_bindings_dir() -> Optional[Path]:
    local_app = os.environ.get("LOCALAPPDATA")
    if not local_app:
        return None
    p = Path(local_app) / "Frontier Developments" / "Elite Dangerous" / "Options" / "Bindings"
    return p if p.exists() else None


def _active_preset_name(bindings_dir: Path) -> str:
    """Read StartPreset.4.start — line 2 is the ship preset name."""
    start_file = bindings_dir / "StartPreset.4.start"
    if not start_file.exists():
        return "Custom"
    lines = [l.strip() for l in start_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    log.info("StartPreset.4.start categories: %s", lines)
    return lines[1] if len(lines) > 1 else (lines[0] if lines else "Custom")


def _find_active_binds_file(bindings_dir: Path, preset_name: str) -> Optional[Path]:
    """
    Find the highest-version non-backup .binds file for the given preset.
    e.g. Custom.4.2.binds > Custom.4.1.binds > Custom.4.0.binds
    """
    candidates = []
    for f in bindings_dir.glob(f"{preset_name}.*.binds"):
        # Exclude backup files (contain extra numeric suffix after .binds)
        if ".binds." in f.name:
            continue
        # Parse version from name: Preset.Major.Minor.binds
        parts = f.stem.split(".")  # ["Custom", "4", "2"]
        if len(parts) >= 3:
            try:
                major = int(parts[-2])
                minor = int(parts[-1])
                candidates.append((major, minor, f))
            except ValueError:
                pass
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return candidates[0][2]


def _parse_binds_file(binds_file: Path) -> dict[str, ActionBinding]:
    """Parse one .binds file into a dict of action → ActionBinding."""
    try:
        tree = ET.parse(binds_file)
        root = tree.getroot()
    except Exception as exc:
        log.error("Failed to parse binds file %s: %s", binds_file, exc)
        return {}

    result: dict[str, ActionBinding] = {}

    for action_elem in root:
        action = action_elem.tag
        # Skip non-action elements (MouseXMode, KeyboardLayout etc.)
        primary = action_elem.find("Primary")
        secondary = action_elem.find("Secondary")
        if primary is None and secondary is None:
            continue

        kb: Optional[Binding] = None
        ctrl: Optional[Binding] = None

        for slot in (primary, secondary):
            if slot is None:
                continue
            parsed = _parse_key_element(slot)
            if not parsed:
                continue
            key, mods, is_ctrl = parsed
            b = Binding(key=key, modifiers=mods, is_controller=is_ctrl)
            if is_ctrl and ctrl is None:
                ctrl = b
            elif not is_ctrl and kb is None:
                kb = b

        if kb is None and ctrl is None:
            continue

        result[action] = ActionBinding(
            action=action,
            display_name=_action_display_name(action),
            keyboard=kb,
            controller=ctrl,
        )

    return result


def load_bindings(bindings_dir: Optional[Path] = None) -> dict[str, ActionBinding]:
    """
    Parse the user's active .binds file (highest version of the ship preset in
    the game's Bindings folder, e.g. Custom.4.2.binds) and return a dict of
    action → ActionBinding. Returns empty dict on any failure.
    """
    if bindings_dir is None:
        bindings_dir = _find_bindings_dir()
    if not bindings_dir:
        log.warning("Elite Dangerous bindings folder not found")
        return {}

    preset = _active_preset_name(bindings_dir)
    binds_file = _find_active_binds_file(bindings_dir, preset)
    if not binds_file:
        log.warning("No .binds file found for preset '%s' in %s", preset, bindings_dir)
        return {}

    log.info("Loading bindings from %s", binds_file)
    result = _parse_binds_file(binds_file)
    log.info("Loaded %d bound actions from %s", len(result), binds_file.name)
    return result
